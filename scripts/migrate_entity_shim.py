#!/usr/bin/env python3
"""Copy a module into entity and leave a compatibility shim at the old path."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IMPORT_REWRITES = (
    (r"\btau\.agent\.types\b", "entity.types"),
    (r"\btau\.agent\.messages\b", "entity.messages"),
    (r"\btau\.agent\.session\.entries\b", "entity.session.entries"),
    (r"\btau\.agent\.assistant_events\b", "entity.assistant_events"),
    (r"\btau\.agent\.events\b", "entity.events"),
)


def rewrite_imports(text: str) -> str:
    for pattern, replacement in IMPORT_REWRITES:
        text = re.sub(pattern, replacement, text)
    return text


def migrate(relative_source: str, relative_entity: str, *, doc: str) -> None:
    source = ROOT / relative_source
    target = ROOT / relative_entity
    target.parent.mkdir(parents=True, exist_ok=True)
    body = rewrite_imports(source.read_text(encoding="utf-8"))
    target.write_text(body, encoding="utf-8")
    module = "/".join(Path(relative_entity).with_suffix("").parts[2:])  # entity/...
    shim = (
        f'"""Compatibility re-exports. Canonical definitions live in ``tau.{module.replace("/", ".")}``."""\n\n'
        f"from tau.{module.replace('/', '.')} import *  # noqa: F403\n"
    )
    if doc:
        shim = f'"""{doc}\n\nCompatibility re-exports. Canonical: ``tau.{module.replace("/", ".")}``."""\n\n' + (
            f"from tau.{module.replace('/', '.')} import *  # noqa: F403\n"
        )
    source.write_text(shim, encoding="utf-8")
    print("migrated", relative_source, "->", relative_entity)


def main(argv: list[str]) -> None:
    pairs = [line.split(":", 1) for line in argv if ":" in line]
    for src, dst in pairs:
        migrate(src, dst, doc="")


if __name__ == "__main__":
    main(sys.argv[1:])
