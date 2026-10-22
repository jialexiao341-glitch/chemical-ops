"""确定性询价成本拆分；缺少关键口径时不生成完整总额。"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class TotalCost:
    purchase_quantity: Decimal | None
    moq_extra_quantity: Decimal | None
    goods_amount: Decimal | None
    goods_tax: Decimal | None
    freight_amount: Decimal | None
    freight_tax: Decimal | None
    total_cost: Decimal | None
    complete: bool
    reasons: list[str]


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _tax(amount: Decimal, rate: Decimal, included: bool) -> Decimal:
    if included:
        return _money(amount * rate / (Decimal("100") + rate)) if rate else ZERO
    return _money(amount * rate / Decimal("100"))


def calculate_total_cost(
    *,
    requested_quantity: Decimal,
    requested_unit_id: int,
    quoted_unit_id: int,
    unit_price: Decimal,
    tax_rate: Decimal | None,
    tax_included: bool | None,
    moq_quantity: Decimal | None,
    moq_unit_id: int | None,
    freight_amount: Decimal | None,
    freight_tax_rate: Decimal | None,
    freight_tax_included: bool | None,
) -> TotalCost:
    """按询价量或同单位 MOQ 算采购量，税费及运费分别拆分。"""
    reasons: list[str] = []
    purchase_quantity: Decimal | None = requested_quantity
    moq_extra_quantity: Decimal | None = ZERO
    if quoted_unit_id != requested_unit_id:
        purchase_quantity = None
        moq_extra_quantity = None
        reasons.append("报价单位与询价单位不同")
    if moq_quantity is not None:
        if purchase_quantity is None:
            pass
        elif moq_unit_id != requested_unit_id:
            purchase_quantity = None
            moq_extra_quantity = None
            reasons.append("MOQ单位与询价单位不同")
        else:
            purchase_quantity = max(requested_quantity, moq_quantity)
            moq_extra_quantity = max(ZERO, moq_quantity - requested_quantity)

    goods_amount = None
    goods_tax = None
    if purchase_quantity is not None:
        goods_amount = _money(unit_price * purchase_quantity)
        if tax_rate is None or tax_included is None:
            reasons.append("商品税务口径不完整")
        else:
            goods_tax = _tax(goods_amount, tax_rate, tax_included)

    if freight_amount is None:
        reasons.append("运费未登记")
        freight_tax = None
    elif freight_amount == ZERO:
        freight_tax = ZERO
    elif freight_tax_rate is None or freight_tax_included is None:
        reasons.append("运费税务口径不完整")
        freight_tax = None
    else:
        freight_tax = _tax(freight_amount, freight_tax_rate, freight_tax_included)

    complete = purchase_quantity is not None and goods_tax is not None and freight_amount is not None and freight_tax is not None
    total_cost = None
    if complete:
        goods_total = goods_amount if tax_included else goods_amount + goods_tax
        freight_total = freight_amount if freight_tax_included else freight_amount + freight_tax
        total_cost = _money(goods_total + freight_total)

    return TotalCost(
        purchase_quantity=purchase_quantity,
        moq_extra_quantity=moq_extra_quantity,
        goods_amount=goods_amount,
        goods_tax=goods_tax,
        freight_amount=freight_amount,
        freight_tax=freight_tax,
        total_cost=total_cost,
        complete=complete,
        reasons=reasons,
    )
