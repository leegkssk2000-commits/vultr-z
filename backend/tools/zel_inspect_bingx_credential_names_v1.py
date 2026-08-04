from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

TARGET = Path("/home/z/z/config/creds.py")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def names_from_ast(text: str) -> list[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and "bingx" in target.id.lower():
                        names.add(target.id)
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        value = key.value
                        if "bingx" in value.lower() or re.search(r"api.?key|secret", value, re.I):
                            names.add(value)
    return sorted(names)


def main() -> int:
    receipt: dict[str, Any] = {
        "schema_version": "zel.bingx.credential_name_inventory.v1",
        "target_exists": TARGET.is_file(),
        "target_path_sha256": stable_sha(str(TARGET)),
        "candidate_names": [],
        "secret_values_read": False,
        "secret_values_logged": False,
        "secret_values_artifacted": False,
        "order_authority": "BLOCKED",
        "execution_authority": "NONE",
        "action": "hold",
    }
    if TARGET.is_file():
        text = TARGET.read_text(encoding="utf-8", errors="ignore")
        receipt["candidate_names"] = names_from_ast(text)
        receipt["file_content_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    receipt["receipt_sha256"] = stable_sha(receipt)
    Path("/tmp/zel_bingx_credential_name_inventory.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"candidate_names": receipt["candidate_names"], "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
