/**
 * 前端统一展示格式，避免把数据库的 Decimal 和状态编码直接展示给用户。
 */

type DisplayValue = number | string | null | undefined;

export type UnitOption = { id: number; unit_code: string; unit_name: string };

const statusLabels: Record<string, string> = {
  ACTIVE: "启用",
  INACTIVE: "已停用",
  SUSPENDED: "暂停合作",
  LOCKED: "已锁定",
  DRAFT: "草稿",
  SUBMITTED: "已提交",
  APPROVING: "审批中",
  PENDING: "待处理",
  PENDING_APPROVAL: "审批中",
  PENDING_CONFIRMATION: "待确认",
  APPROVED: "已通过",
  REJECTED: "已驳回",
  ORDERED: "已下单",
  PARTIAL: "部分完成",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  OPEN: "待处理",
  PROCESSING: "处理中",
  RESOLVED: "已解决",
  CLOSED: "已关闭",
  AVAILABLE: "可用",
  FROZEN: "已冻结",
  IN_TRANSIT: "运输中",
  INSPECTING: "检验中",
  EXCEPTION: "异常",
  REQUESTED: "待审批",
  PAID: "已付款",
  VERIFIED: "已核验",
  VOIDED: "已作废",
  CONFIRMED: "已确认",
  DISPUTED: "有争议",
  FAILED: "失败",
  PASSED: "合格",
  REINSPECTION: "复检",
  REINSPECTING: "复检中",
  PARTIAL_RECEIVED: "部分到货",
};

const enumLabels: Record<string, string> = {
  LOW: "低",
  NORMAL: "普通",
  HIGH: "高",
  URGENT: "紧急",
  INBOUND: "入库",
  OUTBOUND: "出库",
  ADJUSTMENT: "调整",
  BANK_TRANSFER: "银行转账",
  CASH: "现金",
  QUALITY: "质量",
  SHORT_DELIVERY: "短交",
  OVERDUE: "逾期",
  DOCUMENT: "资料",
  OTHER: "其他",
};

export function formatDecimal(value: DisplayValue, maximumFractionDigits = 6): string {
  if (value === null || value === undefined || value === "") return "—";
  const numericValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numericValue)) return String(value);
  return new Intl.NumberFormat("zh-CN", { useGrouping: false, maximumFractionDigits }).format(numericValue);
}

export function formatAmount(value: DisplayValue): string {
  return formatDecimal(value, 2);
}

export function formatQuantity(value: DisplayValue): string {
  return formatDecimal(value, 6);
}

/** 用于 number 输入框的初始值：保留有效小数，但不把数据库的补位 0 带到界面。 */
export function formatInputQuantity(value: DisplayValue): string {
  if (value === null || value === undefined || value === "") return "";
  const formatted = formatQuantity(value);
  return formatted === "—" ? "" : formatted;
}

export function formatPercent(value: DisplayValue, maximumFractionDigits = 2): string {
  const formatted = formatDecimal(value, maximumFractionDigits);
  return formatted === "—" ? formatted : `${formatted}%`;
}

export function formatQuantityWithUnit(value: DisplayValue, unitId: number | string | null | undefined, units: UnitOption[] = []): string {
  const quantity = formatQuantity(value);
  if (quantity === "—") return quantity;
  const unit = units.find((item) => String(item.id) === String(unitId));
  return unit ? `${quantity} ${unit.unit_name}` : `${quantity}${unitId ? `（单位 ID：${unitId}）` : ""}`;
}

export function formatAmountWithCurrency(value: DisplayValue, currencyCode: string | null | undefined): string {
  const amount = formatAmount(value);
  if (amount === "—") return amount;
  return currencyCode ? `${amount} ${currencyCode}` : amount;
}

export function formatDateTime(value: DisplayValue): string {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date).replaceAll("/", "-");
}

export function statusLabel(value: DisplayValue): string {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  return statusLabels[text] || enumLabels[text] || text;
}
