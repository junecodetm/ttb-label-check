import inspect

from labelcheck.config import GOVERNMENT_WARNING
from labelcheck.models import Status
from labelcheck.rules import warning


def test_exact_statutory_warning_and_prefix_pass() -> None:
    text_result = warning.verify(GOVERNMENT_WARNING)
    prefix_result = warning.verify_prefix(GOVERNMENT_WARNING)

    assert text_result.status is Status.PASS
    assert prefix_result.status is Status.PASS


def test_statutory_warning_expected_text_cannot_be_overridden_by_a_caller() -> None:
    assert "expected" not in inspect.signature(warning.verify).parameters

    result = warning.verify("FAKE WARNING")

    assert result.status is Status.FAIL
    assert result.expected == GOVERNMENT_WARNING


def test_layout_and_known_ocr_artifacts_pass_normalized_exact_match() -> None:
    artifact_warning = (
        GOVERNMENT_WARNING.replace("WARNING", "WARN1NG")
        .replace("alcoholic", "alco-\n holic", 1)
        .replace("ability", "abiIity")
        .replace(" ", "  ")
    )

    result = warning.verify(artifact_warning)

    assert result.status is Status.PASS


def test_title_case_prefix_fails_both_exact_text_and_prefix_checks() -> None:
    altered = GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")

    assert warning.verify(altered).status is Status.FAIL
    assert warning.verify_prefix(altered).status is Status.FAIL


def test_body_case_change_fails_text_but_not_prefix() -> None:
    altered = GOVERNMENT_WARNING.replace("Surgeon General", "surgeon General")

    assert warning.verify(altered).status is Status.FAIL
    assert warning.verify_prefix(altered).status is Status.PASS


def test_omitted_word_fails_with_directional_word_diff() -> None:
    altered = GOVERNMENT_WARNING.replace("health problems", "problems")

    result = warning.verify(altered)

    assert result.status is Status.FAIL
    assert "missing expected [health]" in result.detail


def test_inserted_word_fails_with_directional_word_diff() -> None:
    altered = GOVERNMENT_WARNING.replace("health problems", "serious health problems")

    result = warning.verify(altered)

    assert result.status is Status.FAIL
    assert "unexpected extracted [serious]" in result.detail


def test_punctuation_change_fails_and_diff_identifies_it() -> None:
    altered = GOVERNMENT_WARNING.replace("problems.", "problems!")

    result = warning.verify(altered)

    assert result.status is Status.FAIL
    assert "replace expected [.] with extracted [!]" in result.detail


def test_unlocated_warning_and_prefix_are_not_evaluated() -> None:
    assert warning.verify(None).status is Status.NOT_EVALUATED
    assert warning.verify_prefix(None).status is Status.NOT_EVALUATED


def test_bold_and_type_size_are_explicitly_not_evaluated() -> None:
    bold = warning.verify_bold()
    type_size = warning.verify_type_size()

    assert bold.status is Status.NOT_EVALUATED
    assert type_size.status is Status.NOT_EVALUATED
    assert bold.confidence is None
    assert type_size.confidence is None
    assert "not recoverable" in bold.detail.lower()
    assert bold.expected == "Bold GOVERNMENT WARNING: prefix"
    assert "not available" in type_size.detail.lower()


def test_warning_rule_has_no_fuzzy_or_casefold_fallback() -> None:
    source = inspect.getsource(warning).casefold()

    assert "rapidfuzz" not in source
    assert ".casefold(" not in source


def test_lost_word_spaces_are_reviewed_not_failed() -> None:
    """Real OCR reads stylised warning panels without spaces; that is not a violation."""

    squashed = GOVERNMENT_WARNING.replace(" ", "")

    result = warning.verify(squashed)

    assert result.status is Status.REVIEW
    assert "spaces between words" in result.detail


def test_title_case_is_still_failed_even_without_spaces() -> None:
    """Jenny Park's rejection must survive the space-tolerant comparison."""

    squashed_title_case = GOVERNMENT_WARNING.replace(
        "GOVERNMENT WARNING:", "Government Warning:"
    ).replace(" ", "")

    result = warning.verify(squashed_title_case)
    prefix_result = warning.verify_prefix(squashed_title_case)

    assert result.status is Status.FAIL
    assert prefix_result.status is Status.FAIL


def test_altered_wording_without_spaces_is_still_failed() -> None:
    squashed_wrong = GOVERNMENT_WARNING.replace("birth defects", "birth issues").replace(" ", "")

    assert warning.verify(squashed_wrong).status is Status.FAIL
