import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Unit } from "../types";
import { apiRequest, downloadModuleFile, getModuleData, getModulePage, getUnits, patchModule, postModule, uploadModuleFile } from "../services/api";
import { formatAmountWithCurrency, formatDateTime, formatDecimal, formatPercent, formatQuantityWithUnit, statusLabel } from "../utils/format";
import { ConfirmDialog, TextPromptDialog } from "../components/ActionDialog";
import StructuredFormModal, { type StructuredFormKey } from "../components/StructuredFormModal";
import StructuredTaskActionModal from "../components/StructuredTaskActionModal";

type Row = Record<string, unknown>;
type ModuleSection = "finance" | "logistics" | "inventory-ops" | "exceptions" | "files" | "supplier-portal" | "system";
type TaskActionKind = "update" | "comment" | "list-comments" | "detail";

type ActionConfig = {
  label: string;
  suffix: string;
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  prompt?: string;
  body?: unknown;
  json?: boolean;
};

type TabConfig = {
  key: string;
  label: string;
  path: string;
  paged?: boolean;
  detail?: string;
  createPath?: string;
  createHint?: string;
  columns: Array<[string, string]>;
  actions?: ActionConfig[];
};

const tabGroups: Record<ModuleSection, TabConfig[]> = {
  finance: [
    { key: "reconciliations", label: "财务对账", path: "/finance/reconciliations", paged: true, detail: "/finance/reconciliations/{id}", createPath: "/finance/reconciliations", createHint: '{"po_id": 1, "note": ""}', columns: [["reconciliation_no", "对账单号"], ["po_id", "采购订单"], ["supplier_id", "供应商"], ["total_amount", "金额"], ["status", "状态"]], actions: [{ label: "确认", suffix: "/confirm", body: { reason: "" } }, { label: "争议", suffix: "/dispute", prompt: "请输入对账争议原因" }] },
    { key: "invoices", label: "发票", path: "/finance/invoices", paged: true, detail: "/finance/invoices/{id}", createPath: "/finance/invoices", createHint: '{"reconciliation_id": 1, "invoice_number": "INV-001", "invoice_date": "2026-01-01", "amount_excl_tax": 100, "tax_amount": 13, "amount_incl_tax": 113}', columns: [["invoice_no", "发票号"], ["reconciliation_id", "对账单"], ["supplier_id", "供应商"], ["amount_incl_tax", "价税合计"], ["status", "状态"]], actions: [{ label: "提交核验", suffix: "/submit" }, { label: "核验", suffix: "/verify" }, { label: "驳回", suffix: "/reject", prompt: "请输入发票驳回原因" }] },
    { key: "payments", label: "付款", path: "/finance/payments", paged: true, detail: "/finance/payments/{id}", createPath: "/finance/payments", createHint: '{"reconciliation_id": 1, "amount": 100, "payment_method": "BANK_TRANSFER", "note": ""}', columns: [["payment_no", "付款单号"], ["reconciliation_id", "对账单"], ["amount", "付款金额"], ["payment_method", "付款方式"], ["status", "状态"]], actions: [{ label: "审批", suffix: "/approve" }, { label: "驳回", suffix: "/reject", prompt: "请输入付款驳回原因" }, { label: "登记已付", suffix: "/paid", prompt: "请输入银行流水号", body: (value: string) => ({ transaction_ref: value }) }] },
    { key: "settlements", label: "结算", path: "/finance/settlements", paged: true, detail: "/finance/settlements/{id}", createPath: "/finance/settlements", createHint: '{"reconciliation_id": 1, "note": ""}', columns: [["settlement_no", "结算单号"], ["reconciliation_id", "对账单"], ["supplier_id", "供应商"], ["settlement_amount", "结算金额"], ["status", "状态"]], actions: [{ label: "确认结算", suffix: "/confirm" }, { label: "取消", suffix: "/cancel", prompt: "请输入取消原因" }] },
  ],
  logistics: [
    { key: "purchase-requests", label: "采购申请", path: "/purchase-requests", paged: true, detail: "/purchase-requests/{id}", createPath: "/purchase-requests", createHint: '{"purpose": "实验室采购", "priority": "NORMAL", "currency_code": "CNY", "items": [{"requested_name": "乙醇", "quantity": 1, "unit_id": 1}]}', columns: [["request_no", "申请单号"], ["purpose", "用途"], ["priority", "优先级"], ["status", "状态"]], actions: [{ label: "编辑草稿", suffix: "", method: "PATCH", json: true, body: { purpose: "实验室采购", priority: "NORMAL" } }, { label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve", body: { opinion: "" } }, { label: "驳回", suffix: "/reject", prompt: "请输入驳回原因" }, { label: "取消", suffix: "/cancel", prompt: "请输入取消原因" }] },
    { key: "purchase-orders", label: "采购订单", path: "/purchase-orders", paged: true, detail: "/purchase-orders/{id}", createPath: "/purchase-orders", createHint: '{"comparison_id": 1, "quote_id": 1, "delivery_address": "主仓库"}', columns: [["po_no", "订单号"], ["supplier_id", "供应商"], ["order_amount", "订单金额"], ["status", "状态"]], actions: [{ label: "编辑草稿", suffix: "", method: "PATCH", json: true, body: { delivery_address: "主仓库", note: "" } }, { label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve", body: { opinion: "" } }, { label: "驳回", suffix: "/reject", prompt: "请输入驳回原因" }, { label: "正式下单", suffix: "/place" }, { label: "取消", suffix: "/cancel", prompt: "请输入取消原因" }] },
    { key: "deliveries", label: "到货收货", path: "/deliveries", paged: true, detail: "/deliveries/{id}", createPath: "/deliveries", createHint: '{"po_id": 1, "items": [{"po_item_id": 1, "planned_quantity": 1}]}', columns: [["delivery_no", "到货单号"], ["po_id", "采购订单"], ["supplier_id", "供应商"], ["expected_arrival_date", "预计到货"], ["status", "状态"]], actions: [{ label: "确认收货", suffix: "/receive", json: true, body: { actual_arrival_date: "2026-01-01", items: [{ delivery_item_id: 1, actual_quantity: 1, short_quantity: 0 }] } }] },
    { key: "rfqs", label: "询价比价", path: "/rfqs", paged: true, detail: "/rfqs/{id}", createPath: "/rfqs", createHint: '{"items": [{"requested_name": "乙醇", "quantity": 1, "unit_id": 1}], "supplier_ids": [1]}', columns: [["rfq_no", "询价单号"], ["source_request_id", "采购申请"], ["quote_deadline", "报价截止"], ["status", "状态"]], actions: [{ label: "发送询价", suffix: "/send" }, { label: "录入报价", suffix: "/quotes", json: true, body: { supplier_id: 1, items: [] } }, { label: "生成比价", suffix: "/comparison" }, { label: "查看比价", suffix: "/comparison", method: "GET" }, { label: "确认中选", suffix: "/select-quote", json: true, body: { comparison_id: 1, quote_id: 1, selection_reason: "" } }] },
    { key: "returns", label: "退货申请", path: "/inventory/returns", paged: true, detail: "/inventory/returns/{id}", createPath: "/inventory/returns", createHint: '{"supplier_id": 1, "reason": "质量问题", "items": [{"product_id": 1, "warehouse_id": 1, "location_id": 1, "batch_id": 1, "unit_id": 1, "requested_quantity": 1}]}', columns: [["return_no", "退货单号"], ["supplier_id", "供应商"], ["reason", "退货原因"], ["status", "状态"]], actions: [{ label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve" }, { label: "驳回", suffix: "/reject", prompt: "请输入退货驳回原因" }, { label: "取消", suffix: "/cancel", prompt: "请输入退货取消原因" }, { label: "执行退货", suffix: "/execute" }] },
    { key: "replenishments", label: "补货申请", path: "/replenishments", paged: true, detail: "/replenishments/{id}", createPath: "/replenishments", createHint: '{"supplier_id": 1, "reason": "补足短交", "items": [{"product_id": 1, "unit_id": 1, "requested_quantity": 1}]}', columns: [["replenishment_no", "补货单号"], ["supplier_id", "供应商"], ["reason", "补货原因"], ["status", "状态"]], actions: [{ label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve" }, { label: "驳回", suffix: "/reject", prompt: "请输入补货驳回原因" }, { label: "取消", suffix: "/cancel", prompt: "请输入补货取消原因" }, { label: "完成补货", suffix: "/complete", json: true, body: { fulfillment_po_id: 1 } }] },
  ],
  "inventory-ops": [
    { key: "warehouses", label: "仓库", path: "/inventory/warehouses", createPath: "/inventory/warehouses", createHint: '{"warehouse_code": "WH-001", "warehouse_name": "主仓库"}', columns: [["warehouse_code", "仓库编码"], ["warehouse_name", "仓库名称"], ["region", "区域"], ["status", "状态"]], actions: [{ label: "查看库位", suffix: "/locations", method: "GET" }, { label: "新增库位", suffix: "/locations", json: true, body: { location_code: "A-01", location_name: "一号库位" } }] },
    { key: "balances", label: "库存余额", path: "/inventory/balances", paged: true, detail: "/inventory/balances/{id}/status-logs", columns: [["warehouse_id", "仓库"], ["location_id", "库位"], ["product_id", "产品"], ["quantity", "可用数量"], ["status", "状态"]], actions: [{ label: "冻结", suffix: "/freeze", prompt: "请输入冻结原因" }, { label: "解冻", suffix: "/unfreeze", prompt: "请输入解冻原因" }] },
    { key: "transactions", label: "库存流水", path: "/inventory/transactions", paged: true, columns: [["transaction_no", "流水号"], ["transaction_type", "类型"], ["warehouse_id", "仓库"], ["product_id", "产品"], ["quantity", "数量"]] },
    { key: "inbounds", label: "执行入库", path: "/inventory/inbounds", createPath: "/inventory/inbounds", createHint: '{"delivery_id": 1, "warehouse_id": 1, "location_id": 1}', columns: [["delivery_id", "到货单"], ["transaction_count", "流水数"]] },
    { key: "issues", label: "领用出库", path: "/inventory/issue-requests", paged: true, detail: "/inventory/issue-requests/{id}", createPath: "/inventory/issue-requests", createHint: '{"purpose": "实验领用", "items": [{"product_id": 1, "warehouse_id": 1, "location_id": 1, "batch_id": 1, "unit_id": 1, "requested_quantity": 1}]}', columns: [["issue_no", "领用单号"], ["purpose", "用途"], ["status", "状态"]], actions: [{ label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve" }, { label: "驳回", suffix: "/reject", prompt: "请输入驳回原因" }, { label: "取消", suffix: "/cancel", prompt: "请输入取消原因" }, { label: "执行出库", suffix: "/execute" }] },
    { key: "transfers", label: "库存调拨", path: "/inventory/transfer-requests", paged: true, detail: "/inventory/transfer-requests/{id}", createPath: "/inventory/transfer-requests", createHint: '{"reason": "跨仓调拨", "items": [{"product_id": 1, "source_warehouse_id": 1, "source_location_id": 1, "target_warehouse_id": 1, "target_location_id": 1, "batch_id": 1, "unit_id": 1, "requested_quantity": 1}]}', columns: [["transfer_no", "调拨单号"], ["reason", "调拨原因"], ["status", "状态"]], actions: [{ label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve" }, { label: "驳回", suffix: "/reject", prompt: "请输入驳回原因" }, { label: "取消", suffix: "/cancel", prompt: "请输入取消原因" }, { label: "执行调拨", suffix: "/execute" }] },
    { key: "stocktakes", label: "库存盘点", path: "/inventory/stocktakes", paged: true, detail: "/inventory/stocktakes/{id}", createPath: "/inventory/stocktakes", createHint: '{"warehouse_id": 1, "reason": "月度盘点"}', columns: [["stocktake_no", "盘点单号"], ["warehouse_id", "仓库"], ["reason", "盘点原因"], ["status", "状态"]], actions: [{ label: "提交", suffix: "/submit" }, { label: "审批", suffix: "/approve" }, { label: "驳回", suffix: "/reject", prompt: "请输入驳回原因" }, { label: "取消", suffix: "/cancel", prompt: "请输入取消原因" }, { label: "执行盘点", suffix: "/execute", json: true }] },
    { key: "expiry", label: "有效期预警", path: "/inventory/expiry-alerts?days=30", columns: [["product_id", "产品"], ["batch_no", "批次"], ["quantity", "库存"], ["expiry_date", "到期日"], ["days_remaining", "剩余天数"], ["alert_level", "预警级别"]] },
    { key: "fifo", label: "先进先出出库", path: "/inventory/fifo-outbounds", createPath: "/inventory/fifo-outbounds", createHint: '{"request_no": "OUT-001", "product_id": 1, "warehouse_id": 1, "location_id": 1, "unit_id": 1, "quantity": 1}', columns: [["request_no", "出库请求"], ["product_id", "产品"], ["quantity", "数量"], ["status", "状态"]] },
  ],
  exceptions: [
    { key: "exceptions", label: "运营异常", path: "/operation-exceptions", paged: true, detail: "/operation-exceptions/{id}", createPath: "/operation-exceptions", createHint: '{"exception_type": "OTHER", "source_type": "OTHER", "source_id": 1, "description": "需要处理的异常"}', columns: [["exception_no", "异常编号"], ["exception_type", "类型"], ["severity", "级别"], ["description", "描述"], ["status", "状态"]], actions: [{ label: "处理", suffix: "", method: "PATCH", json: true, body: { status: "PROCESSING" } }, { label: "关闭", suffix: "", method: "PATCH", json: true, body: { status: "CLOSED", closing_note: "已处理" } }, { label: "查询任务", suffix: "/tasks", method: "GET" }, { label: "创建任务", suffix: "/tasks", json: true, body: { title: "异常跟进", priority: "NORMAL" } }] },
    { key: "notifications", label: "我的通知", path: "/notifications", paged: true, columns: [["notification_type", "类型"], ["title", "标题"], ["content", "内容"], ["is_read", "已读"]], actions: [{ label: "标记已读", suffix: "/read" }] },
    { key: "jobs", label: "后台任务", path: "", columns: [["operation", "操作"], ["description", "说明"]] },
  ],
  files: [
    { key: "files", label: "文件与附件", path: "", columns: [["operation", "操作"], ["description", "说明"]] },
  ],
  "supplier-portal": [
    { key: "orders", label: "供应商订单", path: "/supplier-portal/orders", paged: true, detail: "/supplier-portal/orders/{id}", columns: [["po_no", "采购订单"], ["supplier_id", "供应商"], ["order_amount", "订单金额"], ["status", "状态"]], actions: [{ label: "确认订单", suffix: "/confirm" }, { label: "拒绝订单", suffix: "/reject", prompt: "请输入拒绝原因" }] },
  ],
  system: [
    { key: "departments", label: "部门", path: "/system/departments", paged: true, detail: "/system/departments/{id}", createPath: "/system/departments", createHint: '{"department_code": "LAB", "department_name": "实验室"}', columns: [["department_code", "部门编码"], ["department_name", "部门名称"], ["manager_id", "负责人"], ["status", "状态"]], actions: [{ label: "编辑", suffix: "", method: "PATCH", json: true, body: { department_name: "实验室", status: "ACTIVE" } }, { label: "停用", suffix: "", method: "DELETE" }] },
    { key: "roles", label: "角色", path: "/system/roles", paged: true, detail: "/system/roles/{id}", createPath: "/system/roles", createHint: '{"role_code": "WAREHOUSE", "role_name": "仓储人员", "permission_ids": []}', columns: [["role_code", "角色编码"], ["role_name", "角色名称"], ["description", "说明"], ["status", "状态"]], actions: [{ label: "编辑", suffix: "", method: "PATCH", json: true, body: { role_name: "仓储人员", status: "ACTIVE" } }, { label: "停用", suffix: "", method: "DELETE" }] },
    { key: "permissions", label: "权限", path: "/system/permissions", paged: true, detail: "/system/permissions/{id}", createPath: "/system/permissions", createHint: '{"permission_code": "demo.read", "permission_name": "示例查询", "permission_type": "API", "resource": "demo", "action": "read"}', columns: [["permission_code", "权限编码"], ["permission_name", "权限名称"], ["resource", "资源"], ["action", "动作"]], actions: [{ label: "编辑", suffix: "", method: "PATCH", json: true, body: { permission_name: "示例查询", permission_type: "API", resource: "demo", action: "read" } }, { label: "删除", suffix: "", method: "DELETE" }] },
  ],
};

const sectionMeta: Record<ModuleSection, { eyebrow: string; title: string; description: string }> = {
  finance: { eyebrow: "业务运营 / 财务", title: "财务管理", description: "对账、发票、付款和结算统一在这里闭环处理。" },
  logistics: { eyebrow: "业务运营 / 物流", title: "到货与供应业务", description: "覆盖询价、到货、收货、退货和补货全过程。" },
  "inventory-ops": { eyebrow: "业务运营 / 仓储", title: "仓储作业", description: "仓库、库存流水、领用、调拨、盘点和先进先出成本动作。" },
  exceptions: { eyebrow: "控制中心", title: "异常与通知", description: "处理运营异常、站内通知，并手工触发后台逾期扫描。" },
  files: { eyebrow: "文件中心", title: "文件与附件", description: "上传文件、查看元数据、下载和绑定业务对象。" },
  "supplier-portal": { eyebrow: "供应商门户", title: "供应商门户", description: "供应商账号只查看自己的订单并确认或拒绝订单。" },
  system: { eyebrow: "系统设置", title: "组织与权限", description: "补齐部门、角色、权限三类系统基础资料维护。" },
};

function valueOf(row: Row, key: string, units: Unit[]) {
  const value = row[key];
  if (value === null || value === undefined || value === "") return "—";
  if (key === "is_read") return value ? "已读" : "未读";
  if (key === "unit_id" || key.endsWith("_unit_id")) {
    const unit = units.find((item) => String(item.id) === String(value));
    return unit ? `${unit.unit_name}（${unit.unit_code}）` : `单位 ID：${value}`;
  }
  if (key === "status" || key.endsWith("_status")) return statusLabel(value as string | number);
  if (["amount", "amount_excl_tax", "amount_incl_tax", "order_amount", "settlement_amount", "total_amount", "tax_amount", "budget_amount", "unit_price", "total_cost", "outbound_cost"].includes(key)) return formatAmountWithCurrency(value as string | number, row.currency_code as string | undefined);
  if (key === "tax_rate" || key.endsWith("_rate")) return formatPercent(value as string | number, 2);
  if (key === "purity_value") return `${formatDecimal(value as string | number, 4)}${row.purity_unit || "%"}`;
  if (key === "days_remaining") return `${formatQuantityWithUnit(value as string | number, undefined, units)} 天`;
  if (["quantity", "locked_quantity", "requested_quantity", "planned_quantity", "actual_quantity", "short_quantity", "returned_quantity", "fulfilled_quantity", "issued_quantity", "original_quantity", "remaining_quantity", "outbound_quantity"].includes(key)) return formatQuantityWithUnit(value as string | number, row.unit_id as string | number | undefined, units);
  if (key.endsWith("_date") || key.endsWith("_time")) return formatDateTime(value as string);
  if (key === "transaction_type" || key === "priority" || key === "payment_method" || key === "exception_type" || key === "alert_level") return statusLabel(value as string | number);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDetail(value: unknown, units: Unit[]): unknown {
  if (Array.isArray(value)) return value.map((item) => formatDetail(item, units));
  if (!value || typeof value !== "object") return value;
  const row = value as Row;
  return Object.fromEntries(Object.entries(row).map(([key, item]) => {
    if (item && typeof item === "object") return [key, formatDetail(item, units)];
    return [key, valueOf(row, key, units)];
  }));
}

function contextualActions(row: Row, tab: TabConfig) {
  const actions = tab.actions || [];
  const status = String(row.status || "").toUpperCase();
  if (!status) return actions;
  const has = (labels: string[]) => actions.filter((action) => labels.includes(action.label));

  // 已完成或已关闭的数据不再展示已经失效的流程按钮。
  if (["purchase-requests"].includes(tab.key)) {
    if (["DRAFT", "REJECTED"].includes(status)) return has(["编辑草稿", "提交", "取消"]);
    if (["SUBMITTED", "PENDING_APPROVAL", "APPROVING"].includes(status)) return has(["审批", "驳回"]);
    return [];
  }
  if (tab.key === "purchase-orders") {
    if (status === "DRAFT") return has(["编辑草稿", "提交", "取消"]);
    if (["SUBMITTED", "PENDING_APPROVAL", "APPROVING"].includes(status)) return has(["审批", "驳回", "取消"]);
    if (status === "APPROVED") return has(["正式下单", "取消"]);
    return [];
  }
  if (["returns", "replenishments", "issues", "transfers", "stocktakes"].includes(tab.key)) {
    if (["DRAFT", "REJECTED"].includes(status)) return has(["提交", "取消"]);
    if (["SUBMITTED", "PENDING_APPROVAL", "APPROVING"].includes(status)) return has(["审批", "驳回"]);
    if (status === "APPROVED") return actions.filter((action) => ["取消", "执行退货", "完成补货", "执行出库", "执行调拨", "执行盘点"].includes(action.label));
    return [];
  }
  if (tab.key === "reconciliations") {
    if (status === "DRAFT") return has(["确认", "争议"]);
    if (status === "DISPUTED") return has(["确认"]);
    if (status === "CONFIRMED") return has(["争议"]);
    return [];
  }
  if (tab.key === "balances") return status === "FROZEN" ? has(["解冻"]) : has(["冻结"]);
  if (tab.key === "notifications") return row.is_read ? [] : has(["标记已读"]);
  if (tab.key === "deliveries") return ["RECEIVED", "COMPLETED", "CLOSED"].includes(status) ? [] : has(["确认收货"]);
  if (tab.key === "orders" && tab.path.startsWith("/supplier-portal")) return ["PENDING_CONFIRMATION", "SUBMITTED"].includes(status) ? actions : [];
  return actions;
}

function isDangerAction(label: string) {
  return label.includes("驳回") || label.includes("删除") || label.includes("取消");
}

function RowActionGroup({ row, tab, onDetail, onAction }: { row: Row; tab: TabConfig; onDetail: () => void; onAction: (action: ActionConfig) => void }) {
  const actions = contextualActions(row, tab);
  const directActions = actions.length > 2 ? actions.slice(0, 2) : actions;
  const extraActions = actions.length > 2 ? actions.slice(2) : [];
  const visibleCount = Math.min(7, directActions.length + extraActions.length + 1);
  const button = (action: ActionConfig) => <button key={action.label} className={`row-action ${isDangerAction(action.label) ? "danger-action" : ""}`} onClick={() => onAction(action)}>{action.label}</button>;
  return <div className={`module-actions module-actions-count-${visibleCount}`}><button className="row-action" onClick={onDetail}>详情</button>{directActions.map(button)}{extraActions.length > 0 && <details className="row-action-menu"><summary className="row-action">更多</summary><div className="row-action-menu-items">{extraActions.map(button)}</div></details>}</div>;
}

function Pagination({ page, total, pageSize, onChange }: { page: number; total: number; pageSize: number; onChange: (page: number) => void }) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const startPage = Math.min(Math.max(1, page - 3), Math.max(1, pageCount - 6));
  const pageNumbers = Array.from({ length: Math.min(7, pageCount) }, (_, index) => startPage + index);
  return <div className="pagination"><span>共 {total} 条</span><div><button className="outline-button" disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</button>{pageNumbers.map((pageNumber) => <button key={pageNumber} className={`outline-button pagination-page ${pageNumber === page ? "selected" : ""}`} aria-current={pageNumber === page ? "page" : undefined} onClick={() => onChange(pageNumber)}>{pageNumber}</button>)}<button className="outline-button" disabled={page >= pageCount} onClick={() => onChange(page + 1)}>下一页</button></div><span>第 {page} / {pageCount} 页</span></div>;
}

function idOf(row: Row) {
  return Number(row.id || 0);
}

function structuredFormKeyFor(tabKey: string, actionLabel?: string): StructuredFormKey | null {
  if (actionLabel === "编辑草稿" && tabKey === "purchase-requests") return "purchase-requests-edit";
  if (actionLabel === "编辑草稿" && tabKey === "purchase-orders") return "purchase-orders-edit";
  if (actionLabel === "录入报价" && tabKey === "rfqs") return "rfq-quote";
  if (actionLabel === "确认中选" && tabKey === "rfqs") return "rfq-select-quote";
  if (["purchase-requests", "rfqs", "purchase-orders", "reconciliations", "invoices", "payments", "settlements", "exceptions"].includes(tabKey)) return tabKey as StructuredFormKey;
  return null;
}

function JsonModal({ title, hint, onClose, onSubmit }: { title: string; hint: string; onClose: () => void; onSubmit: (data: unknown) => Promise<void> }) {
  const [content, setContent] = useState(hint);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); try { setError(""); const data = JSON.parse(content) as unknown; setSaving(true); await onSubmit(data); } catch (reason) { setError(reason instanceof Error ? reason.message : "JSON 格式不正确"); } finally { setSaving(false); } }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><form className="modal surface" onSubmit={submit}><div className="section-heading"><div><p className="eyebrow">请求数据</p><h2>{title}</h2></div><button type="button" className="icon-button" onClick={onClose}>×</button></div><label className="wide-field json-label">请求 JSON<textarea className="json-editor" value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} /></label>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={onClose}>取消</button><button className="primary-button" disabled={saving}>{saving ? "提交中…" : "提交请求"}</button></div></form></div>;
}

export default function BusinessModulesPage({ token, section }: { token: string; section: ModuleSection }) {
  const tabs = tabGroups[section];
  const [activeKey, setActiveKey] = useState(tabs[0].key);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [units, setUnits] = useState<Unit[]>([]);
  const pageSize = 8;
  const [modal, setModal] = useState<{ title: string; hint: string; path: string; formKey?: StructuredFormKey | null; method?: "GET" | "POST" | "PATCH" | "DELETE" } | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [taskAction, setTaskAction] = useState<TaskActionKind | null>(null);
  const [textDialog, setTextDialog] = useState<{ title: string; label: string; placeholder?: string; required?: boolean; submit: (value: string) => Promise<void> | void } | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{ title: string; description: string; confirm: () => Promise<void> | void } | null>(null);
  const [fileCategory, setFileCategory] = useState("OTHER");
  const [accessLevel, setAccessLevel] = useState("INTERNAL");
  const fileRef = useRef<HTMLInputElement>(null);
  const activeTab = useMemo(() => tabs.find((tab) => tab.key === activeKey) || tabs[0], [activeKey, tabs]);
  const meta = sectionMeta[section];

  useEffect(() => {
    // 切换左侧功能区时，回到该功能区的第一个页签，避免沿用上个功能区的页签状态。
    setActiveKey(tabs[0].key);
  }, [section, tabs]);

  async function load(requestedPage = page) {
    setLoading(true); setError("");
    try {
      if (!activeTab.path) { setRows([]); return; }
      const data = activeTab.paged ? await getModulePage<Row>(token, activeTab.path, requestedPage, pageSize) : await getModuleData<Row[] | Row>(token, activeTab.path);
      if (Array.isArray(data)) {
        // 没有服务端分页的旧接口，在前端统一切分当前页，保证所有列表交互一致。
        const totalRows = data.length;
        const pageCount = Math.max(1, Math.ceil(totalRows / pageSize));
        const safePage = Math.min(requestedPage, pageCount);
        setRows(data.slice((safePage - 1) * pageSize, safePage * pageSize));
        setTotal(totalRows);
        setPage(safePage);
      } else {
        const pageData = data as { items?: Row[]; total?: number; page?: number };
        const pageItems = pageData.items || [data as Row];
        setRows(pageItems);
        setTotal(pageData.total ?? pageItems.length);
        setPage(pageData.page ?? requestedPage);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "模块数据加载失败"); } finally { setLoading(false); }
  }
  useEffect(() => { setPage(1); void load(1); }, [token, section, activeKey]);
  useEffect(() => { void getUnits(token).then(setUnits).catch(() => setUnits([])); }, [token]);

  async function callAction(row: Row, action: ActionConfig, inputValue?: string, confirmed = false) {
    const id = idOf(row);
    if (!id && action.suffix) { setError("该数据缺少有效 ID，无法执行操作"); return; }
    if (action.method === "DELETE" && !confirmed) {
      setConfirmDialog({ title: `确认${action.label}`, description: `确定要${action.label}当前记录吗？`, confirm: () => callAction(row, action, undefined, true) });
      return;
    }
    let data: unknown = action.body;
    if (action.prompt && inputValue === undefined) {
      setTextDialog({ title: action.label, label: action.prompt.replace(/^请输入/, "").replace(/[：:]$/, "") || "处理说明", required: true, submit: (value) => callAction(row, action, value, confirmed) });
      return;
    }
    if (action.prompt) data = typeof action.body === "function" ? action.body(inputValue || "") : { reason: inputValue || "" };
    if (action.json) { setModal({ title: `${action.label}（ID：${id}）`, hint: JSON.stringify(action.body || {}, null, 2), formKey: structuredFormKeyFor(activeTab.key, action.label), path: `${activeTab.path}/${id}${action.suffix}`, method: action.method || "POST" }); return; }
    try { setError(""); const path = action.suffix ? `${activeTab.path}/${id}${action.suffix}` : `${activeTab.path}/${id}`; if (action.method === "GET") setDetail(await getModuleData<Row>(token, path)); else if (action.method === "DELETE") await apiRequest(path, { method: "DELETE" }, token); else await postModule(token, path, data); if (action.method !== "GET") await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
  }

  async function submitModal(data: unknown) {
    if (!modal) return;
    if (modal.path === "__attach_file__") {
      const payload = data as { file_id?: number | string; resource_type?: string; resource_id?: number | string };
      if (!payload.file_id || !payload.resource_type || !payload.resource_id) throw new Error("请填写完整的附件关联信息");
      setDetail(await postModule<Row>(token, `/files/${payload.file_id}/attachments`, { resource_type: payload.resource_type, resource_id: Number(payload.resource_id) }));
      setModal(null);
      return;
    }
    if (modal.path === "__list_attachments__") {
      const payload = data as { resource_type?: string; resource_id?: number | string };
      if (!payload.resource_type || !payload.resource_id) throw new Error("请填写完整的查询条件");
      setDetail(await getModuleData<Row>(token, `/files/attachments/${payload.resource_type}/${payload.resource_id}`));
      setModal(null);
      return;
    }
    if (modal.method === "PATCH") await patchModule(token, modal.path, data);
    else if (modal.method === "DELETE") await apiRequest(modal.path, { method: "DELETE" }, token);
    else await postModule(token, modal.path, data);
    setModal(null); await load();
  }

  async function showDetail(row: Row) {
    if (!activeTab.detail) { setDetail(row); return; }
    try { setDetail(await getModuleData<Row>(token, activeTab.detail.replace("{id}", String(idOf(row))))); } catch (reason) { setError(reason instanceof Error ? reason.message : "详情加载失败"); }
  }

  async function runJob() { try { setError(""); const result = await postModule<Row>(token, "/jobs/overdue-scan"); setDetail(result); } catch (reason) { setError(reason instanceof Error ? reason.message : "后台扫描失败"); } }
  async function markAllRead() { try { await postModule(token, "/notifications/read-all"); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "批量已读失败"); } }
  async function uploadFile() { const file = fileRef.current?.files?.[0]; if (!file) { setError("请先选择文件"); return; } try { setError(""); setDetail(await uploadModuleFile<Row>(token, file, fileCategory, accessLevel)); } catch (reason) { setError(reason instanceof Error ? reason.message : "文件上传失败"); } }
  function queryFile() { setTextDialog({ title: "查询文件", label: "文件 ID", placeholder: "请输入文件 ID", required: true, submit: async (fileId) => { try { setDetail(await getModuleData<Row>(token, `/files/${fileId}`)); } catch (reason) { setError(reason instanceof Error ? reason.message : "文件查询失败"); } } }); }
  function attachFile() { setModal({ title: "关联业务附件", hint: '{\n  "resource_type": "PURCHASE_ORDER",\n  "resource_id": 1\n}', formKey: "attach-file", path: "__attach_file__" }); }
  function listAttachments() { setModal({ title: "查询业务附件", hint: '{\n  "resource_type": "DELIVERY",\n  "resource_id": 1\n}', formKey: "list-attachments", path: "__list_attachments__" }); }
  function downloadFile() { setTextDialog({ title: "下载文件", label: "文件 ID", placeholder: "请输入文件 ID", required: true, submit: async (fileId) => { try { const blob = await downloadModuleFile(token, Number(fileId)); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `chemicalops-file-${fileId}`; anchor.click(); URL.revokeObjectURL(url); } catch (reason) { setError(reason instanceof Error ? reason.message : "文件下载失败"); } } }); }
  function openTaskAction(kind: TaskActionKind) { setTaskAction(kind); }
  async function submitTaskAction(exceptionId: string, taskId: string, content: string) { const base = `/operation-exceptions/${exceptionId}/tasks/${taskId}`; setError(""); if (taskAction === "detail") { setTaskAction(null); setDetail(await getModuleData<Row>(token, base)); } else if (taskAction === "list-comments") { setTaskAction(null); setDetail(await getModuleData<Row>(token, `${base}/comments`)); } else { const data = JSON.parse(content) as unknown; if (taskAction === "update") await patchModule(token, base, data); else await postModule(token, `${base}/comments`, data); setTaskAction(null); await load(); } }

  const actionLayout = Math.min(4, (activeTab.actions?.length || 0) + 1);
  const structuredModal = modal?.formKey ? <StructuredFormModal title={modal.title} formKey={modal.formKey} hint={modal.hint} units={units} onClose={() => setModal(null)} onSubmit={submitModal} /> : modal ? <JsonModal title={modal.title} hint={modal.hint} onClose={() => setModal(null)} onSubmit={submitModal} /> : null;
  return <><div className={`page-heading ${section === "exceptions" ? "page-heading-exceptions" : ""}`}><div>{section !== "exceptions" && <p className="eyebrow">{meta.eyebrow}</p>}<h1>{meta.title}</h1>{section !== "exceptions" && <p>{meta.description}</p>}</div>{activeTab.createPath && <button className="primary-button" onClick={() => setModal({ title: `新增${activeTab.label}`, hint: activeTab.createHint || "{}", formKey: structuredFormKeyFor(activeTab.key), path: activeTab.createPath || "/" })}>＋ 新增{activeTab.label}</button>}</div><section className={`surface list-card ${section === "exceptions" ? "exceptions-card" : ""}`}><div className="tab-bar">{tabs.map((tab) => <button key={tab.key} className={`tab-button ${tab.key === activeKey ? "selected" : ""}`} onClick={() => setActiveKey(tab.key)}>{tab.label}</button>)}</div>{section === "files" && <div className="file-tools"><input ref={fileRef} type="file" /><select className="filter-button" value={fileCategory} onChange={(event) => setFileCategory(event.target.value)}><option value="OTHER">其他文件</option><option value="INVOICE">发票</option><option value="CERTIFICATE">证书</option><option value="CONTRACT">合同</option></select><select className="filter-button" value={accessLevel} onChange={(event) => setAccessLevel(event.target.value)}><option value="INTERNAL">内部</option><option value="PRIVATE">私有</option><option value="PUBLIC">公开</option></select><button className="primary-button" onClick={() => void uploadFile()}>上传文件</button><button className="outline-button" onClick={queryFile}>查询文件</button><button className="outline-button" onClick={downloadFile}>下载文件</button><button className="outline-button" onClick={attachFile}>关联附件</button><button className="outline-button" onClick={listAttachments}>查询附件</button></div>}{section === "exceptions" && activeKey === "jobs" && <div className="job-panel"><h2>逾期到货扫描</h2><p>手工触发一次后台扫描，扫描结果会返回新增或更新的异常数量。</p><button className="primary-button" onClick={() => void runJob()}>立即扫描</button></div>}{section === "exceptions" && activeKey === "exceptions" && <div className="exception-tool-panel"><div className="exception-tool-header"><div><h2>异常任务工具</h2></div><div className="exception-tool-status" aria-label="可执行操作 4 项"><span className="status-dot" aria-hidden="true" /><strong>4</strong></div></div><div className="exception-tool-actions"><button className="exception-tool-action" onClick={() => openTaskAction("detail")}><span className="tool-action-icon">01</span><span><strong>任务详情</strong></span><span className="tool-arrow">↗</span></button><button className="exception-tool-action" onClick={() => openTaskAction("update")}><span className="tool-action-icon">02</span><span><strong>更新任务</strong></span><span className="tool-arrow">↗</span></button><button className="exception-tool-action" onClick={() => openTaskAction("list-comments")}><span className="tool-action-icon">03</span><span><strong>处理记录</strong></span><span className="tool-arrow">↗</span></button><button className="exception-tool-action" onClick={() => openTaskAction("comment")}><span className="tool-action-icon">04</span><span><strong>追加记录</strong></span><span className="tool-arrow">↗</span></button></div></div>}{section === "exceptions" && activeKey === "notifications" && <div className="list-toolbar"><button className="outline-button" onClick={() => void markAllRead()}>全部标记已读</button><button className="outline-button" onClick={() => void load()}>刷新</button></div>}{error && <div className="inline-error">{error}</div>}{activeTab.path && activeKey !== "jobs" && activeKey !== "files" && <div className="table-scroll"><table className={`module-table module-table-actions-${actionLayout}`}><thead><tr>{activeTab.columns.map(([, label]) => <th key={label}>{label}</th>)}<th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={activeTab.columns.length + 1} className="table-empty">正在加载…</td></tr> : rows.length === 0 ? <tr><td colSpan={activeTab.columns.length + 1} className="table-empty">暂无数据</td></tr> : rows.map((row, index) => <tr key={String(row.id || index)}>{activeTab.columns.map(([key]) => <td key={key}>{valueOf(row, key, units)}</td>)}<td className="module-actions-cell"><RowActionGroup row={row} tab={activeTab} onDetail={() => void showDetail(row)} onAction={(action) => void callAction(row, action)} /></td></tr>)}</tbody></table></div>}{activeTab.path && activeKey !== "jobs" && activeKey !== "files" && <Pagination page={page} total={total} pageSize={pageSize} onChange={(nextPage) => void load(nextPage)} />}</section>{structuredModal}{textDialog && <TextPromptDialog title={textDialog.title} label={textDialog.label} placeholder={textDialog.placeholder} required={textDialog.required} confirmText="确认" onClose={() => setTextDialog(null)} onSubmit={textDialog.submit} />}{confirmDialog && <ConfirmDialog title={confirmDialog.title} description={confirmDialog.description} confirmText="确认操作" onClose={() => setConfirmDialog(null)} onConfirm={confirmDialog.confirm} />}{taskAction && <StructuredTaskActionModal kind={taskAction} onClose={() => setTaskAction(null)} onSubmit={submitTaskAction} />}{detail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetail(null); }}><div className="modal surface"><div className="section-heading"><div><p className="eyebrow">详情数据</p><h2>接口返回详情</h2></div><button className="icon-button" onClick={() => setDetail(null)}>×</button></div><pre className="detail-json">{JSON.stringify(formatDetail(detail, units), null, 2)}</pre><div className="modal-actions"><button className="outline-button" onClick={() => setDetail(null)}>关闭</button></div></div></div>}</>;
}

