# -*- coding: utf-8 -*-
from importlib import import_module
import pkgutil, inspect
from pathlib import Path

_REG = {}

def register(name: str):
    def deco(fn):
        _REG[name] = fn
        return fn
    return deco

def get(name: str):
    return _REG.get(name)

def load_auto():
    base = Path(__file__).resolve().parents[1] / "strategies"
    for m in pkgutil.iter_modules([str(base)]):
        mod = import_module(f"strategies.{m.name}")
        for k, fn in inspect.getmembers(mod, inspect.isfunction):
            if k.startswith("run_"):
                _REG[m.name] = fn # 파일명=전략명
    return len(_REG)