#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    required = [
        root / "docs" / "requirements.md",
        root / "docs" / "architecture.md",
        root / "docs" / "test-plan.md",
        root / "fixtures" / "platform" / "minimum-contract.json",
        root / "src" / "browser_skill" / "platform" / "probe.py",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        for path in missing:
            print(f"missing required path: {path}")
        return 1

    commands = [
        [sys.executable, "-m", "ruff", "check", str(root)],
        [sys.executable, "-m", "mypy", str(root / "src" / "browser_skill")],
        [sys.executable, "-m", "pytest", str(root / "tests")],
    ]
    for command in commands:
        print("$", " ".join(command))
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode != 0:
            return completed.returncode
    print("quick_validate: all repository gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
