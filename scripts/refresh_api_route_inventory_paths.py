"""Normalize and validate the OpenSpec API route inventory against FastAPI OpenAPI."""

from __future__ import annotations

import argparse
import ast
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app


DEFAULT_INVENTORY = (
    ROOT
    / "openspec/changes/complete-three-level-rbac/evidence/api-route-authorization-inventory.csv"
)


def _registered_path(path: str, methods: set[str], openapi_paths: dict) -> str:
    parts = path.strip("/").split("/")
    tail = parts[2:] if parts[:2] == ["api", "v1"] else parts

    # Older inventory rows repeated the router prefix. Try removing a repeated
    # prefix only when the candidate path and method are registered by FastAPI.
    for size in range(len(tail) // 2, 0, -1):
        if tail[:size] != tail[size : size * 2]:
            continue
        candidate_tail = tail[:size] + tail[size * 2 :]
        candidate_parts = parts[:2] + candidate_tail if parts[:2] == ["api", "v1"] else candidate_tail
        candidate = "/" + "/".join(candidate_parts)
        registered_methods = {method.upper() for method in openapi_paths.get(candidate, {})}
        if methods.issubset(registered_methods):
            return candidate

    registered_methods = {method.upper() for method in openapi_paths.get(path, {})}
    if methods.issubset(registered_methods):
        return path
    raise ValueError(f"No FastAPI OpenAPI path matches {methods} {path}")


def _insight_source_locations() -> dict[tuple[str, str], str]:
    controller = ROOT / "backend/app/modules/insights/controller.py"
    tree = ast.parse(controller.read_text(encoding="utf-8"))
    locations: dict[tuple[str, str], str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "router":
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            path = decorator.args[0].value
            if not isinstance(path, str):
                continue
            locations[(f"/api/v1/insights{path}", method)] = (
                f"backend/app/modules/insights/controller.py:{node.lineno}"
            )
    return locations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()

    with args.inventory.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames or "api_path" not in fieldnames or "http_methods" not in fieldnames:
        raise ValueError("Inventory must contain api_path and http_methods columns")

    openapi_paths = app.openapi()["paths"]
    insight_sources = _insight_source_locations()
    expected_pairs = {
        (path, method.upper())
        for path, operations in openapi_paths.items()
        if path.startswith("/api/v1/")
        for method in operations
    }
    actual_pairs: set[tuple[str, str]] = set()
    changed = 0
    for row in rows:
        methods = {method.strip().upper() for method in row["http_methods"].split(",") if method.strip()}
        normalized = _registered_path(row["api_path"], methods, openapi_paths)
        if normalized != row["api_path"]:
            changed += 1
            row["api_path"] = normalized
        if normalized.startswith("/api/v1/insights/") and len(methods) == 1:
            source = insight_sources.get((normalized, next(iter(methods))))
            if source is None:
                raise ValueError(f"No controller source anchor matches {methods} {normalized}")
            row["source_location"] = source
            row["authorization_location"] = "有效用户身份 + 控制器 _check_permission + 服务对象范围校验"
            method = next(iter(methods))
            if normalized.startswith("/api/v1/insights/batch-impact/") and "/recall-reports" in normalized:
                row["scope_rule"] = "选中库存余额须在授权仓库；报告仅对创建者、负责人/复核人或符合待复核范围的用户可见"
                if method == "POST" and normalized.endswith("/workflow"):
                    row["required_permission_or_guard"] = "ai.workspace.read + warehouse.inventory.write"
                elif method == "GET" and normalized.endswith("/owners"):
                    row["required_permission_or_guard"] = "ai.workspace.read + warehouse.inventory.write"
                elif method == "POST":
                    row["required_permission_or_guard"] = "ai.workspace.read + warehouse.inventory.write"
                    row["evidence_status"] = "本轮 API 负向权限回归：仅有仓库读取权不能创建召回演练报告，且记录数不变"
                else:
                    row["required_permission_or_guard"] = "ai.workspace.read + warehouse.inventory.read"
            elif (
                normalized == "/api/v1/insights/finance-difference/{order_id}/checks"
                and method == "GET"
            ):
                row["required_permission_or_guard"] = "ai.workspace.read + finance.reconciliations.read"
            elif normalized == "/api/v1/insights/finance-difference/{order_id}/checks/{check_id}/events":
                row["required_permission_or_guard"] = "ai.workspace.read + finance.reconciliations.read"
            elif normalized.startswith("/api/v1/insights/finance-difference/") and (
                method in {"POST", "PATCH"} or "/assignees" in normalized
            ):
                row["required_permission_or_guard"] = "ai.workspace.read + finance.reconciliations.write"
            elif normalized.startswith("/api/v1/insights/finance-difference/"):
                row["required_permission_or_guard"] = (
                    "ai.workspace.read + finance.reconciliations.read + procurement.orders.read"
                )
            elif normalized.startswith("/api/v1/insights/"):
                row["required_permission_or_guard"] = (
                    "ai.workspace.read + kind-specific base permission; linked source records require their own read permission"
                )
        pairs = {(normalized, method) for method in methods}
        if actual_pairs.intersection(pairs):
            raise ValueError(f"Duplicate route/method entry: {sorted(pairs)}")
        actual_pairs.update(pairs)

    missing = expected_pairs - actual_pairs
    stale = actual_pairs - expected_pairs
    if missing or stale:
        raise ValueError(
            f"Inventory/OpenAPI mismatch: missing={len(missing)} stale={len(stale)}"
        )

    if not args.check:
        with args.inventory.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    print(
        f"route_method_pairs={len(actual_pairs)} paths={len(openapi_paths)} "
        f"normalized_rows={changed} openapi_mismatches=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
