"""Business-facing wording for the local development dataset.

These records are synthetic. Keep that fact in environment-level documentation;
the individual business fields describe their own workflow state.
"""

from __future__ import annotations


def business_no(number: int, kind: str) -> str:
    return f"{kind}-2026-{number:04d}"


def batch_no(number: int) -> str:
    return f"B2609{number:04d}"


def acceptance_copy(stage: str, product_name: str, ordered: int, received: int,
                    case_no: int = 0) -> tuple[dict, str]:
    documents = "待补齐" if stage == "DOCUMENT" else "已核对"
    if stage in {"SETTLED", "RECEIVED"}:
        conclusions = (
            f"{product_name}实到{received}，与订单数量一致；批号及随货合格证明已核对，同意入库。",
            f"{product_name}本次收货{received}，包装标识和批次资料完成核对，验收合格。",
            f"{product_name}到货{received}，订单数量、批号及随货资料核对一致，可办理入库。",
        )
        return ({"documents": documents, "quantity_check": "与订单一致", "inspection": "已完成"},
                conclusions[case_no % len(conclusions)])
    if stage == "SHORT":
        return ({"documents": documents, "quantity_check": f"订购{ordered}，实到{received}", "inspection": "已完成"},
                f"{product_name}实到{received}，较订单少{ordered - received}；到货部分已验收，差额待供应商补交。")
    return ({"documents": documents, "quantity_check": "待复核", "inspection": "待完成"},
            f"{product_name}随货质量证明待补齐，批次资料未完成复核，暂缓确认验收。")
