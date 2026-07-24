"""Collect every schema dict a family publishes, for registry assembly.

Each family's schema package (extractors/<family>/schemas/*) exposes an
`ALL_SCHEMAS` list per module. This walks them into one flat list so a
registry can turn each into a `TableSpec` without hand-listing all ~40 tables.
"""

import importlib
import pkgutil


def collect_schemas(family: str) -> list:
    pkg = importlib.import_module(f"extractors.{family}.schemas")
    schemas = []
    for m in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"extractors.{family}.schemas.{m.name}")
        for s in getattr(mod, "ALL_SCHEMAS", []):
            schemas.append(s)
    return schemas
