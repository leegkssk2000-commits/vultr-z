"""Exact public signatures for the immutable saved evaluator; no runtime code."""

import argparse as argparse

import hashlib as hashlib

import importlib as importlib

import inspect as inspect

import json as json

import math as math

import sys as sys

import urllib as urllib

from dataclasses import asdict as asdict, is_dataclass as is_dataclass

from datetime import datetime as datetime

from pathlib import Path as Path

from typing import Any as Any, Mapping as Mapping

ROOT: Path

LEDGER_PATH: Path

INVENTORY_PATH: Path

COST_PATH: Path

KLINE_API: str

DEPTH_API: str

FUNDING_API: str

def stable_sha(value: Any) -> str: ...
def git_blob_sha(path: Path) -> str: ...
def load_json(path: Path) -> dict[str, Any]: ...
def request_json(url: str, params: dict[str, Any]) -> Any: ...
def interval_for_ms(ms: int) -> str: ...
def fetch_bars(
    symbol: str, interval: str, limit: int = 1000
) -> list[dict[str, float | int]]: ...
def _depth_vwap(levels: list[list[str]], target_quote: float) -> float: ...
def fetch_execution_snapshot(
    symbol: str, authority: dict[str, Any]
) -> dict[str, Any]: ...
def funding_cost(
    entry_ts: int, exit_ts: int, rows: list[dict[str, float | int]]
) -> float: ...
def load_policy(
    strategy_id: str, inventory: dict[str, Any]
) -> tuple[Any, Path, str]: ...
def config_instance(module: Any) -> Any: ...
def policy_functions(module: Any, strategy_id: str) -> tuple[Any, Any]: ...
def intent_sha(intent: Any) -> str: ...
def sealed_intent_geometry(intent: Any, *, policy_sha: str) -> dict[str, Any]: ...
def max_drawdown(values: list[float]) -> float: ...
def profit_factor(gross_profit: float, gross_loss: float) -> float | None: ...
def execution_ownership_policy(intent: Any) -> tuple[bool, int]: ...
def ownership_blocked(entry_ts: int, blocked_until_ts: int) -> bool: ...
def reserve_position_ownership(
    *,
    exit_ts: int | None,
    open_horizon_ts: int | None,
    cooldown_bars: int,
    timeframe_ms: int
) -> int: ...
def self_test() -> int: ...
def main() -> None: ...
