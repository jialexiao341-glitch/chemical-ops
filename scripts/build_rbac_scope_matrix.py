"""Refresh the role/page/operation scope matrix from the approved seeds and DB snapshot."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from seed_demo_accounts import PERMISSIONS, ROLE_SCOPES


FIELDS = (
    "role_code",
    "page_resource",
    "operation",
    "permission_code",
    "allowed_by_role_baseline",
    "data_scope",
    "allow_acceptance_case",
    "deny_acceptance_case",
    "evidence_status",
    "evidence_reference",
)


def _scope_for(resource: str) -> str:
    if resource == "dashboard":
        return "全局运营汇总；不继承底层业务记录读写权限"
    if resource == "ai.workspace":
        return "工作台权限不授予业务数据；各工具、数据集和来源按原业务权限及对象范围复核"
    if resource.startswith("supplier.portal"):
        return "账号绑定供应商；询价还须满足邀请关系，关联业务对象沿用同一主体范围"
    if resource.startswith("warehouse."):
        return "授权仓库；本人领用申请及其办理人范围按具体资源规则复核"
    if resource.startswith("procurement."):
        return "本人、授权部门或明确分配的采购记录；管理角色按批准职责范围"
    if resource.startswith("finance."):
        return "授权财务单据及关联业务对象；敏感字段按独立字段权限控制"
    if resource.startswith("quality."):
        return "被分配的验收/质量记录；质量复核遵守经办人与复核人分离"
    if resource.startswith("operations."):
        return "本人、被分配任务或批准的异常处理范围"
    if resource.startswith("system."):
        return "系统职责范围或当前用户自身资料/凭据"
    return "依页面权限和源业务对象范围校验；不因关联展示扩大读写权限"


def _evidence_reference(status: str, role: str, permission_code: str) -> str:
    route_inventory = "openspec/changes/complete-three-level-rbac/evidence/api-route-authorization-inventory.csv"
    snapshot = "openspec/changes/complete-three-level-rbac/evidence/rbac-migration-postcheck.csv"
    if "财务范围回归" in status:
        reference = "tests/test_ai_foundation_regressions.py::test_financial_scope_matches_lists_details_queries_and_does_not_grant_order_writes"
        if "浏览器实测" in status:
            reference += "; openspec/changes/complete-three-level-rbac/evidence/browser-acceptance-2026-10-09.md"
        return reference
    if "采购申请范围回归" in status:
        return "tests/test_rbac_separation.py::test_buyer_request_list_count_and_detail_share_department_scope"
    if "供应商询价范围回归" in status:
        return "tests/test_supplier_portal_api.py::test_supplier_portal_rfq_scope_quote_submission_and_revision"
    if "多角色仓库范围回归" in status:
        return "tests/test_rbac_separation.py::test_combined_technical_and_warehouse_roles_keep_warehouse_scope"
    if "库存只读拒绝写入" in status:
        return "tests/test_rbac_separation.py::test_read_only_warehouse_cannot_create_recall_report"
    if "洞察财务权限回归" in status:
        return (
            "tests/test_rbac_separation.py::test_procurement_role_cannot_read_financial_records_through_insight; "
            "tests/test_rbac_separation.py::test_procurement_role_cannot_read_or_write_finance_checklists"
        )
    if "供应商画像来源权限回归" in status:
        return "tests/test_rbac_separation.py::test_supplier_insight_omits_quality_evidence_without_quality_permission"
    if "库存审批最小权限回归" in status:
        return "tests/test_inventory_api.py::test_issue_request_repeat_execute_is_rejected; tests/test_inventory_api.py::test_stocktake_requires_unchanged_book_quantity"
    if "MSDS 来源权限回归" in status:
        return "tests/test_rbac_separation.py::test_msds_insight_requires_chemical_read_even_when_inventory_is_readable"
    if permission_code == "ai.workspace.read" and "本轮 API 参数化验证：12 角色" in status:
        return (
            "tests/test_rbac_separation.py::test_all_builtin_roles_share_dashboard_and_supplier_is_excluded_from_internal_ai; "
            "tests/test_rbac_separation.py::test_business_insights_require_ai_permission_in_addition_to_resource_permission"
        )
    if "本轮 API 参数化验证：12 角色" in status:
        return "tests/test_rbac_separation.py::test_all_builtin_roles_share_dashboard_and_supplier_is_excluded_from_internal_ai"
    if "采购员获准" in status:
        return "tests/test_rbac_separation.py::test_rfq_compare_and_award_api_actions_match_all_role_grants"
    if "仓储 FIFO" in status and role == "WAREHOUSE" and permission_code == "warehouse.inventory.cost.write":
        return "tests/test_rbac_separation.py::test_warehouse_can_execute_fifo_without_receiving_cost_fields"
    if "浏览器实测" in status:
        return "openspec/changes/complete-three-level-rbac/evidence/browser-acceptance-2026-10-09.md"
    if "API" in status and "范围" in status and "未逐项验证" not in status:
        return f"{route_inventory}; {snapshot}"
    return (
        f"{snapshot}; {route_inventory} "
        "(静态权限/代码锚点；资源范围与状态行为未逐项验证)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postcheck",
        type=Path,
        default=ROOT / "openspec/changes/complete-three-level-rbac/evidence/rbac-migration-postcheck.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "openspec/changes/complete-three-level-rbac/evidence/role-page-operation-scope-matrix.csv",
    )
    args = parser.parse_args()

    permissions = {
        code: {"name": name, "resource": resource, "action": action}
        for code, name, _kind, resource, action in PERMISSIONS
    }
    expected_pairs = {
        (role, code)
        for role in ROLE_SCOPES
        for code in permissions
    }
    with args.postcheck.open(encoding="utf-8-sig", newline="") as file:
        snapshot = list(csv.DictReader(file))
    snapshot_pairs = {(row["role_code"], row["permission_code"]) for row in snapshot}
    if snapshot_pairs != expected_pairs or any(row["matches"] != "true" for row in snapshot):
        raise RuntimeError("数据库授权回读与种子权限矩阵不一致；拒绝刷新验收矩阵")

    existing: dict[tuple[str, str], dict[str, str]] = {}
    if args.output.exists():
        with args.output.open(encoding="utf-8-sig", newline="") as file:
            existing = {
                (row["role_code"], row["permission_code"]): row
                for row in csv.DictReader(file)
            }

    rows = []
    for role in ROLE_SCOPES:
        for code, metadata in permissions.items():
            key = (role, code)
            row = existing.get(key, {})
            expected = code in ROLE_SCOPES[role]
            evidence_status = row.get("evidence_status") or (
                "数据库角色绑定快照一致；该权限码的 API 范围/状态行为未逐项验证"
            )
            if (
                code == "warehouse.inventory.cost.write"
                and role != "WAREHOUSE"
                and "仓储 FIFO" in evidence_status
            ):
                evidence_status = (
                    "数据库角色绑定快照一致；该角色的 FIFO 授权/响应脱敏行为未单独验证"
                )
            if code in {
                "finance.reconciliations.read",
                "finance.invoices.read",
                "finance.payments.read",
            } and role in {"FINANCE_CLERK", "FINANCE_VIEWER"}:
                browser_note = (
                    f"；{evidence_status}" if "浏览器实测" in evidence_status else ""
                )
                if role == "FINANCE_CLERK":
                    evidence_status = "本轮 API 财务范围回归：授权角色可读目标单据；发票/付款过滤列表总数一致"
                else:
                    evidence_status = "本轮 API 财务范围回归：范围外对象不可见；发票/付款过滤列表总数为零"
                evidence_status += browser_note
            if role == "BUYER" and code == "procurement.requests.read":
                evidence_status = "本轮 API 采购申请范围回归：本人/同部门可见、跨部门不可见；列表总数与详情范围一致"
            if role == "SUPPLIER_PORTAL" and code == "supplier.portal.rfq.read":
                evidence_status = "本轮 API 供应商询价范围回归：邀请对象可读；未邀请对象详情/列表/总数不泄露"
            if role == "WAREHOUSE" and code == "warehouse.inventory.read":
                evidence_status = "本轮 API 多角色仓库范围回归：TECHNICAL+WAREHOUSE 组合仍按仓库负责人范围过滤"
            if role == "WAREHOUSE" and code == "warehouse.inventory.write":
                evidence_status = "本轮 API 库存只读拒绝写入：仅仓库读取权不能创建召回演练报告，记录数保持不变"
            if role == "BUYER" and code == "finance.reconciliations.read":
                evidence_status = "本轮 API 洞察财务权限回归：仅有订单读取权限时，财务分析与核查清单均拒绝"
            if role == "BUYER" and code == "finance.reconciliations.write":
                evidence_status = "本轮 API 洞察财务权限回归：采购员不能创建或更新财务核查清单"
            if role == "BUYER" and code == "quality.acceptances.read":
                evidence_status = "本轮 API 供应商画像来源权限回归：无质量读取权限时不返回验收结果"
            if role == "WAREHOUSE" and code == "master.chemicals.read":
                evidence_status = "本轮 API MSDS 来源权限回归：仅库存权限不能读取化学品资料分析"
            if role == "PROCUREMENT_MANAGER" and code in {
                "warehouse.inventory.issue.approve",
                "warehouse.inventory.stocktake.approve",
            }:
                evidence_status = "本轮 API 库存审批最小权限回归：采购经理无审批授权，系统管理员办理完整流程"
            row.update(
                {
                    "role_code": role,
                    "page_resource": row.get("page_resource") or f"{metadata['name']} ({metadata['resource']})",
                    "operation": metadata["action"],
                    "permission_code": code,
                    "allowed_by_role_baseline": "允许" if expected else "拒绝",
                    "data_scope": row.get("data_scope") or _scope_for(metadata["resource"]),
                    "allow_acceptance_case": row.get("allow_acceptance_case") or (
                        f"{role} 具备该权限且资源范围、业务状态满足要求时，{metadata['action']} 成功；"
                        "列表、详情、分页总数、附件、导出与 AI 来源遵循相同对象范围"
                    ),
                    "deny_acceptance_case": row.get("deny_acceptance_case") or (
                        "缺少权限、访问范围外对象或业务状态不允许时应拒绝；不得泄露行数或改变数据"
                    ),
                    "evidence_status": evidence_status,
                    "evidence_reference": _evidence_reference(evidence_status, role, code),
                }
            )
            rows.append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"roles={len(ROLE_SCOPES)} permissions={len(permissions)} "
        f"matrix_rows={len(rows)} database_grant_mismatches=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
