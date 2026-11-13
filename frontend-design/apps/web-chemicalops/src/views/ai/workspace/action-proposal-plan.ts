/** 将 /ai/route 返回的写操作路由统一映射为提案创建参数与文案，供工作台与悬浮助手共用。 */

export type ActionProposalRoute =
  | 'exception_task'
  | 'purchase_order_submit'
  | 'purchase_submit'
  | 'purchase_update'
  | 'replenishment_draft'
  | 'rfq_draft';

const ACTION_PROPOSAL_ROUTES = new Set<string>([
  'exception_task',
  'purchase_order_submit',
  'purchase_submit',
  'purchase_update',
  'replenishment_draft',
  'rfq_draft',
]);

export interface RouteUnderstandingPayload {
  action_fields?: null | Record<string, unknown>;
  slots?: null | {
    exception_no?: null | string;
    po_no?: null | string;
    product_keyword?: null | string;
    request_no?: null | string;
    supplier_code?: null | string;
  };
}

export interface AccessChecker {
  hasCode: (codes: string[]) => boolean;
  hasRole: (roles: string[]) => boolean;
}

export type ActionProposalPlan =
  | {
      actionType: string;
      confirmNote: string;
      confirmOkText: string;
      executedMessage: (result: Record<string, any>) => string;
      modalTitle: string;
      ok: true;
      payload: Record<string, unknown>;
      progressText: string;
      subjectLine: string;
      successToast: string;
    }
  | {
      kind: 'error' | 'warning';
      message: string;
      ok: false;
    };

/** 判断路由是否为需要生成动作提案的受控写操作。 */
export function isActionProposalRoute(route: string): route is ActionProposalRoute {
  return ACTION_PROPOSAL_ROUTES.has(route);
}

function hasAnyCodeOrAdmin(access: AccessChecker, codes: string[]): boolean {
  return access.hasRole(['SYS_ADMIN']) || codes.every((code) => access.hasCode([code]));
}

/** 校验写操作必需槽位、前端按钮权限与动作负载，生成提案请求参数。 */
export function buildActionProposalPlan(
  route: string,
  understanding: RouteUnderstandingPayload,
  access: AccessChecker,
): ActionProposalPlan {
  const slots = understanding.slots ?? {};
  const fields = understanding.action_fields ?? {};

  if (route === 'purchase_update' || route === 'purchase_submit' || route === 'rfq_draft') {
    const requestNo = slots.request_no;
    if (!requestNo) {
      return { kind: 'warning', message: '需要准确的采购申请编号，当前请求没有创建提案。', ok: false };
    }
    if (route === 'rfq_draft') {
      if (!hasAnyCodeOrAdmin(access, ['procurement.rfqs.write', 'master.suppliers.read'])) {
        return { kind: 'error', message: '创建询价提案需要询价写入和供应商读取权限。', ok: false };
      }
      return {
        actionType: 'rfq.create_draft',
        confirmNote: '确认后仅执行预览所列动作。',
        confirmOkText: '确认创建询价草稿',
        executedMessage: (result) => `已执行提案${result.rfq_no || result.id ? `，单号：${result.rfq_no || result.id}` : ''}${result.status ? `，状态：${result.status}` : ''}。`,
        modalTitle: '确认创建询价草稿',
        ok: true,
        payload: { source_request_no: requestNo, ...fields },
        progressText: '正在校验单据、权限和候选差异…',
        subjectLine: `申请：${requestNo}`,
        successToast: '已按确认的预览执行动作',
      };
    }
    if (!access.hasRole(['SYS_ADMIN']) && !access.hasCode(['procurement.requests.write'])) {
      return { kind: 'error', message: '当前账号没有采购申请写入权限，未创建提案。', ok: false };
    }
    const isSubmit = route === 'purchase_submit';
    return {
      actionType: isSubmit ? 'purchase_request.submit' : 'purchase_request.update_draft',
      confirmNote: '确认后仅执行预览所列动作。',
      confirmOkText: isSubmit ? '确认提交' : '确认修改',
      executedMessage: (result) => `已执行提案${result.request_no || result.id ? `，单号：${result.request_no || result.id}` : ''}${result.status ? `，状态：${result.status}` : ''}。`,
      modalTitle: isSubmit ? '确认提交采购申请' : '确认修改采购申请',
      ok: true,
      payload: isSubmit ? { request_no: requestNo } : { changes: fields, request_no: requestNo },
      progressText: '正在校验单据、权限和候选差异…',
      subjectLine: `申请：${requestNo}`,
      successToast: '已按确认的预览执行动作',
    };
  }

  if (route === 'purchase_order_submit') {
    const poNo = slots.po_no;
    if (!poNo) {
      return { kind: 'warning', message: '需要准确的采购订单号，当前请求没有创建提案。', ok: false };
    }
    if (!hasAnyCodeOrAdmin(access, ['procurement.orders.write'])) {
      return { kind: 'error', message: '当前账号没有采购订单写入权限，未创建提案。', ok: false };
    }
    return {
      actionType: 'purchase_order.submit',
      confirmNote: '提交后进入采购经理审批，不会自动审批或下单。',
      confirmOkText: '确认提交',
      executedMessage: (result) => `已提交采购订单 ${result.po_no || poNo}，状态：${result.status || 'APPROVING'}。`,
      modalTitle: '确认提交采购订单审批',
      ok: true,
      payload: { po_no: poNo },
      progressText: '正在校验采购订单、审批状态和权限…',
      subjectLine: `采购订单：${poNo}`,
      successToast: '已按确认的预览提交采购订单审批',
    };
  }

  if (route === 'exception_task') {
    const exceptionNo = slots.exception_no;
    if (!exceptionNo) {
      return { kind: 'warning', message: '需要准确的运营异常编号，当前请求没有创建提案。', ok: false };
    }
    if (!hasAnyCodeOrAdmin(access, ['operations.exceptions.write'])) {
      return { kind: 'error', message: '当前账号没有运营异常写入权限，未创建提案。', ok: false };
    }
    const title = typeof fields.title === 'string' ? fields.title.trim() : '';
    if (!title) {
      return { kind: 'warning', message: '请说明要创建的处理任务标题，当前请求没有创建提案。', ok: false };
    }
    return {
      actionType: 'exceptions.create_task',
      confirmNote: '确认后仅为该异常新增处理任务，并按既有规则推进异常状态。',
      confirmOkText: '确认创建',
      executedMessage: (result) => `已创建异常处理任务：${result.title || title}${result.id ? `（#${result.id}）` : ''}。`,
      modalTitle: '确认创建异常处理任务',
      ok: true,
      payload: { exception_no: exceptionNo, ...fields },
      progressText: '正在校验异常、权限和任务候选…',
      subjectLine: `异常：${exceptionNo}`,
      successToast: '已按确认的预览创建异常处理任务',
    };
  }

  if (route === 'replenishment_draft') {
    const supplierCode = slots.supplier_code;
    const productKeyword = slots.product_keyword;
    if (!supplierCode || !productKeyword) {
      return { kind: 'warning', message: '需要准确的供应商编码和产品编码或名称，当前请求没有创建提案。', ok: false };
    }
    if (!hasAnyCodeOrAdmin(access, ['procurement.replenishment.write'])) {
      return { kind: 'error', message: '当前账号没有补货申请写入权限，未创建提案。', ok: false };
    }
    const quantity = Number(fields.quantity);
    const reason = typeof fields.reason === 'string' ? fields.reason.trim() : '';
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return { kind: 'warning', message: '请提供正数补货数量，当前请求没有创建提案。', ok: false };
    }
    if (!reason) {
      return { kind: 'warning', message: '请说明补货原因，当前请求没有创建提案。', ok: false };
    }
    return {
      actionType: 'inventory.create_replenishment',
      confirmNote: '确认后仅创建状态为“草稿”的补货申请。',
      confirmOkText: '确认创建',
      executedMessage: (result) => `已创建补货申请 ${result.replenishment_no || result.id}。`,
      modalTitle: '确认创建补货申请',
      ok: true,
      payload: { product_keyword: productKeyword, supplier_code: supplierCode, ...fields },
      progressText: '正在校验收货产品、供应商和补货候选…',
      subjectLine: `供应商：${supplierCode}\n产品：${productKeyword}`,
      successToast: '已按确认的预览创建补货申请草稿',
    };
  }

  return { kind: 'error', message: '当前动作路由暂未配置提案生成方式。', ok: false };
}
