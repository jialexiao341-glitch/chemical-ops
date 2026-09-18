import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Chemical, CurrentUser, DashboardOverview, DashboardReport, Delivery, InventoryBalance, Product, PurchaseOrder, PurchaseRequest, PurchaseRequestItem, QualityAcceptance, Supplier, SystemStatus, SystemUser, Unit, ViewKey } from "./types";
import { approvePurchaseOrder, approvePurchaseRequest, cancelPurchaseOrder, cancelPurchaseRequest, checkHealth, createChemical, createProduct, createPurchaseRequest, createQualityAcceptance, createSupplier, createUser, deleteChemical, deleteProduct, deleteSupplier, deleteUser, freezeInventoryBalance, getChemical, getChemicals, getCurrentUser, getDashboardOverview, getDashboardReport, getDeliveries, getInventoryBalances, getProduct, getProducts, getPurchaseOrders, getPurchaseRequests, getQualityAcceptance, getQualityAcceptances, getSupplier, getSuppliers, getSystemStatus, getUnits, getUnreadNotificationCount, getUser, getUsers, login, placePurchaseOrder, rejectPurchaseOrder, rejectPurchaseRequest, submitPurchaseOrder, submitPurchaseRequest, submitQualityResult, unfreezeInventoryBalance, updateChemical, updateProduct, updateSupplier, updateUser } from "./services/api";
import BusinessModulesPage from "./pages/BusinessModulesPage";
import { DeliveriesPage, InboundsPage } from "./pages/FulfillmentPages";
import { ConfirmDialog, TextPromptDialog } from "./components/ActionDialog";
import AIFloatingAssistant from "./components/AIFloatingAssistant";
import { formatAmount, formatAmountWithCurrency, formatDateTime, formatDecimal, formatPercent, formatQuantity, formatQuantityWithUnit, statusLabel } from "./utils/format";

type IconName =
  | "activity"
  | "beaker"
  | "box"
  | "cart"
  | "check"
  | "chevron"
  | "clock"
  | "database"
  | "file"
  | "grid"
  | "menu"
  | "search"
  | "settings"
  | "shield"
  | "truck"
  | "users"
  | "warning";

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, string> = {
    activity: "M3 12h4l2-7 4 14 2-7h6",
    beaker: "M9 3h6M10 3v5l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7 15h10",
    box: "m4 7 8-4 8 4v10l-8 4-8-4V7Zm0 0 8 4 8-4M12 11v10",
    cart: "M3 4h2l2 11h10l2-8H6M9 19a1 1 0 1 1-2 0m11 0a1 1 0 1 1-2 0",
    check: "m5 12 4 4L19 6",
    chevron: "m8 10 4 4 4-4",
    clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
    database: "M4 5c0-2 16-2 16 0v14c0 2-16 2-16 0V5Zm0 0c0 2 16 2 16 0M4 12c0 2 16 2 16 0",
    file: "M6 3h8l4 4v14H6V3Zm8 0v5h4M9 13h6m-6 4h4",
    grid: "M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z",
    menu: "M4 6h16M4 12h16M4 18h16",
    search: "m20 20-4.5-4.5M10.5 17a6.5 6.5 0 1 1 0-13 6.5 6.5 0 0 1 0 13Z",
    settings: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm0-13v2m0 13v2m9-9h-2M5 12H3m15.4-6.4-1.4 1.4M7 17l-1.4 1.4m12.8 0L17 17M7 7 5.6 5.6",
    shield: "M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Zm-3 9 2 2 4-4",
    truck: "M3 6h11v10H3V6Zm11 4h4l3 3v3h-7v-6Zm-8 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
    users: "M16 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1m7-9a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm6-7a3 3 0 0 1 0 6m4 7v-1a4 4 0 0 0-3-3.9",
    warning: "M12 3 2.5 20h19L12 3Zm0 6v5m0 3h.01",
  };

  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={paths[name]} />
    </svg>
  );
}

function roleLabel(code?: string) {
  return ({ SYS_ADMIN: "系统管理员", ADMIN: "管理员", PURCHASER: "采购人员", WAREHOUSE: "仓储人员", QUALITY: "质量人员", SUPPLIER: "供应商用户" } as Record<string, string>)[code || ""] || "业务用户";
}

function ListPagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startPage = Math.min(Math.max(1, page - 3), Math.max(1, totalPages - 6));
  const pageNumbers = Array.from({ length: Math.min(7, totalPages) }, (_, index) => startPage + index);
  return <div className="pagination"><span>共 {total} 条</span><div><button className="outline-button" disabled={page <= 1} onClick={() => onChange(page - 1)}>上一页</button>{pageNumbers.map((pageNumber) => <button key={pageNumber} className={`outline-button pagination-page ${pageNumber === page ? "selected" : ""}`} aria-current={pageNumber === page ? "page" : undefined} onClick={() => onChange(pageNumber)}>{pageNumber}</button>)}<button className="outline-button" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>下一页</button></div><span>第 {page} / {totalPages} 页</span></div>;
}

const menuGroups = [
  {
    title: "工作区",
    items: [{ key: "dashboard" as ViewKey, label: "运营总览", icon: "activity" as IconName }],
  },
  {
    title: "基础数据",
    items: [
      { key: "chemicals" as ViewKey, label: "化学品管理", icon: "beaker" as IconName },
      { key: "suppliers" as ViewKey, label: "供应商管理", icon: "users" as IconName },
      { key: "products" as ViewKey, label: "产品与包装", icon: "box" as IconName },
    ],
  },
  {
    title: "采购履约",
    items: [
      { key: "purchases" as ViewKey, label: "采购申请与订单", icon: "cart" as IconName },
      { key: "deliveries" as ViewKey, label: "到货与收货", icon: "truck" as IconName },
      { key: "quality" as ViewKey, label: "质量验收", icon: "shield" as IconName },
      { key: "inbounds" as ViewKey, label: "库存入库", icon: "box" as IconName },
    ],
  },
  {
    title: "业务支撑",
    items: [
      { key: "inventory" as ViewKey, label: "库存台账", icon: "database" as IconName },
      { key: "logistics" as ViewKey, label: "询价与供应", icon: "users" as IconName },
      { key: "finance" as ViewKey, label: "财务管理", icon: "database" as IconName },
      { key: "inventory-ops" as ViewKey, label: "仓储作业", icon: "box" as IconName },
    ],
  },
  { title: "控制中心", items: [{ key: "exceptions" as ViewKey, label: "异常与通知", icon: "warning" as IconName }, { key: "files" as ViewKey, label: "文件与附件", icon: "file" as IconName }, { key: "supplier-portal" as ViewKey, label: "供应商门户", icon: "users" as IconName }] },
  { title: "系统设置", items: [{ key: "users" as ViewKey, label: "用户与权限", icon: "settings" as IconName }, { key: "system" as ViewKey, label: "组织与权限", icon: "shield" as IconName }] },
];

function LoginPage({ onLogin }: { onLogin: (user: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState("system_admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onLogin(username, password);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <div className="login-decoration decoration-one" />
      <div className="login-decoration decoration-two" />
      <section className="login-panel">
        <div className="login-brand"><img className="brand-mark brand-logo" src="/chemicalops-icon.svg" alt="化学品运营" /><span>化学品<span>运营</span></span></div>
        <div className="login-intro">
          <p className="eyebrow">化学品运营平台</p>
          <h1>让每一批化学品，<br /><em>都可追溯、可控、可决策。</em></h1>
          <p className="login-copy">连接采购、仓储、质量与供应商数据，构建面向化学品业务的运营控制台。</p>
        </div>
        <form onSubmit={submit} className="login-form">
          <label>登录账号<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="请输入账号" autoComplete="username" /></label>
          <label>登录密码<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" placeholder="请输入密码" autoComplete="current-password" /></label>
          {error && <div className="form-error"><Icon name="warning" size={16} />{error}</div>}
          <button className="primary-button login-button" disabled={loading}>{loading ? "正在验证…" : "进入运营工作台"}<span>→</span></button>
        </form>
      </section>
      <aside className="login-aside">
        <div className="aside-orbit orbit-a" /><div className="aside-orbit orbit-b" />
        <div className="molecule molecule-a"><span /><span /><span /></div>
        <div className="molecule molecule-b"><span /><span /><span /><span /></div>
        <div className="login-aside-content"><p className="eyebrow">运营中心 / 01</p><h2>数据稳定，<br /><span>决策更快。</span></h2><p>从化学品主数据到库存预警，化学品运营平台把关键动作放在同一张运营地图上。</p><div className="aside-status"><span className="status-dot" />系统服务已准备就绪</div></div>
      </aside>
    </main>
  );
}

function Sidebar({ activeView, onSelect, user }: { activeView: ViewKey; onSelect: (view: ViewKey) => void; user: CurrentUser }) {
  const canUseSupplierPortal = user.role_codes.includes("SUPPLIER_PORTAL") && user.permission_codes.includes("supplier.portal.read");
  return (
    <aside className="sidebar">
      <div className="sidebar-brand"><img className="brand-mark brand-logo" src="/chemicalops-icon.svg" alt="化学品运营" /><span>化学品<span>运营</span></span></div>
      <div className="workspace-switch"><span className="workspace-icon">C</span><span><strong>化学品运营中心</strong><small>主工作区</small></span><Icon name="chevron" size={15} /></div>
      <nav className="sidebar-nav">
        {menuGroups.map((group) => <div className="nav-group" key={group.title}><div className="nav-group-title">{group.title}</div>{group.items.filter((item) => item.key !== "supplier-portal" || canUseSupplierPortal).map((item) => <button key={`${group.title}-${item.label}`} className={`nav-item ${activeView === item.key && item.key !== "coming-soon" ? "active" : ""}`} onClick={() => onSelect(item.key)}><Icon name={item.icon} size={17} /><span>{item.label}</span></button>)}</div>)}
      </nav>
    </aside>
  );
}

type AccountPanel = "profile" | "edit" | "password" | "recovery" | null;

function AccountMenu({ user, token, onUserUpdate, onLogout }: { user: CurrentUser; token: string; onUserUpdate: (user: CurrentUser) => void; onLogout: () => void }) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [panel, setPanel] = useState<AccountPanel>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [profile, setProfile] = useState({ display_name: user.display_name, email: user.email || "", phone: user.phone || "" });
  const [password, setPassword] = useState({ current: "", next: "", confirm: "" });

  useEffect(() => {
    if (!open) return;
    function handleOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  function openPanel(next: Exclude<AccountPanel, null>) {
    setOpen(false); setPanel(next); setError("");
    if (next === "edit") setProfile({ display_name: user.display_name, email: user.email || "", phone: user.phone || "" });
    if (next === "password") setPassword({ current: "", next: "", confirm: "" });
  }
  function closePanel() { if (!saving) { setPanel(null); setError(""); } }
  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!profile.display_name.trim()) { setError("请输入姓名"); return; }
    setSaving(true); setError("");
    try { await updateUser(token, user.id, { display_name: profile.display_name.trim(), email: profile.email.trim() || null, phone: profile.phone.trim() || null }); onUserUpdate(await getCurrentUser(token)); setPanel(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "个人信息保存失败"); }
    finally { setSaving(false); }
  }
  async function savePassword(event: FormEvent) {
    event.preventDefault();
    if (password.next.length < 8) { setError("新密码至少需要 8 位"); return; }
    if (password.next !== password.confirm) { setError("两次输入的新密码不一致"); return; }
    setSaving(true); setError("");
    try { await updateUser(token, user.id, { password: password.next }); setPanel(null); setPassword({ current: "", next: "", confirm: "" }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "密码修改失败"); }
    finally { setSaving(false); }
  }

  return <div className="account-menu" ref={menuRef}>
    <button type="button" className="user-menu user-menu-trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((current) => !current)}><span className="avatar">{user.display_name.slice(0, 1)}</span><span><strong>{user.display_name}</strong><small>{roleLabel(user.role_codes[0])}</small></span><Icon name="chevron" size={15} /></button>
    {open && <div className="account-dropdown" role="menu"><div className="account-dropdown-header"><span>当前账号</span><strong>{user.username}</strong></div><button type="button" role="menuitem" onClick={() => openPanel("profile")}>个人资料<span>→</span></button><button type="button" role="menuitem" onClick={() => openPanel("edit")}>修改信息<span>→</span></button><button type="button" role="menuitem" onClick={() => openPanel("password")}>修改密码<span>→</span></button><button type="button" role="menuitem" onClick={() => openPanel("recovery")}>找回密码<span>→</span></button><div className="account-dropdown-divider" /><button type="button" className="account-logout" role="menuitem" onClick={onLogout}>退出登录</button></div>}
    {panel === "profile" && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePanel(); }}><section className="modal surface account-modal"><div className="section-heading"><div><h2>个人资料</h2><p>查看当前账号信息</p></div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={closePanel}>×</button></div><div className="account-info-grid"><span>登录账号<strong>{user.username}</strong></span><span>姓名<strong>{user.display_name}</strong></span><span>邮箱<strong>{user.email || "未填写"}</strong></span><span>手机号<strong>{user.phone || "未填写"}</strong></span><span>账号角色<strong>{roleLabel(user.role_codes[0])}</strong></span><span>账号状态<strong>{user.status === "ACTIVE" ? "正常" : "已停用"}</strong></span></div><div className="modal-actions"><button type="button" className="primary-button" onClick={closePanel}>关闭</button></div></section></div>}
    {panel === "edit" && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePanel(); }}><form className="modal surface account-modal" onSubmit={saveProfile}><div className="section-heading"><div><h2>修改信息</h2><p>更新个人联系信息</p></div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={closePanel}>×</button></div><div className="form-grid"><label>姓名<input value={profile.display_name} onChange={(event) => setProfile({ ...profile, display_name: event.target.value })} /></label><label>邮箱<input type="email" value={profile.email} onChange={(event) => setProfile({ ...profile, email: event.target.value })} /></label><label>手机号<input value={profile.phone} onChange={(event) => setProfile({ ...profile, phone: event.target.value })} /></label></div>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={closePanel}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "保存信息"}</button></div></form></div>}
    {panel === "password" && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePanel(); }}><form className="modal surface account-modal" onSubmit={savePassword}><div className="section-heading"><div><h2>修改密码</h2><p>设置新的登录密码</p></div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={closePanel}>×</button></div><div className="form-grid"><label className="wide-field">当前密码<input type="password" value={password.current} onChange={(event) => setPassword({ ...password, current: event.target.value })} /></label><label>新密码<input type="password" value={password.next} onChange={(event) => setPassword({ ...password, next: event.target.value })} /></label><label>确认新密码<input type="password" value={password.confirm} onChange={(event) => setPassword({ ...password, confirm: event.target.value })} /></label></div>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={closePanel}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "确认修改"}</button></div></form></div>}
    {panel === "recovery" && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closePanel(); }}><section className="modal surface account-modal"><div className="section-heading"><div><h2>找回密码</h2><p>需要重置密码时，请联系系统管理员处理。</p></div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={closePanel}>×</button></div><div className="recovery-note"><strong>账号：{user.username}</strong><span>管理员完成重置后，请使用新密码登录。</span></div><div className="modal-actions"><button type="button" className="primary-button" onClick={closePanel}>知道了</button></div></section></div>}
  </div>;
}

type BarChartRow = { id: string | number; label: string; value: number; detail: string; tone?: string };

function getAlertLevel(level: string) {
  return level === "EXPIRED" ? { label: "已过期", tone: "critical" } : level === "URGENT" ? { label: "7 天内到期", tone: "urgent" } : { label: "30 天内到期", tone: "warning" };
}

function HorizontalBarChart({ rows, valueFormatter, emptyLabel }: { rows: BarChartRow[]; valueFormatter: (value: number) => string; emptyLabel: string }) {
  const maxValue = Math.max(1, ...rows.map((row) => row.value));
  return rows.length ? <div className="dashboard-chart-list" role="list">{rows.map((row) => <div className="dashboard-chart-row" key={row.id} role="listitem"><div className="dashboard-chart-label"><span title={row.label}>{row.label}</span><strong>{valueFormatter(row.value)}</strong></div><div className="dashboard-chart-track"><i className={row.tone || ""} style={{ width: `${Math.max(7, (row.value / maxValue) * 100)}%`, animationDelay: `${Math.min(420, rows.indexOf(row) * 55)}ms` }} /></div><small>{row.detail}</small></div>)}</div> : <div className="dashboard-chart-empty">{emptyLabel}</div>;
}

function InventoryExpiryChart({ rows, onViewInventory }: { rows: DashboardReport["inventory_alerts"] | null; onViewInventory: () => void }) {
  if (!rows) return <div className="inventory-expiry-empty is-loading"><span>…</span><div><strong>正在加载预警数据</strong><small>正在从数据库汇总库存批次状态</small></div></div>;
  const riskCounts = [
    { key: "EXPIRED", label: "已过期", tone: "critical", count: rows.filter((row) => row.level === "EXPIRED").length },
    { key: "URGENT", label: "7 天内到期", tone: "urgent", count: rows.filter((row) => row.level === "URGENT").length },
    { key: "WARNING", label: "30 天内到期", tone: "warning", count: rows.filter((row) => row.level === "WARNING").length },
  ];
  const total = rows.length;
  const maxDays = Math.max(30, ...rows.map((row) => Math.max(0, row.days_remaining)));
  return <div className="inventory-expiry-chart">
    <div className="inventory-risk-summary" aria-label={`库存有效期预警共 ${total} 项`}>
      {riskCounts.map((item) => <div className={`inventory-risk-stat ${item.tone}`} key={item.key}><span><i />{item.label}</span><strong>{item.count}</strong><small>{total ? `${Math.round((item.count / total) * 100)}%` : "0%"}</small></div>)}
    </div>
    <div className="inventory-risk-meter" aria-hidden="true">
      {riskCounts.map((item) => <i key={item.key} className={item.tone} style={{ width: `${total ? (item.count / total) * 100 : 0}%` }} />)}
    </div>
    {rows.length ? <div className="inventory-expiry-list" role="list">{rows.slice(0, 6).map((row, index) => {
      const level = getAlertLevel(row.level);
      const progress = row.days_remaining < 0 ? 100 : Math.max(8, Math.min(100, ((maxDays - row.days_remaining) / maxDays) * 100));
      return <div className="inventory-expiry-row" key={`${row.product_name}-${row.expiry_date}-${index}`} role="listitem">
        <div className="inventory-expiry-row-head"><span title={row.product_name}>{row.product_name}</span><strong>{row.days_remaining < 0 ? `已过期 ${Math.abs(row.days_remaining)} 天` : `${row.days_remaining} 天后到期`}</strong></div>
        <div className="inventory-expiry-track"><i className={level.tone} style={{ width: `${progress}%` }} /></div>
        <div className="inventory-expiry-row-meta"><small>{formatQuantity(row.quantity)} {row.unit_name} · 到期 {row.expiry_date}</small><span className={`risk-pill ${level.tone}`}><i />{level.label}</span></div>
      </div>;
    })}</div> : <div className="inventory-expiry-empty"><span>✓</span><div><strong>当前没有 30 天内有效期预警</strong><small>库存批次状态稳定，可继续关注实时变化</small></div></div>}
    <button type="button" className="inventory-expiry-link" onClick={onViewInventory}>查看库存明细 <span>→</span></button>
  </div>;
}

function PurchaseTrendChart({ rows }: { rows: DashboardReport["order_trend"] }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  if (!rows.length) return <div className="dashboard-chart-empty">暂无近 30 日采购趋势数据</div>;
  const width = 620;
  const height = 190;
  const chartLeft = 34;
  const chartRight = 10;
  const chartTop = 12;
  const chartBottom = 30;
  const values = rows.map((row) => Number(row.order_amount) || 0);
  const maxValue = Math.max(1, ...values);
  const points = rows.map((row, index) => {
    const x = rows.length === 1 ? (width + chartLeft - chartRight) / 2 : chartLeft + (index / (rows.length - 1)) * (width - chartLeft - chartRight);
    const y = height - chartBottom - (values[index] / maxValue) * (height - chartTop - chartBottom);
    return { x, y, row };
  });
  const labels = Array.from(new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1]));
  const linePoints = points.map((point) => `${point.x},${point.y}`).join(" ");
  const hoveredPoint = hoveredIndex === null ? null : points[hoveredIndex];
  return <div className="line-chart-wrap" onMouseLeave={() => setHoveredIndex(null)}><svg className="dashboard-line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="采购订单金额趋势图"><g className="dashboard-line-grid">{[0, 1, 2, 3].map((step) => { const y = chartTop + step * ((height - chartTop - chartBottom) / 3); return <line key={step} x1={chartLeft} y1={y} x2={width - chartRight} y2={y} />; })}</g>{points.length > 1 && <polyline className="dashboard-line-area" points={`${chartLeft},${height - chartBottom} ${linePoints} ${width - chartRight},${height - chartBottom}`} />}<polyline className="dashboard-line-path" points={linePoints} />{points.map((point, index) => <circle key={point.row.date} className={hoveredIndex === index ? "is-hovered" : ""} cx={point.x} cy={point.y} r="3.5" tabIndex={0} onMouseEnter={() => setHoveredIndex(index)} onFocus={() => setHoveredIndex(index)} onBlur={() => setHoveredIndex(null)}><title>{`${point.row.date} · ${formatAmount(point.row.order_amount)} CNY · ${point.row.order_count} 单`}</title></circle>)}{labels.map((index) => <text key={rows[index].date} x={points[index].x} y={height - 8} textAnchor={index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle"}>{rows[index].date.slice(5)}</text>)}</svg>{hoveredPoint && <div className="line-chart-tooltip" style={{ left: `${(hoveredPoint.x / width) * 100}%`, top: `${Math.max(4, (hoveredPoint.y / height) * 100 - 16)}%` }}><strong>{formatAmount(hoveredPoint.row.order_amount)} CNY</strong><span>{hoveredPoint.row.date} · {hoveredPoint.row.order_count} 单</span></div>}<div className="line-chart-caption"><span><i />采购金额 <small>悬停查看每日明细</small></span><small>单位：CNY</small></div></div>;
}

function OrderStatusPieChart({ rows }: { rows: DashboardReport["order_statuses"] }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const total = rows.reduce((sum, row) => sum + row.order_count, 0);
  if (!total) return <div className="dashboard-chart-empty">暂无订单状态数据</div>;
  const colors = ["#1e9b88", "#6eb9db", "#e3a54c", "#dc7061", "#8c9da3"];
  const radius = 47;
  const circumference = 2 * Math.PI * radius;
  let cursor = 0;
  const segments = rows.map((row, index) => {
    const ratio = row.order_count / total;
    const segment = { row, index, ratio, percent: ratio * 100, offset: cursor };
    cursor += ratio * circumference;
    return segment;
  });
  return (
    <div className="pie-chart-layout">
      <div className="dashboard-pie" role="img" aria-label={`订单状态分布，共 ${total} 单`}>
        <svg className="dashboard-pie-svg" viewBox="0 0 120 120" aria-hidden="true">
          <circle className="dashboard-pie-track" cx="60" cy="60" r={radius} />
          <g transform="rotate(-90 60 60)">
            {segments.map((segment) => (
              <circle
                key={segment.row.status}
                className={`dashboard-pie-segment ${activeIndex === segment.index ? "is-active" : ""}`}
                style={{ animationDelay: `${segment.index * 90}ms` }}
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke={colors[segment.index % colors.length]}
                strokeWidth="18"
                strokeLinecap="butt"
                strokeDasharray={`${Math.max(0, segment.ratio * circumference - 1.5)} ${circumference}`}
                strokeDashoffset={-segment.offset}
                onMouseEnter={() => setActiveIndex(segment.index)}
                onMouseLeave={() => setActiveIndex(null)}
              />
            ))}
          </g>
          <text className="dashboard-pie-number" x="60" y="57" textAnchor="middle">{activeIndex === null ? total : rows[activeIndex].order_count}</text>
          <text className="dashboard-pie-label" x="60" y="69" textAnchor="middle">{activeIndex === null ? "订单总数" : purchaseStatusLabel(rows[activeIndex].status)}</text>
          {activeIndex !== null && <text className="dashboard-pie-percent" x="60" y="80" textAnchor="middle">{formatPercent((rows[activeIndex].order_count / total) * 100, 1)}</text>}
        </svg>
      </div>
      <div className="pie-chart-legend">
        {segments.map((segment) => (
          <button
            type="button"
            key={segment.row.status}
            className={`pie-chart-legend-row ${activeIndex === segment.index ? "is-active" : ""}`}
            onMouseEnter={() => setActiveIndex(segment.index)}
            onMouseLeave={() => setActiveIndex(null)}
            onFocus={() => setActiveIndex(segment.index)}
            onBlur={() => setActiveIndex(null)}
          >
            <span className="pie-chart-legend-name"><i style={{ background: colors[segment.index % colors.length] }}></i><span>{purchaseStatusLabel(segment.row.status)}</span></span>
            <span className="pie-chart-legend-value"><strong>{formatPercent(segment.percent, segment.percent >= 10 ? 0 : 1)}</strong><small>{segment.row.order_count} 单</small></span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Dashboard({ user, token, apiOnline, onSelect }: { user: CurrentUser; token: string; apiOnline: boolean; onSelect: (view: ViewKey) => void }) {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [report, setReport] = useState<DashboardReport | null>(null);
  const [overviewError, setOverviewError] = useState("");
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [lastSyncedAt, setLastSyncedAt] = useState("");
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  function inventoryMetric() {
    if (!overview) return "—";
    const units = overview.inventory_units || [];
    if (units.length === 1) return `${formatQuantity(units[0].quantity)} ${units[0].unit_name}`;
    if (units.length > 1) return "多单位";
    return formatQuantity(overview.inventory_quantity);
  }
  function inventoryCaption() {
    if (!overview?.inventory_units?.length) return "库存余额";
    return overview.inventory_units.map((item) => `${formatQuantity(item.quantity)} ${item.unit_name}`).join(" · ");
  }
  function taskCount(taskType: string) {
    return report?.pending_tasks.find((task) => task.task_type === taskType)?.task_count ?? 0;
  }
  async function loadDashboard() {
    setDashboardLoading(true); setOverviewError("");
    try { const [overviewData, reportData] = await Promise.all([getDashboardOverview(token), getDashboardReport(token)]); setOverview(overviewData); setReport(reportData); setLastSyncedAt(new Date().toISOString()); }
    catch (reason) { setOverviewError(reason instanceof Error ? reason.message : "运营总览数据加载失败"); }
    finally { setDashboardLoading(false); }
  }
  useEffect(() => {
    void loadDashboard();
    void getSystemStatus().then(setSystemStatus).catch(() => setSystemStatus(null));
    const refreshTimer = window.setInterval(() => {
      if (!document.hidden) void loadDashboard();
    }, 60_000);
    return () => window.clearInterval(refreshTimer);
  }, [token]);
  const greeting = user.display_name || user.username;
  const nowLabel = new Intl.DateTimeFormat("zh-CN", { weekday: "long", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()).replaceAll("/", " / ");
  const taskRows = [
    { type: "PURCHASE_ORDER_APPROVAL", icon: "file" as IconName, tone: "coral", title: "采购订单待审批", description: "采购订单等待审批", view: "purchases" as ViewKey },
    { type: "QUALITY_ACCEPTANCE", icon: "beaker" as IconName, tone: "amber", title: "质检任务待处理", description: "质量验收等待处理", view: "quality" as ViewKey },
    { type: "DELIVERY_CONFIRMATION", icon: "truck" as IconName, tone: "blue", title: "到货单待确认", description: "运输中的到货单", view: "logistics" as ViewKey },
    { type: "OPEN_EXCEPTION", icon: "warning" as IconName, tone: "coral", title: "异常事项待处理", description: "异常记录等待跟进", view: "exceptions" as ViewKey },
    { type: "INVENTORY_EXPIRY", icon: "clock" as IconName, tone: "amber", title: "库存有效期预警", description: "库存批次临近或已过期", view: "inventory" as ViewKey },
  ];
  const orderStatusRows: BarChartRow[] = report?.order_statuses.map((row) => ({ id: row.status, label: purchaseStatusLabel(row.status), value: row.order_count, detail: `${formatAmount(row.order_amount)} CNY`, tone: "mineral" })) || [];
  const supplierRows: BarChartRow[] = report?.supplier_performance.slice(0, 5).map((row) => ({ id: row.supplier_id, label: row.supplier_name, value: Number(row.order_amount), detail: `${row.order_count} 个订单${row.overdue_deliveries ? ` · ${row.overdue_deliveries} 个逾期` : ""}`, tone: "blue" })) || [];
  const inventoryCostRows: BarChartRow[] = report?.inventory_costs.slice(0, 5).map((row) => ({ id: row.product_id, label: row.product_name, value: Number(row.outbound_cost), detail: `出库 ${formatQuantity(row.outbound_quantity)}`, tone: "amber" })) || [];
  const dataModeLabel = systemStatus?.data_mode === "demo" ? "演示环境" : systemStatus?.data_mode === "production" ? "生产环境" : "环境未知";
  return <>
    <div className="page-heading"><div><p className="eyebrow">{nowLabel}</p><h1>运营总览</h1><p>早上好，{greeting}。这里是今天的业务脉搏。</p></div><div className="dashboard-heading-actions"><span className="data-source-badge" title="指标来自当前数据库，不代表已接入生产业务系统；页面每 60 秒自动同步"><i className="status-dot" />数据库实时聚合 · {dataModeLabel} · 自动同步 60 秒{lastSyncedAt ? ` · ${formatDateTime(lastSyncedAt)}` : ""}</span><button className="outline-button" onClick={() => void loadDashboard()} disabled={dashboardLoading}>{dashboardLoading ? "同步中…" : "刷新数据"}<span aria-hidden="true">↻</span></button><button className="outline-button" onClick={() => onSelect("chemicals")}><Icon name="database" size={16} />查看化学品台账</button></div></div>
    {overviewError && <div className="inline-error"><Icon name="warning" size={16} />{overviewError}</div>}<div className="metrics-grid">
      <Metric icon="beaker" label="库存总量" value={inventoryMetric()} change="实时" caption={inventoryCaption()} tone="green" />
      <Metric icon="warning" label="逾期到货" value={overview ? String(overview.deliveries_overdue) : "—"} change="实时" caption="待处理" tone="amber" />
      <Metric icon="file" label="进行中订单" value={overview ? String(overview.purchase_orders_in_progress) : "—"} change="实时" caption={`共 ${overview?.purchase_orders_total ?? "—"} 个`} tone="blue" />
      <Metric icon="users" label="异常事项" value={overview ? String(overview.open_exceptions) : "—"} change="实时" caption="待关注" tone="green" />
    </div>
    <div className="dashboard-visuals-grid">
      <section className="surface chart-card"><div className="section-heading"><div><p className="eyebrow">采购趋势</p><h2>近 30 日采购金额</h2></div><span className="report-date">按日聚合</span></div><PurchaseTrendChart rows={report?.order_trend || []} /></section>
      <section className="surface chart-card"><div className="section-heading"><div><p className="eyebrow">订单结构</p><h2>订单状态分布</h2></div><span className="report-date">实时汇总</span></div><OrderStatusPieChart rows={report?.order_statuses || []} /></section>
    </div>
    <div className="dashboard-grid">
      <section className="surface chart-card"><div className="section-heading"><div><p className="eyebrow">采购动态</p><h2>订单状态</h2></div><span className="report-date">实时汇总</span></div><div className="chart-summary"><strong>{report ? report.order_statuses.reduce((total, row) => total + row.order_count, 0) : "—"}</strong><span>订单总数</span></div><HorizontalBarChart rows={orderStatusRows} valueFormatter={(value) => `${value} 单`} emptyLabel={report ? "暂无订单统计" : "正在加载订单统计…"} /></section>
      <section className="surface todo-card"><div className="section-heading"><div><p className="eyebrow">待办队列</p><h2>待办事项</h2></div><button className="text-button" onClick={() => onSelect("exceptions")}>查看全部 <span>→</span></button></div>{taskRows.map((task) => <TodoItem key={task.type} icon={task.icon} tone={task.tone} title={task.title} desc={`${report ? taskCount(task.type) : "—"} 个${task.description}`} count={report ? String(taskCount(task.type)) : "—"} time="实时" onClick={() => onSelect(task.view)} />)}</section>
    </div>
    <div className="dashboard-charts-grid">
      <section className="surface chart-card"><div className="section-heading"><div><p className="eyebrow">供应商表现</p><h2>采购金额 TOP 5</h2></div><span className="report-date">按订单金额</span></div><HorizontalBarChart rows={supplierRows} valueFormatter={(value) => `${formatAmount(value)} CNY`} emptyLabel={report ? "暂无供应商采购统计" : "正在加载供应商统计…"} /></section>
      <section className="surface chart-card"><div className="section-heading"><div><p className="eyebrow">库存成本</p><h2>出库成本 TOP 5</h2></div><span className="report-date">按出库成本</span></div><HorizontalBarChart rows={inventoryCostRows} valueFormatter={(value) => `${formatAmount(value)} CNY`} emptyLabel={report ? "暂无出库成本统计" : "正在加载库存成本…"} /></section>
    </div>
    <section className="surface alert-card"><div className="section-heading"><div><p className="eyebrow">风险关注</p><h2>库存有效期预警</h2></div><span className="report-date">按风险等级</span></div><InventoryExpiryChart rows={report?.inventory_alerts ?? null} onViewInventory={() => onSelect("inventory")} /></section>
    <footer className="page-footer"><span>化学品运营中心 · 数据加载时间 {formatDateTime(new Date().toISOString())}</span><span className={apiOnline ? "online-label" : "offline-label"}><i className="status-dot" />{apiOnline ? "服务在线" : "服务连接异常"}</span></footer>
  </>;
}

function Metric({ icon, label, value, change, caption, tone }: { icon: IconName; label: string; value: string; change: string; caption: string; tone: string }) { return <article className="metric-card"><div className={`metric-icon ${tone}`}><Icon name={icon} size={21} /></div><div className="metric-content"><span>{label}</span><strong>{value}</strong><small className={tone === "amber" ? "change-up" : "change-down"}>{tone === "amber" ? "↑" : "↑"} {change} <em>{caption}</em></small></div><span className="metric-spark">↗</span></article>; }

function TodoItem({ icon, tone, title, desc, count, time, onClick }: { icon: IconName; tone: string; title: string; desc: string; count: string; time: string; onClick: () => void }) { return <button type="button" className="todo-item" onClick={onClick}><span className={`todo-icon ${tone}`}><Icon name={icon} size={18} /></span><span className="todo-copy"><strong>{title}</strong><small>{desc}</small></span><span className={`todo-count ${tone}`}>{count}</span><span className="todo-time">{time}</span></button>; }

// 危险类别使用统一选项，避免同一类别被录入成不同文字。
const hazardClassOptions = ["易燃液体", "腐蚀性物质", "急性毒性", "氧化性物质", "有害/刺激性", "环境危害"];

function ChemicalsPage({ token }: { token: string }) {
  const [chemicals, setChemicals] = useState<Chemical[]>([]);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 8;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Partial<Chemical> | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  async function loadChemicals(search = keyword, selectedStatus = status, requestedPage = 1) {
    setLoading(true); setError("");
    try { const result = await getChemicals(token, search, selectedStatus, requestedPage, pageSize); setChemicals(result.items.map((item) => ({ ...item, molecular_weight: formatDecimal(item.molecular_weight) }))); setPage(result.page); setTotal(result.total); } catch (reason) { setError(reason instanceof Error ? reason.message : "化学品数据加载失败"); } finally { setLoading(false); }
  }

  async function saveChemical(event: FormEvent) {
    event.preventDefault();
    if (!editing?.chemical_name?.trim()) { setError("化学品名称不能为空"); return; }
    setSaving(true); setError("");
    try { const payload = { chemical_name: editing.chemical_name.trim(), english_name: editing.english_name || null, alias_text: editing.alias_text || null, cas_no: editing.cas_no || null, chemical_formula: editing.chemical_formula || null, molecular_weight: editing.molecular_weight ?? null, hazard_class: editing.hazard_class || null, source_text: editing.source_text || null }; if (editing.id) await updateChemical(token, editing.id, payload); else await createChemical(token, payload); setEditing(null); await loadChemicals(keyword, status, page); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "化学品保存失败"); }
    finally { setSaving(false); }
  }
  async function disableChemical(id: number) { setError(""); try { await deleteChemical(token, id); await loadChemicals(keyword, status, page); } catch (reason) { setError(reason instanceof Error ? reason.message : "化学品停用失败"); } }

  useEffect(() => { void loadChemicals("", "", 1); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">基础数据 / 化学品</p><h1>化学品管理</h1><p>维护化学品基础资料、危险属性和生命周期状态。</p></div><button className="primary-button" onClick={() => setEditing({ chemical_name: "", english_name: "", alias_text: "", cas_no: "", chemical_formula: "", molecular_weight: null, hazard_class: "", source_text: "" })}><span>＋</span>新增化学品</button></div><section className="surface list-card"><div className="list-toolbar"><div className="search-box"><Icon name="search" size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadChemicals(); }} placeholder="搜索中文名、CAS 号…" /></div><select className="filter-button" value={status} onChange={(event) => { setStatus(event.target.value); void loadChemicals(keyword, event.target.value); }}><option value="">状态：全部</option><option value="ACTIVE">启用</option><option value="INACTIVE">已停用</option></select><button className="outline-button" onClick={() => void loadChemicals()}>查询</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>化学品名称</th><th>CAS 号</th><th>分子式</th><th>分子量（g/mol）</th><th>危险类别</th><th>状态</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={7} className="table-empty">正在加载化学品数据…</td></tr> : chemicals.length === 0 ? <tr><td colSpan={7} className="table-empty">暂无化学品数据</td></tr> : chemicals.map((chemical) => <tr key={chemical.id}><td className="material-name">{chemical.chemical_name}</td><td className="mono-text">{chemical.cas_no || "—"}</td><td>{chemical.chemical_formula || "—"}</td><td>{chemical.molecular_weight == null ? "—" : `${chemical.molecular_weight} g/mol`}</td><td>{chemical.hazard_class || "未分类"}</td><td><span className={`status-pill ${chemical.status === "ACTIVE" ? "active" : "inactive"}`}><i />{chemical.status === "ACTIVE" ? "启用" : "停用"}</span></td><td><button className="row-action" onClick={() => setEditing({ ...chemical })}>编辑</button><button className="row-action danger-action" onClick={() => setConfirmingId(chemical.id)}>停用</button></td></tr>)}</tbody></table></div><ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadChemicals(keyword, status, nextPage)} /></section>{editing && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><form className="modal surface" onSubmit={saveChemical}><div className="section-heading"><div><p className="eyebrow">化学品资料</p><h2>{editing.id ? "编辑化学品" : "新增化学品"}</h2></div><button type="button" className="icon-button" onClick={() => setEditing(null)}>×</button></div><div className="form-grid"><label>化学品名称<input value={editing.chemical_name || ""} onChange={(event) => setEditing({ ...editing, chemical_name: event.target.value })} /></label><label>英文名称<input value={editing.english_name || ""} onChange={(event) => setEditing({ ...editing, english_name: event.target.value })} /></label><label>CAS 号<input value={editing.cas_no || ""} onChange={(event) => setEditing({ ...editing, cas_no: event.target.value })} /></label><label>分子式<input value={editing.chemical_formula || ""} onChange={(event) => setEditing({ ...editing, chemical_formula: event.target.value })} /></label><label>分子量（g/mol）<input type="number" min="0" step="0.000001" value={editing.molecular_weight ?? ""} onChange={(event) => setEditing({ ...editing, molecular_weight: event.target.value ? Number(event.target.value) : null })} /></label><label>危险类别<select value={editing.hazard_class || ""} onChange={(event) => setEditing({ ...editing, hazard_class: event.target.value || null })}><option value="">未分类</option>{hazardClassOptions.map((option) => <option key={option} value={option}>{option}</option>)}</select></label><label className="wide-field">别名<input value={editing.alias_text || ""} onChange={(event) => setEditing({ ...editing, alias_text: event.target.value })} /></label><label className="wide-field">来源说明<textarea value={editing.source_text || ""} onChange={(event) => setEditing({ ...editing, source_text: event.target.value })} /></label></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "保存化学品"}</button></div></form></div>}{confirmingId !== null && <ConfirmDialog title="停用化学品" description="停用后该化学品将不再出现在可用列表中。" confirmText="确认停用" onClose={() => setConfirmingId(null)} onConfirm={() => disableChemical(confirmingId)} />}</>;
}

const emptySupplier: Partial<Supplier> = { supplier_code: "", supplier_name: "", country_code: "CN", region: "", address: "", cooperation_level: "", payment_terms: "", default_lead_days: null, note: "" };

function SupplierPage({ token }: { token: string }) {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 8;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Partial<Supplier> | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  async function loadSuppliers(search = keyword, selectedStatus = status, requestedPage = 1) {
    setLoading(true); setError("");
    try { const result = await getSuppliers(token, search, selectedStatus, requestedPage, pageSize); setSuppliers(result.items); setPage(result.page); setTotal(result.total); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "供应商数据加载失败"); }
    finally { setLoading(false); }
  }

  async function saveSupplier(event: FormEvent) {
    event.preventDefault();
    if (!editing?.supplier_code || !editing.supplier_name) { setError("供应商编码和供应商名称不能为空"); return; }
    setSaving(true); setError("");
    try {
      const payload = { supplier_code: editing.supplier_code, supplier_name: editing.supplier_name, country_code: editing.country_code || "CN", region: editing.region || null, address: editing.address || null, cooperation_level: editing.cooperation_level || null, payment_terms: editing.payment_terms || null, default_lead_days: editing.default_lead_days ?? null, note: editing.note || null };
      if (editing.id) await updateSupplier(token, editing.id, payload); else await createSupplier(token, payload);
      setEditing(null); await loadSuppliers(keyword, status, page);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "供应商保存失败"); }
    finally { setSaving(false); }
  }

  async function disableSupplier(id: number) {
    setError("");
    try { await deleteSupplier(token, id); await loadSuppliers(keyword, status, page); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "供应商停用失败"); }
  }

  useEffect(() => { void loadSuppliers("", "", 1); }, [token]);
  return <>
    <div className="page-heading"><div><p className="eyebrow">基础数据 / 供应商</p><h1>供应商管理</h1><p>维护供应商资质、合作条件和供应状态。</p></div><button className="primary-button" onClick={() => setEditing({ ...emptySupplier })}><span>＋</span>新增供应商</button></div>
    <section className="surface list-card"><div className="list-toolbar"><div className="search-box"><Icon name="search" size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadSuppliers(keyword, status, 1); }} placeholder="搜索供应商名称…" /></div><select className="filter-button" value={status} onChange={(event) => { setStatus(event.target.value); void loadSuppliers(keyword, event.target.value, 1); }}><option value="">状态：全部</option><option value="ACTIVE">正常</option><option value="SUSPENDED">暂停合作</option><option value="INACTIVE">已停用</option></select><button className="outline-button" onClick={() => void loadSuppliers(keyword, status, 1)}>查询</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>供应商编码</th><th>供应商名称</th><th>地区</th><th>合作等级</th><th>交付周期</th><th>状态</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={7} className="table-empty">正在加载供应商数据…</td></tr> : suppliers.length === 0 ? <tr><td colSpan={7} className="table-empty">暂无供应商数据</td></tr> : suppliers.map((supplier) => <tr key={supplier.id}><td className="mono-text">{supplier.supplier_code}</td><td className="material-name">{supplier.supplier_name}</td><td>{supplier.region || "—"}</td><td>{supplier.cooperation_level || "—"}</td><td>{supplier.default_lead_days == null ? "—" : `${supplier.default_lead_days} 天`}</td><td><span className={`status-pill ${supplier.status === "ACTIVE" ? "active" : "inactive"}`}><i />{supplier.status === "ACTIVE" ? "正常" : supplier.status === "SUSPENDED" ? "暂停合作" : "已停用"}</span></td><td><button className="row-action" onClick={() => void getSupplier(token, supplier.id).then(setEditing).catch((reason) => setError(reason instanceof Error ? reason.message : "供应商详情加载失败"))}>详情</button><button className="row-action" onClick={() => void getSupplier(token, supplier.id).then(setEditing).catch((reason) => setError(reason instanceof Error ? reason.message : "供应商详情加载失败"))}>编辑</button><button className="row-action danger-action" onClick={() => setConfirmingId(supplier.id)}>停用</button></td></tr>)}</tbody></table></div><ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadSuppliers(keyword, status, nextPage)} /></section>
    {editing && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><form className="modal surface" onSubmit={saveSupplier}><div className="section-heading"><div><p className="eyebrow">供应商资料</p><h2>{editing.id ? "编辑供应商" : "新增供应商"}</h2></div><button type="button" className="icon-button" onClick={() => setEditing(null)}>×</button></div><div className="form-grid"><label>供应商编码<input value={editing.supplier_code || ""} disabled={Boolean(editing.id)} onChange={(event) => setEditing({ ...editing, supplier_code: event.target.value })} /></label><label>供应商名称<input value={editing.supplier_name || ""} onChange={(event) => setEditing({ ...editing, supplier_name: event.target.value })} /></label><label>所在地区<input value={editing.region || ""} onChange={(event) => setEditing({ ...editing, region: event.target.value })} /></label><label>合作等级<input value={editing.cooperation_level || ""} onChange={(event) => setEditing({ ...editing, cooperation_level: event.target.value })} /></label><label>默认交付周期（天）<input type="number" min="0" value={editing.default_lead_days ?? ""} onChange={(event) => setEditing({ ...editing, default_lead_days: event.target.value === "" ? null : Number(event.target.value) })} /></label><label>付款条件<input value={editing.payment_terms || ""} onChange={(event) => setEditing({ ...editing, payment_terms: event.target.value })} /></label><label className="wide-field">地址<input value={editing.address || ""} onChange={(event) => setEditing({ ...editing, address: event.target.value })} /></label><label className="wide-field">备注<textarea value={editing.note || ""} onChange={(event) => setEditing({ ...editing, note: event.target.value })} /></label></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "保存供应商"}</button></div></form></div>}{confirmingId !== null && <ConfirmDialog title="停用供应商" description="停用后该供应商将不再出现在可用列表中。" confirmText="确认停用" onClose={() => setConfirmingId(null)} onConfirm={() => disableSupplier(confirmingId)} />}
  </>;
}

const emptyProduct: Partial<Product> = { product_code: "", product_name: "", chemical_id: undefined, category_id: null, model: "", purity_value: null, purity_unit: "%", packaging_spec: "", unit_id: undefined };

function ProductPage({ token }: { token: string }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 8;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Partial<Product> | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  async function loadProducts(search = keyword, selectedStatus = status, requestedPage = 1) {
    setLoading(true); setError("");
    try { const result = await getProducts(token, search, selectedStatus, requestedPage, pageSize); setProducts(result.items.map((item) => ({ ...item, purity_value: item.purity_value == null ? null : formatDecimal(item.purity_value, 4) }))); setPage(result.page); setTotal(result.total); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "产品数据加载失败"); }
    finally { setLoading(false); }
  }

  function unitLabel(unitId: number) {
    const unit = units.find((item) => item.id === unitId);
    return unit ? `${unit.unit_name}（${unit.unit_code}）` : `单位 ID：${unitId}`;
  }

  async function saveProduct(event: FormEvent) {
    event.preventDefault();
    if (!editing?.product_code || !editing.product_name || !editing.chemical_id || !editing.unit_id) { setError("产品编码、产品名称、化学品 ID 和单位 ID 不能为空"); return; }
    setSaving(true); setError("");
    try {
      const payload = { product_code: editing.product_code, product_name: editing.product_name, chemical_id: editing.chemical_id, category_id: editing.category_id || null, model: editing.model || null, purity_value: editing.purity_value ?? null, purity_unit: editing.purity_unit || "%", packaging_spec: editing.packaging_spec || null, unit_id: editing.unit_id, parameter_json: editing.parameter_json || null };
      if (editing.id) await updateProduct(token, editing.id, payload); else await createProduct(token, payload);
      setEditing(null); await loadProducts(keyword, status, page);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "产品保存失败"); }
    finally { setSaving(false); }
  }

  async function disableProduct(id: number) {
    setError("");
    try { await deleteProduct(token, id); await loadProducts(keyword, status, page); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "产品停用失败"); }
  }

  useEffect(() => { void loadProducts("", "", 1); void getUnits(token).then(setUnits).catch((reason) => setError(reason instanceof Error ? reason.message : "计量单位加载失败")); }, [token]);
  return <>
    <div className="page-heading"><div><p className="eyebrow">基础数据 / 产品</p><h1>产品与包装</h1><p>维护化学品对应的产品规格、纯度和包装信息。</p></div><button className="primary-button" onClick={() => setEditing({ ...emptyProduct })}><span>＋</span>新增产品</button></div>
     <section className="surface list-card"><div className="list-toolbar"><div className="search-box"><Icon name="search" size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadProducts(keyword, status, 1); }} placeholder="搜索产品名称或编码…" /></div><select className="filter-button" value={status} onChange={(event) => { setStatus(event.target.value); void loadProducts(keyword, event.target.value, 1); }}><option value="">状态：全部</option><option value="ACTIVE">启用</option><option value="PENDING_CONFIRMATION">待确认</option><option value="INACTIVE">已停用</option></select><button className="outline-button" onClick={() => void loadProducts(keyword, status, 1)}>查询</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table className="product-table"><thead><tr><th>产品编码</th><th>产品名称</th><th>化学品 ID</th><th>规格型号</th><th>纯度</th><th>包装</th><th>交易单位</th><th>状态</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={9} className="table-empty">正在加载产品数据…</td></tr> : products.length === 0 ? <tr><td colSpan={9} className="table-empty">暂无产品数据</td></tr> : products.map((product) => <tr key={product.id}><td className="mono-text">{product.product_code}</td><td className="material-name">{product.product_name}</td><td>{product.chemical_id}</td><td>{product.model || "—"}</td><td>{product.purity_value == null ? "—" : `${product.purity_value}${product.purity_unit || "%"}`}</td><td>{product.packaging_spec || "—"}</td><td>{unitLabel(product.unit_id)}</td><td><span className={`status-pill ${product.status === "ACTIVE" ? "active" : "inactive"}`}><i />{product.status === "ACTIVE" ? "启用" : product.status === "PENDING_CONFIRMATION" ? "待确认" : "已停用"}</span></td><td className="product-actions-cell"><button className="row-action" onClick={() => void getProduct(token, product.id).then(setEditing).catch((reason) => setError(reason instanceof Error ? reason.message : "产品详情加载失败"))}>详情</button><button className="row-action" onClick={() => void getProduct(token, product.id).then(setEditing).catch((reason) => setError(reason instanceof Error ? reason.message : "产品详情加载失败"))}>编辑</button><button className="row-action danger-action" onClick={() => void disableProduct(product.id)}>停用</button></td></tr>)}</tbody></table></div><ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadProducts(keyword, status, nextPage)} /></section>
     {editing && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><form className="modal surface" onSubmit={saveProduct}><div className="section-heading"><div><p className="eyebrow">产品资料</p><h2>{editing.id ? "编辑产品" : "新增产品"}</h2></div><button type="button" className="icon-button" onClick={() => setEditing(null)}>×</button></div><div className="form-grid"><label>产品编码<input value={editing.product_code || ""} disabled={Boolean(editing.id)} onChange={(event) => setEditing({ ...editing, product_code: event.target.value })} /></label><label>产品名称<input value={editing.product_name || ""} onChange={(event) => setEditing({ ...editing, product_name: event.target.value })} /></label><label>化学品 ID<input type="number" min="1" value={editing.chemical_id ?? ""} onChange={(event) => setEditing({ ...editing, chemical_id: event.target.value === "" ? undefined : Number(event.target.value) })} /></label><label>交易单位<select value={editing.unit_id ?? ""} onChange={(event) => setEditing({ ...editing, unit_id: event.target.value === "" ? undefined : Number(event.target.value) })}><option value="">请选择单位</option>{units.filter((unit) => unit.status === "ACTIVE" || unit.id === editing.unit_id).map((unit) => <option key={unit.id} value={unit.id}>{unit.unit_name}（{unit.unit_code}）</option>)}</select></label><label>分类 ID<input type="number" min="1" value={editing.category_id ?? ""} onChange={(event) => setEditing({ ...editing, category_id: event.target.value === "" ? null : Number(event.target.value) })} /></label><label>规格型号<input value={editing.model || ""} onChange={(event) => setEditing({ ...editing, model: event.target.value })} /></label><label>纯度数值<input type="number" min="0" max="100" step="0.01" value={editing.purity_value ?? ""} onChange={(event) => setEditing({ ...editing, purity_value: event.target.value === "" ? null : Number(event.target.value) })} /></label><label>包装规格<input value={editing.packaging_spec || ""} onChange={(event) => setEditing({ ...editing, packaging_spec: event.target.value })} /></label></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "保存产品"}</button></div></form></div>}{confirmingId !== null && <ConfirmDialog title="停用产品" description="停用后该产品将不再出现在可用列表中。" confirmText="确认停用" onClose={() => setConfirmingId(null)} onConfirm={() => disableProduct(confirmingId)} />}
  </>;
}

function purchaseStatusLabel(status: string) {
  const labels: Record<string, string> = { DRAFT: "草稿", SUBMITTED: "审批中", PENDING_APPROVAL: "审批中", APPROVING: "审批中", APPROVED: "已通过", REJECTED: "已驳回", ORDERED: "已下单", PARTIAL: "部分到货", CANCELLED: "已取消", COMPLETED: "已完成" };
  return labels[status] || statusLabel(status);
}

function PurchasePage({ token }: { token: string }) {
  const [tab, setTab] = useState<"requests" | "orders">("requests");
  const [requests, setRequests] = useState<PurchaseRequest[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 8;
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [requestDraft, setRequestDraft] = useState<{ purpose: string; priority: string; department_id: number | null; budget_amount: number | null; currency_code: string; expected_date: string; items: PurchaseRequestItem[] }>({ purpose: "", priority: "NORMAL", department_id: null, budget_amount: null, currency_code: "CNY", expected_date: "", items: [{ requested_name: "", quantity: 1, unit_id: 1, product_id: null, technical_requirements: "", budget_price: null, expected_date: "" }] });
  const [showRequestForm, setShowRequestForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [actionPrompt, setActionPrompt] = useState<{ kind: "request" | "order"; item: PurchaseRequest | PurchaseOrder; action: string; title: string; label: string; required: boolean } | null>(null);

  async function loadPurchases(search = keyword, selectedStatus = status, requestedPage = 1) {
    setLoading(true); setError("");
    try {
      const [requestResult, orderResult] = await Promise.all([getPurchaseRequests(token, search, selectedStatus, requestedPage, pageSize), getPurchaseOrders(token, search, selectedStatus, requestedPage, pageSize)]);
      setRequests(requestResult.items.map((item) => ({ ...item, budget_amount: item.budget_amount == null ? null : formatAmount(item.budget_amount), expected_date: item.expected_date ? formatDateTime(item.expected_date) : null }))); setOrders(orderResult.items.map((item) => ({ ...item, order_amount: formatAmount(item.order_amount), order_date: item.order_date ? formatDateTime(item.order_date) : null, expected_arrival_date: item.expected_arrival_date ? formatDateTime(item.expected_arrival_date) : null }))); setPage(requestedPage); setTotal(Math.max(requestResult.total, orderResult.total));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "采购数据加载失败"); }
    finally { setLoading(false); }
  }

  function unitLabel(unitId: number) {
    const unit = units.find((item) => item.id === unitId);
    return unit ? unit.unit_name : `单位 ID：${unitId}`;
  }

  function itemUnitSummary(items: PurchaseRequestItem[]) {
    const summaries = items.map((item) => `${formatQuantity(item.quantity)} ${unitLabel(item.unit_id)}`);
    return summaries.length > 3 ? `${summaries.slice(0, 3).join("、")} 等` : summaries.join("、") || "—";
  }

  useEffect(() => { void loadPurchases("", "", 1); void getUnits(token).then(setUnits).catch((reason) => setError(reason instanceof Error ? reason.message : "计量单位加载失败")); }, [token]);
  const requestStatuses = ["", "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"];
  const orderStatuses = ["", "DRAFT", "PENDING_APPROVAL", "APPROVED", "ORDERED", "CANCELLED"];
  async function saveRequest(event: FormEvent) {
    event.preventDefault();
    if (!requestDraft.purpose.trim() || requestDraft.items.some((item) => !item.requested_name.trim() || Number(item.quantity) <= 0 || Number(item.unit_id) <= 0)) { setError("采购用途、物料名称、数量和单位 ID 不能为空且必须有效"); return; }
    setSaving(true); setError("");
    try { await createPurchaseRequest(token, { ...requestDraft, purpose: requestDraft.purpose.trim(), expected_date: requestDraft.expected_date || null, budget_amount: requestDraft.budget_amount ?? null, department_id: requestDraft.department_id ?? null, items: requestDraft.items.map((item) => ({ ...item, expected_date: item.expected_date || null, technical_requirements: item.technical_requirements || null, product_id: item.product_id || null, budget_price: item.budget_price ?? null })) }); setShowRequestForm(false); setRequestDraft({ purpose: "", priority: "NORMAL", department_id: null, budget_amount: null, currency_code: "CNY", expected_date: "", items: [{ requested_name: "", quantity: 1, unit_id: 1, product_id: null, technical_requirements: "", budget_price: null, expected_date: "" }] }); await loadPurchases(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "采购申请创建失败"); }
    finally { setSaving(false); }
  }
  async function requestAction(item: PurchaseRequest, action: "submit" | "approve" | "reject" | "cancel", opinion?: string) {
    if (action !== "submit" && opinion === undefined) {
      setActionPrompt({ kind: "request", item, action, title: action === "approve" ? "审批采购申请" : action === "reject" ? "驳回采购申请" : "取消采购申请", label: action === "cancel" ? "取消原因" : action === "reject" ? "驳回意见" : "审批意见", required: action !== "approve" });
      return;
    }
    let result: Promise<PurchaseRequest>;
    if (action === "submit") result = submitPurchaseRequest(token, item.id);
    else if (action === "approve") result = approvePurchaseRequest(token, item.id, opinion || "");
    else if (action === "reject") result = rejectPurchaseRequest(token, item.id, opinion!.trim());
    else result = cancelPurchaseRequest(token, item.id, opinion!.trim());
    setError(""); try { await result; await loadPurchases(); } catch (reason) { setError(reason instanceof Error ? reason.message : "采购申请操作失败"); }
  }
  async function orderAction(item: PurchaseOrder, action: "submit" | "approve" | "reject" | "place" | "cancel", opinion?: string) {
    if (["approve", "reject", "cancel"].includes(action) && opinion === undefined) {
      setActionPrompt({ kind: "order", item, action, title: action === "approve" ? "审批采购订单" : action === "reject" ? "驳回采购订单" : "取消采购订单", label: action === "cancel" ? "取消原因" : action === "reject" ? "驳回意见" : "审批意见", required: action === "cancel" });
      return;
    }
    let result: Promise<PurchaseOrder>;
    if (action === "submit") result = submitPurchaseOrder(token, item.id);
    else if (action === "approve") result = approvePurchaseOrder(token, item.id, opinion || "");
    else if (action === "reject") result = rejectPurchaseOrder(token, item.id, opinion || "");
    else if (action === "place") result = placePurchaseOrder(token, item.id);
    else result = cancelPurchaseOrder(token, item.id, opinion!.trim());
    setError(""); try { await result; await loadPurchases(); } catch (reason) { setError(reason instanceof Error ? reason.message : "采购订单操作失败"); }
  }
  return <>
    <div className="page-heading"><div><p className="eyebrow">业务运营 / 采购</p><h1>采购管理</h1><p>查看采购申请和采购订单的审批、执行状态。</p></div><button className="primary-button" onClick={() => setShowRequestForm(true)}>＋ 新建采购申请</button></div>
     <section className="surface list-card"><div className="tab-bar"><button className={tab === "requests" ? "tab-button selected" : "tab-button"} onClick={() => { setTab("requests"); setStatus(""); }}>采购申请</button><button className={tab === "orders" ? "tab-button selected" : "tab-button"} onClick={() => { setTab("orders"); setStatus(""); }}>采购订单</button></div><div className="list-toolbar"><div className="search-box"><Icon name="search" size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadPurchases(keyword, status, 1); }} placeholder={tab === "requests" ? "搜索申请编号或用途…" : "搜索订单编号…"} /></div><select className="filter-button" value={status} onChange={(event) => { setStatus(event.target.value); void loadPurchases(keyword, event.target.value, 1); }}>{(tab === "requests" ? requestStatuses : orderStatuses).map((item) => <option key={item} value={item}>{item ? purchaseStatusLabel(item) : "状态：全部"}</option>)}</select><button className="outline-button" onClick={() => void loadPurchases(keyword, status, 1)}>查询</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}{tab === "requests" ? <div className="table-scroll"><table><thead><tr><th>申请编号</th><th>申请用途</th><th>优先级</th><th>预算金额</th><th>期望日期</th><th>状态</th><th>申请明细（数量/单位）</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={8} className="table-empty">正在加载采购申请…</td></tr> : requests.length === 0 ? <tr><td colSpan={8} className="table-empty">暂无采购申请</td></tr> : requests.map((item) => <tr key={item.id}><td className="mono-text">{item.request_no}</td><td className="material-name">{item.purpose}</td><td>{statusLabel(item.priority)}</td><td>{formatAmountWithCurrency(item.budget_amount, item.currency_code)}</td><td>{item.expected_date || "—"}</td><td><span className="status-pill active"><i />{purchaseStatusLabel(item.status)}</span></td><td>{itemUnitSummary(item.items)}</td><td>{["DRAFT", "REJECTED"].includes(item.status) && <button className="row-action" onClick={() => void requestAction(item, "submit")}>提交</button>}{["SUBMITTED", "PENDING_APPROVAL"].includes(item.status) && <><button className="row-action" onClick={() => void requestAction(item, "approve")}>通过</button><button className="row-action danger-action" onClick={() => void requestAction(item, "reject")}>驳回</button></>}{["DRAFT", "REJECTED"].includes(item.status) && <button className="row-action danger-action" onClick={() => void requestAction(item, "cancel")}>取消</button>}</td></tr>)}</tbody></table></div> : <div className="table-scroll"><table><thead><tr><th>订单编号</th><th>供应商 ID</th><th>订单金额</th><th>下单日期</th><th>预计到货</th><th>状态</th><th>明细数</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={8} className="table-empty">正在加载采购订单…</td></tr> : orders.length === 0 ? <tr><td colSpan={8} className="table-empty">暂无采购订单</td></tr> : orders.map((item) => <tr key={item.id}><td className="mono-text">{item.po_no}</td><td>{item.supplier_id}</td><td className="material-name">{formatAmountWithCurrency(item.order_amount, item.currency_code)}</td><td>{item.order_date || "—"}</td><td>{item.expected_arrival_date || "—"}</td><td><span className="status-pill active"><i />{purchaseStatusLabel(item.status)}</span></td><td>{item.items.length}</td><td>{item.status === "DRAFT" && <button className="row-action" onClick={() => void orderAction(item, "submit")}>提交</button>}{["PENDING_APPROVAL", "SUBMITTED"].includes(item.status) && <><button className="row-action" onClick={() => void orderAction(item, "approve")}>通过</button><button className="row-action danger-action" onClick={() => void orderAction(item, "reject")}>驳回</button></>}{item.status === "APPROVED" && <button className="row-action" onClick={() => void orderAction(item, "place")}>正式下单</button>}{["DRAFT", "PENDING_APPROVAL", "APPROVED"].includes(item.status) && <button className="row-action danger-action" onClick={() => void orderAction(item, "cancel")}>取消</button>}</td></tr>)}</tbody></table></div>}<ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadPurchases(keyword, status, nextPage)} /></section>
     {showRequestForm && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowRequestForm(false); }}><form className="modal surface" onSubmit={saveRequest}><div className="section-heading"><div><p className="eyebrow">采购申请</p><h2>新建采购申请</h2></div><button type="button" className="icon-button" onClick={() => setShowRequestForm(false)}>×</button></div><div className="form-grid"><label className="wide-field">采购用途<input value={requestDraft.purpose} onChange={(event) => setRequestDraft({ ...requestDraft, purpose: event.target.value })} placeholder="请输入采购用途" /></label><label>优先级<select value={requestDraft.priority} onChange={(event) => setRequestDraft({ ...requestDraft, priority: event.target.value })}><option value="LOW">低</option><option value="NORMAL">普通</option><option value="HIGH">高</option><option value="URGENT">紧急</option></select></label><label>部门 ID<input type="number" min="1" value={requestDraft.department_id ?? ""} onChange={(event) => setRequestDraft({ ...requestDraft, department_id: event.target.value ? Number(event.target.value) : null })} /></label><label>预算金额（CNY）<input type="number" min="0" step="0.01" value={requestDraft.budget_amount ?? ""} onChange={(event) => setRequestDraft({ ...requestDraft, budget_amount: event.target.value ? Number(event.target.value) : null })} /></label><label>期望日期<input type="date" value={requestDraft.expected_date} onChange={(event) => setRequestDraft({ ...requestDraft, expected_date: event.target.value })} /></label></div><div className="item-editor"><div className="section-heading"><h2>申请明细</h2><button type="button" className="outline-button" onClick={() => setRequestDraft({ ...requestDraft, items: [...requestDraft.items, { requested_name: "", quantity: 1, unit_id: units[0]?.id || 1, product_id: null, technical_requirements: "", budget_price: null, expected_date: "" }] })}>＋ 添加明细</button></div>{requestDraft.items.map((item, index) => <div className="item-row" key={index}><input value={item.requested_name} onChange={(event) => setRequestDraft({ ...requestDraft, items: requestDraft.items.map((line, lineIndex) => lineIndex === index ? { ...line, requested_name: event.target.value } : line) })} placeholder="物料名称" /><input type="number" min="0.01" step="0.01" value={item.quantity} onChange={(event) => setRequestDraft({ ...requestDraft, items: requestDraft.items.map((line, lineIndex) => lineIndex === index ? { ...line, quantity: Number(event.target.value) } : line) })} placeholder="数量" /><select value={item.unit_id} onChange={(event) => setRequestDraft({ ...requestDraft, items: requestDraft.items.map((line, lineIndex) => lineIndex === index ? { ...line, unit_id: Number(event.target.value) } : line) })}><option value="">选择单位</option>{units.filter((unit) => unit.status === "ACTIVE").map((unit) => <option key={unit.id} value={unit.id}>{unit.unit_name}（{unit.unit_code}）</option>)}</select>{requestDraft.items.length > 1 && <button type="button" className="row-action danger-action" onClick={() => setRequestDraft({ ...requestDraft, items: requestDraft.items.filter((_line, lineIndex) => lineIndex !== index) })}>删除</button>}</div>)}</div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setShowRequestForm(false)}>取消</button><button className="primary-button" disabled={saving}>{saving ? "创建中…" : "创建采购申请"}</button></div></form></div>}
     {actionPrompt && <TextPromptDialog title={actionPrompt.title} label={actionPrompt.label} required={actionPrompt.required} placeholder={actionPrompt.required ? `请输入${actionPrompt.label}` : "可不填写"} confirmText="确认" onClose={() => setActionPrompt(null)} onSubmit={(value) => actionPrompt.kind === "request" ? requestAction(actionPrompt.item as PurchaseRequest, actionPrompt.action as "approve" | "reject" | "cancel", value) : orderAction(actionPrompt.item as PurchaseOrder, actionPrompt.action as "approve" | "reject" | "cancel", value)} />}
  </>;
}

function InventoryPageReadOnly({ token }: { token: string }) {
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [productId, setProductId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  async function loadBalances() { setLoading(true); setError(""); try { const result = await getInventoryBalances(token, productId, warehouseId); setBalances(result.items.map((item) => ({ ...item, quantity: formatQuantity(item.quantity), locked_quantity: formatQuantity(item.locked_quantity) }))); } catch (reason) { setError(reason instanceof Error ? reason.message : "库存数据加载失败"); } finally { setLoading(false); } }
  useEffect(() => { void loadBalances(); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">业务运营 / 仓储</p><h1>仓储管理</h1><p>查看库存余额、仓库位置和锁定数量。</p></div><button className="primary-button" onClick={() => setError("入库、领用和调拨操作将在库存流程接入时开放")}>＋ 库存操作</button></div><section className="surface list-card"><div className="list-toolbar"><input className="compact-input" type="number" min="1" value={productId} onChange={(event) => setProductId(event.target.value)} placeholder="产品 ID" /><input className="compact-input" type="number" min="1" value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} placeholder="仓库 ID" /><button className="outline-button" onClick={() => void loadBalances()}>查询库存</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>库存 ID</th><th>仓库 ID</th><th>库位 ID</th><th>产品 ID</th><th>批次 ID</th><th>库存数量</th><th>锁定数量</th><th>状态</th></tr></thead><tbody>{loading ? <tr><td colSpan={8} className="table-empty">正在加载库存数据…</td></tr> : balances.length === 0 ? <tr><td colSpan={8} className="table-empty">暂无库存余额</td></tr> : balances.map((item) => <tr key={item.id}><td className="mono-text">{item.id}</td><td>{item.warehouse_id}</td><td>{item.location_id}</td><td>{item.product_id}</td><td>{item.batch_id}</td><td className="material-name">{item.quantity}</td><td>{item.locked_quantity}</td><td><span className="status-pill active"><i />{item.status}</span></td></tr>)}</tbody></table></div></section></>;
}

function qualityResultLabel(result: string) { return ({ PASSED: "合格", PARTIAL: "部分合格", FAILED: "不合格", REINSPECTION: "复检" } as Record<string, string>)[result] || result; }

function QualityPageReadOnly({ token }: { token: string }) {
  const [items, setItems] = useState<QualityAcceptance[]>([]); const [result, setResult] = useState(""); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  async function loadQuality(selectedResult = result) { setLoading(true); setError(""); try { const page = await getQualityAcceptances(token, selectedResult); setItems(page.items); } catch (reason) { setError(reason instanceof Error ? reason.message : "质量验收数据加载失败"); } finally { setLoading(false); } }
  useEffect(() => { void loadQuality(""); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">业务运营 / 质量</p><h1>质量管理</h1><p>查看到货质量验收记录、检测结果和证书状态。</p></div><button className="primary-button" onClick={() => setError("质量验收结果提交将在详情流程接入时开放")}>＋ 新建验收</button></div><section className="surface list-card"><div className="list-toolbar"><select className="filter-button" value={result} onChange={(event) => { setResult(event.target.value); void loadQuality(event.target.value); }}><option value="">结果：全部</option><option value="PASSED">合格</option><option value="PARTIAL">部分合格</option><option value="FAILED">不合格</option><option value="REINSPECTION">复检</option></select><button className="outline-button" onClick={() => void loadQuality()}>刷新</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>验收编号</th><th>到货单 ID</th><th>检验员 ID</th><th>验收结果</th><th>检验时间</th><th>证书</th><th>结论</th></tr></thead><tbody>{loading ? <tr><td colSpan={7} className="table-empty">正在加载质量验收…</td></tr> : items.length === 0 ? <tr><td colSpan={7} className="table-empty">暂无质量验收记录</td></tr> : items.map((item) => <tr key={item.id}><td className="mono-text">{item.acceptance_no}</td><td>{item.delivery_id}</td><td>{item.inspector_id}</td><td><span className={`status-pill ${item.result === "PASSED" ? "active" : "inactive"}`}><i />{qualityResultLabel(item.result)}</span></td><td>{item.inspection_time || "—"}</td><td>{item.certificate_complete ? "完整" : "待补充"}</td><td>{item.conclusion || "—"}</td></tr>)}</tbody></table></div></section></>;
}

function InventoryPage({ token }: { token: string }) {
  const [balances, setBalances] = useState<InventoryBalance[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [productId, setProductId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 8;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [freezePrompt, setFreezePrompt] = useState<InventoryBalance | null>(null);
  function unitLabel(unitId: number) {
    const unit = units.find((item) => item.id === unitId);
    return unit ? unit.unit_name : `单位 ID：${unitId}`;
  }
  async function loadBalances(requestedPage = 1) { setLoading(true); setError(""); try { const result = await getInventoryBalances(token, productId, warehouseId, requestedPage, pageSize); setBalances(result.items.map((item) => ({ ...item, quantity: formatQuantity(item.quantity), locked_quantity: formatQuantity(item.locked_quantity) }))); setPage(result.page); setTotal(result.total); } catch (reason) { setError(reason instanceof Error ? reason.message : "库存数据加载失败"); } finally { setLoading(false); } }
  async function changeFreeze(item: InventoryBalance, reason?: string) { if (reason === undefined) { setFreezePrompt(item); return; } if (!reason.trim()) return; setError(""); try { if (item.status === "FROZEN") await unfreezeInventoryBalance(token, item.id, reason.trim()); else await freezeInventoryBalance(token, item.id, reason.trim()); await loadBalances(page); } catch (failure) { setError(failure instanceof Error ? failure.message : "库存状态更新失败"); } }
  useEffect(() => { void loadBalances(); void getUnits(token).then(setUnits).catch((reason) => setError(reason instanceof Error ? reason.message : "计量单位加载失败")); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">业务运营 / 仓储</p><h1>仓储管理</h1><p>查看库存余额、仓库位置和锁定数量。</p></div><button className="primary-button" onClick={() => setError("入库、领用、调拨和盘点申请将在后续流程接入")}>＋ 库存操作</button></div><section className="surface list-card"><div className="list-toolbar"><input className="compact-input" type="number" min="1" value={productId} onChange={(event) => setProductId(event.target.value)} placeholder="产品 ID" /><input className="compact-input" type="number" min="1" value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} placeholder="仓库 ID" /><button className="outline-button" onClick={() => void loadBalances(1)}>查询库存</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>库存 ID</th><th>仓库 ID</th><th>库位 ID</th><th>产品 ID</th><th>批次 ID</th><th>库存数量</th><th>锁定数量</th><th>计量单位</th><th>状态</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={10} className="table-empty">正在加载库存数据…</td></tr> : balances.length === 0 ? <tr><td colSpan={10} className="table-empty">暂无库存余额</td></tr> : balances.map((item) => <tr key={item.id}><td className="mono-text">{item.id}</td><td>{item.warehouse_id}</td><td>{item.location_id}</td><td>{item.product_id}</td><td>{item.batch_id}</td><td className="material-name">{formatQuantityWithUnit(item.quantity, item.unit_id, units)}</td><td>{formatQuantityWithUnit(item.locked_quantity, item.unit_id, units)}</td><td>{unitLabel(item.unit_id)}</td><td><span className={`status-pill ${item.status === "FROZEN" ? "inactive" : "active"}`}><i />{item.status === "FROZEN" ? "已冻结" : statusLabel(item.status)}</span></td><td><button className="row-action" onClick={() => void changeFreeze(item)}>{item.status === "FROZEN" ? "解冻" : "冻结"}</button></td></tr>)}</tbody></table></div><ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadBalances(nextPage)} /></section>;
     {freezePrompt && <TextPromptDialog title={freezePrompt.status === "FROZEN" ? "解冻库存" : "冻结库存"} label={freezePrompt.status === "FROZEN" ? "解冻原因" : "冻结原因"} placeholder="请输入处理原因" required confirmText="确认" onClose={() => setFreezePrompt(null)} onSubmit={(reason) => changeFreeze(freezePrompt, reason)} />}
  </>;
}

function QualityPage({ token }: { token: string }) {
  const [items, setItems] = useState<QualityAcceptance[]>([]);
  const [result, setResult] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 8;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deliveryId, setDeliveryId] = useState("");
  const [availableDeliveries, setAvailableDeliveries] = useState<Delivery[]>([]);
  const [deliveryLoading, setDeliveryLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<QualityAcceptance | null>(null);
  const [resultForm, setResultForm] = useState({ result: "PASSED", certificate_complete: false, conclusion: "" }); const [detail, setDetail] = useState<QualityAcceptance | null>(null);
  const [saving, setSaving] = useState(false);
  async function loadQuality(selectedResult = result, requestedPage = 1) { setLoading(true); setError(""); try { const resultPage = await getQualityAcceptances(token, selectedResult, requestedPage, pageSize); setItems(resultPage.items.map((item) => ({ ...item, inspection_time: item.inspection_time ? formatDateTime(item.inspection_time) : null }))); setPage(resultPage.page); setTotal(resultPage.total); } catch (reason) { setError(reason instanceof Error ? reason.message : "质量验收数据加载失败"); } finally { setLoading(false); } }
  async function createAcceptance(event: FormEvent) { event.preventDefault(); if (!deliveryId || Number(deliveryId) <= 0) { setError("到货单 ID 必须是正整数"); return; } setSaving(true); setError(""); try { await createQualityAcceptance(token, Number(deliveryId)); setShowCreate(false); setDeliveryId(""); await loadQuality(result, page); } catch (reason) { setError(reason instanceof Error ? reason.message : "质量验收创建失败"); } finally { setSaving(false); } }
  async function saveResult(event: FormEvent) { event.preventDefault(); if (!editing) return; setSaving(true); setError(""); try { await submitQualityResult(token, editing.id, { ...resultForm, conclusion: resultForm.conclusion || null }); setEditing(null); await loadQuality(result, page); } catch (reason) { setError(reason instanceof Error ? reason.message : "质量结果提交失败"); } finally { setSaving(false); } }
  useEffect(() => { void loadQuality("", 1); setDeliveryLoading(true); void getDeliveries(token, "", "RECEIVED", 1, 100).then((resultPage) => setAvailableDeliveries(resultPage.items)).catch((reason) => setError(reason instanceof Error ? reason.message : "已收货到货单加载失败")).finally(() => setDeliveryLoading(false)); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">业务运营 / 质量</p><h1>质量管理</h1><p>查看到货质量验收记录、检测结果和证书状态。</p></div><button className="primary-button" onClick={() => setShowCreate(true)} disabled={!availableDeliveries.length}>＋ 新建验收</button></div><section className="surface list-card"><div className="list-toolbar"><select className="filter-button" value={result} onChange={(event) => { setResult(event.target.value); void loadQuality(event.target.value, 1); }}><option value="">结果：全部</option><option value="PASSED">合格</option><option value="PARTIAL">部分合格</option><option value="FAILED">不合格</option><option value="REINSPECTION">复检</option></select><button className="outline-button" onClick={() => void loadQuality(result, 1)}>刷新</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>验收编号</th><th>到货单 ID</th><th>检验员 ID</th><th>验收结果</th><th>检验时间</th><th>证书</th><th>结论</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={8} className="table-empty">正在加载质量验收…</td></tr> : items.length === 0 ? <tr><td colSpan={8} className="table-empty">暂无质量验收记录</td></tr> : items.map((item) => <tr key={item.id}><td className="mono-text">{item.acceptance_no}</td><td>{item.delivery_id}</td><td>{item.inspector_id}</td><td><span className={`status-pill ${item.result === "PASSED" ? "active" : "inactive"}`}><i />{qualityResultLabel(item.result)}</span></td><td>{item.inspection_time || "—"}</td><td>{item.certificate_complete ? "完整" : "待补充"}</td><td>{item.conclusion || "—"}</td><td><button className="row-action" onClick={() => void getQualityAcceptance(token, item.id).then(setDetail).catch((reason) => setError(reason instanceof Error ? reason.message : "质量详情加载失败"))}>详情</button><button className="row-action" onClick={() => { setEditing(item); setResultForm({ result: item.result || "PASSED", certificate_complete: Boolean(item.certificate_complete), conclusion: item.conclusion || "" }); }}>提交结果</button></td></tr>)}</tbody></table></div><ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadQuality(result, nextPage)} /></section>{showCreate && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false); }}><form className="modal surface" onSubmit={createAcceptance}><div className="section-heading"><div><p className="eyebrow">质量验收</p><h2>新建质量验收</h2></div><button type="button" className="icon-button" onClick={() => setShowCreate(false)}>×</button></div><div className="form-grid"><label className="wide-field">已收货到货单<select value={deliveryId} onChange={(event) => setDeliveryId(event.target.value)} disabled={deliveryLoading || saving}><option value="">{deliveryLoading ? "正在加载已收货到货单…" : availableDeliveries.length ? "请选择到货单" : "暂无可验收的已收货到货单"}</option>{availableDeliveries.map((delivery) => <option key={delivery.id} value={delivery.id}>{delivery.delivery_no} · PO-{delivery.po_id} · 供应商 {delivery.supplier_id}</option>)}</select></label></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button" disabled={saving || !deliveryId}>{saving ? "创建中…" : "创建验收"}</button></div></form></div>}{editing && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><form className="modal surface" onSubmit={saveResult}><div className="section-heading"><div><p className="eyebrow">质量结果</p><h2>提交验收结果</h2></div><button type="button" className="icon-button" onClick={() => setEditing(null)}>×</button></div><div className="form-grid"><label>验收结果<select value={resultForm.result} onChange={(event) => setResultForm({ ...resultForm, result: event.target.value })}><option value="PASSED">合格</option><option value="PARTIAL">部分合格</option><option value="FAILED">不合格</option><option value="REINSPECTION">复检</option></select></label><label className="checkbox-field"><input type="checkbox" checked={resultForm.certificate_complete} onChange={(event) => setResultForm({ ...resultForm, certificate_complete: event.target.checked })} />证书资料完整</label><label className="wide-field">验收结论<textarea value={resultForm.conclusion} onChange={(event) => setResultForm({ ...resultForm, conclusion: event.target.value })} /></label></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button" disabled={saving}>{saving ? "提交中…" : "提交结果"}</button></div></form></div>}{detail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetail(null); }}><div className="modal surface"><div className="section-heading"><div><p className="eyebrow">质量详情</p><h2>验收详情</h2></div><button className="icon-button" onClick={() => setDetail(null)}>×</button></div><pre className="detail-json">{JSON.stringify(detail, null, 2)}</pre></div></div>}</>;
}

function UsersPageReadOnly({ token }: { token: string }) {
  const [users, setUsers] = useState<SystemUser[]>([]); const [keyword, setKeyword] = useState(""); const [status, setStatus] = useState(""); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  async function loadUsers(search = keyword, selectedStatus = status) { setLoading(true); setError(""); try { const page = await getUsers(token, search, selectedStatus); setUsers(page.items); } catch (reason) { setError(reason instanceof Error ? reason.message : "用户数据加载失败"); } finally { setLoading(false); } }
  useEffect(() => { void loadUsers("", ""); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">系统设置 / 用户权限</p><h1>用户与权限</h1><p>维护系统账号、状态和基础联系信息。</p></div><button className="primary-button" onClick={() => setError("用户创建和角色分配将在权限维护流程接入时开放")}>＋ 新增用户</button></div><section className="surface list-card"><div className="list-toolbar"><div className="search-box"><Icon name="search" size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadUsers(); }} placeholder="搜索用户名或姓名…" /></div><select className="filter-button" value={status} onChange={(event) => { setStatus(event.target.value); void loadUsers(keyword, event.target.value); }}><option value="">状态：全部</option><option value="ACTIVE">正常</option><option value="LOCKED">已锁定</option><option value="INACTIVE">已停用</option></select><button className="outline-button" onClick={() => void loadUsers()}>查询</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>用户名</th><th>显示姓名</th><th>部门 ID</th><th>邮箱</th><th>手机号</th><th>状态</th></tr></thead><tbody>{loading ? <tr><td colSpan={6} className="table-empty">正在加载用户数据…</td></tr> : users.length === 0 ? <tr><td colSpan={6} className="table-empty">暂无用户</td></tr> : users.map((item) => <tr key={item.id}><td className="mono-text">{item.username}</td><td className="material-name">{item.display_name}</td><td>{item.department_id || "—"}</td><td>{item.email || "—"}</td><td>{item.phone || "—"}</td><td><span className={`status-pill ${item.status === "ACTIVE" ? "active" : "inactive"}`}><i />{item.status === "ACTIVE" ? "正常" : item.status === "LOCKED" ? "已锁定" : "已停用"}</span></td></tr>)}</tbody></table></div></section></>;
}

type UserDraft = Partial<SystemUser> & { username: string; display_name: string; password: string; role_ids: number[] };

function UsersPage({ token }: { token: string }) {
  const [users, setUsers] = useState<SystemUser[]>([]);
  const [page, setPage] = useState(1); const [total, setTotal] = useState(0); const pageSize = 8;
  const [keyword, setKeyword] = useState(""); const [status, setStatus] = useState(""); const [loading, setLoading] = useState(true); const [error, setError] = useState(""); const [editing, setEditing] = useState<UserDraft | null>(null); const [detail, setDetail] = useState<SystemUser | null>(null); const [saving, setSaving] = useState(false); const [confirmingId, setConfirmingId] = useState<number | null>(null);
  async function loadUsers(search = keyword, selectedStatus = status, requestedPage = 1) { setLoading(true); setError(""); try { const result = await getUsers(token, search, selectedStatus, requestedPage, pageSize); setUsers(result.items); setPage(result.page); setTotal(result.total); } catch (reason) { setError(reason instanceof Error ? reason.message : "用户数据加载失败"); } finally { setLoading(false); } }
  async function saveUser(event: FormEvent) { event.preventDefault(); if (!editing!.display_name.trim() || (!editing!.id && (!editing!.username.trim() || editing!.password.length < 8))) { setError("新增用户必须填写用户名、姓名和至少 8 位密码"); return; } setSaving(true); setError(""); try { if (editing!.id) { await updateUser(token, editing!.id, { ...(editing!.password ? { password: editing!.password } : {}), display_name: editing!.display_name.trim(), department_id: editing!.department_id ?? null, email: editing!.email || null, phone: editing!.phone || null, status: editing!.status, ...(editing!.role_ids.length ? { role_ids: editing!.role_ids } : {}) }); } else { await createUser(token, { username: editing!.username.trim(), password: editing!.password, display_name: editing!.display_name.trim(), department_id: editing!.department_id ?? null, email: editing!.email || null, phone: editing!.phone || null, role_ids: editing!.role_ids }); } setEditing(null); await loadUsers(keyword, status, page); } catch (reason) { setError(reason instanceof Error ? reason.message : "用户保存失败"); } finally { setSaving(false); } }
  async function disableUser(id: number) { setError(""); try { await deleteUser(token, id); await loadUsers(keyword, status, page); } catch (reason) { setError(reason instanceof Error ? reason.message : "用户停用失败"); } }
  useEffect(() => { void loadUsers("", "", 1); }, [token]);
  return <><div className="page-heading"><div><p className="eyebrow">系统设置 / 用户权限</p><h1>用户与权限</h1><p>维护系统账号、状态和基础联系信息。</p></div><button className="primary-button" onClick={() => setEditing({ username: "", display_name: "", password: "", department_id: null, email: "", phone: "", status: "ACTIVE", role_ids: [] })}>＋ 新增用户</button></div><section className="surface list-card"><div className="list-toolbar"><div className="search-box"><Icon name="search" size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadUsers(keyword, status, 1); }} placeholder="搜索用户名或姓名…" /></div><select className="filter-button" value={status} onChange={(event) => { setStatus(event.target.value); void loadUsers(keyword, event.target.value, 1); }}><option value="">状态：全部</option><option value="ACTIVE">正常</option><option value="LOCKED">已锁定</option><option value="INACTIVE">已停用</option></select><button className="outline-button" onClick={() => void loadUsers(keyword, status, 1)}>查询</button></div>{error && <div className="inline-error"><Icon name="warning" size={16} />{error}</div>}<div className="table-scroll"><table><thead><tr><th>用户名</th><th>显示姓名</th><th>部门 ID</th><th>邮箱</th><th>手机号</th><th>状态</th><th>操作</th></tr></thead><tbody>{loading ? <tr><td colSpan={7} className="table-empty">正在加载用户数据…</td></tr> : users.length === 0 ? <tr><td colSpan={7} className="table-empty">暂无用户</td></tr> : users.map((item) => <tr key={item.id}><td className="mono-text">{item.username}</td><td className="material-name">{item.display_name}</td><td>{item.department_id || "—"}</td><td>{item.email || "—"}</td><td>{item.phone || "—"}</td><td><span className={`status-pill ${item.status === "ACTIVE" ? "active" : "inactive"}`}><i />{item.status === "ACTIVE" ? "正常" : item.status === "LOCKED" ? "已锁定" : "已停用"}</span></td><td><button className="row-action" onClick={() => void getUser(token, item.id).then(setDetail).catch((reason) => setError(reason instanceof Error ? reason.message : "用户详情加载失败"))}>详情</button><button className="row-action" onClick={() => setEditing({ ...item, password: "", role_ids: [] })}>编辑</button><button className="row-action danger-action" onClick={() => setConfirmingId(item.id)}>停用</button></td></tr>)}</tbody></table></div><ListPagination page={page} pageSize={pageSize} total={total} onChange={(nextPage) => void loadUsers(keyword, status, nextPage)} /></section>{editing && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><form className="modal surface" onSubmit={saveUser}><div className="section-heading"><div><p className="eyebrow">用户资料</p><h2>{editing.id ? "编辑用户" : "新增用户"}</h2></div><button type="button" className="icon-button" onClick={() => setEditing(null)}>×</button></div><div className="form-grid"><label>用户名<input value={editing.username} disabled={Boolean(editing.id)} onChange={(event) => setEditing({ ...editing, username: event.target.value })} /></label><label>显示姓名<input value={editing.display_name} onChange={(event) => setEditing({ ...editing, display_name: event.target.value })} /></label><label>登录密码<input type="password" value={editing.password} placeholder={editing.id ? "留空表示不修改" : "至少 8 位"} onChange={(event) => setEditing({ ...editing, password: event.target.value })} /></label><label>部门 ID<input type="number" min="1" value={editing.department_id ?? ""} onChange={(event) => setEditing({ ...editing, department_id: event.target.value ? Number(event.target.value) : null })} /></label><label>邮箱<input type="email" value={editing.email || ""} onChange={(event) => setEditing({ ...editing, email: event.target.value })} /></label><label>手机号<input value={editing.phone || ""} onChange={(event) => setEditing({ ...editing, phone: event.target.value })} /></label><label>状态<select value={editing.status || "ACTIVE"} onChange={(event) => setEditing({ ...editing, status: event.target.value })}><option value="ACTIVE">正常</option><option value="LOCKED">已锁定</option><option value="INACTIVE">已停用</option></select></label><label>角色 ID（逗号分隔）<input value={editing.role_ids.join(",")} onChange={(event) => setEditing({ ...editing, role_ids: event.target.value.split(",").map((value) => Number(value.trim())).filter((value) => value > 0) })} /></label></div><div className="modal-actions"><button type="button" className="outline-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中…" : "保存用户"}</button></div></form></div>}{confirmingId !== null && <ConfirmDialog title="停用用户" description="停用后该用户将无法继续登录系统。" confirmText="确认停用" onClose={() => setConfirmingId(null)} onConfirm={() => disableUser(confirmingId)} />}{detail && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetail(null); }}><div className="modal surface"><div className="section-heading"><div><p className="eyebrow">用户详情</p><h2>用户详情</h2></div><button className="icon-button" onClick={() => setDetail(null)}>×</button></div><pre className="detail-json">{JSON.stringify(detail, null, 2)}</pre></div></div>}</>;
}

function ComingSoon() { return <section className="empty-state surface"><span className="empty-icon"><Icon name="activity" size={28} /></span><p className="eyebrow">模块接入中</p><h1>这个模块正在接入</h1><p>当前先完成工作台、认证、化学品和供应商主数据。采购、仓储、质量等模块会沿用同一套权限和数据交互规范。</p></section>; }

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("chemicalops_token") || "");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [activeView, setActiveView] = useState<ViewKey>("dashboard");
  const [apiOnline, setApiOnline] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [authLoading, setAuthLoading] = useState(Boolean(token));

  useEffect(() => { void checkHealth().then(setApiOnline).catch(() => setApiOnline(false)); }, []);
  useEffect(() => { if (!token) { setAuthLoading(false); return; } void getCurrentUser(token).then(setUser).catch(() => { localStorage.removeItem("chemicalops_token"); setToken(""); }).finally(() => setAuthLoading(false)); }, [token]);
  useEffect(() => { if (!token) { setUnreadCount(0); return; } void getUnreadNotificationCount(token).then((result) => setUnreadCount(result.unread_count)).catch(() => setUnreadCount(0)); }, [token, activeView]);

  async function handleLogin(username: string, password: string) { const result = await login(username, password); localStorage.setItem("chemicalops_token", result.access_token); setToken(result.access_token); }
  function handleLogout() { localStorage.removeItem("chemicalops_token"); setToken(""); setUser(null); setActiveView("dashboard"); }
  const page = useMemo(() => { if (activeView === "dashboard" && user) return <Dashboard user={user} token={token} apiOnline={apiOnline} onSelect={setActiveView} />; if (activeView === "chemicals") return <ChemicalsPage token={token} />; if (activeView === "suppliers") return <SupplierPage token={token} />; if (activeView === "products") return <ProductPage token={token} />; if (activeView === "purchases") return <PurchasePage token={token} />; if (activeView === "deliveries") return <DeliveriesPage token={token} />; if (activeView === "inbounds") return <InboundsPage token={token} />; if (activeView === "inventory") return <InventoryPage token={token} />; if (activeView === "quality") return <QualityPage token={token} />; if (activeView === "users") return <UsersPage token={token} />; if (activeView === "finance" || activeView === "logistics" || activeView === "inventory-ops" || activeView === "exceptions" || activeView === "files" || activeView === "supplier-portal" || activeView === "system") return <BusinessModulesPage token={token} section={activeView} />; return <ComingSoon />; }, [activeView, apiOnline, token, user]);

  if (authLoading) return <div className="loading-screen"><span className="loading-ring" /><p>正在连接系统…</p></div>;
  if (!user) return <LoginPage onLogin={async (username, password) => { const result = await login(username, password); localStorage.setItem("chemicalops_token", result.access_token); setToken(result.access_token); }} />;
  return <div className="app-shell"><Sidebar activeView={activeView} onSelect={setActiveView} user={user} /><main className="main-content"><header className="topbar"><button className="mobile-menu"><Icon name="menu" size={20} /></button><div className="breadcrumbs"><span>化学品运营中心</span><b>/</b><strong>{activeView === "dashboard" ? "运营总览" : activeView === "chemicals" ? "化学品管理" : activeView === "suppliers" ? "供应商管理" : activeView === "products" ? "产品与包装" : activeView === "purchases" ? "采购申请与订单" : activeView === "deliveries" ? "到货与收货" : activeView === "quality" ? "质量验收" : activeView === "inbounds" ? "库存入库" : activeView === "inventory" ? "库存台账" : activeView === "users" ? "用户与权限" : activeView === "finance" ? "财务管理" : activeView === "logistics" ? "询价与供应" : activeView === "inventory-ops" ? "仓储作业" : activeView === "exceptions" ? "异常与通知" : activeView === "files" ? "文件与附件" : activeView === "supplier-portal" ? "供应商门户" : activeView === "system" ? "组织与权限" : "模块接入中"}</strong></div><div className="topbar-actions"><div className="global-search"><Icon name="search" size={17} /><span>搜索化学品、供应商、订单…</span><kbd>快捷键</kbd></div><button className="icon-button" aria-label="查看通知" onClick={() => setActiveView("exceptions")}><Icon name="warning" size={18} />{unreadCount > 0 && <span className="notification-dot">{unreadCount > 99 ? "99+" : unreadCount}</span>}</button><AccountMenu user={user} token={token} onUserUpdate={setUser} onLogout={handleLogout} /></div></header><div className="content-wrap">{page}</div></main><AIFloatingAssistant token={token} /></div>;
}





