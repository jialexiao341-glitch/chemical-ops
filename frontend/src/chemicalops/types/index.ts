export type ViewKey = "dashboard" | "ai" | "chemicals" | "suppliers" | "products" | "purchases" | "deliveries" | "quality" | "inbounds" | "inventory" | "users" | "finance" | "logistics" | "inventory-ops" | "exceptions" | "files" | "supplier-portal" | "system" | "coming-soon";

export interface CurrentUser {
  id: number;
  username: string;
  display_name: string;
  email?: string | null;
  phone?: string | null;
  status: string;
  role_codes: string[];
  permission_codes: string[];
}

export interface Chemical {
  id: number;
  chemical_name: string;
  english_name?: string | null;
  alias_text?: string | null;
  cas_no?: string | null;
  chemical_formula?: string | null;
  molecular_weight?: number | string | null;
  hazard_class?: string | null;
  source_text?: string | null;
  status: "ACTIVE" | "INACTIVE";
  created_at?: string;
  updated_at?: string;
}

export interface Supplier {
  id: number;
  supplier_code: string;
  supplier_name: string;
  unified_credit_code?: string | null;
  country_code: string;
  region?: string | null;
  address?: string | null;
  business_scope?: string | null;
  cooperation_level?: string | null;
  payment_terms?: string | null;
  default_lead_days?: number | null;
  note?: string | null;
  status: "ACTIVE" | "SUSPENDED" | "INACTIVE";
  created_at: string;
  updated_at: string;
}

export interface Product {
  id: number;
  product_code: string;
  product_name: string;
  chemical_id: number;
  category_id?: number | null;
  model?: string | null;
  purity_value?: number | string | null;
  purity_unit?: string | null;
  packaging_spec?: string | null;
  unit_id: number;
  parameter_json?: Record<string, unknown> | null;
  version_no: number;
  status: "ACTIVE" | "INACTIVE" | "PENDING_CONFIRMATION";
  created_at: string;
  updated_at: string;
}

export interface Unit {
  id: number;
  unit_code: string;
  unit_name: string;
  dimension: string;
  status: string;
}

export interface PurchaseRequest {
  id: number;
  request_no: string;
  applicant_id: number;
  department_id?: number | null;
  purpose: string;
  priority: string;
  budget_amount?: number | string | null;
  currency_code: string;
  expected_date?: string | null;
  status: string;
  items: PurchaseRequestItem[];
  approvals: unknown[];
}

export interface PurchaseRequestItem {
  id?: number;
  product_id?: number | null;
  requested_name: string;
  technical_requirements?: string | null;
  quantity: number | string;
  unit_id: number;
  budget_price?: number | string | null;
  expected_date?: string | null;
}

export interface PurchaseOrder {
  id: number;
  po_no: string;
  supplier_id: number;
  order_amount: number | string;
  currency_code: string;
  delivery_address?: string | null;
  order_date?: string | null;
  expected_arrival_date?: string | null;
  status: string;
  items: PurchaseOrderItem[];
}

export interface PurchaseOrderItem {
  id: number;
  po_id: number;
  line_no: number;
  product_id: number;
  product_name_snapshot: string;
  supplier_model_snapshot?: string | null;
  order_quantity: number | string;
  unit_id: number;
  unit_price: number | string;
  tax_rate?: number | string | null;
  planned_arrival_date?: string | null;
  received_quantity: number | string;
  status: string;
  note?: string | null;
}

export interface DeliveryItem {
  id: number;
  delivery_id: number;
  po_item_id: number;
  product_id: number;
  line_no: number;
  batch_no?: string | null;
  package_spec?: string | null;
  planned_quantity: number | string;
  actual_quantity: number | string;
  short_quantity: number | string;
  unit_id: number;
  production_date?: string | null;
  expiry_date?: string | null;
  document_complete: number;
  note?: string | null;
}

export interface Delivery {
  id: number;
  delivery_no: string;
  po_id: number;
  supplier_id: number;
  shipment_date?: string | null;
  expected_arrival_date?: string | null;
  actual_arrival_date?: string | null;
  logistics_company?: string | null;
  tracking_no?: string | null;
  status: string;
  received_by?: number | null;
  received_at?: string | null;
  note?: string | null;
  created_at: string;
  updated_at: string;
  items: DeliveryItem[];
}

export interface Warehouse {
  id: number;
  warehouse_code: string;
  warehouse_name: string;
  region?: string | null;
  address?: string | null;
  manager_id?: number | null;
  status: string;
  note?: string | null;
}

export interface WarehouseLocation {
  id: number;
  warehouse_id: number;
  location_code: string;
  location_name: string;
  status: string;
  note?: string | null;
}

export interface InboundResult {
  delivery_id: number;
  transaction_count: number;
  transactions: Array<{ id: number; transaction_no: string; transaction_type: string; warehouse_id: number; location_id: number; product_id: number; batch_id: number; unit_id: number; quantity: number | string; delivery_item_id?: number | null; source_type?: string | null; source_id?: number | null; operator_id: number; note?: string | null; created_at: string }>;
  balances: InventoryBalance[];
}

export interface InventoryBalance {
  id: number;
  warehouse_id: number;
  location_id: number;
  product_id: number;
  batch_id: number;
  unit_id: number;
  quantity: number | string;
  locked_quantity: number | string;
  status: string;
}

export interface QualityAcceptance {
  id: number;
  acceptance_no: string;
  delivery_id: number;
  inspector_id: number;
  result: string;
  inspection_time?: string | null;
  certificate_complete: number;
  report_file_id?: number | null;
  conclusion?: string | null;
}

export interface SystemUser {
  id: number;
  username: string;
  display_name: string;
  department_id?: number | null;
  email?: string | null;
  phone?: string | null;
  status: string;
}

export interface SystemStatus {
  status: string;
  service: string;
  environment: string;
  data_source: "database";
  data_mode: "demo" | "production";
}

export interface DashboardOverview {
  purchase_orders_total: number;
  purchase_orders_in_progress: number;
  deliveries_overdue: number;
  inventory_quantity: number | string;
  inventory_units?: Array<{ unit_id: number; unit_code: string; unit_name: string; quantity: number | string }>;
  open_exceptions: number;
  confirmed_reconciliations: number;
  paid_amount: number | string;
  expiry_alerts: number;
}

export interface DashboardReport {
  date_from?: string | null;
  date_to?: string | null;
  order_trend: Array<{ date: string; order_count: number; order_amount: number | string }>;
  order_statuses: Array<{ status: string; order_count: number; order_amount: number | string }>;
  supplier_performance: Array<{ supplier_id: number; supplier_name: string; order_count: number; order_amount: number | string; overdue_deliveries: number }>;
  inventory_costs: Array<{ product_id: number; product_name: string; outbound_quantity: number | string; outbound_cost: number | string }>;
  pending_tasks: Array<{ task_type: string; task_count: number }>;
  inventory_alerts: Array<{ product_name: string; quantity: number | string; unit_name: string; expiry_date: string; days_remaining: number; level: string }>;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
