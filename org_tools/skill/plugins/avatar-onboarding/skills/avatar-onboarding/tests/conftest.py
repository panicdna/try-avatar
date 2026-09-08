"""Shared loader for scripts/<name>.py as an importable module.

The scripts under ../scripts are standalone CLI tools, not an installed package, so each
test module needs to load its target the same way (spec_from_file_location + exec_module).
Keep that boilerplate here once instead of repeating it per test file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_script(name: str) -> ModuleType:
    script = Path(__file__).parent.parent / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
