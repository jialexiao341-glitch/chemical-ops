/**
 * 后端枚举字典。
 *
 * 所有取值均与 backend/app/modules 下各模块 schema.py 中的字面量保持一致，
 * 页面统一通过字典对象的 label / color / options 取用，
 * 避免在页面里散落硬编码的中文映射。
 */

/** 一个字典项 */
export interface DictItem {
  /** antd Tag 颜色，`default` 表示无强调色 */
  color: string;
  label: string;
  value: string;
}

/** 构建字典查询表 */
function buildDict(items: DictItem[]) {
  const map = new Map(items.map((item) => [item.value, item]));
  return {
    items,
    map,
    color(value?: null | string) {
      return value ? (map.get(value)?.color ?? 'default') : 'default';
    },
    label(value?: null | string) {
      if (!value) {
        return '-';
      }
      return map.get(value)?.label ?? value;
    },
    options() {
      return items.map((item) => ({ label: item.label, value: item.value }));
    },
  };
}

/** 启用/停用类状态 */
export const ENABLE_STATUS_DICT = buildDict([
  { color: 'success', label: '启用', value: 'ACTIVE' },
  { color: 'default', label: '停用', value: 'INACTIVE' },
]);

/** 用户状态，比通用启用状态多一个锁定 */
export const USER_STATUS_DICT = buildDict([
  { color: 'success', label: '启用', value: 'ACTIVE' },
  { color: 'warning', label: '锁定', value: 'LOCKED' },
  { color: 'default', label: '停用', value: 'INACTIVE' },
]);

/** 产品状态 */
export const PRODUCT_STATUS_DICT = buildDict([
  { color: 'success', label: '启用', value: 'ACTIVE' },
  { color: 'warning', label: '待确认', value: 'PENDING_CONFIRMATION' },
  { color: 'default', label: '停用', value: 'INACTIVE' },
]);

/** 供应商状态 */
export const SUPPLIER_STATUS_DICT = buildDict([
  { color: 'success', label: '合作中', value: 'ACTIVE' },
  { color: 'warning', label: '已暂停', value: 'SUSPENDED' },
  { color: 'default', label: '已停用', value: 'INACTIVE' },
]);

/** 优先级 */
export const PRIORITY_DICT = buildDict([
  { color: 'default', label: '低', value: 'LOW' },
  { color: 'blue', label: '普通', value: 'NORMAL' },
  { color: 'warning', label: '高', value: 'HIGH' },
  { color: 'error', label: '紧急', value: 'URGENT' },
]);

/** 采购申请状态 */
export const PURCHASE_REQUEST_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'processing', label: '已提交', value: 'SUBMITTED' },
  { color: 'processing', label: '审批中', value: 'APPROVING' },
  { color: 'success', label: '已批准', value: 'APPROVED' },
  { color: 'error', label: '已驳回', value: 'REJECTED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 采购订单状态 */
export const PURCHASE_ORDER_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'processing', label: '审批中', value: 'APPROVING' },
  { color: 'cyan', label: '已批准', value: 'APPROVED' },
  { color: 'blue', label: '已下单', value: 'ORDERED' },
  { color: 'warning', label: '部分到货', value: 'PARTIAL' },
  { color: 'success', label: '已完成', value: 'COMPLETED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 订单/申请明细行状态 */
export const LINE_STATUS_DICT = buildDict([
  { color: 'default', label: '未完成', value: 'PENDING' },
  { color: 'warning', label: '部分完成', value: 'PARTIAL' },
  { color: 'success', label: '已完成', value: 'FULFILLED' },
]);

/** 到货单状态 */
export const DELIVERY_STATUS_DICT = buildDict([
  { color: 'blue', label: '在途', value: 'IN_TRANSIT' },
  { color: 'cyan', label: '已收货', value: 'RECEIVED' },
  { color: 'processing', label: '检验中', value: 'INSPECTING' },
  { color: 'success', label: '验收通过', value: 'ACCEPTED' },
  { color: 'error', label: '异常', value: 'EXCEPTION' },
]);

/** 供应商质量资料状态 */
export const SUPPLIER_QUALITY_DOCUMENT_STATUS_DICT = buildDict([
  { color: 'processing', label: '已提交', value: 'SUBMITTED' },
  { color: 'success', label: '已接收', value: 'ACCEPTED' },
  { color: 'error', label: '需补充', value: 'REJECTED' },
]);

/** 质量验收结果 */
export const ACCEPTANCE_RESULT_DICT = buildDict([
  // 后端创建验收时初始态为 PENDING（尚未录入结果）
  { color: 'processing', label: '待检验', value: 'PENDING' },
  { color: 'success', label: '合格', value: 'PASSED' },
  { color: 'warning', label: '部分合格', value: 'PARTIAL' },
  { color: 'error', label: '不合格', value: 'FAILED' },
  { color: 'processing', label: '待复检', value: 'REINSPECTION' },
]);

/** 询价单状态 */
export const RFQ_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'blue', label: '已发送', value: 'SENT' },
  { color: 'processing', label: '报价中', value: 'RESPONDING' },
  { color: 'success', label: '已关闭', value: 'CLOSED' },
]);

/** 供应商报价状态 */
export const QUOTE_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'processing', label: '已提交', value: 'SUBMITTED' },
  { color: 'success', label: '中选', value: 'SELECTED' },
  { color: 'error', label: '未中选', value: 'REJECTED' },
]);

/** 比价单状态 */
export const COMPARISON_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'success', label: '已确认', value: 'CONFIRMED' },
]);

/** 询价邀请的供应商响应状态 */
export const RFQ_SUPPLIER_RESPONSE_DICT = buildDict([
  { color: 'warning', label: '待响应', value: 'PENDING' },
  { color: 'success', label: '已响应', value: 'RESPONDED' },
  // 兼容已有演示数据中的报价响应状态。
  { color: 'success', label: '已报价', value: 'QUOTED' },
  { color: 'error', label: '已拒绝', value: 'DECLINED' },
  { color: 'default', label: '已过期', value: 'EXPIRED' },
]);

/** 通用单据审批流状态（领用/调拨/盘点/退货/补货） */
export const APPROVAL_FLOW_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'processing', label: '待审批', value: 'SUBMITTED' },
  { color: 'success', label: '已批准', value: 'APPROVED' },
  { color: 'error', label: '已驳回', value: 'REJECTED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
  { color: 'cyan', label: '已完成', value: 'COMPLETED' },
]);

/** 库存余额状态 */
export const INVENTORY_BALANCE_STATUS_DICT = buildDict([
  { color: 'success', label: '可用', value: 'AVAILABLE' },
  { color: 'warning', label: '冻结', value: 'FROZEN' },
]);

/** 库存流水类型 */
export const INVENTORY_TRANSACTION_TYPE_DICT = buildDict([
  { color: 'blue', label: '入库', value: 'INBOUND' },
  { color: 'orange', label: '出库', value: 'OUTBOUND' },
  { color: 'purple', label: '库存调整', value: 'ADJUSTMENT' },
  { color: 'cyan', label: '调拨入库', value: 'TRANSFER_IN' },
  { color: 'volcano', label: '调拨出库', value: 'TRANSFER_OUT' },
]);

/** 库存流水来源类型 */
export const INVENTORY_TRANSACTION_SOURCE_TYPE_DICT = buildDict([
  { color: 'cyan', label: '到货单', value: 'DELIVERY' },
  { color: 'orange', label: '领用申请', value: 'ISSUE_REQUEST' },
  { color: 'purple', label: '调拨申请', value: 'TRANSFER_REQUEST' },
  { color: 'purple', label: '调拨申请', value: 'INVENTORY_TRANSFER' },
  { color: 'geekblue', label: '盘点单', value: 'INVENTORY_STOCKTAKE' },
  { color: 'volcano', label: '退货申请', value: 'INVENTORY_RETURN' },
]);

/**
 * 有效期预警级别。
 *
 * 取值来自后端 `inventory_cost/service.py`：
 * 已过期 → EXPIRED，7 天内到期 → URGENT，其余在查询窗口内 → WARNING。
 */
export const EXPIRY_ALERT_LEVEL_DICT = buildDict([
  { color: 'error', label: '已过期', value: 'EXPIRED' },
  { color: 'error', label: '紧急（7 天内）', value: 'URGENT' },
  { color: 'warning', label: '即将到期', value: 'WARNING' },
]);

/** 运营异常类型 */
export const EXCEPTION_TYPE_DICT = buildDict([
  { color: 'orange', label: '短交', value: 'SHORT_DELIVERY' },
  { color: 'error', label: '质量异常', value: 'QUALITY' },
  { color: 'gold', label: '待验收超时', value: 'QUALITY_PENDING' },
  { color: 'warning', label: '单证缺失', value: 'DOCUMENT' },
  { color: 'volcano', label: '逾期到货', value: 'OVERDUE' },
  { color: 'purple', label: '库存临期', value: 'INVENTORY_EXPIRY' },
  { color: 'volcano', label: '低库存', value: 'LOW_STOCK' },
  { color: 'default', label: '其他', value: 'OTHER' },
]);

/** 运营异常严重级别 */
export const EXCEPTION_SEVERITY_DICT = buildDict([
  { color: 'default', label: '低', value: 'LOW' },
  { color: 'blue', label: '中', value: 'MEDIUM' },
  { color: 'warning', label: '高', value: 'HIGH' },
  { color: 'error', label: '严重', value: 'CRITICAL' },
]);

/** 运营异常状态 */
export const EXCEPTION_STATUS_DICT = buildDict([
  { color: 'error', label: '待处理', value: 'OPEN' },
  { color: 'processing', label: '处理中', value: 'PROCESSING' },
  { color: 'cyan', label: '已解决', value: 'RESOLVED' },
  { color: 'success', label: '已关闭', value: 'CLOSED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 异常处理任务状态 */
export const TASK_STATUS_DICT = buildDict([
  { color: 'error', label: '待处理', value: 'OPEN' },
  { color: 'processing', label: '处理中', value: 'PROCESSING' },
  { color: 'success', label: '已完成', value: 'COMPLETED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 对账单状态 */
export const RECONCILIATION_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'success', label: '已确认', value: 'CONFIRMED' },
  { color: 'error', label: '有争议', value: 'DISPUTED' },
  { color: 'cyan', label: '已关闭', value: 'CLOSED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 发票状态 */
export const INVOICE_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'processing', label: '待核验', value: 'SUBMITTED' },
  { color: 'success', label: '人工已复核', value: 'VERIFIED' },
  { color: 'error', label: '已驳回', value: 'REJECTED' },
  { color: 'default', label: '已作废', value: 'VOIDED' },
]);

/** 付款状态 */
export const PAYMENT_STATUS_DICT = buildDict([
  { color: 'processing', label: '待审批', value: 'REQUESTED' },
  { color: 'cyan', label: '已批准', value: 'APPROVED' },
  { color: 'success', label: '已登记付款', value: 'PAID' },
  { color: 'error', label: '已驳回', value: 'REJECTED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 付款方式 */
export const PAYMENT_METHOD_DICT = buildDict([
  { color: 'blue', label: '银行转账', value: 'BANK_TRANSFER' },
  { color: 'default', label: '现金', value: 'CASH' },
  { color: 'default', label: '其他', value: 'OTHER' },
]);

/** 结算单状态 */
export const SETTLEMENT_STATUS_DICT = buildDict([
  { color: 'default', label: '草稿', value: 'DRAFT' },
  { color: 'success', label: '已确认', value: 'CONFIRMED' },
  { color: 'default', label: '已取消', value: 'CANCELLED' },
]);

/** 业务附件所属资源类型 */
export const ATTACHMENT_RESOURCE_DICT = buildDict([
  { color: 'blue', label: '采购订单', value: 'PURCHASE_ORDER' },
  { color: 'cyan', label: '到货单', value: 'DELIVERY' },
  { color: 'green', label: '质量验收', value: 'QUALITY_ACCEPTANCE' },
  { color: 'red', label: '运营异常', value: 'OPERATION_EXCEPTION' },
  { color: 'purple', label: '财务发票', value: 'FINANCE_INVOICE' },
  { color: 'orange', label: '库存退货', value: 'INVENTORY_RETURN' },
  { color: 'gold', label: '补货申请', value: 'REPLENISHMENT' },
]);

/** 文件解析状态 */
export const PARSE_STATUS_DICT = buildDict([
  { color: 'default', label: '未解析', value: 'NOT_STARTED' },
  { color: 'processing', label: '解析中', value: 'PROCESSING' },
  { color: 'success', label: '解析成功', value: 'SUCCEEDED' },
  { color: 'warning', label: '内容为空', value: 'EMPTY' },
  { color: 'error', label: '解析失败', value: 'FAILED' },
  { color: 'error', label: '文件过大', value: 'TOO_LARGE' },
  { color: 'warning', label: '需要 OCR', value: 'OCR_REQUIRED' },
  { color: 'default', label: '不支持的类型', value: 'UNSUPPORTED' },
]);

/** 异常来源类型 */
export const EXCEPTION_SOURCE_TYPE_DICT = buildDict([
  { color: 'blue', label: '采购订单', value: 'PURCHASE_ORDER' },
  { color: 'cyan', label: '到货单', value: 'DELIVERY' },
  { color: 'geekblue', label: '到货明细', value: 'DELIVERY_ITEM' },
  { color: 'green', label: '质量验收', value: 'QUALITY_ACCEPTANCE' },
  { color: 'default', label: '其他', value: 'OTHER' },
]);
