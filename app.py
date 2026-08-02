from __future__ import annotations

import csv
import io
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Protocol

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import labelcheck.ocr
import labelcheck.pipeline
import labelcheck.preprocess
from labelcheck import batch as label_batch
from labelcheck import report as batch_report
from labelcheck.models import ApplicationRecord, FieldResult, LabelReport, Status

# Agents see plain-language errors; the traceback still has to land somewhere a
# developer can find it, or every fault degrades into "could not read this label".
_LOGGER = logging.getLogger(__name__)

_FIELD_LABELS = {
    "brand_name": "Brand name",
    "class_type": "Class or type",
    "alcohol_content": "Alcohol content",
    "net_contents": "Net contents",
    "net_contents_standard_of_fill": "Approved container size",
    "bottler": "Bottler or producer",
    "origin_country": "Country of origin",
    "government_warning": "Government warning wording",
    "government_warning_prefix": "Government warning heading",
    "government_warning_bold": "Government warning bold text",
    "government_warning_type_size": "Government warning type size",
}

_STATUS_LABELS = {
    Status.PASS: "Matches",
    Status.REVIEW: "Close — worth checking",
    Status.FAIL: "Does not match",
    Status.NOT_EVALUATED: "Not checked",
}

_FIELD_STATUS_COPY = {
    Status.PASS: "Matches the application.",
    Status.REVIEW: "Close — worth checking. Compare the crop with the two values.",
    Status.FAIL: "Does not match the application. Review the crop and decide the next step.",
    Status.NOT_EVALUATED: "Not checked. See the reason below.",
}

_OVERALL_STATUS_COPY = {
    Status.PASS: "Overall: All completed checks match the application.",
    Status.REVIEW: ("Overall: Close — worth checking. At least one check needs your judgment."),
    Status.FAIL: "Overall: At least one value does not match the application.",
    Status.NOT_EVALUATED: "Overall: Some or all checks were not completed.",
}

_STATIC_STYLES = """
<style>
    .stButton > button,
    .stDownloadButton > button,
    div[data-testid="stFormSubmitButton"] > button {
        min-height: 3.25rem;
        font-size: 1.08rem;
        font-weight: 700;
    }
    div[data-testid="stFileUploaderDropzone"] {
        min-height: 8rem;
        padding: 1.25rem;
    }
    div[data-testid="stForm"] {
        padding: 1.5rem;
    }
    .status-neutral {
        background: #eceff1;
        border-left: 0.35rem solid #687078;
        border-radius: 0.35rem;
        color: #202124;
        margin: 0.5rem 0;
        padding: 0.85rem 1rem;
    }
</style>
"""

_NEUTRAL_FIELD_STATUS = """
<div class="status-neutral" role="status"><strong>Not checked.</strong> See the reason below.</div>
"""

_NEUTRAL_OVERALL_STATUS = """
<div class="status-neutral" role="status">
    <strong>Overall: Some or all checks were not completed.</strong>
</div>
"""

# Only advertise formats this host can actually decode: offering HEIC on a machine
# without the wheel would take the upload and then fail it.
_UPLOAD_TYPES = ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"] + (
    ["heic", "heif"] if labelcheck.preprocess.HEIF_SUPPORTED else []
)
# Streamlit already lists the accepted extensions under the dropzone, so the label
# stays plain rather than repeating them back as jargon.
_UPLOAD_LABEL = "Label image"

_SAMPLES_DIRECTORY = Path(__file__).resolve().parent / "samples"
_SAMPLE_LABEL_FILENAME = "compliant-bourbon.png"
_SAMPLE_IMAGE_KEY = "labelcheck_sample_image"
_SAMPLE_NAME_KEY = "labelcheck_sample_name"
_SAMPLE_VALUES_KEY = "labelcheck_sample_values"

_BATCH_VIEW_KEY = "labelcheck_batch_view"
_BATCH_RESULTS_KEY = "labelcheck_batch_results"
_BATCH_FRAME_KEY = "labelcheck_batch_frame"
_BATCH_PARTIAL_KEY = "labelcheck_batch_partial"


class _UploadedFile(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


@st.cache_resource(show_spinner=False)
def _warm_ocr_engine() -> object:
    """Keep model startup out of each label check and each Streamlit rerun."""

    return labelcheck.ocr.warm()


def _friendly_field_label(field_name: str) -> str:
    return _FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())


def _display_application_value(value: str | None) -> str:
    return value or "Not provided"


def _display_read_value(value: str | None) -> str:
    return value or "Nothing readable was found"


def _user_detail(result: FieldResult) -> str | None:
    return result.detail or None


def _render_status(status: Status, *, overall: bool = False) -> None:
    copy = _OVERALL_STATUS_COPY[status] if overall else _FIELD_STATUS_COPY[status]
    if status is Status.PASS:
        st.success(copy)
    elif status is Status.REVIEW:
        st.warning(copy)
    elif status is Status.FAIL:
        st.error(copy)
    elif overall:
        st.markdown(_NEUTRAL_OVERALL_STATUS, unsafe_allow_html=True)
    else:
        st.markdown(_NEUTRAL_FIELD_STATUS, unsafe_allow_html=True)


def _render_overall_status(report: LabelReport) -> None:
    _render_status(report.overall_status, overall=True)
    count = len(_checks_that_could_not_run(report))
    if count:
        noun = "check" if count == 1 else "checks"
        st.info(f"{count} {noun} could not be run — see below.")


def _checks_that_could_not_run(report: LabelReport) -> tuple[str, ...]:
    explicitly_unevaluated = report.unevaluated_checks
    missing = tuple(field_name for field_name in _FIELD_LABELS if field_name not in report.results)
    return explicitly_unevaluated + missing


def _render_field(field_name: str, result: FieldResult) -> None:
    label = _friendly_field_label(field_name)
    with st.container(border=True):
        st.subheader(label)
        crop_column, value_column = st.columns([2, 3], gap="large", vertical_alignment="top")
        with crop_column:
            st.image(
                result.crop,
                caption=f"Label crop for {label.lower()}",
                width="stretch",
            )
        with value_column:
            st.markdown("**Application value**")
            st.write(_display_application_value(result.expected))
            st.markdown("**We read this as**")
            st.write(_display_read_value(result.extracted))
            _render_status(result.status)
            detail = _user_detail(result)
            if detail:
                st.write(detail)


def _report_to_csv(report: LabelReport) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Check", "Status", "Application value", "Read value", "Detail"])
    for field_name, result in report.results.items():
        writer.writerow(
            [
                _friendly_field_label(field_name),
                _STATUS_LABELS[result.status],
                _display_application_value(result.expected),
                _display_read_value(result.extracted),
                _user_detail(result) or _FIELD_STATUS_COPY[result.status],
            ]
        )
    for field_name in _FIELD_LABELS:
        if field_name in report.results:
            continue
        writer.writerow(
            [
                _friendly_field_label(field_name),
                _STATUS_LABELS[Status.NOT_EVALUATED],
                _display_application_value(None),
                _display_read_value(None),
                "This check could not be run.",
            ]
        )
    return output.getvalue().encode("utf-8")


def _render_report(
    report: LabelReport,
    elapsed_seconds: float,
    *,
    image_bytes: bytes | None = None,
) -> None:
    st.subheader("3. Review the results")
    st.caption(f"Checked in {elapsed_seconds:.1f} seconds.")
    _render_overall_status(report)
    if image_bytes:
        # The preview is context, not the verdict. A format Streamlit cannot render
        # must never cost the agent the results themselves.
        try:
            st.image(image_bytes, caption="The label you uploaded", width="stretch")
        except Exception:
            pass
    st.write("Review each crop before making your decision.")

    for field_name, result in report.results.items():
        _render_field(field_name, result)

    st.download_button(
        "Download results as CSV",
        data=_report_to_csv(report),
        file_name="label-check-results.csv",
        mime="text/csv",
        on_click="ignore",
        width="stretch",
    )


def _render_batch_page() -> None:
    if st.button("Back to one label", width="stretch"):
        _clear_batch_results()
        st.session_state[_BATCH_VIEW_KEY] = False
        st.rerun()

    with st.form("batch_label_check"):
        st.subheader("1. Upload all label images")
        uploaded_files = st.file_uploader(
            _UPLOAD_LABEL.replace("image", "images"),
            type=_UPLOAD_TYPES,
            accept_multiple_files=True,
            help="Choose every label image in this group.",
        )
        st.subheader("2. Upload the application values")
        manifest_file = st.file_uploader(
            "Application values CSV",
            type=["csv"],
            help="Each row must name one image and give the values expected on that label.",
        )
        st.write("Use these column names in this order:")
        st.code(", ".join(label_batch.MANIFEST_COLUMNS), language=None)
        submitted = st.form_submit_button(
            "Check all labels",
            type="primary",
            width="stretch",
        )

    if submitted:
        _handle_batch_submission(uploaded_files, manifest_file)
    _render_saved_batch_results()


def _load_sample_label() -> bool:
    """Fill the whole form from a bundled label so the tool can be tried in one click.

    An evaluator opening the deployed app otherwise has to find a bottle photograph
    and invent six matching application values before anything happens.
    """

    image_path = _SAMPLES_DIRECTORY / _SAMPLE_LABEL_FILENAME
    manifest_path = _SAMPLES_DIRECTORY / "application-values.csv"
    try:
        image_bytes = image_path.read_bytes()
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return False

    row = next((row for row in rows if row.get("filename") == _SAMPLE_LABEL_FILENAME), None)
    if row is None or not image_bytes:
        return False

    st.session_state[_SAMPLE_VALUES_KEY] = {
        field_name: (row.get(field_name) or "")
        for field_name in (
            "brand_name",
            "class_type",
            "alcohol_content",
            "net_contents",
            "bottler",
            "origin_country",
        )
    }
    st.session_state[_SAMPLE_IMAGE_KEY] = image_bytes
    st.session_state[_SAMPLE_NAME_KEY] = _SAMPLE_LABEL_FILENAME
    return True


def _prefill(field_name: str) -> str:
    values = st.session_state.get(_SAMPLE_VALUES_KEY)
    if not isinstance(values, dict):
        return ""
    value = values.get(field_name, "")
    return value if isinstance(value, str) else ""


def _progress_text(completed: int, total: int, elapsed_seconds: float) -> str:
    """Tell the agent how long the queue still needs, in words, not a spinner.

    The vendor pilot did not fail because the work was impossible. It failed because
    nobody could tell whether it was progressing.
    """

    done = f"Completed {completed} of {total} labels"
    if completed <= 0 or completed >= total or elapsed_seconds <= 0:
        return done

    remaining_seconds = (elapsed_seconds / completed) * (total - completed)
    if remaining_seconds < 90:
        return f"{done} — under 2 minutes left"
    minutes = round(remaining_seconds / 60)
    return f"{done} — about {minutes} minute{'s' if minutes != 1 else ''} left"


def _handle_batch_submission(
    uploaded_files: Sequence[_UploadedFile] | None,
    manifest_file: _UploadedFile | None,
) -> None:
    _clear_batch_results()
    if manifest_file is None:
        st.error(
            "Upload the application values CSV, then choose Check all labels again. "
            "You may leave the image list empty to see which files are missing."
        )
        return

    try:
        manifest_bytes = manifest_file.getvalue()
        images = [
            label_batch.UploadedImage(upload.name, upload.getvalue())
            for upload in uploaded_files or ()
        ]
    except Exception:
        _LOGGER.exception("Reading the uploaded batch files failed.")
        st.error("One of these files could not be opened. Choose the files again and retry.")
        return
    if not manifest_bytes:
        st.error("The application values CSV is empty. Choose a completed CSV and retry.")
        return

    try:
        manifest = label_batch.parse_manifest(manifest_bytes)
    except label_batch.ManifestError as error:
        st.error(str(error))
        return

    progress = st.progress(0.0, text="Completed 0 labels")
    st.caption(
        "A large batch takes a few minutes. If you stop it, the labels already checked "
        "are kept and shown."
    )
    started_at = perf_counter()
    # Stopping a Streamlit run raises inside run_batch, so nothing it returns survives.
    # Each finished label is therefore banked in session state as it arrives, which is
    # what makes the promise above true rather than decorative.
    st.session_state[_BATCH_PARTIAL_KEY] = []

    def show_progress(completed: int, total: int) -> None:
        fraction = completed / total if total else 1.0
        progress.progress(
            fraction,
            text=_progress_text(completed, total, perf_counter() - started_at),
        )

    def bank_result(result: object) -> None:
        st.session_state[_BATCH_PARTIAL_KEY].append(result)

    try:
        results = label_batch.run_batch(
            images,
            manifest,
            progress_callback=show_progress,
            result_callback=bank_result,
        )
        elapsed_seconds = perf_counter() - started_at
    except label_batch.BatchInputError as error:
        st.error(str(error))
        return
    except Exception:
        _LOGGER.exception("Batch verification failed.")
        st.error(
            "The labels could not be checked. Keep this page open, confirm the files, and retry."
        )
        return

    frame = batch_report.results_to_dataframe(results)
    st.session_state[_BATCH_RESULTS_KEY] = results
    st.session_state[_BATCH_FRAME_KEY] = frame
    st.success(
        f"Completed {len(results)} of {len(results)} labels in {elapsed_seconds:.1f} seconds."
    )


def _render_saved_batch_results() -> None:
    results = st.session_state.get(_BATCH_RESULTS_KEY)
    frame = st.session_state.get(_BATCH_FRAME_KEY)
    if not isinstance(results, list) or frame is None:
        results = _stopped_batch_results()
        if results is None:
            return
        st.warning(
            f"This batch was stopped before it finished. Here are the {len(results)} "
            "labels that were checked. The rest were not checked."
        )
        frame = batch_report.results_to_dataframe(results)

    st.subheader("Review the results")
    st.write("Problems appear first. You can sort the table by choosing a column heading.")
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button(
        "Download all results as CSV",
        data=batch_report.dataframe_to_csv(frame),
        file_name="label-check-batch-results.csv",
        mime="text/csv",
        on_click="ignore",
        width="stretch",
    )

    reviewable = [result for result in results if result.report is not None]
    if not reviewable:
        return
    selected_index = st.selectbox(
        "Choose a label to review with its image crops",
        options=range(len(reviewable)),
        format_func=lambda index: reviewable[index].filename,
    )
    selected = reviewable[selected_index]
    st.subheader(f"Evidence for {selected.filename}")
    if selected.report is not None:
        _render_overall_status(selected.report)
        st.write("Review every crop before making your decision.")
        for field_name, result in selected.report.results.items():
            _render_field(field_name, result)


def _stopped_batch_results() -> list | None:
    """Recover the labels a stopped batch had already finished, or None if there are none."""

    partial = st.session_state.get(_BATCH_PARTIAL_KEY)
    if not isinstance(partial, list) or not partial:
        return None
    return label_batch.sort_results(partial)


def _clear_batch_results() -> None:
    st.session_state.pop(_BATCH_RESULTS_KEY, None)
    st.session_state.pop(_BATCH_FRAME_KEY, None)
    st.session_state.pop(_BATCH_PARTIAL_KEY, None)


def main() -> None:
    """Present one accessible path while the domain package owns every check."""

    st.set_page_config(
        page_title="Alcohol Label Check",
        page_icon="🔎",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_STATIC_STYLES, unsafe_allow_html=True)
    batch_view = bool(st.session_state.get(_BATCH_VIEW_KEY, False))
    if batch_view:
        st.title("Check many alcohol labels")
        st.write(
            "Upload all label images together with one CSV containing the application values "
            "for each filename."
        )
    else:
        st.title("Check an alcohol label")
        st.write(
            "Upload one label and enter the application values. We will show what matches "
            "and what needs your judgment."
        )

    try:
        _warm_ocr_engine()
    except Exception:
        _LOGGER.exception("OCR engine warm-up failed.")
        st.error("The label reader could not start. Reload the page and try again.")
        return

    if batch_view:
        _render_batch_page()
        return

    sample_name = st.session_state.get(_SAMPLE_NAME_KEY)

    with st.form("single_label_check"):
        st.subheader("1. Upload the label")
        uploaded_file = st.file_uploader(
            _UPLOAD_LABEL,
            type=_UPLOAD_TYPES,
            help="For the clearest result, use a straight-on photo in good light.",
        )
        if sample_name:
            st.caption(f"Using the sample label {sample_name}. Upload a file to use that instead.")

        st.subheader("2. Enter the application values")
        brand_name = st.text_input("Brand name (required)", value=_prefill("brand_name"))
        class_type = st.text_input("Class or type (required)", value=_prefill("class_type"))
        alcohol_content = st.text_input(
            "Alcohol content (required)", value=_prefill("alcohol_content")
        )
        net_contents = st.text_input("Net contents (required)", value=_prefill("net_contents"))
        bottler = st.text_input("Bottler or producer (required)", value=_prefill("bottler"))
        origin_country = st.text_input(
            "Country of origin (optional)", value=_prefill("origin_country")
        )
        submitted = st.form_submit_button("Check label", type="primary", width="stretch")
        # Kept inside the form so the demo sits where the agent is already looking,
        # and so the page still offers one primary action rather than two rival ones.
        wants_sample = st.form_submit_button("Try a sample label", width="stretch")

    if wants_sample:
        if _load_sample_label():
            st.rerun()
        st.error("The sample label is unavailable. Upload your own image instead.")

    if submitted:
        _handle_single_submission(
            uploaded_file,
            brand_name=brand_name,
            class_type=class_type,
            alcohol_content=alcohol_content,
            net_contents=net_contents,
            bottler=bottler,
            origin_country=origin_country,
        )

    st.divider()
    st.subheader("Have many labels to check?")
    st.write("Upload the images together and track progress while they are checked.")
    if st.button("Check many labels", width="stretch"):
        st.session_state[_BATCH_VIEW_KEY] = True
        st.rerun()


def _handle_single_submission(
    uploaded_file: _UploadedFile | None,
    *,
    brand_name: str,
    class_type: str,
    alcohol_content: str,
    net_contents: str,
    bottler: str,
    origin_country: str,
) -> None:
    """Keep the results directly beneath the button the agent just pressed."""

    sample_bytes = st.session_state.get(_SAMPLE_IMAGE_KEY)
    if uploaded_file is None and not sample_bytes:
        st.error("Upload a label image, then choose Check label again.")
        return
    if not all((brand_name, class_type, alcohol_content, net_contents, bottler)):
        st.error(
            "Enter all five required application values, then choose Check label again. "
            "Country of origin can stay blank."
        )
        return

    try:
        image_bytes = uploaded_file.getvalue() if uploaded_file is not None else sample_bytes
    except Exception:
        _LOGGER.exception("Reading the uploaded image failed.")
        st.error("We could not open this image. Choose another image and try again.")
        return
    if not image_bytes:
        st.error("This image is empty. Choose a different image and try again.")
        return

    application = ApplicationRecord(
        brand_name=brand_name,
        class_type=class_type,
        alcohol_content=alcohol_content,
        net_contents=net_contents,
        bottler=bottler,
        origin_country=origin_country or None,
    )

    try:
        started_at = perf_counter()
        report = labelcheck.pipeline.verify(image_bytes, application)
        elapsed_seconds = perf_counter() - started_at
    except Exception:
        _LOGGER.exception("Verification raised for an uploaded label.")
        st.error(
            "We could not read this label. Try a clear, straight-on PNG or JPEG in better light."
        )
        return

    try:
        _render_report(report, elapsed_seconds, image_bytes=image_bytes)
    except Exception:
        _LOGGER.exception("Rendering the finished report failed.")
        st.error(
            "The label was checked, but the results could not be displayed. Reload the "
            "page and try again."
        )


if __name__ == "__main__":
    main()
