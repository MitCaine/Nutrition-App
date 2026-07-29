from __future__ import annotations

import ast
import hashlib
from importlib import import_module
import json
from pathlib import Path


initial_schema = import_module("app.migrations.versions.0001_initial_schema")
MIGRATION = Path(initial_schema.__file__)
FROZEN_ROWS_SHA256 = "4df8dab43826ea4b6eb3141e7cffedcc25fe206e7b4b6998e5802a48f046adab"


def test_initial_nutrient_seed_is_migration_owned_and_frozen() -> None:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    rows = initial_schema._initial_nutrient_seed_rows()
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()

    assert "app.catalog.nutrients" not in imported_modules
    assert digest == FROZEN_ROWS_SHA256
    assert len(rows) == 16
    assert len({row["id"] for row in rows}) == len(rows)
