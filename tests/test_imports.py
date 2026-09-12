"""Import smoke test.

The production entrypoint was once committed as a raw patch blob (`*** Begin Patch`),
and the package simultaneously used flat and relative imports, so several modules could
not be imported at all. Both breakages reached main because nothing checked that the
package simply imports. This test is that check.
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

import src

MODULES = [
    "src.analytics",
    "src.config",
    "src.content",
    "src.guards",
    "src.main",
    "src.media",
    "src.meta",
    "src.seo",
    "src.utils",
    "src.visuals",
    "src.youtube",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name):
    assert importlib.import_module(module_name) is not None


def test_every_src_module_is_covered():
    """Fail when a new module is added to src/ without being added to MODULES."""
    discovered = {f"src.{m.name}" for m in pkgutil.iter_modules(src.__path__)}
    assert discovered == set(MODULES), f"MODULES is out of date: {discovered ^ set(MODULES)}"


def test_entrypoint_exposes_run():
    from src.main import run

    assert callable(run)
