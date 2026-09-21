import { FormEvent, ReactNode, useState } from "react";
import type { CurrentUser, ViewKey } from "../types";
import ReferenceAccountMenu from "../components/ReferenceAccountMenu";

type RIconName = "home" | "overview" | "cart" | "factory" | "box" | "quality" | "shield" | "finance" | "ai" | "chart" | "settings" | "search" | "bell" | "calendar" | "truck" | "file" | "warning" | "users" | "clock" | "cube" | "download" | "filter" | "chevron";

export function RIcon({ name, size = 20 }: { name: RIconName; size?: number }) {
  const paths: Record<RIconName, ReactNode> = {
    home: <><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10.5V21h14V10.5M9 21v-6h6v6"/></>,
    overview: <><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 15v-3m4 3V8m4 7v-5"/></>,
    cart: <><path d="M3 4h2l2 11h10l2-8H6"/><circle cx="9" cy="19" r="1"/><circle cx="17" cy="19" r="1"/></>,
    factory: <><path d="M3 21V10l6 3V9l6 4V6h4l2 15Z"/><path d="M7 17h2m3 0h2m3 0h2"/></>,
    box: <><path d="m4 7 8-4 8 4-8 4Z"/><path d="M4 7v10l8 4 8-4V7M12 11v10"/></>,
    quality: <><path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6Z"/><path d="m9 12 2 2 4-4"/></>,
    shield: <><path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6Z"/><path d="M12 8v4m0 4h.01"/></>,
    finance: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8m-8 4h5"/></>,
    ai: <><path d="M12 3v3m0 12v3M3 12h3m12 0h3"/><path d="m7 7 2 2m6 6 2 2m0-10-2 2m-6 6-2 2"/><circle cx="12" cy="12" r="4"/></>,
    chart: <><path d="M4 20V10m5 10V4m5 16v-7m5 7V7"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H3v-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V3h4v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18"/></>,
    truck: <><path d="M3 6h11v10H3Z"/><path d="M14 10h4l3 3v3h-7Z"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></>,
    file: <><path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h4M9 13h6m-6 4h6"/></>,
    warning: <><path d="M12 3 2.5 20h19Z"/><path d="M12 9v5m0 3h.01"/></>,
    users: <><circle cx="9" cy="8" r="4"/><path d="M2 21v-2a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v2m1-17a4 4 0 0 1 0 8m5 9v-2a5 5 0 0 0-4-4"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    cube: <><path d="m4 7 8-4 8 4-8 4Z"/><path d="M4 7v10l8 4 8-4V7M12 11v10"/></>,
    download: <><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 21h16"/></>,
    filter: <path d="M3 5h18l-7 8v6l-4 2v-8Z"/>,
    chevron: <path d="m9 18 6-6-6-6"/>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function Brand({ dark = false }: { dark?: boolean }) {
  return <div className={`ref-brand ${dark ? "on-dark" : ""}`}><img src="/chemicalops-icon.svg" alt=""/><strong>Chemical<span>Ops</span></strong></div>;
}

export function ReferenceLoginPage({ onLogin }: { onLogin: (user: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError("");
    try { await onLogin(username, password); } catch (reason) { setError(reason instanceof Error ? reason.message : "登录失败，请稍后重试"); } finally { setLoading(false); }
  }
  return <main className="ref-login">
    <section className="ref-login-visual">
      <Brand dark />
      <p className="ref-login-brandline">化学驱动 · 智能运营 · 更安全的未来</p>
      <div className="ref-login-copy"><h1>让化工运营<br/>更智能 · 更安全 · 更高效</h1><p>连接数据、人员与工艺，<br/>构建可持续的化工未来。</p><span className="ref-login-rule"/><small>SAFER CHEMISTRY<br/>BRIGHTER TOMORROW</small></div>
      <div className="ref-login-benefits"><span><RIcon name="chart"/>更高的<br/>运行效率</span><span><RIcon name="quality"/>更强的<br/>安全合规</span><span><RIcon name="overview"/>更低的<br/>环境影响</span><span><RIcon name="users"/>更协同的<br/>团队作业</span></div>
    </section>
    <section className="ref-login-form-panel">
      <div className="ref-login-tagline"><span/>化学让世界更美好</div>
      <form onSubmit={submit} className="ref-login-form">
        <h2>登录 Chemical<span>Ops</span></h2>
        <label>用户名<div className="ref-input"><RIcon name="users"/><input value={username} onChange={event => setUsername(event.target.value)} autoComplete="username"/></div></label>
        <label>密码<div className="ref-input"><RIcon name="shield"/><input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password"/></div></label>
        <label className="ref-remember"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)}/><span>✓</span>记住我</label>
        {error && <p className="ref-login-error">{error}</p>}
        <button className="ref-login-submit" disabled={loading}>{loading ? "正在登录" : "登录"}<span>→</span></button>
        <div className="ref-login-security"><RIcon name="quality"/>我们采取多重安全措施，保护您的数据安全。</div>
      </form>
    </section>
  </main>;
}

const navItems: Array<{ label: string; icon: RIconName; view: ViewKey }> = [
  { label: "运营总览", icon: "overview", view: "dashboard" },
  { label: "采购管理", icon: "cart", view: "purchases" },
  { label: "生产管理", icon: "factory", view: "products" },
  { label: "库存管理", icon: "box", view: "inventory" },
  { label: "质量管理", icon: "quality", view: "quality" },
  { label: "安全环保", icon: "shield", view: "exceptions" },
  { label: "财务管理", icon: "finance", view: "finance" },
  { label: "数据中心", icon: "chart", view: "files" },
  { label: "主数据", icon: "cube", view: "chemicals" },
  { label: "系统管理", icon: "settings", view: "users" },
];
const navGroups = [
  { title: "工作台", items: navItems.slice(0, 1) },
  { title: "业务运营", items: navItems.slice(1, 5) },
  { title: "风险与经营", items: navItems.slice(5, 7) },
  { title: "数据与主数据", items: navItems.slice(7, 9) },
  { title: "系统设置", items: navItems.slice(9) },
];

export function ReferenceWorkspace({ activeView, onSelect, user, token, onUserUpdate, onLogout, children }: { activeView: ViewKey; onSelect: (view: ViewKey) => void; user: CurrentUser; token: string; onUserUpdate: (user: CurrentUser) => void; onLogout: () => void; children: ReactNode }) {
  return <div className={`ref-shell ${activeView === "ai" ? "ref-shell-ai" : ""}`}>
    <aside className="ref-sidebar">
      <Brand dark/><p className="ref-sidebar-subtitle">化工企业运营平台</p>
      <nav>{navGroups.map(group=><section className="ref-nav-group" key={group.title}><h3>{group.title}</h3>{group.items.map((item) => <button key={`${item.label}-${item.view}`} className={activeView === item.view ? "active" : ""} onClick={() => onSelect(item.view)}><RIcon name={item.icon}/><span>{item.label}</span></button>)}</section>)}</nav>
      <p className="ref-sidebar-slogan">让化工运营更高效<br/>更安全 · 更可持续</p>
    </aside>
    <main className="ref-main">{children}</main><ReferenceAccountMenu user={user} token={token} onUserUpdate={onUserUpdate} onLogout={onLogout}/>
  </div>;
}

export function RefTopbar({ user, compact = false }: { user: CurrentUser; compact?: boolean }) {
  return <header className={`ref-topbar ${compact ? "compact" : ""}`}>
    {!compact && <label className="ref-global-search"><RIcon name="search"/><input placeholder="搜索物料、供应商、订单或批次..."/><kbd>⌘ K</kbd></label>}
    <div className="ref-topbar-spacer"/>
    <button className="ref-date-control"><RIcon name="calendar"/>2024年10月1日 - 2024年10月31日⌃</button>
    <button className="ref-bell"><RIcon name="bell"/><i>3</i></button>
  </header>;
}

const trendValues = [80, 145, 145, 175, 235, 210, 235, 320, 200, 210, 205, 220];
function ProcurementTrend() {
  const line = trendValues.map((value, index) => `${36 + index * 48},${194 - value * .42}`).join(" ");
  return <div className="ref-trend"><div className="ref-chart-meta"><span>金额（万元）</span><span><i className="y23"/>2023年 <i className="y24"/>2024年 <i className="line"/>累计金额</span></div><svg viewBox="0 0 620 230" role="img" aria-label="采购金额趋势">{[35,75,115,155,195].map(y=><line key={y} x1="34" y1={y} x2="610" y2={y} className="grid"/>)}{trendValues.map((v,i)=><g key={i}><rect x={40+i*48} y={195-v*.32} width="15" height={v*.32} className="bar-old"/><rect x={56+i*48} y={195-v*.42} width="15" height={v*.42} className="bar-new"/><text x={55+i*48} y="218" textAnchor="middle">{i+1}月</text></g>)}<polyline points={line} className="ref-line"/>{trendValues.map((v,i)=><circle key={i} cx={36+i*48} cy={194-v*.42} r="3.4"/>)}</svg><div className="ref-chart-tip"><b>2024年10月</b><span>采购金额 248 万元</span><span>较上月 <em>+12.6%</em></span></div></div>;
}

export function ReferenceDashboard({ user, onSelect }: { user: CurrentUser; onSelect: (view: ViewKey) => void }) {
  const risks = [
    ["PO-20240912-001","丙酮（分析纯） 5,000 kg","杭州化工科技有限公司","逾期 5 天","2024-10-15"],
    ["PO-20240918-003","乙醇（无水） 2,000 L","华东试剂供应商","逾期 3 天","2024-10-17"],
    ["PO-20240920-007","硫酸（98%） 1,000 kg","江苏化学股份有限公司","逾期 2 天","2024-10-18"],
  ];
  return <div className="ref-dashboard-page"><RefTopbar user={user}/><div className="ref-page-pad">
    <div className="ref-dashboard-title"><div><h1>化运运营总览</h1><p>实时掌握采购、到货、库存与质量动态，保障化学品供应安全稳定</p></div><div className="ref-handwriting">化学的力量 让产业更美好<span/></div></div>
    <div className="ref-kpis">
      <article><span className="mint"><RIcon name="finance"/></span><div><small>本月采购金额</small><strong>¥2,480,000</strong><em className="up">↑ 12.6%</em><p>较上月 ¥2,201,000</p></div><b className="spark">⌁</b></article>
      <article><span className="mint"><RIcon name="file"/></span><div><small>待处理申请</small><strong>18</strong><em className="danger">↑ 28.6%</em><p>较上月 14</p></div><b className="bars">▂▅▇▃▆▅</b></article>
      <article><span className="mint"><RIcon name="truck"/></span><div><small>逾期到货</small><strong>7</strong><em className="up">↓ 46.2%</em><p>较上月 13</p></div><b className="bars">▇▆▅▄▃▂</b></article>
      <article><span className="rose"><RIcon name="warning"/></span><div><small>库存风险</small><strong>12</strong><em className="up">↓ 33.3%</em><p>较上月 18</p></div><b className="bars">▂▄▇▆▄▃</b></article>
    </div>
    <div className="ref-dashboard-grid"><section className="ref-panel ref-trend-panel"><div className="ref-panel-head"><h2>采购金额趋势</h2><button>按月⌄</button></div><ProcurementTrend/></section><section className="ref-panel ref-risk-panel"><div className="ref-panel-head"><h2>风险事项</h2><button className="link" onClick={()=>onSelect("exceptions")}>查看全部 (19) ›</button></div><div className="ref-risk-tabs"><b>逾期到货 (7)</b><span>临近有效期 (5)</span></div>{risks.map((row,index)=><div className="ref-risk-row" key={row[0]}><i className={index===1?"orange":"red"}/><div><strong>{row[0]} <em>{row[3]}</em></strong><span>{row[1]}</span><small>{row[2]}</small></div><time>{row[4]}</time><b>…</b></div>)}</section></div>
    <div className="ref-dashboard-lower"><section className="ref-panel ref-supplier-panel"><div className="ref-panel-head"><h2>供应商绩效（本月）</h2><button className="link">查看全部</button></div><div className="ref-supplier-head"><span>供应商</span><span>准时交付率</span><span>质量合格率</span><span>本月采购额（万元）</span></div>{[["华东化学有限公司",100,99,680],["江苏试剂集团",92,98,420],["杭州化工科技有限公司",85,100,310],["上海源和化学",90,97,280],["广东化学材料",88,100,260]].map(row=><div className="ref-supplier-row" key={String(row[0])}><strong>{row[0]}</strong><span><i style={{width:`${row[1]}%`}}/>{row[1]}%</span><span><i style={{width:`${row[2]}%`}}/>{row[2]}%</span><b>{row[3]}</b></div>)}</section><section className="ref-panel ref-ai-insight"><div className="ref-panel-head"><h2><RIcon name="ai"/>化运助手 <em>AI</em></h2><button className="link" onClick={()=>onSelect("ai")}>换一换</button></div><div className="ref-ai-highlight"><RIcon name="ai"/><p><strong>本月采购金额较上月增长 12.6%</strong><span>主要来自溶剂类（+32%）和酸类（+18%）的采购增加，建议关注后续到货计划，确保库存周转。</span></p></div>{["有 3 个供应商的交付准时率低于 90%，建议跟进沟通","未来 30 天内有 5 个批次将到期，建议优先使用","根据历史数据，11 月溶剂类需求预计上升 20%，建议提前备货"].map((x,i)=><button className="ref-ai-line" key={x}><span>{i+1}</span>{x}<b>›</b></button>)}</section></div>
  </div></div>;
}

const purchaseRows = [
  ["PO20240826001","浙江新华工股份有限公司","328,500","执行中","2024-09-02","王丽"],
  ["PO20240825003","上海化学试剂有限公司","126,800","已下单","2024-08-28","张建国"],
  ["PO20240824007","江苏华东化工集团","985,000","审批中","2024-09-05","李娜"],
  ["PO20240823011","巴斯夫化学（中国）","560,000","执行中","2024-08-30","王丽"],
  ["PO20240822009","南京化工原料有限公司","78,400","已到货","2024-08-25","赵强"],
  ["PO20240821006","山东鲁北化工股份","432,000","执行中","2024-09-01","陈敏"],
  ["PO20240820008","广州化工贸易有限公司","215,600","已逾期","2024-08-18","李娜"],
  ["PO20240819004","天津渤化集团","687,300","已下单","2024-08-29","张建国"],
  ["PO20240818002","杭州浙化科技有限公司","95,200","已到货","2024-08-20","王磊"],
];

export function ReferenceProcurement() {
  return <div className="ref-procurement"><div className="ref-proc-main"><div className="ref-breadcrumb">⌂　›　采购管理　›　采购订单</div><div className="ref-module-title"><div><h1>采购管理</h1><p>高效、合规、透明的采购协同，保障生产稳定运行</p></div><button className="ref-primary">＋　新建采购申请</button></div><div className="ref-module-kpis">{[["file","待审批","12","较上周　+3 ↑"],["clock","执行中","28","较上周　-5 ↓"],["warning","已逾期","6","较上周　+2 ↑"],["finance","本月金额","¥1,268,500","较上月　+12% ↑"]].map((k,i)=><article key={k[1]}><span className={i===2?"rose":"mint"}><RIcon name={k[0] as RIconName}/></span><div><small>{k[1]}</small><strong>{k[2]}</strong><p>{k[3]}</p></div></article>)}</div><div className="ref-tabs"><button>采购申请（32）</button><button className="active">采购订单（86）</button><button>供应商（128）</button></div><div className="ref-filters"><label><RIcon name="search"/><input placeholder="请输入单号、供应商或物料名称"/></label><button>全部状态⌄</button><button>全部供应商⌄</button><button className="date">2024-08-01　~　2024-08-31　▣</button><button>更多筛选 <RIcon name="filter" size={16}/></button></div><section className="ref-purchase-table"><table><thead><tr><th>□　单号</th><th>供应商</th><th>金额（¥）</th><th>状态</th><th>期望到货</th><th>负责人</th><th>操作</th></tr></thead><tbody>{purchaseRows.map((row,i)=><tr key={row[0]} className={i===1?"selected":""}><td>{i===1?"☑":"□"}　<a>{row[0]}</a></td><td>{row[1]}</td><td>{row[2]}</td><td><span className={`ref-status s-${row[3]}`}>{row[3]}</span></td><td className={row[3]==="已逾期"?"danger-text":""}>{row[4]}</td><td>{row[5]}</td><td>…</td></tr>)}</tbody></table><div className="ref-pagination"><span>共 86 条　每页　<b>10⌄</b>　条</span><span>‹　<b>1</b>　2　3　4　5　…　9　›</span></div></section><div className="ref-proc-ai"><span><RIcon name="ai"/></span><p><strong>化运助手</strong><small>根据历史采购数据，建议对 乙二醇 的采购提前 7 天启动，预计下月价格可能上涨 5%。</small></p><button>查看详情</button><button>一键生成采购申请</button></div></div><aside className="ref-order-detail"><div className="ref-detail-head"><h2>采购订单 PO20240825003 <span>已下单</span></h2><button>×</button></div><div className="ref-detail-tabs"><b>详情</b><span>物料清单</span><span>收货与验收</span><span>相关单据</span></div><section><h3>基本信息</h3>{[["单号","PO20240825003"],["供应商","上海化学试剂有限公司　›"],["合同号","CT20240825-01"],["申请单","PR20240820011"],["下单日期","2024-08-25"],["期望到货","2024-08-28"],["负责人","张建国"],["备注","实验室常用试剂，按框架协议执行。"]].map(x=><p key={x[0]}><span>{x[0]}</span><strong>{x[1]}</strong></p>)}</section><section className="ref-progress"><h3>执行进度</h3><div><span className="done">✓<small>申请<br/>08-20</small></span><i/><span className="done">✓<small>审批<br/>08-22</small></span><i/><span className="current">●<small>下单<br/>08-25</small></span><i/><span>○<small>到货<br/>待确认</small></span><i/><span>○<small>验收<br/>待确认</small></span></div></section><section className="ref-materials"><div className="ref-panel-head"><h3>物料清单（3）</h3><button className="link">全部展开</button></div><table><thead><tr><th>物料名称</th><th>规格型号</th><th>数量</th><th>单价（¥）</th><th>金额（¥）</th></tr></thead><tbody><tr><td>乙醇</td><td>AR 500ml</td><td>100 瓶</td><td>68.00</td><td>6,800</td></tr><tr><td>丙酮</td><td>AR 4L</td><td>50 桶</td><td>120.00</td><td>6,000</td></tr><tr><td>盐酸</td><td>36% 工业级</td><td>200 桶</td><td>570.00</td><td>114,000</td></tr></tbody></table></section><div className="ref-detail-actions"><h3>操作</h3><div><button className="ref-primary">收货登记</button><button>查看合同</button><button>打印</button><button>…</button></div></div></aside></div>;
}

const inventoryRows = [["丙酮","AC20241008","甲类库A","25.0 吨","20.0 吨","2025-10-08","正常"],["乙醇（工业级）","ET20240912","甲类库B","8.5 吨","10.0 吨","2025-03-12","低于安全库存"],["盐酸（32%）","HCL20240821","酸碱库","42.0 吨","30.0 吨","2026-08-21","正常"],["氢氧化钠","NAOH20240718","化学品库C","4.0 吨","10.0 吨","2024-12-18","30天内到期"],["甲苯","TOL20240901","甲类库A","60.0 吨","50.0 吨","2026-09-01","正常"],["异丙醇","IPA20240830","甲类库B","12.5 吨","20.0 吨","2025-01-15","低于安全库存"],["硫酸（98%）","H2SO42040725","酸碱库","18.0 吨","15.0 吨","2024-11-05","30天内到期"],["乙酸乙酯","EAC20240920","甲类库C","35.0 吨","30.0 吨","2026-09-20","正常"]];

function QualityDonut(){return <div className="ref-quality-viz"><div className="ref-donut"><span>86<small>批次</small></span></div><div><p><i className="green"/>合格　<b>62</b>（72.1%）</p><p><i className="amber"/>部分合格　<b>16</b>（18.6%）</p><p><i className="red"/>不合格　<b>8</b>（9.3%）</p></div></div>}

export function ReferenceInventoryQuality({ user }: { user: CurrentUser }) {
  return <div className="ref-inventory"><header className="ref-inventory-head"><div><h1>库存与质量</h1><p>掌握库存状态与质量风险，保障供应连续性与产品合规</p></div><div><button className="ref-bell"><RIcon name="bell"/><i/></button><span className="ref-user-avatar">{user.display_name.slice(0,1)}</span><strong>{user.display_name}<small>运营部</small></strong>⌄</div></header><div className="ref-inventory-pad"><div className="ref-inventory-filters"><label>仓库 <button>全部仓库　⌄</button></label><label>物料类别 <button>全部　⌄</button></label><label>物料 <button>请选择物料　⌄</button></label><label>日期范围 <button><RIcon name="calendar" size={16}/>2024-10-01　~　2024-10-31</button></label><button className="ref-primary">查询</button><button>重置</button></div><div className="ref-inventory-kpis">{[["cube","可用库存","1,286.5 吨","↑ 2.3%","mint"],["warning","低于安全库存","12 个物料","↑ 3","amber"],["clock","30天内到期","8 批次","↑ 2","rose"],["file","待验收","6 批次","↓ 4","blue"]].map(k=><article key={k[1]}><span className={k[4]}><RIcon name={k[0] as RIconName}/></span><div><small>{k[1]}</small><strong>{k[2]}</strong></div><p>{k[3]}<small>较上月</small></p></article>)}</div><div className="ref-inventory-grid"><section className="ref-panel ref-stock-table"><div className="ref-panel-head"><h2>仓库库存明细</h2><button className="link">查看全部 ›</button></div><table><thead><tr><th>物料</th><th>批次</th><th>仓库</th><th>可用量</th><th>安全库存</th><th>有效期</th><th>风险状态</th><th>操作</th></tr></thead><tbody>{inventoryRows.map(row=><tr key={row[1]}>{row.slice(0,6).map((x,i)=><td key={i}>{x}</td>)}<td><span className={`ref-stock-status ${row[6]==="正常"?"ok":"warn"}`}>{row[6]}</span></td><td><a>详情</a></td></tr>)}</tbody></table></section><section className="ref-panel ref-quality-panel"><div className="ref-panel-head"><h2>质量检验结果</h2><button>近30天　⌄</button></div><QualityDonut/><h3>近6个月质量趋势</h3><div className="ref-stacked-bars">{[28,27,20,31,28,27].map((v,i)=><span key={i}><i style={{height:v}}/><b style={{height:v*.45}}/><em style={{height:6+(i%2)*4}}/><small>{i+5}月</small></span>)}</div></section><section className="ref-panel ref-risk-list"><div className="ref-panel-head"><h2>风险待办清单</h2></div><div className="ref-risk-tabs"><b>30天内到期 (8)</b><span>冻结库存 (4)</span><span>逾期未检 (6)</span></div><table><thead><tr><th>类型</th><th>物料</th><th>批次</th><th>仓库</th><th>数量</th><th>到期日 / 触发日</th><th>负责人</th><th>下一步操作</th><th>操作</th></tr></thead><tbody>{[["即将到期","硫酸（98%）","H2SO42040725","酸碱库","18.0 吨","2024-11-05","李芳","安排使用"],["即将到期","氢氧化钠","NAOH20240718","化学品库C","4.0 吨","2024-12-18","王强","评估处置"],["冻结库存","甲苯","TOL20240815","甲类库B","12.0 吨","2024-10-12","陈敏","等待复检"],["冻结库存","异丙醇","IPA20240828","甲类库B","6.5 吨","2024-10-18","陈敏","调查原因"],["逾期未检","乙酸乙酯","EAC20240920","甲类库C","20.0 吨","2024-10-05","刘洋","尽快送检"]].map(row=><tr key={row[2]}>{row.map((x,i)=><td key={i} className={i===5?"danger-text":""}>{x}</td>)}<td><a>处理</a></td></tr>)}</tbody></table></section><section className="ref-panel ref-batch-detail"><div className="ref-panel-head"><h2>批次详情</h2><button className="link">查看全部 ›</button></div><div className="ref-batch-product"><span><RIcon name="quality"/></span><p><strong>硫酸（98%）　<em>30天内到期</em></strong><small>批次号　H2SO42040725　　仓库　酸碱库<br/>可用量　<b>18.0 吨</b>（总量 20.0 吨）<br/>有效期　<b>2024-11-05</b>（<i>剩余 12 天</i>）</small></p></div><h3>溯源记录</h3>{[["2024-07-25","生产入库","生产批次：S20240725-01"],["2024-07-26","质量检验","结果：合格"],["2024-07-27","入库上架","库位：A-03-02"],["2024-10-20","库存盘点","数量：20.0 吨"],["2024-10-24","预警触发","距离到期 12 天"]].map((x,i)=><div className={`ref-trace ${i===4?"last":""}`} key={x[0]}><i/><span>{x[0]}</span><b>{x[1]}</b><em>{x[2]}</em></div>)}</section></div></div></div>;
}

export function ReferenceAIWorkspace() {
  const conversations = [["查询本月各供应商采购...","已生成图表与明细表","10:24"],["分析丙酮采购价格趋势","已完成分析","09:18"],["对比华东地区供应商交付...","已生成对比结果","08:42"],["本季度化工原料采购成本...","已完成分析","17:20"],["供应商交货及时率分析","已生成图表","15:06"],["提示：哪些原材料价格上涨...","已生成分析","11:33"],["查询上月库存周转天数","已完成分析","04-22"],["生成安全库存建议","已生成建议","04-21"]];
  return <div className="ref-ai-workspace"><aside className="ref-conversations"><div className="ref-conv-head"><h1>化运助手</h1><button>✎</button><p>用数据，驱动更好的化工运营</p></div><div className="ref-conv-tabs"><b>对话</b><span>智能体</span><span>知识库</span></div><h3>今天</h3>{conversations.slice(0,3).map((x,i)=><button className={i===0?"active":""} key={x[0]}><strong>{x[0]}</strong><small>{x[1]}</small><time>{x[2]}</time></button>)}<h3>昨天</h3>{conversations.slice(3,6).map(x=><button key={x[0]}><strong>{x[0]}</strong><small>{x[1]}</small><time>{x[2]}</time></button>)}<h3>更早</h3>{conversations.slice(6).map(x=><button key={x[0]}><strong>{x[0]}</strong><small>{x[1]}</small><time>{x[2]}</time></button>)}</aside><section className="ref-ai-main"><header><span><RIcon name="ai"/></span><div><h2>AI 分析工作区</h2><p>基于企业数据的可信分析，助您快速获取业务洞察</p></div><em>🤖 · AI · 化运助手<br/><small>专业 · 准确 · 可追溯</small></em></header><div className="ref-chat"><div className="ref-user-message"><span>U</span><p>查询本月各供应商采购订单金额排名<time>10:24</time></p></div><div className="ref-bot-message"><span>🤖</span><p>已为您查询到本月各供应商采购订单金额排名，并生成图表与明细表。<br/>数据来自企业采购系统，结果为只读数据，可追溯。<time>10:24</time></p></div><section className="ref-ai-result"><div className="ref-panel-head"><h3>▣　本月各供应商采购订单金额排名</h3><small>单位：万元</small></div>{[["中化国际",2480],["万华化学",1920],["上海石化",1360],["巴斯夫（中国）",980],["陶氏化学",760]].map((x,i)=><div className="ref-rank" key={x[0]}><span>{i+1}</span><b>{x[0]}</b><i style={{width:`${Number(x[1])/11}px`}}/><strong>{Number(x[1]).toLocaleString()}</strong></div>)}<div className="ref-panel-head ref-detail-title"><h3>▣　供应商采购订单明细（本月）</h3><button className="link"><RIcon name="download" size={16}/>下载表格</button></div><table><thead><tr><th>排名</th><th>供应商名称</th><th>采购订单金额（万元）</th><th>订单数量（笔）</th><th>占比</th></tr></thead><tbody>{[[1,"中化国际","2,480",46,"28.4%"],[2,"万华化学","1,920",38,"22.0%"],[3,"上海石化","1,360",32,"15.6%"],[4,"巴斯夫（中国）","980",21,"11.2%"],[5,"陶氏化学","760",18,"8.7%"]].map(x=><tr key={String(x[0])}>{x.map(v=><td key={String(v)}>{v}</td>)}</tr>)}</tbody></table></section><div className="ref-ai-notice">ⓘ　本结果为企业内部数据的只读分析，已记录查询过程，可随时追溯数据来源。</div></div><form className="ref-ai-input"><span>♧</span><input placeholder="继续提问，或输入“/”选择常用指令..."/><button>➤</button></form></section><aside className="ref-query-basis"><header><h2>查询依据</h2><span>● 结果可追溯</span></header>{[["数据集","采购订单事实表 (dw_purchase_order)","来自企业数据中心 · 已更新至 2024-10-31"],["时间范围","2024-10-01 至 2024-10-31","本月"],["权限范围","基于您当前的组织权限","华东化工有限公司 · 采购相关数据"],["已验证查询","SQL 已执行并通过校验","返回 5 条供应商结果"]].map((x,i)=><section key={x[0]}><h3><span>{["▰","▣","♟","✓"][i]}</span>{x[0]}</h3><strong>{x[1]}</strong><p>{x[2]}</p>{i===3&&<pre>SELECT<br/>　supplier_name,<br/>　SUM(order_amount) AS amount<br/>FROM dw_purchase_order<br/>WHERE order_date BETWEEN '2024-10-01'<br/>　AND '2024-10-31'<br/>GROUP BY supplier_name<br/>ORDER BY amount DESC<br/>LIMIT 5;</pre>}</section>)}<section><h3>⚑ 数据来源</h3>{["采购订单事实表 (dw_purchase_order)","供应商维度表 (dim_supplier)","组织权限视图 (vw_data_permission)"].map((x,i)=><p className="ref-source" key={x}><b>{i+1}</b>{x}<span>↗</span></p>)}</section></aside></div>;
}
