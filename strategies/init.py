# 자동 로더
import pkgutil, importlib, pathlib
_pkg = pathlib.Path(__file__).parent
for m in pkgutil.iter_modules([str(_pkg)]):
    if m.name.startswith("_"):
        continue
    importlib.import_module(f"{__name__}.{m.name}")