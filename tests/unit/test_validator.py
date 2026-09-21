from browser_skill.models import DownloadedFile, DownloadStatus
from browser_skill.runtime.validator import ResultValidator


def test_required_field_missing_fails(template) -> None:
    report = ResultValidator().validate(
        template,
        [{"sample_id": "S1", "sn": ""}],
        [],
        pagination_complete=True,
    )
    assert report.ok is False
    assert report.field_completeness == 0.5


def test_duplicate_record_key_fails(template) -> None:
    records = [
        {"sample_id": "S1", "sn": "same"},
        {"sample_id": "S2", "sn": "same"},
    ]
    report = ResultValidator().validate(template, records, [], pagination_complete=True)
    assert report.ok is False
    assert any(issue.code == "record_key" for issue in report.issues)


def test_optional_attachment_failure_is_partial(template_data) -> None:
    from browser_skill.models import BrowserTemplate

    template = BrowserTemplate.model_validate(template_data)
    files = [
        DownloadedFile(
            record_key="SN1",
            attachment_key="inventory_evidence",
            relative_path="",
            status=DownloadStatus.MISSING,
        )
    ]
    report = ResultValidator().validate(
        template,
        [{"sample_id": "S1", "sn": "SN1"}],
        files,
        pagination_complete=True,
    )
    assert report.ok is True
    assert report.partial is True
