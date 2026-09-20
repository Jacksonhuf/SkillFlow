from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from browser_skill.models import BrowserTemplate


@pytest.fixture
def template_data() -> dict[str, Any]:
    return yaml.safe_load(Path("templates/inventory_feedback/1.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def template(template_data: dict[str, Any]) -> BrowserTemplate:
    data = deepcopy(template_data)
    data["target"]["attachments"] = []
    data["workflow"]["hints"] = []
    data["validation"]["min_records"] = 1
    return BrowserTemplate.model_validate(data)
