import asyncio
import json
from copy import deepcopy
from pathlib import Path

from browser_skill.app import BrowserSkillApp
from browser_skill.browser.fake import FakeBrowserAdapter
from browser_skill.models import (
    AttachmentSpec,
    BrowserSnapshot,
    BrowserTemplate,
    CommandResult,
    FieldSpec,
    LearnedSpec,
    SkillRequest,
    TemplateDraftInput,
    VariableSpec,
)
from browser_skill.templates.store import TemplateStore


def test_start_returns_platform_template_menu(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(template_data))
    app = BrowserSkillApp(templates_root, tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(app.handle(SkillRequest(action="start")))
    interaction = response.data["interaction"]
    assert interaction["kind"] == "template_menu"
    assert interaction["choices"][0]["id"] == "inventory_feedback"
    assert interaction["text"]


def test_run_requests_only_missing_required_variables(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    data = deepcopy(template_data)
    data["variables"]["date"].pop("default")  # type: ignore[index]
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(data))
    app = BrowserSkillApp(templates_root, tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="run",
                template_id="inventory_feedback",
                variables={},
            )
        )
    )
    interaction = response.data["interaction"]
    assert interaction["kind"] == "variable_form"
    assert [field["name"] for field in interaction["fields"]] == ["date"]


def test_resume_rejects_workspace_escape(tmp_path: Path) -> None:
    app = BrowserSkillApp(
        tmp_path / "templates",
        tmp_path / "runs",
        FakeBrowserAdapter(),
    )
    response = asyncio.run(app.handle(SkillRequest(action="resume", run_id="../../outside")))
    assert response.ok is False
    assert response.message == "run_id 无效"


def test_create_returns_reviewable_draft_and_next_version(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    store = TemplateStore(templates_root)
    store.save(BrowserTemplate.model_validate(template_data))
    app = BrowserSkillApp(templates_root, tmp_path / "runs", FakeBrowserAdapter())
    draft_input = TemplateDraftInput(
        template_id="inventory_feedback",
        name="样机盘点反馈新版",
        entry_url="https://example.internal/",
        fields=[
            FieldSpec(
                key="sn",
                name="SN",
                required=True,
                semantic=["SN", "序列号"],
            )
        ],
        attachments=[
            AttachmentSpec(
                key="evidence",
                name="凭证",
                semantic=["凭证附件"],
                per_record=True,
            )
        ],
        variables={"date": VariableSpec(type="date", required=True, prompt="请输入日期")},
        record_key=["sn"],
        page_hints=["资产管理", "盘点反馈"],
    )
    response = asyncio.run(app.handle(SkillRequest(action="create", draft=draft_input)))
    assert response.ok is True
    assert response.data["version"] == 2
    assert response.data["interaction"]["kind"] == "template_review"
    saved = store.load("inventory_feedback", 2, require_published=False)
    assert saved.name == "样机盘点反馈新版"
    assert saved.target.attachments[0].key == "evidence"
    assert saved.variables["date"].required is True
    assert saved.target.record_key == ["sn"]
    assert saved.learned.page_hints == ["资产管理", "盘点反馈"]


def test_repair_creates_testing_version_and_keeps_published_version(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    store = TemplateStore(templates_root)
    store.save(BrowserTemplate.model_validate(template_data))
    app = BrowserSkillApp(templates_root, tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="repair",
                template_id="inventory_feedback",
                learned=LearnedSpec(page_hints=["新版盘点页面"]),
            )
        )
    )
    assert response.ok is True
    assert response.data["version"] == 2
    assert store.load("inventory_feedback").version == 1
    assert store.load("inventory_feedback", 2, require_published=False).status == "testing"


def test_publish_without_confirmation_returns_structured_error(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(template_data))
    app = BrowserSkillApp(templates_root, tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="publish",
                template_id="inventory_feedback",
                version=1,
                run_id="run_test",
                confirmed=False,
            )
        )
    )
    assert response.ok is False
    assert response.data["interaction"]["kind"] == "error"
    assert response.data["error"]["code"] == "E_ACTION_NOT_ALLOWED"


def test_publish_with_exact_completed_evidence_returns_platform_result(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    data = deepcopy(template_data)
    data["status"] = "testing"
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(data))
    run_dir = tmp_path / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"template": "inventory_feedback@1", "state": "COMPLETED"}),
        encoding="utf-8",
    )
    app = BrowserSkillApp(templates_root, tmp_path / "runs", FakeBrowserAdapter())
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="publish",
                template_id="inventory_feedback",
                version=1,
                run_id="run_test",
                confirmed=True,
            )
        )
    )
    assert response.ok is True
    assert response.message == "模板已发布"
    assert response.data["interaction"]["actions"] == ["run_template"]


def test_analyze_sample_returns_editable_target_review(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "target.csv").write_text(
        "SN,产品型号,凭证附件\nSN-1,P-1,evidence.pdf\n",
        encoding="utf-8",
    )
    app = BrowserSkillApp(
        tmp_path / "templates",
        tmp_path / "runs",
        FakeBrowserAdapter(),
        samples_root=uploads,
    )
    response = asyncio.run(
        app.handle(SkillRequest(action="analyze_sample", sample_path=Path("target.csv")))
    )
    assert response.ok is True
    assert response.data["interaction"]["kind"] == "target_review"
    assert response.data["interaction"]["actions"] == [
        "accept_sample_inference",
        "edit_sample_inference",
        "cancel_template",
    ]


def test_metrics_returns_accessible_aggregate_interaction(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "run_metric"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps(
            {
                "state": "COMPLETED",
                "template": "inventory_feedback@1",
                "record_count": 4,
                "download_count": 2,
                "duration_ms": 20,
                "validation": {
                    "field_completeness": 1.0,
                    "download_success_rate": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    app = BrowserSkillApp(tmp_path / "templates", tmp_path / "runs", FakeBrowserAdapter())

    response = asyncio.run(app.handle(SkillRequest(action="metrics")))

    assert response.ok is True
    assert response.data["metrics"]["total_records"] == 4
    assert response.data["interaction"]["kind"] == "metrics"
    assert response.data["interaction"]["text"]


def test_analyze_sample_rejects_workspace_escape(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("SN\nA\n", encoding="utf-8")
    app = BrowserSkillApp(
        tmp_path / "templates",
        tmp_path / "runs",
        FakeBrowserAdapter(),
        samples_root=uploads,
    )
    response = asyncio.run(
        app.handle(SkillRequest(action="analyze_sample", sample_path=Path("../outside.csv")))
    )
    assert response.ok is False
    assert response.data["error"]["code"] == "E_UNSAFE_OUTPUT_PATH"


def test_discover_creates_testing_mapping_candidate_without_snapshot_refs(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    store = TemplateStore(templates_root)
    store.save(BrowserTemplate.model_validate(template_data))
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    title="盘点反馈",
                    text="退出登录",
                    elements=[
                        {"ref": "@field1", "text": "样机ID"},
                        {"ref": "@field2", "text": "SN"},
                        {"ref": "@attachment", "text": "凭证附件"},
                    ],
                )
            ]
        }
    )
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="discover",
                template_id="inventory_feedback",
                version=1,
            )
        )
    )
    assert response.ok is True
    assert response.data["candidate_version"] == 2
    assert response.data["interaction"]["kind"] == "mapping_review"
    candidate_path = templates_root / "inventory_feedback" / "2.yaml"
    candidate = candidate_path.read_text(encoding="utf-8")
    assert "@field1" not in candidate
    assert "@field2" not in candidate
    assert store.load("inventory_feedback").version == 1


def test_discover_requires_authentication_before_mapping(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(template_data))
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/login",
                    text="用户名 登录",
                )
            ]
        }
    )
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)
    response = asyncio.run(
        app.handle(
            SkillRequest(
                action="discover",
                template_id="inventory_feedback",
                version=1,
            )
        )
    )
    assert response.ok is False
    assert response.data["error"]["code"] == "E_AUTH_REQUIRED"
    assert not (templates_root / "inventory_feedback" / "2.yaml").exists()


def test_discover_explores_declared_page_hints_before_creating_candidate(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    data = deepcopy(template_data)
    data["learned"]["page_hints"] = ["资产管理", "盘点反馈"]  # type: ignore[index]
    templates_root = tmp_path / "templates"
    store = TemplateStore(templates_root)
    store.save(BrowserTemplate.model_validate(data))
    adapter = FakeBrowserAdapter(
        {
            "snapshot": [
                BrowserSnapshot(
                    url="https://example.internal/home",
                    text="退出登录",
                ),
                BrowserSnapshot(
                    url="https://example.internal/assets",
                    text="退出登录",
                    elements=[{"text": "样机ID"}],
                ),
                BrowserSnapshot(
                    url="https://example.internal/inventory",
                    text="退出登录",
                    elements=[{"text": "SN"}, {"text": "产品型号"}],
                ),
            ],
            "find_result": [
                CommandResult(ok=True, operation="find", data={"ref": "@assets"}),
                CommandResult(ok=True, operation="find", data={"ref": "@inventory"}),
            ],
        }
    )
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)

    response = asyncio.run(
        app.handle(SkillRequest(action="discover", template_id="inventory_feedback", version=1))
    )

    assert response.ok is True
    assert response.data["candidate_version"] == 2
    assert response.data["exploration"]["visited_urls"] == [
        "https://example.internal/home",
        "https://example.internal/assets",
        "https://example.internal/inventory",
    ]
    assert response.data["exploration"]["steps"] == 6
    candidate = store.load("inventory_feedback", 2, require_published=False)
    assert set(candidate.learned.field_mappings) == {"sample_id", "sn", "product_model"}


def test_platform_can_query_and_cancel_auth_paused_run(
    tmp_path: Path, template_data: dict[str, object]
) -> None:
    templates_root = tmp_path / "templates"
    TemplateStore(templates_root).save(BrowserTemplate.model_validate(template_data))
    adapter = FakeBrowserAdapter(
        {"snapshot": [BrowserSnapshot(url="https://example.internal/login", text="用户名 登录")]}
    )
    app = BrowserSkillApp(templates_root, tmp_path / "runs", adapter)
    started = asyncio.run(app.handle(SkillRequest(action="run", template_id="inventory_feedback")))
    status = asyncio.run(app.handle(SkillRequest(action="status", run_id=started.run_id)))
    assert status.state == "WAIT_USER_AUTH"
    assert status.data["interaction"]["kind"] == "progress"
    cancelled = asyncio.run(app.handle(SkillRequest(action="cancel", run_id=started.run_id)))
    assert cancelled.state == "CANCELLED"
    assert cancelled.data["interaction"]["actions"] == []
