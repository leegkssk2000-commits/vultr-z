from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any, NoReturn

FailCallback = Callable[[str, str], NoReturn]


class ValidationPrimitives:
    """Stateless fail-closed validation helpers bound to a module-specific error callback."""

    __slots__ = ("_fail",)

    def __init__(self, fail: FailCallback) -> None:
        if not callable(fail):
            raise TypeError("FAIL_CALLBACK_REQUIRED")
        self._fail = fail

    def mapping(self, value: Any, name: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            self._fail("OBJECT_REQUIRED", name)
        return dict(value)

    def string(self, value: Any, name: str, *, maximum: int = 180) -> str:
        if not isinstance(value, str) or not value.strip():
            self._fail("STRING_REQUIRED", name)
        result = value.strip()
        if len(result) > maximum:
            self._fail("STRING_TOO_LONG", name)
        return result

    def sha256(self, value: Any, name: str) -> str:
        result = self.string(value, name, maximum=64).lower()
        if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
            self._fail("SHA256_REQUIRED", name)
        return result

    def boolean(self, value: Any, name: str) -> bool:
        if not isinstance(value, bool):
            self._fail("BOOL_REQUIRED", name)
        return value

    def integer(
        self,
        value: Any,
        name: str,
        *,
        minimum: int = 0,
        maximum: int | None = None,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail("INT_REQUIRED", name)
        if value < minimum:
            self._fail("INT_BELOW_MIN", name)
        if maximum is not None and value > maximum:
            self._fail("INT_ABOVE_MAX", name)
        return value

    def number(
        self,
        value: Any,
        name: str,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._fail("NUMBER_REQUIRED", name)
        result = float(value)
        if not math.isfinite(result):
            self._fail("NUMBER_NOT_FINITE", name)
        if minimum is not None and result < minimum:
            self._fail("NUMBER_BELOW_MIN", name)
        if maximum is not None and result > maximum:
            self._fail("NUMBER_ABOVE_MAX", name)
        return result
