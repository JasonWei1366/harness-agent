"""Entity layer must stay free of service dependencies."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "application",
    "server",
    "agent",
    "model",
)


def test_entity_modules_do_not_import_upper_layers() -> None:
    entity_root = Path("src/entity")
    for path in entity_root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("from ", "import ")):
                continue
            for prefix in FORBIDDEN_PREFIXES:
                if re.search(rf"(?:^from |^import ){prefix}(?:\.|$)", stripped):
                    assert False, f"{path}: {stripped}"
