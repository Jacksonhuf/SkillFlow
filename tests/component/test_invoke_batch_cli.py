"""skill-scripts/invoke.py: batch variables (--var repeated, --var-file) and the probe command."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    BrowserCapabilities,
    BrowserSnapshot,
    BrowserTemplate,
    CommandResult,
    TemplateStatus,
)
from browser_skill.templates.store import TemplateStore

REPO = Path(__file__).resolve().parents[2]
CAPS = BrowserCapabilities(
    snapshot=True, find=True, download=True, downloads=True, tabs=True, network=True
)
HOME = BrowserSnapshot(url="https://example.internal/home", text="退出登录 订单中心")


def _load_invoke() -> Any:
    script = REPO / "skill-scripts" / "invoke.py"
    spec = importlib.util.spec_from_file_location("invoke_cli", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _detail(order_no: str) -> BrowserSnapshot:
    return BrowserSnapshot(
        url=f"https://example.internal/orders/{order_no}",
        text=f"退出登录\n订单号：{order_no}\n客户：ACME\n",
        elements=[{"ref": f"@c-{order_no}", "role": "link", "text": "合同.pdf"}],
    )


def _published_batch_template(template_data: dict[str, Any], root: Path) -> None:
    data = deepcopy(template_data)
    data["schema_version"] = "2.0"
    data["template_id"] = "orders"
    data["status"] = TemplateStatus.PUBLISHED.value
    data["system"]["url_template"] = "https://example.internal/orders/{order_no}"
    data["variables"] = {
        "order_no": {"type": "string", "required": True, "multiple": True, "prompt": "订单号"}
    }
    data["run"] = {"mode": "detail_batch", "driver_variable": "order_no", "per_item_delay_ms": 0}
    data["target"]["record_key"] = ["order_no"]
    data["target"]["fields"] = [
        {"key": "order_no", "name": "订单号", "required": True, "semantic": ["订单号"]},
        {"key": "customer", "name": "客户", "required": False, "semantic": ["客户"]},
    ]
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["output"]["columns"] = ["order_no", "customer"]
    data["output"]["filename_pattern"] = "orders"
    TemplateStore(root).save(BrowserTemplate.model_validate(data))


@pytest.fixture
def invoke_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, template_data: dict[str, Any]
) -> tuple[Any, FakeBrowserAdapter, Path]:
    root = tmp_path / "skill"
    (root / "runtime" / "src").mkdir(parents=True)
    _published_batch_template(template_data, root / "templates")
    adapter = FakeBrowserAdapter(
        {
            "capabilities": [CAPS] * 6,
            "snapshot": [HOME, _detail("ORD-1"), _detail("ORD-2"), _detail("ORD-3")],
        }
    )
    module = _patch_invoke(monkeypatch, root, adapter)
    return module, adapter, root


def _patch_invoke(monkeypatch: pytest.MonkeyPatch, root: Path, adapter: FakeBrowserAdapter) -> Any:
    """Point invoke.py at a temp skill root and a fake browser; env changes are scoped."""
    module = _load_invoke()
    monkeypatch.setattr(module, "_skill_root", lambda: root)
    monkeypatch.setenv("UNIVERSAL_BROWSER_SKILL_ROOT", str(root))
    import browser_skill.standalone as standalone

    monkeypatch.setattr(
        standalone,
        "make_standalone_app",
        lambda *_args, **_kwargs: BrowserSkillApp(
            root / "templates", root / "runs", adapter, samples_root=root / "runs" / "uploads"
        ),
    )
    return module


def _run(module: Any, capsys: pytest.CaptureFixture[str], argv: list[str]) -> dict[str, Any]:
    code = module.main(argv)
    out = capsys.readouterr().out
    payload = json.loads(out)
    payload["_exit_code"] = code
    return payload


def test_repeated_var_runs_a_batch(
    invoke_env: tuple[Any, FakeBrowserAdapter, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    module, adapter, _root = invoke_env

    payload = _run(
        module,
        capsys,
        ["run", "orders", "--var", "order_no=ORD-1", "--var", "order_no=ORD-2"],
    )

    assert payload["_exit_code"] == 0, payload["message"]
    assert payload["data"]["items"]["total"] == 2
    assert payload["data"]["items"]["ok"] == 2
    opened = [call[1][0] for call in adapter.calls if call[0] == "open"]
    assert "https://example.internal/orders/ORD-1" in opened
    assert "https://example.internal/orders/ORD-2" in opened


def test_var_file_column_feeds_the_driver_variable(
    invoke_env: tuple[Any, FakeBrowserAdapter, Path],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module, _adapter, _root = invoke_env
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("客户,订单号\n张三,ORD-1\n李四,ORD-2\n王五,ORD-3\n", encoding="utf-8")

    payload = _run(
        module,
        capsys,
        ["run", "orders", "--var-file", str(csv_path), "--var-column", "订单号"],
    )

    assert payload["_exit_code"] == 0, payload["message"]
    assert payload["data"]["items"] == {
        "total": 3,
        "pending": 0,
        "ok": 3,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "failed_values": [],
    }


def test_var_file_bad_column_is_reported_as_json_error(
    invoke_env: tuple[Any, FakeBrowserAdapter, Path],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module, _adapter, _root = invoke_env
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("客户,订单号\n张三,ORD-1\n", encoding="utf-8")

    payload = _run(
        module, capsys, ["run", "orders", "--var-file", str(csv_path), "--var-column", "编号"]
    )

    assert payload["_exit_code"] == 1
    assert payload["ok"] is False
    assert payload["data"]["error"]["code"] == "E_VARIABLE_INVALID"
    assert payload["data"]["error"]["details"]["columns"] == ["客户", "订单号"]


def test_probe_command_prints_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "skill"
    (root / "runtime" / "src").mkdir(parents=True)
    (root / "templates").mkdir()
    adapter = FakeBrowserAdapter(
        {
            "capabilities": [CAPS],
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/orders/ORD-1/detail",
                    title="订单详情",
                    text="退出登录\n订单号：ORD-1\n客户：ACME\n",
                    elements=[{"ref": "@c", "role": "link", "text": "合同.pdf"}],
                )
            ],
            "network": [CommandResult(ok=True, operation="network", data=[])],
        }
    )
    module = _patch_invoke(monkeypatch, root, adapter)

    payload = _run(module, capsys, ["probe", "https://example.internal/orders/ORD-1/detail"])

    assert payload["_exit_code"] == 0, payload["message"]
    probe = payload["data"]["probe"]
    assert probe["url_analysis"]["template_suggestion"] == (
        "https://example.internal/orders/{order_no}/detail"
    )
    assert {item["key"] for item in probe["fields"]} >= {"order_no", "customer"}
    assert probe["attachments"][0]["name"] == "合同"
    assert payload["data"]["interaction"]["actions"][0] == "create_from_probe"
