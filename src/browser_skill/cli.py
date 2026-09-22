from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from browser_skill.app import parse_variables
from browser_skill.browser.chrome_use import ChromeUseAdapter, ChromeUseToolAdapter
from browser_skill.errors import SkillError
from browser_skill.interaction.template_menu import TemplateMenu
from browser_skill.interaction.variables import VariableResolver
from browser_skill.models import BrowserTemplate, RunState
from browser_skill.platform.acceptance import validate_acceptance_bundle
from browser_skill.platform.probe import probe_adapter
from browser_skill.runtime.repair import RepairService
from browser_skill.runtime.runner import Runner
from browser_skill.runtime.teach import TeachCompiler
from browser_skill.templates.store import TemplateStore

app = typer.Typer(
    name="browser-skill",
    help="Template-driven tasks in your signed-in Chrome session.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


def _store(path: Path) -> TemplateStore:
    return TemplateStore(path)


@app.command("templates")
def list_templates(
    root: Annotated[Path, typer.Option("--root", help="Template store root")] = Path("templates"),
    all_versions: Annotated[
        bool, typer.Option("--all", help="Include unpublished templates")
    ] = False,
) -> None:
    """Show a calm, stable template menu."""
    items = _store(root).list(include_unpublished=all_versions)
    title = Text(" Universal Browser ", style="bold white on #4f46e5")
    console.print(
        Panel(title, subtitle="目标驱动 · 真实 Chrome · 结果校验", border_style="#6366f1")
    )
    table = Table(box=box.ROUNDED, border_style="#6366f1", header_style="bold #a5b4fc")
    table.add_column("#", justify="right", style="bold cyan", width=4)
    table.add_column("模板", style="bold white")
    table.add_column("说明", style="dim")
    table.add_column("版本", justify="center")
    table.add_column("状态", justify="center")
    for index, item in enumerate(items, 1):
        table.add_row(
            str(index), item.name, item.description or "—", f"v{item.version}", item.status.value
        )
    table.add_row(str(len(items) + 1), "＋ 创建新模板", "进入 Teach 模式", "—", "draft")
    console.print(table)
    if not items:
        console.print("[dim]还没有可用模板。选择 1 开始创建。[/dim]")


@app.command()
def inspect(
    selector: str,
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
) -> None:
    """Inspect a template's contract without exposing learned browser internals."""
    store = _store(root)
    template_id = TemplateMenu(store.list(include_unpublished=True)).resolve(selector)
    if template_id is None:
        raise typer.BadParameter("The create item is not a template")
    template = store.load(template_id, require_published=False)
    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column(style="bold #818cf8")
    table.add_column()
    table.add_row(
        "模板", f"{template.name}  [dim]({template.template_id}@{template.version})[/dim]"
    )
    table.add_row("状态", template.status.value)
    table.add_row("入口", str(template.system.entry_url))
    table.add_row("变量", ", ".join(template.variables) or "无")
    table.add_row("字段", ", ".join(field.name for field in template.target.fields) or "无")
    table.add_row("附件", ", ".join(item.name for item in template.target.attachments) or "无")
    table.add_row("输出", template.output.format.value)
    console.print(Panel(table, title="[bold]模板契约[/bold]", border_style="#6366f1"))


@app.command("create")
def create_template(
    template_id: Annotated[str, typer.Option(prompt="模板 ID（小写 snake_case）")],
    name: Annotated[str, typer.Option(prompt="模板名称")],
    entry_url: Annotated[str, typer.Option(prompt="系统入口 URL")],
    field: Annotated[
        list[str] | None,
        typer.Option("--field", help="Field key:name[:required], repeatable"),
    ] = None,
    description: Annotated[str, typer.Option(prompt="简要说明")] = "",
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
) -> None:
    """Create a safe Teach-mode draft from an explicit target field list."""
    definitions: list[dict[str, object]] = []
    for value in field or []:
        parts = value.split(":")
        if len(parts) < 2:
            raise typer.BadParameter("--field must be key:name[:required]")
        key, display_name = parts[:2]
        required = len(parts) > 2 and parts[2].casefold() in {"required", "true", "yes", "1"}
        definitions.append(
            {
                "key": key,
                "name": display_name,
                "required": required,
                "semantic": [display_name],
                "source": "list",
            }
        )
    if not definitions:
        raise typer.BadParameter("At least one --field is required")
    try:
        draft = TeachCompiler().compile_draft(
            template_id=template_id,
            name=name,
            description=description,
            entry_url=entry_url,
            fields=definitions,
        )
        path = _store(root).save(draft)
        console.print(
            Panel(
                f"[bold green]草稿已创建[/bold green]\n{draft.name}\n[dim]{path}[/dim]\n\n"
                "下一步：检查模板、执行 test、确认结果后 publish。",
                border_style="green",
            )
        )
    except SkillError as exc:
        console.print(Panel(str(exc), title="[red]创建失败[/red]", border_style="red"))
        raise typer.Exit(2) from exc


@app.command("doctor")
def doctor(
    executable: Annotated[str, typer.Option(help="chrome-use executable")] = "chrome-use",
) -> None:
    """Probe the installed browser bridge before a real run."""

    async def check() -> object:
        adapter = ChromeUseAdapter(executable=executable)
        return await probe_adapter(adapter, mode="local_cli")

    report = asyncio.run(check())
    table = Table(box=box.ROUNDED, title="环境诊断", border_style="#6366f1")
    table.add_column("检查项")
    table.add_column("结果", justify="center")
    table.add_row("status", "[green]✓[/green]" if report.status_ok else "[red]✗[/red]")
    for name, enabled in report.capabilities.model_dump().items():
        table.add_row(name, "[green]✓[/green]" if enabled else "[yellow]—[/yellow]")
    console.print(table)
    console.print(Panel(report.text, title="诊断摘要", border_style="#6366f1"))
    if not report.ready:
        raise typer.Exit(1)
    console.print("[bold green]环境已就绪。[/bold green]")


@app.command("probe-platform")
def probe_platform(
    report_out: Annotated[
        Path | None, typer.Option("--report-out", help="Write JSON probe report")
    ] = None,
    fixture: Annotated[
        Path | None,
        typer.Option(
            help="Replay a recorded platform capabilities payload instead of a live invoker"
        ),
    ] = None,
) -> None:
    """Verify the injected platform chrome-use tool against the release contract."""

    async def run_probe() -> object:
        if fixture is not None:
            payload = json.loads(fixture.read_text(encoding="utf-8"))

            async def invoke(_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
                if arguments.get("operation") == "status":
                    return {"ok": True, "data": {"ready": True}}
                if arguments.get("operation") == "capabilities":
                    return payload
                return {"ok": True, "data": {"operation": arguments.get("operation")}}

            adapter = ChromeUseToolAdapter(invoke)
        else:
            raise typer.BadParameter(
                "Provide --fixture with a recorded capabilities response, "
                "or invoke probe through the Agent platform app action against a live invoker."
            )
        return await probe_adapter(adapter, mode="platform_tool")

    report = asyncio.run(run_probe())
    console.print(Panel(report.text, title="平台能力探针", border_style="#6366f1"))
    if report_out is not None:
        report_out.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        console.print(f"[dim]Report written to {report_out}[/dim]")
    if not report.ready:
        raise typer.Exit(1)


@app.command("validate-acceptance")
def validate_acceptance(
    bundle: Annotated[Path, typer.Argument(help="Acceptance evidence bundle JSON")],
    require_sign_off: Annotated[
        bool, typer.Option(help="Require approved sign_off block")
    ] = False,
) -> None:
    """Validate the structure of an internal-platform acceptance evidence bundle."""
    result = validate_acceptance_bundle(bundle, require_sign_off=require_sign_off)
    color = "green" if result.ok else "red"
    console.print(Panel(result.text, title="验收证据校验", border_style=color))
    for warning in result.warnings:
        console.print(f"[yellow]{warning}[/yellow]")
    if not result.ok:
        raise typer.Exit(2)


@app.command()
def run(
    selector: str,
    variable: Annotated[list[str] | None, typer.Option("--var", help="Runtime name=value")] = None,
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
    runs_root: Annotated[Path, typer.Option("--runs-root")] = Path("runs"),
    executable: Annotated[str, typer.Option(help="chrome-use executable")] = "chrome-use",
    dry_run: Annotated[bool, typer.Option(help="Validate without browser actions")] = False,
) -> None:
    """Run a published template with a concise progress summary."""
    try:
        store = _store(root)
        template_id = TemplateMenu(store.list()).resolve(selector)
        if template_id is None:
            console.print("[cyan]请选择 Teach 流程创建模板。[/cyan]")
            raise typer.Exit()
        template = store.load(template_id)
        supplied = parse_variables(variable or [])
        resolver = VariableResolver()
        for name in resolver.missing(template, supplied):
            spec = template.variables[name]
            suffix = f" ({'/'.join(spec.options)})" if spec.options else ""
            supplied[name] = typer.prompt(f"{spec.prompt}{suffix}", hide_input=spec.sensitive)
        console.print(
            Panel(
                f"[bold]{template.name}[/bold]\n[dim]{template.description}[/dim]",
                border_style="#6366f1",
            )
        )
        with console.status("[bold #818cf8]正在执行并校验业务结果…[/bold #818cf8]", spinner="dots"):
            response = asyncio.run(
                Runner(ChromeUseAdapter(executable=executable), runs_root).run(
                    template, supplied, dry_run=dry_run
                )
            )
        color = (
            "green"
            if response.ok
            else "yellow"
            if response.state == RunState.WAIT_USER_AUTH
            else "red"
        )
        console.print(
            Panel(
                f"[bold {color}]{response.message}[/bold {color}]\n"
                f"[dim]Run ID: {response.run_id or '—'} · 状态: {response.state or '—'}[/dim]",
                title="执行结果",
                border_style=color,
            )
        )
        if response.data.get("artifacts"):
            for name, path in response.data["artifacts"].items():
                console.print(f"  [cyan]↳[/cyan] {name}: {path}")
        if not response.ok:
            raise typer.Exit(2)
    except (SkillError, ValueError) as exc:
        console.print(Panel(str(exc), title="[red]无法执行[/red]", border_style="red"))
        raise typer.Exit(2) from exc


@app.command("ui")
def local_console(
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
    runs_root: Annotated[Path, typer.Option("--runs-root")] = Path("runs"),
    executable: Annotated[str, typer.Option(help="chrome-use executable")] = "chrome-use",
    port: Annotated[int, typer.Option(help="Port (0 = random free port)")] = 8765,
    no_browser: Annotated[bool, typer.Option("--no-browser")] = False,
) -> None:
    """Open the local web console (binds to 127.0.0.1 only)."""
    from browser_skill.app import BrowserSkillApp
    from browser_skill.console.server import serve_console

    skill_app = BrowserSkillApp(root, runs_root, ChromeUseAdapter(executable=executable))
    serve_console(skill_app, port=port, open_browser=not no_browser)


@app.command("test")
def test_template(
    selector: str,
    variable: Annotated[list[str] | None, typer.Option("--var")] = None,
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
    runs_root: Annotated[Path, typer.Option("--runs-root")] = Path("runs"),
    executable: Annotated[str, typer.Option(help="chrome-use executable")] = "chrome-use",
) -> None:
    """Execute an unpublished template and retain evidence for the publish gate."""
    try:
        store = _store(root)
        template_id = TemplateMenu(store.list(include_unpublished=True)).resolve(selector)
        if template_id is None:
            raise typer.BadParameter("Select a template, not the create item")
        template = store.load(template_id, require_published=False)
        supplied = parse_variables(variable or [])
        resolver = VariableResolver()
        for name in resolver.missing(template, supplied):
            spec = template.variables[name]
            supplied[name] = typer.prompt(spec.prompt, hide_input=spec.sensitive)
        with console.status("[bold #818cf8]正在执行完整 Test Run…[/bold #818cf8]"):
            response = asyncio.run(
                Runner(ChromeUseAdapter(executable=executable), runs_root).run(template, supplied)
            )
        console.print(
            Panel(
                f"{response.message}\n[dim]Run ID: {response.run_id} · {response.state}[/dim]",
                border_style="green" if response.ok else "red",
            )
        )
        if not response.ok:
            raise typer.Exit(2)
    except (SkillError, ValueError) as exc:
        console.print(Panel(str(exc), title="[red]测试失败[/red]", border_style="red"))
        raise typer.Exit(2) from exc


@app.command("publish")
def publish_template(
    template_id: str,
    version: int,
    run_id: Annotated[str, typer.Option(help="Passing Test Run evidence")],
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
    runs_root: Annotated[Path, typer.Option("--runs-root")] = Path("runs"),
) -> None:
    """Publish only when a matching completed Test Run is present."""
    summary_path = (runs_root / run_id / "summary.json").resolve()
    if runs_root.resolve() not in summary_path.parents or not summary_path.exists():
        raise typer.BadParameter("Test Run summary was not found")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = f"{template_id}@{version}"
    passed = (
        summary.get("template") == expected and summary.get("state") == RunState.COMPLETED.value
    )
    if not passed:
        console.print("[red]Test Run does not prove this exact template version passed.[/red]")
        raise typer.Exit(2)
    published = _store(root).publish(template_id, version, test_passed=True)
    console.print(f"[bold green]✓ 已发布 {published.template_id}@{published.version}[/bold green]")


@app.command("repair-candidate")
def repair_candidate(
    template_id: str,
    learned_file: Annotated[Path, typer.Option(help="YAML containing only a LearnedSpec")],
    root: Annotated[Path, typer.Option("--root")] = Path("templates"),
) -> None:
    """Create a testing version with changed learned data and a frozen business contract."""
    from browser_skill.models import LearnedSpec

    store = _store(root)
    original = store.load(template_id)
    learned = LearnedSpec.model_validate(yaml.safe_load(learned_file.read_text(encoding="utf-8")))
    candidate = RepairService().candidate(original, learned)
    if not RepairService().contract_unchanged(original, candidate):
        raise typer.BadParameter("Repair attempted to change the business contract")
    path = store.save(candidate)
    console.print(
        Panel(
            f"[bold]Repair 候选已创建[/bold]\n{candidate.template_id}@{candidate.version}\n"
            f"[dim]{path}[/dim]\n\n必须执行 test 并通过后才能 publish。",
            border_style="#6366f1",
        )
    )


@app.command()
def resume(
    run_id: str,
    variable: Annotated[list[str] | None, typer.Option("--var")] = None,
    runs_root: Annotated[Path, typer.Option("--runs-root")] = Path("runs"),
    executable: Annotated[str, typer.Option(help="chrome-use executable")] = "chrome-use",
) -> None:
    """Continue a run after authentication was completed in Chrome."""
    try:
        workspace = (runs_root / run_id).resolve()
        root = runs_root.resolve()
        if root not in workspace.parents:
            raise typer.BadParameter("Invalid run ID")
        with console.status("[bold #818cf8]正在重新检查登录并恢复任务…[/bold #818cf8]"):
            response = asyncio.run(
                Runner(ChromeUseAdapter(executable=executable), runs_root).resume(
                    workspace, parse_variables(variable or [])
                )
            )
        color = "green" if response.ok else "yellow"
        console.print(
            Panel(
                f"[bold {color}]{response.message}[/bold {color}]\n"
                f"[dim]Run ID: {response.run_id or run_id} · 状态: {response.state or '—'}[/dim]",
                title="恢复结果",
                border_style=color,
            )
        )
        if not response.ok:
            raise typer.Exit(2)
    except SkillError as exc:
        console.print(Panel(str(exc), title="[red]无法恢复[/red]", border_style="red"))
        raise typer.Exit(2) from exc


@app.command("package")
def build_package(
    full: Annotated[
        bool,
        typer.Option("--full", help="Include templates/ and runtime/ Python source in the zip"),
    ] = False,
) -> None:
    """Build dist/universal-browser-*.zip for Skill Hub upload (maintainers only)."""
    from browser_skill.install import build_full_skill_package, build_skill_package

    if full:
        skill_dir, zip_path = build_full_skill_package()
        note = (
            "完整包含 templates/ + runtime/（服务端 pip install ./runtime）。"
            "仍需要平台 chrome-use。"
        )
    else:
        skill_dir, zip_path = build_skill_package()
        note = "标准包仅含 SKILL.md + references/。执行层需平台单独部署。"
    console.print(
        Panel(
            f"[bold green]已生成[/bold green]\n\n"
            f"目录: [cyan]{skill_dir}[/cyan]\n"
            f"ZIP:  [cyan]{zip_path}[/cyan]\n\n"
            f"{note}\n"
            "说明: docs/RUNTIME.zh.md",
            title="Universal Browser",
            border_style="green",
        )
    )


@app.command()
def setup(
    global_install: Annotated[
        bool, typer.Option("--global", help="Install to ~/.config/opencode/skills")
    ] = False,
    skills_root: Annotated[
        list[Path] | None,
        typer.Option("--skills-root", help="Custom skills root; repeatable"),
    ] = None,
) -> None:
    """Install the universal-browser Skill into OpenCode / standard skills directories."""
    from browser_skill.install import default_skill_targets, install_skill_paths, repo_root

    root = repo_root()
    targets = list(skills_root or []) or default_skill_targets(global_install=global_install)
    installed = install_skill_paths(targets, root=root)
    lines = [f"• {path / 'SKILL.md'}" for path in installed]
    console.print(
        Panel(
            "[bold green]Skill 已安装[/bold green]\n\n"
            + "\n".join(lines)
            + "\n\n在 Agent 对话输入: [cyan]/universal-browser[/cyan]\n"
            "或说: 「列出浏览器任务」\n\n"
            "详细说明: docs/QUICKSTART.zh.md",
            title="Universal Browser",
            border_style="green",
        )
    )


@app.command()
def schema() -> None:
    """Print the machine-readable Template 1.0 JSON Schema."""
    console.print_json(json.dumps(BrowserTemplate.model_json_schema()))


if __name__ == "__main__":
    app()
