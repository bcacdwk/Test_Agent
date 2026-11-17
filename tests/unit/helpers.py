"""Helpers shared by the config and model tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def write_yaml(path: Path, data: Any) -> Path:
    """Write ``data`` as UTF-8 YAML, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def assert_roundtrip(model: BaseModel) -> None:
    """The model survives JSON and YAML serialization unchanged."""
    cls = type(model)
    assert cls.model_validate_json(model.model_dump_json()) == model
    as_yaml = yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert cls.model_validate(yaml.safe_load(as_yaml)) == model
