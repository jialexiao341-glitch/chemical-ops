import type { Chemical, CurrentUser, DashboardOverview, DashboardReport, Delivery, InboundResult, InventoryBalance, PageResult, Product, PurchaseOrder, PurchaseRequest, PurchaseRequestItem, QualityAcceptance, Supplier, SystemStatus, SystemUser, Unit, Warehouse, WarehouseLocation } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface AIChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface AIQuerySlot {
  name: string;
  label: string;
  value: unknown;
  display_value: string;
  status: "filled" | "empty";
}

export interface AIQueryColumn {
  key: string;
  label: string;
  format: "text" | "amount";
}

export interface AIQueryTrace {
  query: string;
  answer?: string | null;
  dataset?: string | null;
  dataset_label?: string | null;
  permission?: string | null;
  thread_id?: string | null;
  executed_at?: string | null;
  data_scope?: Record<string, unknown> | null;
  context?: { continued?: boolean; inherited?: string[]; changed?: string[] } | null;
  slots: AIQuerySlot[];
  template: string;
  sql: string;
  parameterized_sql?: string;
  columns: AIQueryColumn[];
  rows: Array<Record<string, unknown>>;
  unit?: string | null;
  unit_note?: string | null;
  row_count: number;
  truncated: boolean;
  stages: string[];
  render: {
    type: "table";
    title: string;
    empty_text: string;
    columns: AIQueryColumn[];
    unit?: string | null;
    unit_note?: string | null;
    visualization?: { type: "bar"; category: string; value: string; title: string } | null;
  };
}

export interface AIChatResponse {
  message: AIChatMessage;
  conversation_id: number;
  model: string;
  provider: string;
  usage?: Record<string, number> | null;
  citations?: unknown[] | null;
  query_trace?: AIQueryTrace | null;
  query_slots?: AIQuerySlot[] | null;
  user_query?: string | null;
  answer?: string | null;
}

export interface UploadedFileMetadata {
  id: number;
  file_name: string;
  mime_type: string;
  file_size_bytes: number;
  parse_status: string;
}

export interface AIConversationSummary {
  id: number;
  title?: string | null;
  business_scene: string;
  status: string;
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AIConversationMessage extends AIChatMessage {
  id: number;
  conversation_id: number;
  citations?: unknown[] | null;
  created_at: string;
}

interface ApiErrorResponse {
  code?: number;
  message?: string;
  detail?: string | Array<{ message?: string }>;
}

interface ApiRequestOptions extends RequestInit {
  idempotencyKey?: string;
}

function newIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const STATUS_MESSAGES: Record<number, string> = {
  400: "请求不符合业务规则",
  401: "登录已失效，请重新登录",
  403: "没有执行该操作的权限",
  404: "请求的资源不存在",
  405: "当前请求方法不允许",
  409: "数据已存在，不能重复提交",
  415: "请求格式不支持",
  422: "请求参数校验失败",
  500: "服务器内部错误，请稍后重试",
};

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}, token?: string): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (!isFormData && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", "Bearer " + token);
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && !headers.has("Idempotency-Key")) {
    headers.set("Idempotency-Key", options.idempotencyKey || newIdempotencyKey());
  }
  const response = await fetch(API_BASE_URL + path, {
    ...options,
    method,
    headers,
  });
  if (!response.ok) {
    let message = STATUS_MESSAGES[response.status] || `请求失败（${response.status}）`;
    try {
      const error = (await response.json()) as ApiErrorResponse;
      if (typeof error.detail === "string" && error.detail.trim()) {
        message = error.detail;
      } else if (Array.isArray(error.detail)) {
        const messages = error.detail.map((item) => item.message).filter((item): item is string => Boolean(item?.trim()));
        if (messages.length) message = messages.join("；");
      } else if (error.message) {
        message = error.message;
      }
    } catch {
      // 非 JSON 响应使用默认错误提示。
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

const request = apiRequest;

export function login(username: string, password: string) {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getCurrentUser(token: string) {
  return request<CurrentUser>("/auth/me", {}, token);
}

export function sendAIChat(token: string, messages: AIChatMessage[], attachments: string[] = [], attachmentFileIds: number[] = [], conversationId?: number) {
  return request<AIChatResponse>("/ai/chat", { method: "POST", body: JSON.stringify({ messages, attachments, attachment_file_ids: attachmentFileIds, conversation_id: conversationId }) }, token);
}

export type AIStreamEvent =
  | { type: "delta"; content: string }
  | { type: "done"; conversation_id: number; model: string; provider: string; citations?: unknown[] | null; query_trace?: AIQueryTrace | null; query_slots?: AIQuerySlot[] | null; user_query?: string | null; answer?: string | null }
  | { type: "error"; message: string };

export async function streamAIChat(
  token: string,
  messages: AIChatMessage[],
  attachments: string[] = [],
  attachmentFileIds: number[] = [],
  onEvent: (event: AIStreamEvent) => void,
  idempotencyKey?: string,
  conversationId?: number,
) {
  const response = await fetch(`${API_BASE_URL}/ai/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey || newIdempotencyKey(), Authorization: `Bearer ${token}` },
    body: JSON.stringify({ messages, attachments, attachment_file_ids: attachmentFileIds, conversation_id: conversationId }),
  });
  if (!response.ok) {
    let message = STATUS_MESSAGES[response.status] || `请求失败（${response.status}）`;
    try {
      const error = (await response.json()) as ApiErrorResponse;
      if (typeof error.detail === "string" && error.detail.trim()) message = error.detail;
    } catch { /* 使用状态码提示。 */ }
    throw new Error(message);
  }
  if (!response.body) throw new Error("浏览器不支持 SSE 流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;
  const consume = (record: string) => {
    const eventName = record.match(/^event:\s*(\w+)/m)?.[1] || "message";
    const dataLine = record.split("\n").find((line) => line.startsWith("data:"));
    if (!dataLine) return;
    const data = JSON.parse(dataLine.slice(5).trim()) as Record<string, unknown>;
    if (eventName === "delta" && typeof data.content === "string") onEvent({ type: "delta", content: data.content });
    else if (eventName === "done" && typeof data.conversation_id === "number" && typeof data.model === "string" && typeof data.provider === "string") {
      sawDone = true;
      onEvent({ type: "done", conversation_id: data.conversation_id, model: data.model, provider: data.provider, citations: Array.isArray(data.citations) ? data.citations : null, query_trace: data.query_trace && typeof data.query_trace === "object" ? data.query_trace as AIQueryTrace : null, query_slots: Array.isArray(data.query_slots) ? data.query_slots as AIQuerySlot[] : null, user_query: typeof data.user_query === "string" ? data.user_query : null, answer: typeof data.answer === "string" ? data.answer : null });
    }
    else if (eventName === "error") onEvent({ type: "error", message: typeof data.message === "string" ? data.message : "AI 服务暂时不可用" });
  };
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const records = buffer.split("\n\n");
    buffer = records.pop() || "";
    records.forEach(consume);
    if (done) break;
  }
  if (buffer.trim()) consume(buffer);
  if (!sawDone) throw new Error("AI 响应未完整返回，请重试");
}

export function getAIConversations(token: string) {
  return request<{ items: AIConversationSummary[]; total: number }>("/ai/conversations?limit=50", {}, token);
}

export function getAIConversationMessages(token: string, conversationId: number) {
  return request<{ items: AIConversationMessage[]; total: number }>(`/ai/conversations/${conversationId}/messages?limit=200`, {}, token);
}

export function deleteAIConversation(token: string, conversationId: number) {
  return request<{ deleted: boolean; conversation_id: number }>(`/ai/conversations/${conversationId}`, { method: "DELETE" }, token);
}

export function clearAIQueryContext(token: string, conversationId: number) {
  return request<{ cleared: boolean; conversation_id: number }>(`/ai/conversations/${conversationId}/query-context`, { method: "DELETE" }, token);
}

export function getChemicals(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<Chemical>>(`/chemicals?${query.toString()}`, {}, token);
}

export function createChemical(token: string, data: Partial<Chemical>) {
  return request<Chemical>("/chemicals", { method: "POST", body: JSON.stringify(data) }, token);
}

export function getChemical(token: string, id: number) {
  return request<Chemical>(`/chemicals/${id}`, {}, token);
}


export function updateChemical(token: string, id: number, data: Partial<Chemical>) {
  return request<Chemical>(`/chemicals/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token);
}

export function deleteChemical(token: string, id: number) {
  return request<Chemical>(`/chemicals/${id}`, { method: "DELETE" }, token);
}

export function getSuppliers(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<Supplier>>(`/suppliers?${query.toString()}`, {}, token);
}

export function createSupplier(token: string, data: Partial<Supplier>) {
  return request<Supplier>("/suppliers", { method: "POST", body: JSON.stringify(data) }, token);
}

export function getSupplier(token: string, id: number) {
  return request<Supplier>(`/suppliers/${id}`, {}, token);
}


export function updateSupplier(token: string, id: number, data: Partial<Supplier>) {
  return request<Supplier>(`/suppliers/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token);
}

export function deleteSupplier(token: string, id: number) {
  return request<Supplier>(`/suppliers/${id}`, { method: "DELETE" }, token);
}

export function getProducts(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<Product>>(`/products?${query.toString()}`, {}, token);
}

export function getUnits(token: string) {
  return request<Unit[]>("/products/units", {}, token);
}

export function createProduct(token: string, data: Partial<Product>) {
  return request<Product>("/products", { method: "POST", body: JSON.stringify(data) }, token);
}

export function getProduct(token: string, id: number) {
  return request<Product>(`/products/${id}`, {}, token);
}


export function updateProduct(token: string, id: number, data: Partial<Product>) {
  return request<Product>(`/products/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token);
}

export function deleteProduct(token: string, id: number) {
  return request<Product>(`/products/${id}`, { method: "DELETE" }, token);
}

export function getPurchaseRequests(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<PurchaseRequest>>(`/purchase-requests?${query.toString()}`, {}, token);
}

export function getPurchaseOrders(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<PurchaseOrder>>(`/purchase-orders?${query.toString()}`, {}, token);
}

export function getDeliveries(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<Delivery>>(`/deliveries?${query.toString()}`, {}, token);
}

export function getDelivery(token: string, id: number) {
  return request<Delivery>(`/deliveries/${id}`, {}, token);
}

export function createDelivery(token: string, data: { po_id: number; expected_arrival_date?: string | null; logistics_company?: string | null; tracking_no?: string | null; items: Array<{ po_item_id: number; planned_quantity: number; batch_no?: string | null; expiry_date?: string | null }> }) {
  return request<Delivery>("/deliveries", { method: "POST", body: JSON.stringify(data) }, token);
}

export function receiveDelivery(token: string, id: number, data: { actual_arrival_date?: string | null; items: Array<{ delivery_item_id: number; actual_quantity: number; short_quantity: number }> }) {
  return request<Delivery>(`/deliveries/${id}/receive`, { method: "POST", body: JSON.stringify(data) }, token);
}

export function createPurchaseRequest(token: string, data: { purpose: string; priority: string; department_id?: number | null; budget_amount?: number | null; currency_code: string; expected_date?: string | null; items: PurchaseRequestItem[] }) {
  return request<PurchaseRequest>("/purchase-requests", { method: "POST", body: JSON.stringify(data) }, token);
}

export function submitPurchaseRequest(token: string, id: number) {
  return request<PurchaseRequest>(`/purchase-requests/${id}/submit`, { method: "POST" }, token);
}

export function approvePurchaseRequest(token: string, id: number, opinion = "") {
  return request<PurchaseRequest>(`/purchase-requests/${id}/approve`, { method: "POST", body: JSON.stringify({ opinion: opinion || null }) }, token);
}

export function rejectPurchaseRequest(token: string, id: number, opinion: string) {
  return request<PurchaseRequest>(`/purchase-requests/${id}/reject`, { method: "POST", body: JSON.stringify({ opinion }) }, token);
}

export function cancelPurchaseRequest(token: string, id: number, reason: string) {
  return request<PurchaseRequest>(`/purchase-requests/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) }, token);
}

export function submitPurchaseOrder(token: string, id: number) {
  return request<PurchaseOrder>(`/purchase-orders/${id}/submit`, { method: "POST" }, token);
}

export function approvePurchaseOrder(token: string, id: number, opinion = "") {
  return request<PurchaseOrder>(`/purchase-orders/${id}/approve`, { method: "POST", body: JSON.stringify({ opinion: opinion || null }) }, token);
}

export function rejectPurchaseOrder(token: string, id: number, opinion: string) {
  return request<PurchaseOrder>(`/purchase-orders/${id}/reject`, { method: "POST", body: JSON.stringify({ opinion: opinion || null }) }, token);
}

export function placePurchaseOrder(token: string, id: number) {
  return request<PurchaseOrder>(`/purchase-orders/${id}/place`, { method: "POST" }, token);
}

export function cancelPurchaseOrder(token: string, id: number, reason: string) {
  return request<PurchaseOrder>(`/purchase-orders/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) }, token);
}

export function getInventoryBalances(token: string, productId = "", warehouseId = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (productId) query.set("product_id", productId);
  if (warehouseId) query.set("warehouse_id", warehouseId);
  return request<PageResult<InventoryBalance>>(`/inventory/balances?${query.toString()}`, {}, token);
}

export function getWarehouses(token: string) {
  return request<Warehouse[]>("/inventory/warehouses", {}, token);
}

export function getWarehouseLocations(token: string, warehouseId: number) {
  return request<WarehouseLocation[]>(`/inventory/warehouses/${warehouseId}/locations`, {}, token);
}

export function createInbound(token: string, data: { delivery_id: number; warehouse_id: number; location_id: number; note?: string | null }) {
  return request<InboundResult>("/inventory/inbounds", { method: "POST", body: JSON.stringify(data) }, token);
}

export function freezeInventoryBalance(token: string, id: number, reason: string) {
  return request<InventoryBalance>(`/inventory/balances/${id}/freeze`, { method: "POST", body: JSON.stringify({ reason }) }, token);
}

export function unfreezeInventoryBalance(token: string, id: number, reason: string) {
  return request<InventoryBalance>(`/inventory/balances/${id}/unfreeze`, { method: "POST", body: JSON.stringify({ reason }) }, token);
}

export function getQualityAcceptances(token: string, result = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (result) query.set("result", result);
  return request<PageResult<QualityAcceptance>>(`/quality-acceptances?${query.toString()}`, {}, token);
}

export function getQualityAcceptance(token: string, id: number) {
  return request<QualityAcceptance>(`/quality-acceptances/${id}`, {}, token);
}

export function createQualityAcceptance(token: string, deliveryId: number) {
  return request<QualityAcceptance>("/quality-acceptances", { method: "POST", body: JSON.stringify({ delivery_id: deliveryId }) }, token);
}

export function submitQualityResult(token: string, id: number, data: { result: string; certificate_complete: boolean; conclusion?: string | null }) {
  return request<QualityAcceptance>(`/quality-acceptances/${id}/result`, { method: "POST", body: JSON.stringify(data) }, token);
}

export function getUsers(token: string, keyword = "", status = "", page = 1, pageSize = 8) {
  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (keyword.trim()) query.set("keyword", keyword.trim());
  if (status) query.set("status", status);
  return request<PageResult<SystemUser>>(`/system/users?${query.toString()}`, {}, token);
}

export function getUser(token: string, id: number) {
  return request<SystemUser>(`/system/users/${id}`, {}, token);
}

export function createUser(token: string, data: { username: string; password: string; display_name: string; department_id?: number | null; email?: string | null; phone?: string | null; role_ids: number[] }) {
  return request<SystemUser>("/system/users", { method: "POST", body: JSON.stringify(data) }, token);
}

export function updateUser(token: string, id: number, data: { password?: string; display_name?: string; department_id?: number | null; email?: string | null; phone?: string | null; status?: string; role_ids?: number[] }) {
  return request<SystemUser>(`/system/users/${id}`, { method: "PATCH", body: JSON.stringify(data) }, token);
}

export function deleteUser(token: string, id: number) {
  return request<SystemUser>(`/system/users/${id}`, { method: "DELETE" }, token);
}

export function getDashboardOverview(token: string) {
  return request<DashboardOverview>("/dashboard/overview", {}, token);
}

export function getDashboardReport(token: string) {
  return request<DashboardReport>("/dashboard/report", {}, token);
}

export function getUnreadNotificationCount(token: string) {
  return request<{ unread_count: number }>("/notifications/unread-count", {}, token);
}

/** 读取统一分页接口，供业务工作台的扩展模块复用。 */
export function getModulePage<T>(token: string, path: string, page = 1, pageSize = 8) {
  const separator = path.includes("?") ? "&" : "?";
  return apiRequest<PageResult<T>>(`${path}${separator}page=${page}&page_size=${pageSize}`, {}, token);
}

/** 读取详情或列表以外的数组接口。 */
export function getModuleData<T>(token: string, path: string) {
  return apiRequest<T>(path, {}, token);
}

/** 提交扩展业务模块的 JSON 请求。 */
export function postModule<T>(token: string, path: string, data?: unknown) {
  return apiRequest<T>(path, { method: "POST", ...(data === undefined ? {} : { body: JSON.stringify(data) }) }, token);
}

/** 修改扩展业务模块的 JSON 请求。 */
export function patchModule<T>(token: string, path: string, data: unknown) {
  return apiRequest<T>(path, { method: "PATCH", body: JSON.stringify(data) }, token);
}

/** 上传文件时使用 FormData，浏览器会自动补充 multipart 边界。 */
export function uploadModuleFile<T>(token: string, file: File, fileCategory: string, accessLevel: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("file_category", fileCategory);
  formData.append("access_level", accessLevel);
  return apiRequest<T>("/files", { method: "POST", body: formData, headers: {} }, token);
}

export async function downloadModuleFile(token: string, fileId: number) {
  const response = await fetch(`${API_BASE_URL}/files/${fileId}/download`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new Error(`文件下载失败（${response.status}）`);
  return response.blob();
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const response = await fetch("/health");
  if (!response.ok) throw new Error(`服务状态检查失败（${response.status}）`);
  return response.json() as Promise<SystemStatus>;
}

export async function checkHealth() {
  try {
    await getSystemStatus();
    return true;
  } catch {
    return false;
  }
}
