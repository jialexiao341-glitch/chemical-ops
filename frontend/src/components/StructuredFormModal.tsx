import { FormEvent, useMemo, useState } from "react";
import type { Unit } from "../types";

export type StructuredFormKey =
  | "purchase-requests"
  | "purchase-requests-edit"
  | "rfqs"
  | "rfq-quote"
  | "rfq-select-quote"
  | "purchase-orders"
  | "purchase-orders-edit"
  | "reconciliations"
  | "invoices"
  | "payments"
  | "settlements"
  | "exceptions"
  | "attach-file"
  | "list-attachments";

type RowItem = Record<string, string>;
type FormData = Record<string, string>;

type Props = {
  title: string;
  formKey: StructuredFormKey;
  hint?: string;
  units: Unit[];
  onClose: () => void;
  onSubmit: (data: unknown) => Promise<void>;
};

function parseHint(hint?: string): Record<string, unknown> {
  if (!hint) return {};
  try {
    const value = JSON.parse(hint) as unknown;
    return value && typeof value === "object" ? value as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function stringValue(value: unknown, fallback = "") {
  return value === null || value === undefined ? fallback : String(value);
}

function numberValue(value: string, optional = false) {
  if (optional && !value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function nullableText(value: string) {
  return value.trim() || null;
}

function unitLabel(unit: Unit) {
  return `${unit.unit_name}（${unit.unit_code}）`;
}

function Field({ label, value, onChange, type = "text", placeholder, required = false, min, max, step }: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string; required?: boolean; min?: string; max?: string; step?: string }) {
  return <label>{label}{required && <span className="required-mark">*</span>}<input type={type} required={required} value={value} min={min} max={max} step={step} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function SelectField({ label, value, onChange, options, required = false }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }>; required?: boolean }) {
  return <label>{label}{required && <span className="required-mark">*</span>}<select required={required} value={value} onChange={(event) => onChange(event.target.value)}><option value="">请选择</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}

function TextAreaField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="wide-field">{label}<textarea value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function FormSection({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return <section className="structured-form-section"><div className="structured-form-section-heading"><div><p className="eyebrow">{eyebrow}</p><h3>{title}</h3></div></div>{children}</section>;
}

function UnitSelect({ value, onChange, units }: { value: string; onChange: (value: string) => void; units: Unit[] }) {
  return <SelectField label="计量单位" value={value} onChange={onChange} required options={units.map((unit) => ({ value: String(unit.id), label: unitLabel(unit) }))} />;
}

function ItemEditor({ title, items, setItems, units, kind }: { title: string; items: RowItem[]; setItems: (items: RowItem[]) => void; units: Unit[]; kind: "request" | "rfq" | "quote" }) {
  const addItem = () => {
    const base = kind === "quote"
      ? { rfq_item_id: "", quoted_quantity: "1", unit_id: units[0] ? String(units[0].id) : "", unit_price: "0", tax_rate: "13", lead_days: "", payment_terms: "", note: "" }
      : { requested_name: "", quantity: "1", unit_id: units[0] ? String(units[0].id) : "", ...(kind === "request" ? { budget_price: "", expected_date: "", technical_requirements: "" } : { required_delivery_date: "", technical_requirements: "" }) };
    setItems([...items, base as RowItem]);
  };
  const updateItem = (index: number, key: string, value: string) => setItems(items.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: value } : item));
  return <div className="structured-items"><div className="structured-items-header"><div><strong>{title}</strong><small>至少添加一行明细，提交后将进入后端业务校验。</small></div><button type="button" className="outline-button" onClick={addItem}>＋ 添加明细</button></div>{items.map((item, index) => <div className="structured-item-row" key={`${kind}-${index}`}><div className="structured-item-index">{String(index + 1).padStart(2, "0")}</div><div className="structured-item-fields">{kind === "quote" ? <><Field label="询价明细 ID" value={item.rfq_item_id} onChange={(value) => updateItem(index, "rfq_item_id", value)} type="number" min="1" required /><Field label="报价数量" value={item.quoted_quantity} onChange={(value) => updateItem(index, "quoted_quantity", value)} type="number" min="0.000001" step="0.000001" required /><UnitSelect value={item.unit_id} onChange={(value) => updateItem(index, "unit_id", value)} units={units} /><Field label="含税单价" value={item.unit_price} onChange={(value) => updateItem(index, "unit_price", value)} type="number" min="0" step="0.01" required /><Field label="税率（%）" value={item.tax_rate} onChange={(value) => updateItem(index, "tax_rate", value)} type="number" min="0" max="100" step="0.01" /><Field label="交付天数" value={item.lead_days} onChange={(value) => updateItem(index, "lead_days", value)} type="number" min="0" /><Field label="付款条件" value={item.payment_terms} onChange={(value) => updateItem(index, "payment_terms", value)} placeholder="例如：月结 30 天" /><Field label="报价备注" value={item.note} onChange={(value) => updateItem(index, "note", value)} /></> : <><Field label="物料名称" value={item.requested_name} onChange={(value) => updateItem(index, "requested_name", value)} required placeholder="例如：无水乙醇" /><Field label="数量" value={item.quantity} onChange={(value) => updateItem(index, "quantity", value)} type="number" min="0.000001" step="0.000001" required /><UnitSelect value={item.unit_id} onChange={(value) => updateItem(index, "unit_id", value)} units={units} />{kind === "request" ? <><Field label="预算单价" value={item.budget_price || ""} onChange={(value) => updateItem(index, "budget_price", value)} type="number" min="0" step="0.01" /><Field label="期望到货日" value={item.expected_date || ""} onChange={(value) => updateItem(index, "expected_date", value)} type="date" /></> : <Field label="要求交付日" value={item.required_delivery_date || ""} onChange={(value) => updateItem(index, "required_delivery_date", value)} type="date" />}</>}<TextAreaField label={kind === "quote" ? "" : "技术要求"} value={kind === "quote" ? "" : (item.technical_requirements || "")} onChange={(value) => updateItem(index, "technical_requirements", value)} placeholder={kind === "quote" ? undefined : "可选，填写规格、纯度或包装要求"} /></div><button type="button" className="structured-item-remove" aria-label={`删除第 ${index + 1} 行`} onClick={() => setItems(items.filter((_, itemIndex) => itemIndex !== index))}>×</button></div>)}{items.length === 0 && <div className="structured-items-empty"><span>＋</span><strong>还没有明细</strong><small>点击右上角“添加明细”开始填写。</small></div>}</div>;
}

export default function StructuredFormModal({ title, formKey, hint, units, onClose, onSubmit }: Props) {
  const initial = useMemo(() => parseHint(hint), [hint]);
  const [values, setValues] = useState<FormData>(() => Object.fromEntries(Object.entries(initial).filter(([, value]) => typeof value !== "object").map(([key, value]) => [key, stringValue(value)])));
  const [items, setItems] = useState<RowItem[]>(() => Array.isArray(initial.items) ? (initial.items as unknown[]).map((item) => Object.fromEntries(Object.entries(item as Record<string, unknown>).map(([key, value]) => [key, stringValue(value)]))) : []);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const update = (key: string, value: string) => setValues((current) => ({ ...current, [key]: value }));
  const isActionForm = formKey.endsWith("-edit") || formKey === "rfq-quote" || formKey === "rfq-select-quote";

  function validate() {
    if (["purchase-requests", "rfqs"].includes(formKey) && !items.length) return "请至少添加一行业务明细";
    if (formKey === "rfq-quote" && !items.length) return "请至少添加一行供应商报价明细";
    if (formKey === "rfqs" && !values.supplier_ids?.split(",").map((item) => item.trim()).filter(Boolean).length) return "请填写至少一个供应商 ID";
    if (formKey === "attach-file" && (!values.file_id || !values.resource_type || !values.resource_id)) return "请填写完整的附件关联信息";
    if (formKey === "list-attachments" && (!values.resource_type || !values.resource_id)) return "请填写资源类型和资源 ID";
    return "";
  }

  function buildPayload(): unknown {
    if (formKey === "purchase-requests" || formKey === "purchase-requests-edit") return { department_id: numberValue(values.department_id, true), purpose: values.purpose?.trim(), priority: values.priority || "NORMAL", budget_amount: numberValue(values.budget_amount, true), currency_code: values.currency_code || "CNY", expected_date: nullableText(values.expected_date || ""), ...(formKey === "purchase-requests" || items.length ? { items: items.map((item) => ({ product_id: numberValue(item.product_id || "", true), requested_name: item.requested_name?.trim(), technical_requirements: nullableText(item.technical_requirements || ""), quantity: numberValue(item.quantity) || 0, unit_id: numberValue(item.unit_id) || 0, budget_price: numberValue(item.budget_price || "", true), expected_date: nullableText(item.expected_date || "") })) } : {}) };
    if (formKey === "rfqs") return { source_request_id: numberValue(values.source_request_id, true), quote_deadline: nullableText(values.quote_deadline || ""), requested_delivery_date: nullableText(values.requested_delivery_date || ""), delivery_requirements: nullableText(values.delivery_requirements || ""), supplier_ids: (values.supplier_ids || "").split(",").map((item) => Number(item.trim())).filter((item) => Number.isFinite(item) && item > 0), items: items.map((item) => ({ source_request_item_id: numberValue(item.source_request_item_id || "", true), product_id: numberValue(item.product_id || "", true), requested_name: item.requested_name?.trim(), specification: nullableText(item.specification || ""), quantity: numberValue(item.quantity) || 0, unit_id: numberValue(item.unit_id) || 0, required_delivery_date: nullableText(item.required_delivery_date || ""), technical_requirements: nullableText(item.technical_requirements || "") })) };
    if (formKey === "rfq-quote") return { supplier_id: numberValue(values.supplier_id) || 0, quote_date: nullableText(values.quote_date || ""), valid_until: nullableText(values.valid_until || ""), currency_code: values.currency_code || "CNY", source_file_id: numberValue(values.source_file_id, true), note: nullableText(values.note || ""), items: items.map((item) => ({ rfq_item_id: numberValue(item.rfq_item_id) || 0, supplier_product_id: numberValue(item.supplier_product_id || "", true), supplier_model: nullableText(item.supplier_model || ""), quoted_quantity: numberValue(item.quoted_quantity) || 0, unit_id: numberValue(item.unit_id) || 0, unit_price: numberValue(item.unit_price) || 0, tax_rate: numberValue(item.tax_rate || "", true), moq_quantity: numberValue(item.moq_quantity || "", true), moq_unit_id: numberValue(item.moq_unit_id || "", true), lead_days: numberValue(item.lead_days || "", true), payment_terms: nullableText(item.payment_terms || ""), note: nullableText(item.note || "") })) };
    if (formKey === "rfq-select-quote") return { comparison_id: numberValue(values.comparison_id) || 0, quote_id: numberValue(values.quote_id) || 0, selection_reason: values.selection_reason?.trim() };
    if (formKey === "purchase-orders" || formKey === "purchase-orders-edit") return formKey === "purchase-orders" ? { comparison_id: numberValue(values.comparison_id) || 0, quote_id: numberValue(values.quote_id) || 0, delivery_address: nullableText(values.delivery_address || ""), expected_arrival_date: nullableText(values.expected_arrival_date || ""), note: nullableText(values.note || "") } : { delivery_address: nullableText(values.delivery_address || ""), expected_arrival_date: nullableText(values.expected_arrival_date || ""), note: nullableText(values.note || "") };
    if (formKey === "reconciliations" || formKey === "settlements") return { ...(formKey === "reconciliations" ? { po_id: numberValue(values.po_id) || 0 } : { reconciliation_id: numberValue(values.reconciliation_id) || 0 }), note: nullableText(values.note || "") };
    if (formKey === "invoices") return { reconciliation_id: numberValue(values.reconciliation_id) || 0, invoice_code: nullableText(values.invoice_code || ""), invoice_number: values.invoice_number?.trim(), invoice_date: values.invoice_date, amount_excl_tax: numberValue(values.amount_excl_tax) || 0, tax_amount: numberValue(values.tax_amount) || 0, amount_incl_tax: numberValue(values.amount_incl_tax) || 0, source_file_id: numberValue(values.source_file_id || "", true), note: nullableText(values.note || "") };
    if (formKey === "payments") return { reconciliation_id: numberValue(values.reconciliation_id) || 0, amount: numberValue(values.amount) || 0, payment_method: values.payment_method || "BANK_TRANSFER", note: nullableText(values.note || "") };
    if (formKey === "exceptions") return { exception_type: values.exception_type || "OTHER", source_type: values.source_type || "OTHER", source_id: numberValue(values.source_id) || 0, po_id: numberValue(values.po_id || "", true), delivery_id: numberValue(values.delivery_id || "", true), delivery_item_id: numberValue(values.delivery_item_id || "", true), responsible_department_id: numberValue(values.responsible_department_id || "", true), owner_id: numberValue(values.owner_id || "", true), severity: values.severity || "MEDIUM", description: values.description?.trim(), due_at: nullableText(values.due_at || "") };
    if (formKey === "attach-file") return { file_id: numberValue(values.file_id) || 0, resource_type: values.resource_type, resource_id: numberValue(values.resource_id) || 0 };
    return { resource_type: values.resource_type, resource_id: numberValue(values.resource_id) || 0 };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const validationError = validate();
    if (validationError) { setError(validationError); return; }
    setSaving(true); setError("");
    try { await onSubmit(buildPayload()); } catch (reason) { setError(reason instanceof Error ? reason.message : "提交失败，请检查表单"); } finally { setSaving(false); }
  }

  const unitHint = !units.length ? <div className="form-hint form-hint-warning">暂无计量单位，请先在基础数据中维护单位。</div> : null;
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><form className="modal surface structured-form-modal" onSubmit={submit}><div className="section-heading"><div><p className="eyebrow">业务表单 / 正式录入</p><h2>{title}</h2><p className="modal-description">字段将按业务接口校验后提交，页面不会直接暴露 JSON。</p></div><button type="button" className="icon-button" aria-label="关闭表单" onClick={onClose}>×</button></div>
    {formKey === "purchase-requests" || formKey === "purchase-requests-edit" ? <><FormSection eyebrow="申请信息" title="采购需求"><div className="form-grid"><Field label="用途" value={values.purpose || ""} onChange={(value) => update("purpose", value)} required placeholder="例如：实验室日常检测" /><SelectField label="优先级" value={values.priority || "NORMAL"} onChange={(value) => update("priority", value)} options={[{ value: "LOW", label: "低" }, { value: "NORMAL", label: "普通" }, { value: "HIGH", label: "高" }, { value: "URGENT", label: "紧急" }]} /><Field label="部门 ID" value={values.department_id || ""} onChange={(value) => update("department_id", value)} type="number" min="1" placeholder="可选" /><Field label="预算金额" value={values.budget_amount || ""} onChange={(value) => update("budget_amount", value)} type="number" min="0" step="0.01" placeholder="可选" /><Field label="期望到货日" value={values.expected_date || ""} onChange={(value) => update("expected_date", value)} type="date" /><Field label="币种" value={values.currency_code || "CNY"} onChange={(value) => update("currency_code", value)} required /></div></FormSection><FormSection eyebrow="采购明细" title="需要采购什么">{unitHint}<ItemEditor title="物料明细" items={items} setItems={setItems} units={units} kind="request" /></FormSection></> : null}
    {formKey === "rfqs" ? <><FormSection eyebrow="询价设置" title="询价范围"><div className="form-grid"><Field label="来源采购申请 ID" value={values.source_request_id || ""} onChange={(value) => update("source_request_id", value)} type="number" min="1" placeholder="可选" /><Field label="供应商 ID" value={values.supplier_ids || ""} onChange={(value) => update("supplier_ids", value)} required placeholder="多个 ID 用逗号分隔" /><Field label="报价截止时间" value={values.quote_deadline || ""} onChange={(value) => update("quote_deadline", value)} type="datetime-local" /><Field label="要求交付日" value={values.requested_delivery_date || ""} onChange={(value) => update("requested_delivery_date", value)} type="date" /><TextAreaField label="交付要求" value={values.delivery_requirements || ""} onChange={(value) => update("delivery_requirements", value)} placeholder="可选，填写包装、运输或到货要求" /></div></FormSection><FormSection eyebrow="询价明细" title="本次询价内容">{unitHint}<ItemEditor title="询价明细" items={items} setItems={setItems} units={units} kind="rfq" /></FormSection></> : null}
    {formKey === "rfq-quote" ? <><FormSection eyebrow="供应商报价" title="报价头信息"><div className="form-grid"><Field label="供应商 ID" value={values.supplier_id || ""} onChange={(value) => update("supplier_id", value)} required type="number" min="1" /><Field label="报价日期" value={values.quote_date || ""} onChange={(value) => update("quote_date", value)} type="date" /><Field label="有效期至" value={values.valid_until || ""} onChange={(value) => update("valid_until", value)} type="date" /><Field label="币种" value={values.currency_code || "CNY"} onChange={(value) => update("currency_code", value)} required /><Field label="来源文件 ID" value={values.source_file_id || ""} onChange={(value) => update("source_file_id", value)} type="number" min="1" placeholder="可选" /><TextAreaField label="报价备注" value={values.note || ""} onChange={(value) => update("note", value)} /></div></FormSection><FormSection eyebrow="报价明细" title="逐项录入供应商报价">{unitHint}<ItemEditor title="报价明细" items={items} setItems={setItems} units={units} kind="quote" /></FormSection></> : null}
    {formKey === "rfq-select-quote" ? <FormSection eyebrow="比价定标" title="确认中选报价"><div className="form-grid"><Field label="比价结果 ID" value={values.comparison_id || ""} onChange={(value) => update("comparison_id", value)} required type="number" min="1" /><Field label="中选报价 ID" value={values.quote_id || ""} onChange={(value) => update("quote_id", value)} required type="number" min="1" /><TextAreaField label="定标理由" value={values.selection_reason || ""} onChange={(value) => update("selection_reason", value)} placeholder="说明价格、交期、付款条件或供应商能力等依据" /></div></FormSection> : null}
    {formKey === "purchase-orders" || formKey === "purchase-orders-edit" ? <FormSection eyebrow="采购订单" title={isActionForm ? "编辑订单草稿" : "根据比价结果生成订单"}><div className="form-grid">{formKey === "purchase-orders" && <><Field label="比价结果 ID" value={values.comparison_id || ""} onChange={(value) => update("comparison_id", value)} required type="number" min="1" /><Field label="报价 ID" value={values.quote_id || ""} onChange={(value) => update("quote_id", value)} required type="number" min="1" /></>}<Field label="交付地址" value={values.delivery_address || ""} onChange={(value) => update("delivery_address", value)} placeholder="例如：上海主仓库" /><Field label="预计到货日" value={values.expected_arrival_date || ""} onChange={(value) => update("expected_arrival_date", value)} type="date" /><TextAreaField label="订单备注" value={values.note || ""} onChange={(value) => update("note", value)} /></div></FormSection> : null}
    {formKey === "reconciliations" || formKey === "settlements" ? <FormSection eyebrow="财务单据" title={formKey === "reconciliations" ? "创建财务对账单" : "创建采购结算单"}><div className="form-grid"><Field label={formKey === "reconciliations" ? "采购订单 ID" : "对账单 ID"} value={values.po_id || values.reconciliation_id || ""} onChange={(value) => update(formKey === "reconciliations" ? "po_id" : "reconciliation_id", value)} required type="number" min="1" /><TextAreaField label="备注" value={values.note || ""} onChange={(value) => update("note", value)} /></div></FormSection> : null}
    {formKey === "invoices" ? <FormSection eyebrow="财务单据" title="录入供应商发票"><div className="form-grid"><Field label="对账单 ID" value={values.reconciliation_id || ""} onChange={(value) => update("reconciliation_id", value)} required type="number" min="1" /><Field label="发票代码" value={values.invoice_code || ""} onChange={(value) => update("invoice_code", value)} /><Field label="发票号码" value={values.invoice_number || ""} onChange={(value) => update("invoice_number", value)} required /><Field label="开票日期" value={values.invoice_date || ""} onChange={(value) => update("invoice_date", value)} required type="date" /><Field label="不含税金额" value={values.amount_excl_tax || ""} onChange={(value) => update("amount_excl_tax", value)} required type="number" min="0" step="0.01" /><Field label="税额" value={values.tax_amount || "0"} onChange={(value) => update("tax_amount", value)} type="number" min="0" step="0.01" /><Field label="价税合计" value={values.amount_incl_tax || ""} onChange={(value) => update("amount_incl_tax", value)} required type="number" min="0.01" step="0.01" /><Field label="来源文件 ID" value={values.source_file_id || ""} onChange={(value) => update("source_file_id", value)} type="number" min="1" placeholder="可选" /><TextAreaField label="备注" value={values.note || ""} onChange={(value) => update("note", value)} /></div></FormSection> : null}
    {formKey === "payments" ? <FormSection eyebrow="财务单据" title="发起付款申请"><div className="form-grid"><Field label="对账单 ID" value={values.reconciliation_id || ""} onChange={(value) => update("reconciliation_id", value)} required type="number" min="1" /><Field label="付款金额" value={values.amount || ""} onChange={(value) => update("amount", value)} required type="number" min="0.01" step="0.01" /><SelectField label="付款方式" value={values.payment_method || "BANK_TRANSFER"} onChange={(value) => update("payment_method", value)} options={[{ value: "BANK_TRANSFER", label: "银行转账" }, { value: "CASH", label: "现金" }, { value: "OTHER", label: "其他" }]} /><TextAreaField label="备注" value={values.note || ""} onChange={(value) => update("note", value)} /></div></FormSection> : null}
    {formKey === "exceptions" ? <FormSection eyebrow="运营控制中心" title="登记运营异常"><div className="form-grid"><SelectField label="异常类型" value={values.exception_type || "OTHER"} onChange={(value) => update("exception_type", value)} options={[{ value: "SHORT_DELIVERY", label: "短交" }, { value: "QUALITY", label: "质量" }, { value: "DOCUMENT", label: "文件" }, { value: "OVERDUE", label: "逾期" }, { value: "OTHER", label: "其他" }]} /><SelectField label="来源类型" value={values.source_type || "OTHER"} onChange={(value) => update("source_type", value)} options={[{ value: "PURCHASE_ORDER", label: "采购订单" }, { value: "DELIVERY", label: "到货单" }, { value: "DELIVERY_ITEM", label: "到货明细" }, { value: "QUALITY_ACCEPTANCE", label: "质量验收" }, { value: "OTHER", label: "其他" }]} /><Field label="来源 ID" value={values.source_id || ""} onChange={(value) => update("source_id", value)} required type="number" min="1" /><SelectField label="严重程度" value={values.severity || "MEDIUM"} onChange={(value) => update("severity", value)} options={[{ value: "LOW", label: "低" }, { value: "MEDIUM", label: "中" }, { value: "HIGH", label: "高" }, { value: "CRITICAL", label: "严重" }]} /><Field label="负责人 ID" value={values.owner_id || ""} onChange={(value) => update("owner_id", value)} type="number" min="1" /><Field label="截止时间" value={values.due_at || ""} onChange={(value) => update("due_at", value)} type="datetime-local" /><TextAreaField label="异常描述" value={values.description || ""} onChange={(value) => update("description", value)} placeholder="描述影响范围、当前现象和需要采取的动作" /></div></FormSection> : null}
    {formKey === "attach-file" || formKey === "list-attachments" ? <FormSection eyebrow="文件中心" title={formKey === "attach-file" ? "关联业务附件" : "查询业务附件"}><div className="form-grid"><Field label="文件 ID" value={values.file_id || ""} onChange={(value) => update("file_id", value)} type="number" min="1" required={formKey === "attach-file"} placeholder={formKey === "attach-file" ? "上传后获得" : "不需要"} /><SelectField label="业务资源类型" value={values.resource_type || "PURCHASE_ORDER"} onChange={(value) => update("resource_type", value)} options={[{ value: "PURCHASE_ORDER", label: "采购订单" }, { value: "DELIVERY", label: "到货单" }, { value: "QUALITY_ACCEPTANCE", label: "质量验收" }, { value: "OPERATION_EXCEPTION", label: "运营异常" }, { value: "FINANCE_INVOICE", label: "财务发票" }, { value: "INVENTORY_RETURN", label: "库存退货" }, { value: "REPLENISHMENT", label: "补货申请" }]} required /><Field label="业务资源 ID" value={values.resource_id || ""} onChange={(value) => update("resource_id", value)} required type="number" min="1" /></div></FormSection> : null}
    {error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={onClose}>取消</button><button className="primary-button" disabled={saving || !units.length && ["purchase-requests", "rfqs", "rfq-quote"].includes(formKey)}>{saving ? "提交中…" : "提交表单"}</button></div>
  </form></div>;
}
