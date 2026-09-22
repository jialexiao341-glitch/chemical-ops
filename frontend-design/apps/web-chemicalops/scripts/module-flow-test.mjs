/**
 * 阶段 2 新模块写路径实测（对应 docs/新版前端说明.md 第七节第 6 项）：
 *   G 库存领用：新建 → 提交 → 驳回 → 重提 → 审批 → 执行出库；（另一单）取消
 *   H 库存调拨：新建（源批次 + 目标库位须不同）→ 提交 → 审批 → 执行调拨
 *   I 库存盘点：新建（选仓库 → 批次 → 实盘=账面零差异）→ 提交 → 审批 → 执行盘点
 *   J 运营异常：API 造数 → 详情 → 指派 → 状态推进 → 处理任务全周期 → 处理记录
 *        → 标记解决 → 关闭（必填说明）
 *   K AI 对话：发查询 → 查询链路默认收起 → 展开见槽位/SQL → 再收起
 *
 * 与 flow-test.mjs 的差异（这些页面的实际形态）：
 * - 领用/调拨/盘点/异常列表**没有 keyword 搜索框**（筛选仅状态/类型），
 *   创建后靠 @success 自动刷新 + id 倒序，用业务单号/purpose 定位行。
 * - 确认按钮文案不统一（提交/审批通过/执行出库/确认驳回/确认），
 *   clickConfirm 改为**弹层内 primary 按钮优先**，文本正则兜底。
 * - 调拨目标库位不能与源库位相同（前后端双重校验），按 label 文本避开。
 * - 盘点实盘数量填账面值（零差异），执行不改动库存，可重复跑。
 * - 异常创建没有 UI 入口，J0 用 API 造数（唯一 source_id 避免重复拦截）。
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：
 *   $env:SMOKE_PASSWORD='你的密码'; node scripts/module-flow-test.mjs
 *   （密码只从环境变量读取，不写入仓库）
 */
import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE ?? 'http://localhost:3000';
const API = process.env.SMOKE_API ?? 'http://127.0.0.1:8888';
const USER = process.env.SMOKE_USER ?? 'system_admin';
const PASSWORD = process.env.SMOKE_PASSWORD;
if (!PASSWORD) {
  console.error(
    '请通过环境变量 SMOKE_PASSWORD 提供登录密码（不写入仓库）。\n' +
      "PowerShell: $env:SMOKE_PASSWORD='***'; node scripts/module-flow-test.mjs",
  );
  process.exit(1);
}
const OUT = 'C:/self_project/ChemicalOps/.cache/shots';
mkdirSync(OUT, { recursive: true });

const stamp = Date.now().toString().slice(-8);
const ISSUE_PURPOSE = `领用写路径测试${stamp}`;
const ISSUE_CANCEL_PURPOSE = `领用待取消${stamp}`;
const TRANSFER_PURPOSE = `调拨写路径测试${stamp}`;
const STOCKTAKE_PURPOSE = `盘点写路径测试${stamp}`;
const EXC_DESC = `异常写路径测试${stamp}`;
const TASK_TITLE = `核实测试异常${stamp}`;
const QTY = 1;

const steps = [];
function record(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`${ok ? ' ok ' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

const writes = [];
const pageErrors = [];
/** 关键写接口的最新响应体 */
const captured = {};

function dumpDiagnostics() {
  console.log('\n=== 后端写请求 ===');
  console.log(writes.join('\n') || '(未捕获到写请求)');
  console.log('\n=== 浏览器 pageerror ===');
  console.log(pageErrors.join('\n') || '(无)');
}
process.on('uncaughtException', (e) => {
  console.error('\n脚本异常中止：', e.message);
  dumpDiagnostics();
  process.exit(1);
});

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } });

page.on('pageerror', (e) => pageErrors.push(`[pageerror] ${e.message}`));
page.on('response', async (r) => {
  const req = r.request();
  const method = req.method();
  if (method === 'GET' || method === 'HEAD') return;
  const u = r.url();
  if (!u.includes('/api/v1/')) return;
  let full = '';
  try {
    full = (await r.text()).slice(0, 20_000);
  } catch {
    full = '(unreadable)';
  }
  const path = u.replace(/^.*\/api\/v1/, '');
  writes.push(`${r.status()} ${method} ${path} → ${full.slice(0, 160)}`);
  if (r.status() >= 400 || method !== 'POST') return;
  try {
    const json = JSON.parse(full);
    if (!json || typeof json !== 'object') return;
    if (path === '/inventory/issue-requests') captured.issue = json;
    if (path === '/inventory/transfer-requests') captured.transfer = json;
    if (path === '/inventory/stocktakes') captured.stocktake = json;
    if (path === '/operation-exceptions') captured.exception = json;
    if (path.endsWith('/tasks')) captured.task = json;
  } catch {
    // 非 JSON 响应忽略
  }
});

// ---------- 通用工具 ----------

/** 兜底文本匹配：覆盖各页面不统一的 okText */
const CONFIRM_NAME =
  /^(确\s*认|确\s*定|提\s*交|发\s*送|保\s*存|审批通过|执行出库|执行调拨|执行盘点|确认下单|确认驳回|确认取消|取消任务|取\s*消)$/;

/** 指定标题（或最上层）的可见弹层 */
function dialog(hasText = null) {
  let loc = page.locator('[role="dialog"]:visible');
  if (hasText) loc = loc.filter({ hasText });
  return loc.last();
}

async function login() {
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  const inputs = page.locator('input:visible');
  await inputs.nth(0).fill(USER);
  await inputs.nth(1).fill(PASSWORD);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(5000);
  if (page.url().includes('/auth/login')) {
    throw new Error('登录失败，请确认账号密码与后端状态');
  }
}

async function gotoPage(path) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
}

function row(text) {
  return page.locator('tr', { hasText: text }).first();
}

/** 等行出现（创建后自动刷新，最多 10s） */
async function waitForRow(text, timeout = 10_000) {
  try {
    await row(text).waitFor({ state: 'visible', timeout });
    return true;
  } catch {
    return false;
  }
}

/** 失败诊断：打印当前可见弹层的标题与按钮 */
async function dumpDialogs(tag) {
  const info = await page.evaluate(() => {
    const dialogs = [...document.querySelectorAll('[role="dialog"]')].map(
      (d) => ({
        buttons: [...d.querySelectorAll('button')]
          .map((b) => b.textContent?.trim())
          .filter(Boolean),
        title:
          d.querySelector('header, [role="heading"]')?.textContent?.trim() ??
          d.textContent?.slice(0, 60),
        visible: !!(d.offsetWidth || d.offsetHeight),
      }),
    );
    const toasts = [...document.querySelectorAll('[class*="message-notice"]')]
      .map((el) => el.textContent?.trim())
      .filter(Boolean);
    return { dialogs, toasts };
  });
  console.log(`       [diag:${tag}]`, JSON.stringify(info));
}

/**
 * 点击列表行的操作（内联按钮优先，下拉兜底）。
 * 与 flow-test 同款：点击前 Escape 清残留下拉，打印菜单条目便于定位。
 */
async function rowAction(rowText, itemRe, expectedTitle = null) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const r = row(rowText);
  if ((await r.count()) === 0) {
    await dumpDialogs(`row-missing:${rowText.slice(0, 20)}`);
    throw new Error(`列表里找不到「${rowText}」所在的行`);
  }

  // 内联按钮三种可能的容器：adapter 内建类 / 页面自定义 slot div / 行内裸 button
  let inlineBtn = r
    .locator('.table-operations button')
    .filter({ hasText: itemRe })
    .first();
  if ((await inlineBtn.count()) === 0) {
    inlineBtn = r.locator('button').filter({ hasText: itemRe }).first();
  }
  const hasInline = (await inlineBtn.count()) > 0;
  console.log(
    `       [rowAction] 目标="${rowText.slice(0, 24)}" 模式=${hasInline ? '内联' : '下拉'}`,
  );

  let clickedText;
  if (hasInline) {
    clickedText = ((await inlineBtn.textContent()) ?? '').trim();
    await inlineBtn.click();
  } else {
    let opBtn = r.locator('.table-operations button').last();
    if ((await opBtn.count()) === 0) {
      opBtn = r.locator('button').last();
    }
    if ((await opBtn.count()) === 0) {
      throw new Error(`「${rowText}」行没有操作按钮`);
    }
    await opBtn.click();
    const dropdown = page
      .locator('.ant-dropdown:not(.ant-dropdown-hidden)')
      .last();
    try {
      await dropdown.waitFor({ state: 'visible', timeout: 8000 });
    } catch {
      await dumpDialogs(`dropdown-not-open:${rowText.slice(0, 20)}`);
      throw new Error(`「${rowText}」的操作下拉没有打开`);
    }
    const items = dropdown.locator('button');
    const texts = await items.allTextContents();
    const target = items.filter({ hasText: itemRe }).first();
    if ((await target.count()) === 0) {
      throw new Error(
        `操作菜单中没有匹配 ${itemRe} 的项，可选：${texts.join('/')}`,
      );
    }
    clickedText = ((await target.textContent()) ?? '').trim();
    console.log(`       [menu] 条目=${JSON.stringify(texts)} 点击=${clickedText}`);
    await target.click();
  }
  await page.waitForTimeout(800);

  if (expectedTitle) {
    const opened = await page
      .locator('[role="dialog"]:visible')
      .filter({ hasText: expectedTitle })
      .count();
    if (opened === 0) {
      await dumpDialogs(`expect:${expectedTitle}`);
      throw new Error(`点击「${clickedText}」后未打开「${expectedTitle}」弹层`);
    }
  }
}

/**
 * 在指定弹层内点确认按钮：footer primary 优先（各页 okText 不统一），
 * 找不到再退回文本正则。必须传 titleRe 圈定弹层，避免误点残留弹层。
 */
async function clickConfirm(titleRe) {
  const dlg = dialog(titleRe);
  if ((await dlg.count()) === 0) {
    await dumpDialogs(`confirm-missing:${titleRe}`);
    throw new Error(`找不到弹层：${titleRe}`);
  }
  const allDialogs = await page.locator('[role="dialog"]:visible').count();
  if (allDialogs > 1) {
    console.log(`       [warn] 可见弹层 ${allDialogs} 个，已限定「${titleRe}」`);
  }
  const primary = dlg.locator('button.ant-btn-primary').last();
  if ((await primary.count()) > 0) {
    console.log(`       [confirm] 点击 primary：${titleRe}`);
    await primary.click();
  } else {
    const btn = dlg.getByRole('button', { name: CONFIRM_NAME }).last();
    if ((await btn.count()) === 0) {
      await dumpDialogs(`confirm-no-btn:${titleRe}`);
      throw new Error(`弹层「${titleRe}」内没有可点的确认按钮`);
    }
    console.log(`       [confirm] 文本兜底：${titleRe}`);
    await btn.click();
  }
  await page.waitForTimeout(1500);
}

/** 在指定弹层内填 textarea */
async function fillDialogTextarea(titleRe, text) {
  const dlg = dialog(titleRe);
  if ((await dlg.count()) === 0) {
    await dumpDialogs(`fill-missing:${titleRe}`);
    throw new Error(`找不到弹层：${titleRe}`);
  }
  await dlg.locator('textarea').first().fill(text);
}

async function waitDialogClosed(hasText, timeout = 8000) {
  try {
    await page
      .locator('[role="dialog"]')
      .filter({ hasText })
      .waitFor({ state: 'hidden', timeout });
    return true;
  } catch {
    return false;
  }
}

/** 等弹层内 Spin 结束（选项加载完成再点下拉） */
async function waitSpin(dlg) {
  try {
    await dlg
      .locator('.ant-spin-spinning')
      .waitFor({ state: 'hidden', timeout: 10_000 });
  } catch {
    // 没有 Spin 时不阻塞
  }
}

/** 弹层明细行内选下拉第一个选项 */
async function pickRowSelect(dlgRow, selectIndex, waitMs = 1000) {
  await dlgRow.locator('.ant-select').nth(selectIndex).click();
  await page.waitForTimeout(waitMs);
  const opt = page
    .locator('.ant-select-dropdown:visible .ant-select-item-option')
    .first();
  await opt.waitFor({ state: 'visible', timeout: 8000 });
  const label = ((await opt.textContent()) ?? '').trim();
  await opt.click();
  await page.waitForTimeout(400);
  await page.keyboard.press('Escape');
  return label;
}

// ---------- 登录 ----------
await login();
record('登录成功', true, page.url());

// ============================================================
// G. 库存领用：新建 → 提交 → 驳回 → 重提 → 审批 → 执行；另一单取消
// ============================================================
console.log('\n--- G. 库存领用 ---');
await gotoPage('/warehouse/issue-requests');

async function createIssue(purpose) {
  await page
    .getByRole('button', { name: /新建领用申请/ })
    .click();
  await page.waitForTimeout(2000);
  const dlg = dialog('新建领用申请');
  await waitSpin(dlg);
  await page.fill('textarea[name="purpose"]', purpose);
  const itemRow = dlg.locator('.ant-table-tbody tr').first();
  const batchLabel = await pickRowSelect(itemRow, 0, 1500);
  await itemRow.locator('.ant-input-number-input').first().fill(String(QTY));
  await clickConfirm('新建领用申请');
  const closed = await waitDialogClosed('新建领用申请');
  const appeared = await waitForRow(purpose);
  record(
    `G1 新建领用（${purpose.slice(0, 10)}…）`,
    closed && appeared,
    `批次=${batchLabel.slice(0, 40)} 行可见=${appeared}`,
  );
}

await createIssue(ISSUE_PURPOSE);
if (!(await waitForRow(ISSUE_PURPOSE))) {
  throw new Error('领用单未出现在列表，中止');
}

await rowAction(ISSUE_PURPOSE, /提\s*交/, '提交领用申请');
await clickConfirm('提交领用申请');
await page.waitForTimeout(2000);
record(
  'G2 提交后状态=待审批',
  (await row(ISSUE_PURPOSE).getByText('待审批').count()) > 0,
);

await rowAction(ISSUE_PURPOSE, /驳\s*回/, '驳回领用申请');
await fillDialogTextarea('驳回领用申请', '模块写路径测试驳回');
await clickConfirm('驳回领用申请');
await page.waitForTimeout(2000);
record(
  'G3 驳回后状态=已驳回',
  (await row(ISSUE_PURPOSE).getByText('已驳回').count()) > 0,
);

await rowAction(ISSUE_PURPOSE, /提\s*交/, '提交领用申请');
await clickConfirm('提交领用申请');
await page.waitForTimeout(2000);
record(
  'G4 驳回后可重新提交',
  (await row(ISSUE_PURPOSE).getByText('待审批').count()) > 0,
);

await rowAction(ISSUE_PURPOSE, /审批通过/, '审批领用申请');
await clickConfirm('审批领用申请');
await page.waitForTimeout(2000);
record(
  'G5 审批通过后状态=已批准',
  (await row(ISSUE_PURPOSE).getByText('已批准').count()) > 0,
);
await page.screenshot({ path: `${OUT}/module-G-issue-approved.png` });

await rowAction(ISSUE_PURPOSE, /执\s*行\s*出\s*库/, '执行领用出库');
await clickConfirm('执行领用出库');
await page.waitForTimeout(2500);
const issueExecWrites = writes.filter((w) => w.includes('/execute'));
record(
  'G6 执行出库后状态=已完成',
  (await row(ISSUE_PURPOSE).getByText('已完成').count()) > 0 &&
    issueExecWrites.length > 0,
  `execute请求=${issueExecWrites.length}`,
);

// 另一单测取消
await createIssue(ISSUE_CANCEL_PURPOSE);
await rowAction(ISSUE_CANCEL_PURPOSE, /取\s*消/, '取消领用申请');
await clickConfirm('取消领用申请');
await page.waitForTimeout(2000);
const issueCancelWrites = writes.filter(
  (w) => w.includes('/issue-requests') && w.includes('/cancel'),
);
record(
  'G7 草稿可取消',
  (await row(ISSUE_CANCEL_PURPOSE).getByText('已取消').count()) > 0 &&
    issueCancelWrites.length > 0,
);

// ============================================================
// H. 库存调拨：新建 → 提交 → 审批 → 执行
// ============================================================
console.log('\n--- H. 库存调拨 ---');
await gotoPage('/warehouse/transfers');
await page.getByRole('button', { name: /新建调拨申请/ }).click();
await page.waitForTimeout(2000);
{
  const dlg = dialog('新建调拨申请');
  await waitSpin(dlg);
  await page.fill('textarea[name="purpose"]', TRANSFER_PURPOSE);
  const itemRow = dlg.locator('.ant-table-tbody tr').first();
  const srcLabel = await pickRowSelect(itemRow, 0, 1500);
  // 源 label 形如「产品 @ 仓库/库位 批次N 可用X 单位」，提取「仓库/库位」
  const srcLoc = (srcLabel.match(/@\s*(.+?)\s*批次/) ?? [])[1] ?? '';

  // 目标库位：选第一个与源库位 label 不同的选项（前后端都禁止同库位调拨）
  await itemRow.locator('.ant-select').nth(1).click();
  await page.waitForTimeout(1000);
  const options = page.locator(
    '.ant-select-dropdown:visible .ant-select-item-option',
  );
  const optCount = await options.count();
  let targetPicked = '';
  for (let i = 0; i < optCount; i += 1) {
    const text = ((await options.nth(i).textContent()) ?? '').trim();
    if (srcLoc && text === srcLoc) continue;
    if (!srcLoc && i === 0) {
      targetPicked = text;
      await options.nth(i).click();
      break;
    }
    if (srcLoc) {
      targetPicked = text;
      await options.nth(i).click();
      break;
    }
  }
  await page.waitForTimeout(400);
  await page.keyboard.press('Escape');
  await itemRow.locator('.ant-input-number-input').first().fill(String(QTY));
  await clickConfirm('新建调拨申请');
  const closed = await waitDialogClosed('新建调拨申请');
  const appeared = await waitForRow(TRANSFER_PURPOSE);
  record(
    'H1 新建调拨（源≠目标）',
    closed && appeared && Boolean(targetPicked),
    `源=${srcLoc} 目标=${targetPicked}`,
  );
}
if (!(await waitForRow(TRANSFER_PURPOSE))) {
  throw new Error('调拨单未出现在列表，中止');
}

await rowAction(TRANSFER_PURPOSE, /提\s*交/, '提交调拨申请');
await clickConfirm('提交调拨申请');
await page.waitForTimeout(2000);
record(
  'H2 提交后状态=待审批',
  (await row(TRANSFER_PURPOSE).getByText('待审批').count()) > 0,
);

await rowAction(TRANSFER_PURPOSE, /审批通过/, '审批调拨申请');
await clickConfirm('审批调拨申请');
await page.waitForTimeout(2000);
record(
  'H3 审批通过后状态=已批准',
  (await row(TRANSFER_PURPOSE).getByText('已批准').count()) > 0,
);

await rowAction(TRANSFER_PURPOSE, /执\s*行\s*调\s*拨/, '执行库存调拨');
await clickConfirm('执行库存调拨');
await page.waitForTimeout(2500);
record(
  'H4 执行调拨后状态=已完成',
  (await row(TRANSFER_PURPOSE).getByText('已完成').count()) > 0,
  writes.some((w) => w.includes('/transfer-requests') && w.includes('/execute'))
    ? 'execute请求=✓'
    : 'execute请求未捕获',
);
await page.screenshot({ path: `${OUT}/module-H-transfer-done.png` });

// ============================================================
// I. 库存盘点：新建（实盘=账面零差异）→ 提交 → 审批 → 执行
// ============================================================
console.log('\n--- I. 库存盘点 ---');
await gotoPage('/warehouse/stocktakes');
await page.getByRole('button', { name: /新建盘点申请/ }).click();
await page.waitForTimeout(2000);
{
  const dlg = dialog('新建盘点申请');
  await waitSpin(dlg);
  await page.fill('textarea[name="purpose"]', STOCKTAKE_PURPOSE);

  // 仓库 Select 在 Form 外（drawer 内第一个 .ant-select）
  await dlg.locator('.ant-select').first().click();
  await page.waitForTimeout(1000);
  const whOpt = page
    .locator('.ant-select-dropdown:visible .ant-select-item-option')
    .first();
  await whOpt.waitFor({ state: 'visible', timeout: 8000 });
  const whLabel = ((await whOpt.textContent()) ?? '').trim();
  await whOpt.click();
  await page.waitForTimeout(400);
  await page.keyboard.press('Escape');
  // 选仓库后明细区才渲染（v-if），等批次选项加载
  await page.waitForTimeout(2000);
  await waitSpin(dlg);

  const itemRow = dlg.locator('.ant-table-tbody tr').first();
  const batchLabel = await pickRowSelect(itemRow, 0, 1500);
  // label 形如「产品 / 库位 批次N 账面X 单位」→ 实盘填账面值，零差异执行
  const bookQty = (batchLabel.match(/账面([\d.,]+)/) ?? [])[1];
  const counted = bookQty ? bookQty.replace(/,/g, '') : String(QTY);
  await itemRow
    .locator('.ant-input-number-input')
    .first()
    .fill(counted);

  await clickConfirm('新建盘点申请');
  const closed = await waitDialogClosed('新建盘点申请');
  const appeared = await waitForRow(STOCKTAKE_PURPOSE);
  record(
    'I1 新建盘点（实盘=账面）',
    closed && appeared,
    `仓库=${whLabel.slice(0, 24)} 批次=${batchLabel.slice(0, 40)} 实盘=${counted}`,
  );
}
if (!(await waitForRow(STOCKTAKE_PURPOSE))) {
  throw new Error('盘点单未出现在列表，中止');
}

await rowAction(STOCKTAKE_PURPOSE, /提\s*交/, '提交盘点申请');
await clickConfirm('提交盘点申请');
await page.waitForTimeout(2000);
record(
  'I2 提交后状态=待审批',
  (await row(STOCKTAKE_PURPOSE).getByText('待审批').count()) > 0,
);

await rowAction(STOCKTAKE_PURPOSE, /审批通过/, '审批盘点申请');
await clickConfirm('审批盘点申请');
await page.waitForTimeout(2000);
record(
  'I3 审批通过后状态=已批准',
  (await row(STOCKTAKE_PURPOSE).getByText('已批准').count()) > 0,
);

await rowAction(STOCKTAKE_PURPOSE, /执\s*行\s*盘\s*点/, '执行盘点调整');
await clickConfirm('执行盘点调整');
await page.waitForTimeout(2500);
record(
  'I4 执行盘点后状态=已完成',
  (await row(STOCKTAKE_PURPOSE).getByText('已完成').count()) > 0,
);
await page.screenshot({ path: `${OUT}/module-I-stocktake-done.png` });

// ============================================================
// J. 运营异常：API 造数 → 指派 → 状态推进 → 任务全周期 → 记录 → 解决 → 关闭
// ============================================================
console.log('\n--- J. 运营异常 ---');

// J0 异常没有创建 UI 入口，直接 API 造数（source_id 用时间戳避免重复拦截）
let EXC_NO = '';
try {
  const loginRes = await fetch(`${API}/api/v1/auth/login`, {
    body: JSON.stringify({ password: PASSWORD, username: USER }),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  });
  const loginJson = await loginRes.json();
  const token = loginJson.access_token;
  if (!token) throw new Error(`登录响应无 token: ${JSON.stringify(loginJson)}`);
  const createRes = await fetch(`${API}/api/v1/operation-exceptions`, {
    body: JSON.stringify({
      description: EXC_DESC,
      exception_type: 'OTHER',
      severity: 'MEDIUM',
      source_id: Number(stamp) % 2_000_000_000,
      source_type: 'OTHER',
    }),
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    method: 'POST',
  });
  const created = await createRes.json();
  if (!createRes.ok) {
    throw new Error(`创建异常失败 ${createRes.status}: ${JSON.stringify(created)}`);
  }
  EXC_NO = created.exception_no;
  writes.push(`${createRes.status} POST /operation-exceptions(API造数) → ${EXC_NO}`);
  record('J0 API 造数创建异常', Boolean(EXC_NO), EXC_NO);
} catch (e) {
  record('J0 API 造数创建异常', false, e.message);
  throw e;
}

await gotoPage('/operations/exceptions');
const excAppeared = await waitForRow(EXC_NO);
record('J1 异常出现在列表（id 倒序第一条）', excAppeared, EXC_NO);
if (!excAppeared) throw new Error('异常未出现在列表，中止');

await rowAction(EXC_NO, /详情/);
await page.waitForTimeout(2500);
const excDlg = dialog(`异常详情 · ${EXC_NO}`);
if ((await excDlg.count()) === 0) {
  await dumpDialogs('exc-detail');
  throw new Error('异常详情抽屉未打开');
}

// J2 指派负责人
await excDlg
  .locator('.ant-select')
  .filter({ hasText: '选择异常负责人' })
  .first()
  .click();
await page.waitForTimeout(1000);
const ownerOpt = page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first();
await ownerOpt.waitFor({ state: 'visible', timeout: 8000 });
const ownerLabel = ((await ownerOpt.textContent()) ?? '').trim();
await ownerOpt.click();
await page.waitForTimeout(400);
await page.keyboard.press('Escape');
await excDlg.getByRole('button', { name: '保存指派' }).click();
await page.waitForTimeout(2000);
record(
  'J2 指派负责人',
  writes.some((w) => w.startsWith('200 PATCH /operation-exceptions')),
  ownerLabel.slice(0, 30),
);

// J3 OPEN → 开始处理（点状态推进按钮；此时还没有任务，无同名冲突）
await excDlg.getByRole('button', { name: '开始处理', exact: true }).click();
await page.waitForTimeout(2000);
const advancedToProcessing = await excDlg
  .getByRole('button', { name: '标记解决', exact: true })
  .count();
record('J3 状态推进 开始处理 → 处理中', advancedToProcessing > 0);

// J4 新建处理任务（创建后异常已是 PROCESSING，状态不变）
await excDlg.getByRole('button', { name: '新建处理任务' }).click();
await page.waitForTimeout(2000);
const taskModal = page
  .locator('[role="dialog"]:visible')
  .filter({ has: page.locator('input[placeholder*="与供应商核实"]') })
  .last();
if ((await taskModal.count()) === 0) {
  await dumpDialogs('task-modal');
  throw new Error('新建处理任务弹窗未打开');
}
await taskModal
  .locator('input[placeholder*="与供应商核实"]')
  .fill(TASK_TITLE);
const taskPrimary = taskModal.locator('button.ant-btn-primary').last();
if ((await taskPrimary.count()) > 0) {
  await taskPrimary.click();
} else {
  await taskModal.getByRole('button', { name: CONFIRM_NAME }).last().click();
}
await page.waitForTimeout(2500);
const taskRow = excDlg.locator('tr', { hasText: TASK_TITLE });
record(
  'J4 处理任务创建成功',
  (await taskRow.count()) > 0,
  writes.some((w) => w.includes('/tasks') && w.startsWith('201'))
    ? 'POST tasks=201'
    : '',
);

// J5 任务生命周期：开始处理 → 完成（必填完成说明）
if ((await taskRow.count()) > 0) {
  await taskRow
    .getByRole('button', { name: '开始处理', exact: true })
    .click();
  await page.waitForTimeout(2000);
  const taskProcessing = await taskRow
    .getByRole('button', { name: '完成', exact: true })
    .count();
  record('J5a 任务开始处理 → 处理中', taskProcessing > 0);

  await taskRow.getByRole('button', { name: '完成', exact: true }).click();
  await page.waitForTimeout(1500);
  await fillDialogTextarea('完成任务', '模块写路径测试：任务已完成');
  await clickConfirm('完成任务');
  await page.waitForTimeout(2000);
  const taskDone =
    (await taskRow.getByText('已完成').count()) > 0 ||
    (await taskRow.getByRole('button', { name: '重新处理' }).count()) > 0;
  record('J5b 任务完成（填完成说明）', taskDone);
}

// J6 处理记录：打开面板 → 追加 → 列表可见
await taskRow.getByRole('button', { name: '处理记录' }).click();
await page.waitForTimeout(2000);
const commentArea = excDlg.locator(
  'textarea[placeholder*="追加处理记录"]',
);
if ((await commentArea.count()) > 0) {
  await commentArea.fill('模块写路径测试处理记录');
  // antd 对两字中文按钮自动插空格：实际文本是「追 加」
  await excDlg.getByRole('button', { name: /追\s*加/ }).click();
  await page.waitForTimeout(2000);
  const commentShown =
    (await excDlg.getByText('模块写路径测试处理记录').count()) > 0;
  record(
    'J6 追加处理记录',
    commentShown &&
      writes.some((w) => w.includes('/comments') && w.startsWith('201')),
  );
} else {
  record('J6 追加处理记录', false, '处理记录面板未出现');
}

// J7 状态推进到关闭：标记解决 → 关闭异常（必填关闭说明）
await excDlg.getByRole('button', { name: '标记解决', exact: true }).click();
await page.waitForTimeout(2000);
const toResolved = await excDlg
  .getByRole('button', { name: '关闭异常', exact: true })
  .count();
record('J7a 标记解决 → 已解决', toResolved > 0);

await excDlg.getByRole('button', { name: '关闭异常', exact: true }).click();
await page.waitForTimeout(1500);
await fillDialogTextarea('关闭异常', '模块写路径测试：异常已关闭');
await clickConfirm('关闭异常');
await page.waitForTimeout(2000);
const closedShown =
  (await page.getByText('该异常已进入终态').count()) > 0 ||
  writes.some(
    (w) => w.includes('closing_note') && w.startsWith('200 PATCH'),
  );
record('J7b 关闭异常（必填关闭说明）', closedShown);
await page.screenshot({ path: `${OUT}/module-J-exception-closed.png` });

// 关闭详情抽屉
await page.keyboard.press('Escape');
await page.waitForTimeout(800);

// ============================================================
// K. AI 对话：查询链路默认收起 → 展开（槽位+SQL）→ 再收起
// ============================================================
console.log('\n--- K. AI 对话 ---');
await gotoPage('/ai/workspace');
await page
  .locator('textarea:visible')
  .fill('查询本月各供应商的采购订单金额排名');
await page.keyboard.press('Enter');

const traceBtn = page.locator('button:has-text("查询链路")').last();
try {
  await traceBtn.waitFor({ state: 'visible', timeout: 90_000 });
} catch {
  record('K1 查询链路标题出现', false, '90s 内未出现（LLM/查询超时）');
  await dumpDialogs('ai-trace');
  throw new Error('AI 未返回查询链路');
}
const traceBox = traceBtn.locator('xpath=..');
record('K1 查询链路标题出现', true, (await traceBtn.innerText()).replace(/\n/g, ' '));

// 默认收起：容器内没有 SQL pre、没有槽位 Tag
const collapsedPre = await traceBox.locator('pre').count();
record('K2 默认收起（无 SQL 块）', collapsedPre === 0, `pre=${collapsedPre}`);

// 展开
await traceBtn.click();
await page.waitForTimeout(600);
const expandedPre = await traceBox.locator('pre').count();
const expandedTags = await traceBox.locator('.ant-tag').count();
const btnText = (await traceBtn.innerText()).replace(/\n/g, ' ');
record(
  'K3 展开后 SQL+槽位可见',
  expandedPre === 1 && expandedTags >= 8 && btnText.includes('收起'),
  `pre=${expandedPre} 槽位Tag=${expandedTags}`,
);

// 再收起
await traceBtn.click();
await page.waitForTimeout(600);
const recollapsedPre = await traceBox.locator('pre').count();
record('K4 再次点击收起', recollapsedPre === 0, `pre=${recollapsedPre}`);
await page.screenshot({ path: `${OUT}/module-K-ai-trace.png` });

// ---------- 汇总 ----------
record(
  '全程无未捕获的 Promise 拒绝',
  pageErrors.length === 0,
  pageErrors.slice(0, 3).join(' | ').slice(0, 200),
);

dumpDiagnostics();
await browser.close();

const failed = steps.filter((s) => !s.ok);
console.log(`\n结果：${steps.length - failed.length}/${steps.length} 通过`);
if (failed.length) {
  console.log('失败项：');
  for (const f of failed) console.log(`  - ${f.name}`);
}
process.exit(failed.length === 0 ? 0 : 1);
