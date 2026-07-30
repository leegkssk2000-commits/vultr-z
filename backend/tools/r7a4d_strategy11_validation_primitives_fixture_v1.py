from __future__ import annotations

import json
import math
from pathlib import Path

from backend.contracts.strategy11_validation_primitives_v1 import ValidationPrimitives

OUT = Path("artifacts/strategy11_validation_primitives_v1")


class FixtureValidationError(ValueError):
    pass


def fail(code: str, detail: str = "") -> None:
    raise FixtureValidationError(f"{code}:{detail}" if detail else code)


def expect_error(name: str, callback, code: str) -> dict[str, str]:
    try:
        callback()
    except FixtureValidationError as exc:
        text = str(exc)
        assert text == code, (name, text, code)
        return {"case": name, "state": "PASS_REJECTED", "error": text}
    raise AssertionError(f"EXPECTED_ERROR_NOT_RAISED:{name}:{code}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    validation = ValidationPrimitives(fail)

    source = {"alpha": 1}
    mapped = validation.mapping(source, "mapping")
    assert mapped == source
    assert mapped is not source
    assert validation.string("  abc  ", "string") == "abc"
    assert validation.sha256("A" * 64, "sha") == "a" * 64
    assert validation.boolean(False, "boolean") is False
    assert validation.integer(3, "integer", minimum=1, maximum=4) == 3
    assert validation.number(3, "number", minimum=1.0, maximum=4.0) == 3.0

    negatives = [
        expect_error("mapping", lambda: validation.mapping([], "mapping"), "OBJECT_REQUIRED:mapping"),
        expect_error("string_empty", lambda: validation.string("  ", "string"), "STRING_REQUIRED:string"),
        expect_error("string_long", lambda: validation.string("abc", "string", maximum=2), "STRING_TOO_LONG:string"),
        expect_error("sha", lambda: validation.sha256("g" * 64, "sha"), "SHA256_REQUIRED:sha"),
        expect_error("bool_int", lambda: validation.boolean(1, "boolean"), "BOOL_REQUIRED:boolean"),
        expect_error("integer_bool", lambda: validation.integer(True, "integer"), "INT_REQUIRED:integer"),
        expect_error("integer_low", lambda: validation.integer(0, "integer", minimum=1), "INT_BELOW_MIN:integer"),
        expect_error("integer_high", lambda: validation.integer(5, "integer", maximum=4), "INT_ABOVE_MAX:integer"),
        expect_error("number_bool", lambda: validation.number(False, "number"), "NUMBER_REQUIRED:number"),
        expect_error("number_nan", lambda: validation.number(math.nan, "number"), "NUMBER_NOT_FINITE:number"),
        expect_error("number_low", lambda: validation.number(0, "number", minimum=1), "NUMBER_BELOW_MIN:number"),
        expect_error("number_high", lambda: validation.number(2, "number", maximum=1), "NUMBER_ABOVE_MAX:number"),
    ]

    summary = {
        "state": "PASS_STRATEGY11_VALIDATION_PRIMITIVES",
        "positive_case_count": 7,
        "negative_case_count": len(negatives),
        "mapping_copy_verified": True,
        "bool_int_rejected": True,
        "finite_number_required": True,
        "error_code_preserved": True,
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    (OUT / "negative_cases.json").write_text(json.dumps(negatives, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
