from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = "ZEL_ROUTE_OWNERSHIP_ADJUDICATOR_V1"


def join_path(prefix: str, local: str) -> str:
    left = "/" + prefix.strip("/") if prefix else ""
    right = "/" + local.strip("/") if local else ""
    value = (left + right) or "/"
    return re.sub(r"/{2,}", "/", value)


def function_from_operation_id(operation_id: str | None, functions: set[str]) -> str | None:
    if not operation_id:
        return None
    matches = [name for name in functions if operation_id == name or operation_id.startswith(name + "_")]
    return max(matches, key=len) if matches else None


def candidate_score(operation: dict[str, Any], route: dict[str, Any], inferred_function: str | None) -> int:
    score = 0
    if operation["method"] == route["method"]:
        score += 4
    if inferred_function and route["function"] == inferred_function:
        score += 8
    local = route.get("local_path") or ""
    router_prefix = route.get("router_prefix") or ""
    suffix = join_path(router_prefix, local)
    path = operation["path"]
    if path == suffix:
        score += 8
    elif suffix != "/" and path.endswith(suffix):
        score += 6
    elif local and path.endswith(local):
        score += 3
    source_stem = Path(route["source"]).stem.casefold()
    tags = {str(tag).casefold() for tag in operation.get("tags", [])}
    if source_stem in tags:
        score += 2
    return score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--census", required=True)
    parser.add_argument("--openapi", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    census = json.loads(Path(args.census).read_text(encoding="utf-8"))
    openapi = json.loads(Path(args.openapi).read_text(encoding="utf-8"))
    routes: list[dict[str, Any]] = []
    functions: set[str] = set()
    for file_row in census.get("inventory", []):
        prefixes = file_row.get("router_prefixes") or {}
        for route in file_row.get("routes", []):
            owner = str(route.get("owner") or "")
            function = str(route.get("function") or "")
            functions.add(function)
            routes.append({
                "source": file_row.get("path"),
                "sha256": file_row.get("sha256"),
                "method": route.get("method"),
                "local_path": route.get("local_path"),
                "function": function,
                "owner": owner,
                "router_prefix": prefixes.get(owner, ""),
                "line": route.get("line"),
            })

    ownership: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unowned: list[dict[str, Any]] = []
    claimed_sources: defaultdict[tuple[str, int], list[str]] = defaultdict(list)
    for operation in openapi.get("operations", []):
        inferred = function_from_operation_id(operation.get("operation_id"), functions)
        scored = []
        for route in routes:
            score = candidate_score(operation, route, inferred)
            if score >= 10:
                scored.append((score, route))
        scored.sort(key=lambda item: (-item[0], str(item[1]["source"]), int(item[1].get("line") or 0)))
        best_score = scored[0][0] if scored else 0
        best = [route for score, route in scored if score == best_score]
        row = {
            "key": operation.get("key"),
            "operation_id": operation.get("operation_id"),
            "tags": operation.get("tags", []),
            "inferred_function": inferred,
            "best_score": best_score,
            "owners": best,
        }
        ownership.append(row)
        if not best:
            unowned.append(row)
        elif len(best) > 1:
            ambiguous.append(row)
        for owner in best:
            claimed_sources[(str(owner["source"]), int(owner.get("line") or 0))].append(str(operation.get("key")))

    unexposed: list[dict[str, Any]] = []
    for route in routes:
        key = (str(route["source"]), int(route.get("line") or 0))
        if key not in claimed_sources:
            unexposed.append(route)

    function_collisions: list[dict[str, Any]] = []
    by_function: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in routes:
        by_function[route["function"]].append(route)
    for function, rows in sorted(by_function.items()):
        sources = {(row["source"], row["method"], row.get("local_path")) for row in rows}
        if len(sources) > 1:
            function_collisions.append({"function": function, "definitions": rows, "count": len(rows)})

    blockers: list[str] = []
    if openapi.get("fetch_error"):
        blockers.append("OPENAPI_FETCH_FAILED")
    if openapi.get("duplicate_operation_ids"):
        blockers.append("DUPLICATE_OPERATION_IDS")
    if ambiguous:
        blockers.append("AMBIGUOUS_ROUTE_OWNERSHIP")
    if unowned:
        blockers.append("OPENAPI_OPERATIONS_WITHOUT_SOURCE_OWNER")

    payload = {
        "schema_version": "1.0",
        "version": VERSION,
        "census_version": census.get("version"),
        "openapi_version": openapi.get("version"),
        "source_route_definition_count": len(routes),
        "openapi_operation_count": len(openapi.get("operations", [])),
        "owned_operation_count": len(ownership) - len(unowned),
        "ambiguous_operation_count": len(ambiguous),
        "unowned_operation_count": len(unowned),
        "unexposed_source_route_count": len(unexposed),
        "function_collision_count": len(function_collisions),
        "ownership": ownership,
        "ambiguous_operations": ambiguous,
        "unowned_operations": unowned,
        "unexposed_source_routes": unexposed,
        "function_collisions": function_collisions,
        "blockers": blockers,
        "state": "HOLD_ROUTE_OWNERSHIP_REVIEW_REQUIRED" if blockers else "PASS_ROUTE_OWNERSHIP_ADJUDICATED",
        "safety": {
            "read_only": True,
            "remote_file_created": False,
            "service_changed": False,
            "process_changed": False,
            "database_changed": False,
            "deployment_changed": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        },
        "next": "RESOLVE_ONLY_AMBIGUOUS_OR_UNOWNED_ROUTES_THEN_FREEZE_ACTIVE_ROUTE_SSOT",
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": payload["state"], "owned": payload["owned_operation_count"], "ambiguous": len(ambiguous), "unowned": len(unowned)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
