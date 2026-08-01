from __future__ import annotations

import csv
import io
import sys
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Protocol

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import labelcheck.ocr
import labelcheck.pipeline
from labelcheck import batch as label_batch
from labelcheck import report as batch_report
from labelcheck.models import ApplicationRecord, FieldResult, LabelReport, Status

_FIELD_LABELS = {
    "brand_name": "Brand name",
    "class_type": "Class or type",
    "alcohol_content": "Alcohol content",
    "net_contents": "Net contents",
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

_UNEVALUATED_EXPLANATIONS = {
    "government_warning_bold": (
        "This was not checked because the reader cannot confirm bold text from the "
        "available evidence."
    ),
    "government_warning_type_size": (
        "This was not checked because the image does not provide the physical "
        "measurements needed to confirm type size."
    ),
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

_BATCH_VIEW_KEY = "labelcheck_batch_view"
_BATCH_RESULTS_KEY = "labelcheck_batch_results"
_BATCH_FRAME_KEY = "labelcheck_batch_frame"


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


def _user_detail(field_name: str, result: FieldResult) -> str | None:
    if result.status is Status.NOT_EVALUATED:
        return _UNEVALUATED_EXPLANATIONS.get(field_name, result.detail)
    if result.status in {Status.REVIEW, Status.FAIL}:
        return result.detail
    return None


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
            detail = _user_detail(field_name, result)
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
                _user_detail(field_name, result) or _FIELD_STATUS_COPY[result.status],
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
            "PNG or JPEG label images",
            type=["png", "jpg", "jpeg"],
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

    def show_progress(completed: int, total: int) -> None:
        fraction = completed / total if total else 1.0
        progress.progress(fraction, text=f"Completed {completed} of {total} labels")

    try:
        started_at = perf_counter()
        results = label_batch.run_batch(
            images,
            manifest,
            progress_callback=show_progress,
        )
        elapsed_seconds = perf_counter() - started_at
    except label_batch.BatchInputError as error:
        st.error(str(error))
        return
    except Exception:
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
        return

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


def _clear_batch_results() -> None:
    st.session_state.pop(_BATCH_RESULTS_KEY, None)
    st.session_state.pop(_BATCH_FRAME_KEY, None)


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
        st.error("The label reader could not start. Reload the page and try again.")
        return

    if batch_view:
        _render_batch_page()
        return

    with st.form("single_label_check"):
        st.subheader("1. Upload the label")
        uploaded_file = st.file_uploader(
            "PNG or JPEG label image",
            type=["png", "jpg", "jpeg"],
            help="For the clearest result, use a straight-on photo in good light.",
        )

        st.subheader("2. Enter the application values")
        brand_name = st.text_input("Brand name (required)")
        class_type = st.text_input("Class or type (required)")
        alcohol_content = st.text_input("Alcohol content (required)")
        net_contents = st.text_input("Net contents (required)")
        bottler = st.text_input("Bottler or producer (required)")
        origin_country = st.text_input("Country of origin (optional)")
        submitted = st.form_submit_button("Check label", type="primary", width="stretch")

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

    if uploaded_file is None:
        st.error("Upload a PNG or JPEG label image, then choose Check label again.")
        return
    if not all((brand_name, class_type, alcohol_content, net_contents, bottler)):
        st.error(
            "Enter all five required application values, then choose Check label again. "
            "Country of origin can stay blank."
        )
        return

    try:
        image_bytes = uploaded_file.getvalue()
    except Exception:
        st.error("We could not open this image. Choose another PNG or JPEG and try again.")
        return
    if not image_bytes:
        st.error("This image is empty. Choose a different PNG or JPEG and try again.")
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
        st.error(
            "We could not read this label. Try a clear, straight-on PNG or JPEG in better light."
        )
        return

    try:
        _render_report(report, elapsed_seconds, image_bytes=image_bytes)
    except Exception:
        st.error(
            "The label was checked, but the results could not be displayed. Reload the "
            "page and try again."
        )


if __name__ == "__main__":
    main()
