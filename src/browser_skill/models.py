from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    TESTING = "testing"
    PUBLISHED = "published"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class RunState(StrEnum):
    INIT = "INIT"
    INPUT_READY = "INPUT_READY"
    AUTH_CHECK = "AUTH_CHECK"
    WAIT_USER_AUTH = "WAIT_USER_AUTH"
    NAVIGATING = "NAVIGATING"
    EXTRACTING = "EXTRACTING"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    WRITING_OUTPUT = "WRITING_OUTPUT"
    REPAIRING = "REPAIRING"
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VariableType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    ENUM = "enum"


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"


class SourcePage(StrEnum):
    LIST = "list"
    DETAIL = "detail"


class PaginationStrategy(StrEnum):
    NONE = "none"
    NEXT_BUTTON = "next_button"
    PAGE_NUMBER = "page_number"
    LOAD_MORE = "load_more"
    INFINITE_SCROLL = "infinite_scroll"


class AcquisitionSource(StrEnum):
    API = "api"
    NETWORK = "network"
    DOM = "dom"
    BROWSER = "browser"
    VISION = "vision"


class OutputFormat(StrEnum):
    JSON = "json"
    CSV = "csv"
    XLSX = "xlsx"
    BOTH = "both"
    FILES_ONLY = "files-only"


_URL_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class SystemSpec(StrictModel):
    entry_url: HttpUrl
    preferred_tab_url_contains: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    url_template: str | None = Field(default=None, max_length=2000)
    """Detail-page address with ``{variable}`` placeholders (detail_batch templates)."""

    @model_validator(mode="after")
    def default_allowed_host(self) -> SystemSpec:
        if not self.allowed_hosts and self.entry_url.host:
            self.allowed_hosts = [self.entry_url.host]
        if self.url_template is not None:
            parsed = urlsplit(self.url_template)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("url_template must be an absolute http(s) URL")
            if _URL_PLACEHOLDER.search(parsed.netloc):
                raise ValueError("url_template placeholders are not allowed in the host part")
            if parsed.hostname not in self.allowed_hosts:
                raise ValueError("url_template host must be listed in allowed_hosts")
        return self

    def url_template_variables(self) -> list[str]:
        if not self.url_template:
            return []
        seen: list[str] = []
        for name in _URL_PLACEHOLDER.findall(self.url_template):
            if name not in seen:
                seen.append(name)
        return seen


class RunMode(StrEnum):
    LIST = "list"
    DETAIL_BATCH = "detail_batch"


class RunSpec(StrictModel):
    """How a template is executed. Defaults reproduce the classic list workflow."""

    mode: RunMode = RunMode.LIST
    driver_variable: str | None = None
    concurrency: int = Field(default=1, ge=1, le=4)
    per_item_delay_ms: int = Field(default=300, ge=0, le=60_000)
    on_item_error: Literal["continue", "stop"] = "continue"
    dedupe_values: bool = True
    max_items: int = Field(default=500, ge=1, le=10_000)
    accept_full_urls: bool = True
    capture_tables: bool = False
    # Incremental runs: values already ``ok`` in an earlier run of this template are skipped
    skip_if_exists: bool = False


class SignalSpec(StrictModel):
    url_contains: str | None = None
    semantic_element: str | None = None

    @model_validator(mode="after")
    def exactly_one_signal(self) -> SignalSpec:
        if (self.url_contains is None) == (self.semantic_element is None):
            raise ValueError("signal must set exactly one of url_contains or semantic_element")
        return self


class LoginCheckSpec(StrictModel):
    any: list[SignalSpec] = Field(min_length=1)


class AuthSpec(StrictModel):
    strategy: Literal["reuse_current_chrome_session"] = "reuse_current_chrome_session"
    login_check: LoginCheckSpec
    unauthenticated_signals: list[SignalSpec] = Field(default_factory=list)


class VariableValidation(StrictModel):
    regex: str | None = None
    minimum: float | None = None
    maximum: float | None = None


class VariableSpec(StrictModel):
    type: VariableType
    required: bool = False
    default: Any | None = None
    prompt: str
    options: list[str] = Field(default_factory=list)
    validation: VariableValidation | None = None
    sensitive: bool = False
    multiple: bool = False
    """Accept a list of values (pasted lines / CSV column); used by detail_batch drivers."""

    @model_validator(mode="after")
    def enum_requires_options(self) -> VariableSpec:
        if self.type == VariableType.ENUM and not self.options:
            raise ValueError("enum variable requires options")
        return self


class FieldSpec(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1)
    type: FieldType = FieldType.STRING
    required: bool = False
    semantic: list[str] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    source: SourcePage = SourcePage.LIST
    validation_rule: str | None = Field(default=None, max_length=500)


class AttachmentSpec(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1)
    required: bool = False
    semantic: list[str] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    source: SourcePage = SourcePage.DETAIL
    per_record: bool = True
    multiple: bool = False
    match_by: list[str] = Field(default_factory=list)
    file_types: list[str] = Field(default_factory=list)
    filename_pattern: str = "{original_name}"
    destination_subdir: str = "attachments"
    max_count: int | None = Field(default=None, ge=1)
    min_size_bytes: int | None = Field(default=None, ge=0)
    max_size_bytes: int | None = Field(default=None, ge=1)

    @field_validator("file_types")
    @classmethod
    def normalize_types(cls, values: list[str]) -> list[str]:
        return [value.lower().lstrip(".") for value in values]


class PaginationSpec(StrictModel):
    strategy: PaginationStrategy = PaginationStrategy.NONE
    semantic: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=100, ge=1, le=10_000)
    max_idle_rounds: int = Field(default=3, ge=1, le=20)

    @model_validator(mode="after")
    def semantic_required_for_control(self) -> PaginationSpec:
        if (
            self.strategy
            in {
                PaginationStrategy.NEXT_BUTTON,
                PaginationStrategy.LOAD_MORE,
            }
            and not self.semantic
        ):
            raise ValueError("pagination control strategy requires semantic hints")
        return self


class TargetSpec(StrictModel):
    record_key: list[str] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(default_factory=list)
    attachments: list[AttachmentSpec] = Field(default_factory=list)
    pagination: PaginationSpec = Field(default_factory=PaginationSpec)

    @model_validator(mode="after")
    def keys_are_valid_and_unique(self) -> TargetSpec:
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("field keys must be unique")
        attachment_keys = [item.key for item in self.attachments]
        if len(attachment_keys) != len(set(attachment_keys)):
            raise ValueError("attachment keys must be unique")
        missing = set(self.record_key) - set(keys)
        if missing:
            raise ValueError(f"record_key references unknown fields: {sorted(missing)}")
        if any(item.per_record for item in self.attachments) and not self.record_key:
            raise ValueError("per-record attachments require target.record_key")
        for attachment in self.attachments:
            missing = set(attachment.match_by) - set(keys)
            if missing:
                raise ValueError(
                    f"attachment {attachment.key} match_by references unknown fields: "
                    f"{sorted(missing)}"
                )
        return self


class WorkflowHint(StrictModel):
    action: Literal[
        "ensure_page", "set_filter", "query", "extract", "open_detail", "return_to_list"
    ]
    target: str
    value: str | None = None
    dom_hint: str | None = Field(default=None, max_length=500)

    @field_validator("dom_hint")
    @classmethod
    def safe_dom_hint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        allowed = ("xpath=", "css=", "//", "/html/", "#", ".", "[")
        if not normalized.startswith(allowed):
            raise ValueError("dom_hint must be a selector or XPath, never script or coordinates")
        return normalized


class WorkflowSpec(StrictModel):
    hints: list[WorkflowHint] = Field(default_factory=list)
    iterate_detail_if_needed: bool = False
    detail_link_semantic: list[str] = Field(default_factory=lambda: ["详情", "查看", "明细"])
    return_to_list_action: Literal["browser_back", "semantic"] = "browser_back"
    return_to_list_semantic: list[str] = Field(default_factory=lambda: ["返回", "返回列表"])


class LearnedMapping(StrictModel):
    page: SourcePage
    strategy: Literal["semantic", "table_header", "label_value", "dom_hint"]
    hints: list[str] = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    preferred_source: AcquisitionSource | None = None
    endpoint_hint: str | None = Field(default=None, max_length=500)
    json_path: str | None = Field(default=None, max_length=500)


class LearnedSpec(StrictModel):
    page_hints: list[str] = Field(default_factory=list)
    field_mappings: dict[str, LearnedMapping] = Field(default_factory=dict)
    attachment_mappings: dict[str, LearnedMapping] = Field(default_factory=dict)
    validated_at: datetime | None = None


class LearnedProfileDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    template_version: int = Field(ge=1)
    learned: LearnedSpec = Field(default_factory=LearnedSpec)


class ValidationSpec(StrictModel):
    required_fields_complete: bool = True
    pagination_complete: bool = True
    downloads_complete_for_required: bool = True
    unique_record_keys: bool = True
    min_records: int = Field(default=0, ge=0)
    max_records: int | None = Field(default=None, ge=1)


class OutputSpec(StrictModel):
    format: OutputFormat = OutputFormat.BOTH
    columns: list[str] = Field(default_factory=list)
    filename_pattern: str = "result"
    attachments_dir: str = "attachments"
    include_source_metadata: bool = True
    manifest: bool = True


class ProcessingStepSpec(StrictModel):
    action: Literal["rename_field", "coerce_type", "default_value", "dedupe_records"] = (
        "rename_field"
    )
    params: dict[str, Any] = Field(default_factory=dict)


class ProcessingSpec(StrictModel):
    enabled: bool = False
    steps: list[ProcessingStepSpec] = Field(default_factory=list)


class AnalysisSpec(StrictModel):
    enabled: bool = False
    prompt_template: str = ""
    model_hint: str | None = None
    compare_with_previous: bool = True
    record_change_threshold: float = Field(default=0.5, ge=0.0, le=10.0)


class ReportSpec(StrictModel):
    enabled: bool = False
    title_pattern: str = "{template_id} Report"
    include_summary: bool = True


class DeliveryChannelSpec(StrictModel):
    """One delivery destination.

    ``target`` is a directory (local), an http(s) URL (webhook / wecom robot) or a comma-separated
    recipient list (email). Credentials never live in templates: SMTP settings come from
    ``UNIVERSAL_BROWSER_SMTP_*`` environment variables. ``options`` holds channel-specific knobs
    such as ``subject``, ``attach``, ``max_attachment_mb`` or ``mentioned_mobile_list``.
    """

    type: Literal["local", "webhook", "email", "wecom"] = "local"
    target: str = ""
    enabled: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class DeliverySpec(StrictModel):
    enabled: bool = False
    channels: list[DeliveryChannelSpec] = Field(default_factory=list)


class BrowserTemplate(StrictModel):
    schema_version: Literal["1.0", "2.0"] = "1.0"
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    status: TemplateStatus
    version: int = Field(ge=1)
    system: SystemSpec
    auth: AuthSpec
    variables: dict[str, VariableSpec] = Field(default_factory=dict)
    run: RunSpec = Field(default_factory=RunSpec)
    target: TargetSpec
    workflow: WorkflowSpec = Field(default_factory=WorkflowSpec)
    learned: LearnedSpec = Field(default_factory=LearnedSpec)
    processing: ProcessingSpec = Field(default_factory=ProcessingSpec)
    analysis: AnalysisSpec = Field(default_factory=AnalysisSpec)
    report: ReportSpec = Field(default_factory=ReportSpec)
    delivery: DeliverySpec = Field(default_factory=DeliverySpec)
    validation: ValidationSpec = Field(default_factory=ValidationSpec)
    output: OutputSpec = Field(default_factory=OutputSpec)

    @model_validator(mode="after")
    def mappings_and_columns_reference_targets(self) -> BrowserTemplate:
        field_keys = {field.key for field in self.target.fields}
        attachment_keys = {item.key for item in self.target.attachments}
        if unknown := set(self.learned.field_mappings) - field_keys:
            raise ValueError(f"learned field mappings reference unknown keys: {sorted(unknown)}")
        if unknown := set(self.learned.attachment_mappings) - attachment_keys:
            raise ValueError(f"attachment mappings reference unknown keys: {sorted(unknown)}")
        if unknown := set(self.output.columns) - field_keys:
            raise ValueError(f"output columns reference unknown keys: {sorted(unknown)}")
        if unknown := set(self.system.url_template_variables()) - set(self.variables):
            raise ValueError(f"url_template references undeclared variables: {sorted(unknown)}")
        if self.run.mode == RunMode.DETAIL_BATCH:
            driver = self.run.driver_variable
            if not driver:
                raise ValueError("detail_batch templates require run.driver_variable")
            spec = self.variables.get(driver)
            if spec is None:
                raise ValueError(f"run.driver_variable references unknown variable: {driver}")
            if not spec.multiple:
                raise ValueError("run.driver_variable must be declared with multiple: true")
            if not self.system.url_template and not self.run.accept_full_urls:
                raise ValueError(
                    "detail_batch templates need system.url_template or accept_full_urls"
                )
        elif self.run.driver_variable is not None:
            raise ValueError("run.driver_variable is only valid when run.mode is detail_batch")
        return self


class BrowserCapabilities(StrictModel):
    snapshot: bool = False
    snapshot_diff: bool = False
    find: bool = False
    download: bool = False
    downloads: bool = False
    tabs: bool = False
    sessions: bool = False
    dialogs: bool = False
    network: bool = False
    screenshot: bool = False


class NetworkExchange(StrictModel):
    """One observed HTTP exchange from the user's browser session (response body parsed)."""

    url: str
    method: str = "GET"
    status: int = Field(default=200, ge=0, le=999)
    content_type: str = ""
    body: Any | None = None
    size: int = Field(default=0, ge=0)

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type.casefold() or isinstance(self.body, (dict, list))


class CommandResult(StrictModel):
    ok: bool
    operation: str
    data: Any | None = None
    safe_stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0


class BrowserSnapshot(StrictModel):
    url: str = ""
    title: str = ""
    text: str = ""
    elements: list[dict[str, Any]] = Field(default_factory=list)
    records: list[dict[str, Any]] = Field(default_factory=list)


class AuthState(StrEnum):
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    UNKNOWN = "unknown"


class DownloadStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    FAILED = "failed"
    REJECTED = "rejected"


class DownloadedFile(StrictModel):
    record_key: str | None = None
    attachment_key: str
    relative_path: str
    original_name: str | None = None
    size: int = Field(default=0, ge=0)
    sha256: str | None = None
    status: DownloadStatus
    # Set when the same source URL was already fetched in this run and the bytes were copied
    copied_from: str | None = None


class ValidationIssue(StrictModel):
    code: str
    message: str
    required: bool = True
    record_key: str | None = None


class ValidationReport(StrictModel):
    ok: bool
    partial: bool = False
    issues: list[ValidationIssue] = Field(default_factory=list)
    record_count: int = 0
    download_count: int = 0
    field_completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    download_success_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class Checkpoint(StrictModel):
    state: RunState
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page_url: str | None = None
    record_offset: int = 0


class BatchItemStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    # Not visited in this run because an earlier run of the same template already got it
    SKIPPED = "skipped"


class BatchItemState(StrictModel):
    """Durable per-value progress of a detail_batch run (persisted in batch.json)."""

    index: int = Field(ge=0)
    value: str
    url: str
    status: BatchItemStatus = BatchItemStatus.PENDING
    record_count: int = Field(default=0, ge=0)
    file_count: int = Field(default=0, ge=0)
    reason: str | None = None
    error: dict[str, Any] | None = None
    finished_at: datetime | None = None

    @property
    def done(self) -> bool:
        return self.status in {BatchItemStatus.OK, BatchItemStatus.PARTIAL, BatchItemStatus.SKIPPED}


class BatchProgress(StrictModel):
    driver_variable: str
    template_id: str | None = None
    items: list[BatchItemState] = Field(default_factory=list)

    def stats(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in BatchItemStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return {
            "total": len(self.items),
            **counts,
            "failed_values": [
                item.value for item in self.items if item.status == BatchItemStatus.FAILED
            ],
        }


class RunContext(StrictModel):
    run_id: str
    template_id: str
    template_version: int
    template_snapshot: BrowserTemplate
    variables: dict[str, Any] = Field(default_factory=dict)
    session_name: str = "current"
    workspace: Path
    state: RunState = RunState.INIT
    records: list[dict[str, Any]] = Field(default_factory=list)
    downloaded_files: list[DownloadedFile] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    batch: BatchProgress | None = None
    pagination_complete: bool = True
    repair_attempts: int = 0
    recovery_run_id: str | None = None
    repaired_template_version: int | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class TemplateDraftInput(StrictModel):
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=100)
    entry_url: HttpUrl
    description: str = Field(default="", max_length=300)
    fields: list[FieldSpec] = Field(min_length=1)
    attachments: list[AttachmentSpec] = Field(default_factory=list)
    variables: dict[str, VariableSpec] = Field(default_factory=dict)
    record_key: list[str] = Field(default_factory=list)
    page_hints: list[str] = Field(default_factory=list, max_length=20)


class UrlVariableSuggestion(StrictModel):
    """A URL path segment / query value that looks like the business id of the page."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    sample: str
    position: str
    """``path[<index>]`` or ``query:<key>``."""
    confidence: float = Field(ge=0.0, le=1.0)
    selected: bool = False


class UrlAnalysis(StrictModel):
    url: str
    host: str
    template_suggestion: str
    variables: list[UrlVariableSuggestion] = Field(default_factory=list)


ProbeSource = Literal["url", "dom", "table", "network"]


class ProbeFieldCandidate(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1)
    sample: str = ""
    source: ProbeSource
    strategy: Literal["semantic", "label_value", "table_header"] = "label_value"
    type: FieldType = FieldType.STRING
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    endpoint_hint: str | None = Field(default=None, max_length=500)
    json_path: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list)


class ProbeAttachmentCandidate(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1)
    count: int = Field(default=1, ge=1)
    types: list[str] = Field(default_factory=list)
    sample_href: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class UrlProbeReport(StrictModel):
    url_analysis: UrlAnalysis
    page_title: str = ""
    auth_state: AuthState = AuthState.UNKNOWN
    fields: list[ProbeFieldCandidate] = Field(default_factory=list)
    attachments: list[ProbeAttachmentCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    network_exchanges: int = Field(default=0, ge=0)


class ProbeDraftInput(StrictModel):
    """What the wizard sends back after the user ticked fields/attachments from a probe."""

    template_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    sample_url: HttpUrl
    url_template: str | None = Field(default=None, max_length=2000)
    driver_variable: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    driver_prompt: str | None = Field(default=None, max_length=200)
    driver_regex: str | None = Field(default=None, max_length=200)
    fields: list[ProbeFieldCandidate] = Field(min_length=1)
    attachments: list[ProbeAttachmentCandidate] = Field(default_factory=list)
    record_key: list[str] = Field(default_factory=list)
    required_keys: list[str] = Field(default_factory=list)
    run: dict[str, Any] = Field(default_factory=dict)
    page_hints: list[str] = Field(default_factory=list, max_length=20)


class SampleInference(StrictModel):
    fields: list[FieldSpec] = Field(min_length=1)
    attachment_columns: list[str] = Field(default_factory=list)
    variable_candidates: list[str] = Field(default_factory=list)
    record_key_candidates: list[str] = Field(default_factory=list)
    sample_record_count: int = Field(default=0, ge=0)


class MappingDiscoveryReport(StrictModel):
    learned: LearnedSpec
    matched_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    matched_attachments: list[str] = Field(default_factory=list)
    missing_required_attachments: list[str] = Field(default_factory=list)
    page_url: str = ""

    @property
    def publishable_candidate(self) -> bool:
        return not self.missing_required_fields and not self.missing_required_attachments


class RunMetricsReport(StrictModel):
    scanned_runs: int = 0
    ignored_runs: int = 0
    state_counts: dict[str, int] = Field(default_factory=dict)
    template_counts: dict[str, int] = Field(default_factory=dict)
    total_records: int = 0
    total_downloads: int = 0
    average_duration_ms: float = 0.0
    average_field_completeness: float = 1.0
    average_download_success_rate: float = 1.0
    repaired_runs: int = 0
    recovered_runs: int = 0


class SkillRequest(StrictModel):
    action: Literal[
        "start",
        "run",
        "resume",
        "status",
        "cancel",
        "recover",
        "metrics",
        "analyze_sample",
        "create",
        "discover",
        "test",
        "publish",
        "repair",
        "probe",
        "probe_url",
        "create_from_probe",
        "validate_acceptance",
    ] = "start"
    selector: str | int | None = None
    template_id: str | None = None
    run_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    # Batch runs: read one column of driver values from a text/CSV/TSV/XLSX file.
    values_file: Path | None = None
    values_column: str | None = None
    values_variable: str | None = None
    current_url: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    sample_path: Path | None = None
    draft: TemplateDraftInput | None = None
    probe_draft: ProbeDraftInput | None = None
    learned: LearnedSpec | None = None
    confirmed: bool = False
    acceptance_bundle_path: Path | None = None
    probe_mode: Literal["platform_tool", "local_cli"] = "platform_tool"


class SkillResponse(StrictModel):
    ok: bool
    message: str
    run_id: str | None = None
    state: RunState | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)


def date_today() -> date:
    return date.today()
