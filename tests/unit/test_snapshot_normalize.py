from browser_skill.browser.base import snapshot_from_data


def test_snapshot_from_interactive_list() -> None:
    snapshot = snapshot_from_data(
        {
            "url": "https://example.internal/list",
            "interactive": [
                {"ref": "@evidence", "name": "盘点凭证", "role": "button"},
            ],
        }
    )
    assert snapshot.url.endswith("/list")
    assert len(snapshot.elements) == 1
    assert snapshot.elements[0]["target"] == "@evidence"
    assert "凭证" in snapshot.elements[0]["text"]


def test_snapshot_nested_snapshot_dict() -> None:
    snapshot = snapshot_from_data(
        {
            "snapshot": {
                "elements": [{"ref": "e1", "text": "下载附件"}],
            }
        }
    )
    assert snapshot.elements[0]["ref"] == "e1"
