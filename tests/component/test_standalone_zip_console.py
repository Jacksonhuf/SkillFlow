"""Run the console from a freshly extracted full zip, exactly like open-console.bat does.

Guards against resources that exist in the git checkout but not in the zip (the
``fixtures/platform/minimum-contract.json`` regression surfaced as ``Failed to fetch`` in the UI
because ``/api/setup`` raised ``FileNotFoundError`` from the bundled runtime).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

from browser_skill.install import build_full_skill_package, repo_root

_DRIVER = textwrap.dedent(
    """
    import json, sys, urllib.request
    from pathlib import Path

    skill_root = Path(sys.argv[1])
    sys.path.insert(0, str(skill_root / "runtime" / "src"))
    import browser_skill
    assert Path(browser_skill.__file__).is_relative_to(skill_root), browser_skill.__file__

    from browser_skill.app import BrowserSkillApp
    from browser_skill.browser.fake import FakeBrowserAdapter
    from browser_skill.console.server import ConsoleServer

    app = BrowserSkillApp(skill_root / "templates", skill_root / "runs", FakeBrowserAdapter())
    server = ConsoleServer(app, port=0)
    server.start()
    results = {}
    try:
        for path in ("/", "/api/meta", "/api/setup", "/api/templates", "/api/runs", "/api/doctor"):
            with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}", timeout=20) as r:
                body = r.read()
                results[path] = {
                    "status": r.status,
                    "json": json.loads(body) if path != "/" else None,
                }
    finally:
        server.shutdown()
    print(json.dumps(results, ensure_ascii=False))
    """
)


def test_console_endpoints_work_from_extracted_full_zip(tmp_path: Path) -> None:
    _, zip_path = build_full_skill_package(root=repo_root(), output_dir=tmp_path / "dist")
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extracted)
    skill_root = extracted / "universal-browser"
    assert (skill_root / "SKILL.md").is_file()
    runtime_pkg = skill_root / "runtime" / "src" / "browser_skill"
    assert (runtime_pkg / "platform" / "minimum-contract.json").is_file()

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "UNIVERSAL_BROWSER_SKILL_ROOT"}
    }
    env["UNIVERSAL_BROWSER_CONSOLE_KEEP_OLD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # cwd is a neutral directory so no repo-relative path can leak into the run.
    completed = subprocess.run(
        [sys.executable, "-c", _DRIVER, str(skill_root)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    results = json.loads(completed.stdout.strip().splitlines()[-1])
    for path, result in results.items():
        assert result["status"] == 200, (path, result)
    assert results["/api/setup"]["json"]["ok"] is True
    assert results["/api/setup"]["json"]["setup"]["steps"]
    assert results["/api/templates"]["json"]["templates"]
    assert not (skill_root / "runs" / "console-error.log").exists()
    assert "Traceback" not in completed.stderr
