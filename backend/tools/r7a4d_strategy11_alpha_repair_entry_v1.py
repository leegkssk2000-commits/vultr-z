from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path


_ORIGINAL_MODULE_FROM_SPEC = importlib.util.module_from_spec


def _registered_module_from_spec(spec):
    module = _ORIGINAL_MODULE_FROM_SPEC(spec)
    sys.modules[spec.name] = module
    return module


def main() -> None:
    importlib.util.module_from_spec = _registered_module_from_spec
    target = Path(__file__).with_name("r7a4d_strategy11_alpha_repair_v1.py")
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
