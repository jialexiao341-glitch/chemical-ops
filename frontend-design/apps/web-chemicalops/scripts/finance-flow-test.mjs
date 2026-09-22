/**
 * 财务全链写路径实测（对应 docs/新版前端说明.md 第七节第 7 项）：
 *   L 对账：创建 → 争议 → 重新确认
 *   M 发票：录入（价税校验）→ 提交核验 → 核验
 *   N 付款：发起 → 审批 → 登记付款（流水号）
 *   O 结算：创建 → 确认（对账单同时关闭）
 *
 * 依赖一个「已完成且尚无对账单」的采购订单，J0 式 API 预检动态寻找；
 * 走完后该订单被对账单占用，脚本 fail-fast 并明确提示。
 *
 * 交互约定与 module-flow-test 一致：弹层内 primary 优先点击、
 * 行操作内联优先、antd 两字中文按钮带空格用正则匹配。
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：
 *   $env:SMOKE_PASSWORD='你的密码'; node scripts/finance-flow-test.mjs
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
      "PowerShell: $env:SMOKE_PASSWORD='***'; node scripts/finance-flow-test.mjs",
  );
  process.exit(1);
}
const OUT = 'C:/self_project/ChemicalOps/.cache/shots';
mkdirSync(OUT, { recursive: true });

const stamp = Date.now().toString().slice(-8);
const INVOICE_NUMBER = `TEST-INV-${stamp}`;
const TXN_REF = `TESTREF-${stamp}`;
const TODAY = new Date().toISOString().slice(0, 10);

const steps = [];
function record(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`${ok ? ' ok ' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

const writes = [];
const captured = {};
const pageErrors = [];

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
  if (!u.includes('/api/v1/finance/')) return;
  let full = '';
  try {
    full = (await r.text()).slice(0, 20_000);
  } catch {
    full = '(unreadable)';
  }
  const path = u.replace(/^.*\/api\/v1/, '');
  writes.push(`${r.status()} ${method} ${path} → ${full.slice(0, 140)}`);
  if (r.status() >= 400) return;
  try {
    const json = JSON.parse(full);
    if (!json || typeof json !== 'object') return;
    if (path === '/finance/reconciliations') captured.recon = json;
    if (path === '/finance/invoices') captured.invoice = json;
    if (path === '/finance/payments') captured.payment = json;
    if (path === '/finance/settlements') captured.settlement = json;
  } catch {
    // 非 JSON 忽略
  }
});

// ---------- 通用工具 ----------

const CONFIRM_NAME =
  /^(确\s*认|确\s*定|提\s*交|发\s*送|保\s*存|确认对账|确认发起|提交核验|核验通过|确认驳回|审批通过|确认付款|确认结算|确认取消|取\s*消)$/;

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

async function waitForRow(text, timeout = 10_000) {
  try {
    await row(text).waitFor({ state: 'visible', timeout });
    return true;
  } catch {
    return false;
  }
}

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

/** 点击列表行操作：内联按钮优先（adapter 类 / 裸按钮），下拉兜底 */
async function rowAction(rowText, itemRe, expectedTitle = null) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const r = row(rowText);
  if ((await r.count()) === 0) {
    await dumpDialogs(`row-missing:${rowText.slice(0, 20)}`);
    throw new Error(`列表里找不到「${rowText}」所在的行`);
  }

  let inlineBtn = r
    .locator('.table-operations button')
    .filter({ hasText: itemRe })
    .first();
  if ((await inlineBtn.count()) === 0) {
    inlineBtn = r.locator('button').filter({ hasText: itemRe }).first();
  }
  // vxe 列多触发横向滚动时，fixed-right 操作列被拆到独立 table：
  // 主行有文本无按钮，fixed 行有按钮无文本，两者按 data-rowid 对齐。
  if ((await inlineBtn.count()) === 0) {
    const rowid =
      (await r.getAttribute('data-rowid')) ?? (await r.getAttribute('rowid'));
    if (rowid) {
      inlineBtn = page
        .locator(`tr[data-rowid="${rowid}"], tr[rowid="${rowid}"]`)
        .locator('button')
        .filter({ hasText: itemRe })
        .first();
    }
  }
  const hasInline = (await inlineBtn.count()) > 0;
  console.log(
    `       [rowAction] 目标="${rowText.slice(0, 24)}" 模式=${hasInline ? '内联(rowid跨表)' : '下拉'}`,
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
    const target = items.filter({ hasText: itemRe }).first();
    if ((await target.count()) === 0) {
      const texts = await items.allTextContents();
      throw new Error(
        `操作菜单中没有匹配 ${itemRe} 的项，可选：${texts.join('/')}`,
      );
    }
    clickedText = ((await target.textContent()) ?? '').trim();
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

/** 弹层内点确认：primary 优先，文本正则兜底 */
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
    await btn.click();
  }
  await page.waitForTimeout(1500);
}

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

async function waitSpin(dlg) {
  try {
    await dlg
      .locator('.ant-spin-spinning')
      .waitFor({ state: 'hidden', timeout: 10_000 });
  } catch {
    // 没有 Spin 时不阻塞
  }
}

/** show-search 下拉：点开 → 输入关键字 → 点第一个匹配项 */
async function searchSelect(selectLoc, keyword, waitMs = 1500) {
  await selectLoc.click();
  await page.waitForTimeout(600);
  const input = selectLoc.locator('input');
  if ((await input.count()) > 0) {
    await input.fill(keyword);
  }
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

/**
 * 弹层内日期选择器：antd 输入框是 readonly，只能点开面板选日期。
 * 面板单元格带 title="YYYY-MM-DD"，直接按目标日期点击。
 */
async function fillDatePicker(dlg, dateStr) {
  const picker = dlg.locator('.ant-picker').first();
  await picker.click();
  await page.waitForTimeout(600);
  const cell = page
    .locator('.ant-picker-dropdown:not(.ant-picker-dropdown-hidden) [title]')
    .filter({ hasText: dateStr })
    .last();
  try {
    await cell.waitFor({ state: 'visible', timeout: 5000 });
    await cell.click();
  } catch {
    // 目标日期不在当前视月（例如跨月），回退到面板上「今天」单元格
    const today = page
      .locator(
        `.ant-picker-dropdown:not(.ant-picker-dropdown-hidden) [title="${dateStr}"]`,
      )
      .first();
    if ((await today.count()) === 0) {
      await dumpDialogs(`datepicker:${dateStr}`);
      throw new Error(`日期面板中找不到 ${dateStr}`);
    }
    await today.click();
  }
  await page.waitForTimeout(500);
}

// ---------- L0 API 预检 ----------
// 优先：已完成且无对账单的订单（完整 L→O）。
// 兜底：上轮半途留下的 CONFIRMED 且无发票的对账单（跳过 L，从 M 续跑）。
console.log('\n--- 预检 ---');
let TARGET_PO = null;
let RESUME_RECON = null;
let RECON_NO = '';
let PAYMENT_NO = '';
let SETTLEMENT_NO = '';
try {
  const loginRes = await fetch(`${API}/api/v1/auth/login`, {
    body: JSON.stringify({ password: PASSWORD, username: USER }),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
  });
  const { access_token: token } = await loginRes.json();
  const get = async (path) => {
    const res = await fetch(`${API}/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.json();
  };

  const recons = [];
  let reconTotal = 0;
  for (let p = 1; recons.length < reconTotal || p === 1; p += 1) {
    const r = await get(`/finance/reconciliations?page=${p}&page_size=100`);
    reconTotal = r.total;
    recons.push(...r.items);
    if (p > 10) break;
  }
  const reconPos = new Set(recons.map((i) => i.po_id));

  let poPage = 1;
  let poTotal = 0;
  while (poPage === 1 || (poPage - 1) * 100 < poTotal) {
    const r = await get(
      `/purchase-orders?page=${poPage}&page_size=100&status=COMPLETED`,
    );
    poTotal = r.total;
    const free = r.items.find((o) => !reconPos.has(o.id));
    if (free) {
      TARGET_PO = free;
      break;
    }
    poPage += 1;
    if (poPage > 10) break;
  }

  if (TARGET_PO) {
    record(
      'L0 预检：找到已完成且无对账单的订单',
      true,
      `${TARGET_PO.po_no}（${TARGET_PO.order_amount}）`,
    );
  } else {
    // 续跑候选：CONFIRMED 或 DISPUTED（DISPUTED 可录发票，付款/结算前先确认回来），
    // 且有效发票（DRAFT/SUBMITTED/VERIFIED）未超应付总额。
    // REJECTED/VOIDED 发票不占额度，允许在被驳回的发票后继续录入。
    const candidates = recons.filter((i) =>
      ['CONFIRMED', 'DISPUTED'].includes(i.status),
    );
    for (const recon of candidates.slice(0, 15)) {
      const invs = await get(
        `/finance/invoices?page=1&page_size=100&reconciliation_id=${recon.id}`,
      );
      const used = (invs.items ?? [])
        .filter((i2) => ['DRAFT', 'SUBMITTED', 'VERIFIED'].includes(i2.status))
        .reduce((sum, i2) => sum + Number.parseFloat(i2.amount_incl_tax), 0);
      if (used + 0.01 < Number.parseFloat(recon.total_amount)) {
        RESUME_RECON = recon;
        break;
      }
    }
    if (RESUME_RECON) {
      record(
        'L0 预检：无可用订单，复用未走完的对账单续跑',
        true,
        `${RESUME_RECON.reconciliation_no}（状态 ${RESUME_RECON.status}，跳过创建，从续接处继续）`,
      );
    } else {
      record(
        'L0 预检：可用订单/续跑对账单',
        false,
        '演示数据已耗尽：请用 flow-test 走出新 COMPLETED 订单，或清理测试对账单',
      );
      throw new Error('没有可用的财务链起点');
    }
  }
} catch (e) {
  if (!TARGET_PO && !RESUME_RECON) throw e;
}

const TOTAL = Number.parseFloat(
  (TARGET_PO ?? RESUME_RECON)?.total_amount ??
    TARGET_PO?.order_amount ??
    '0',
);

await login();
record('登录成功', true, page.url());

// ============================================================
// L. 财务对账：创建 → 争议 → 重新确认（续跑时跳过）
// ============================================================
console.log('\n--- L. 财务对账 ---');
if (RESUME_RECON) {
  RECON_NO = RESUME_RECON.reconciliation_no;
  record('L1-L3 跳过（复用续跑对账单）', true, RECON_NO);
  // DISPUTED 状态下发票可录，但付款/结算要求 CONFIRMED——先确认回来
  if (RESUME_RECON.status === 'DISPUTED') {
    await gotoPage('/finance/reconciliations');
    await rowAction(RECON_NO, /确认对账/, '确认对账单');
    await clickConfirm('确认对账单');
    await page.waitForTimeout(2000);
    record(
      'L4 争议态重新确认 → 已确认',
      (await row(RECON_NO).getByText('已确认').count()) > 0,
    );
  }
} else {
  await gotoPage('/finance/reconciliations');
  await page.getByRole('button', { name: /创建对账单/ }).click();
  await page.waitForTimeout(2000);
  {
    const dlg = dialog('创建对账单');
    await waitSpin(dlg);
    const picked = await searchSelect(
      dlg.locator('.ant-select').first(),
      TARGET_PO.po_no,
    );
    await clickConfirm('创建对账单');
    const closed = await waitDialogClosed('创建对账单');
    record(
      'L1 创建对账单（关联目标订单）',
      closed && Boolean(captured.recon),
      `${picked.slice(0, 40)} → ${captured.recon?.reconciliation_no ?? ''}`,
    );
  }
  RECON_NO = captured.recon?.reconciliation_no ?? '';
  if (!RECON_NO) throw new Error('未捕获对账单号，中止');
  if (!(await waitForRow(RECON_NO))) throw new Error('对账单未出现在列表');

  // 争议（必填原因）→ DISPUTED
  await rowAction(RECON_NO, /发起争议/, '发起对账争议');
  await fillDialogTextarea('发起对账争议', '财务写路径测试：金额争议');
  await clickConfirm('发起对账争议');
  await page.waitForTimeout(2000);
  record(
    'L2 发起争议 → 有争议',
    writes.some((w) => w.includes('/dispute') && w.startsWith('200')) &&
      (await row(RECON_NO).getByText('有争议').count()) > 0,
  );

  // 重新确认 → CONFIRMED
  await rowAction(RECON_NO, /确认对账/, '确认对账单');
  await clickConfirm('确认对账单');
  await page.waitForTimeout(2000);
  record(
    'L3 争议后可重新确认 → 已确认',
    (await row(RECON_NO).getByText('已确认').count()) > 0,
  );
  await page.screenshot({ path: `${OUT}/finance-L-confirmed.png` });
}

// ============================================================
// M. 发票：录入 → 提交核验 → 核验
// ============================================================
console.log('\n--- M. 发票 ---');
await gotoPage('/finance/invoices');
await page.getByRole('button', { name: /录入发票/ }).click();
await page.waitForTimeout(2000);
{
  const dlg = dialog('录入发票');
  await waitSpin(dlg);
  // 对账单下拉按单号搜索（label 含单号）
  const picked = await searchSelect(
    dlg.locator('.ant-select').first(),
    RECON_NO,
    2000,
  );
  await dlg.locator('input[placeholder="发票号码"]').fill(INVOICE_NUMBER);
  await fillDatePicker(dlg, TODAY);
  // 价税三项全填，规避 change 事件时序问题
  const numbers = dlg.locator('.ant-input-number-input');
  await numbers.nth(0).fill(TOTAL.toFixed(2));
  await numbers.nth(1).fill('0');
  await numbers.nth(2).fill(TOTAL.toFixed(2));
  await clickConfirm('录入发票');
  const closed = await waitDialogClosed('录入发票');
  record(
    'M1 录入发票（价税=订单全额）',
    closed && Boolean(captured.invoice),
    `${picked.slice(0, 40)} → ${captured.invoice?.invoice_no ?? ''}`,
  );
}
if (!(await waitForRow(INVOICE_NUMBER))) {
  throw new Error('发票未出现在列表，中止');
}

await rowAction(INVOICE_NUMBER, /提交核验/, '提交发票核验');
await clickConfirm('提交发票核验');
await page.waitForTimeout(2000);
record(
  'M2 提交核验 → 待核验',
  (await row(INVOICE_NUMBER).getByText('待核验').count()) > 0,
);

await rowAction(INVOICE_NUMBER, /核验(?!通过)/, '核验发票');
await clickConfirm('核验发票');
await page.waitForTimeout(2000);
record(
  'M3 核验通过 → 已核验',
  (await row(INVOICE_NUMBER).getByText('已核验').count()) > 0,
);
await page.screenshot({ path: `${OUT}/finance-M-invoice-verified.png` });

// ============================================================
// N. 付款：发起 → 审批 → 登记付款
// ============================================================
console.log('\n--- N. 付款 ---');
await gotoPage('/finance/payments');
await page.getByRole('button', { name: /发起付款/ }).click();
await page.waitForTimeout(2000);
{
  const dlg = dialog('发起付款申请');
  await waitSpin(dlg);
  await searchSelect(dlg.locator('.ant-select').first(), RECON_NO, 2000);
  await dlg.locator('.ant-input-number-input').first().fill(TOTAL.toFixed(2));
  await clickConfirm('发起付款申请');
  const closed = await waitDialogClosed('发起付款申请');
  record(
    'N1 发起付款（全额）',
    closed && Boolean(captured.payment),
    captured.payment?.payment_no ?? '',
  );
}
PAYMENT_NO = captured.payment?.payment_no ?? '';
if (!PAYMENT_NO) throw new Error('未捕获付款单号，中止');
if (!(await waitForRow(PAYMENT_NO))) throw new Error('付款单未出现在列表');

await rowAction(PAYMENT_NO, /审批通过/, '审批付款申请');
await clickConfirm('审批付款申请');
await page.waitForTimeout(2000);
record(
  'N2 审批通过 → 已批准',
  (await row(PAYMENT_NO).getByText('已批准').count()) > 0,
);

// 登记付款：流水号必填
await rowAction(PAYMENT_NO, /登记付款/, '登记实际付款');
{
  const dlg = dialog('登记实际付款');
  await dlg.locator('input[placeholder*="银行流水号"]').fill(TXN_REF);
  await clickConfirm('登记实际付款');
}
await page.waitForTimeout(2000);
record(
  'N3 登记付款（流水号）→ 已付款',
  (await row(PAYMENT_NO).getByText('已付款').count()) > 0 &&
    writes.some((w) => w.includes('/paid') && w.startsWith('200')),
  TXN_REF,
);
await page.screenshot({ path: `${OUT}/finance-N-paid.png` });

// ============================================================
// O. 结算：创建 → 确认（对账单关闭）
// ============================================================
console.log('\n--- O. 采购结算 ---');
await gotoPage('/finance/settlements');
await page.getByRole('button', { name: /创建结算单/ }).click();
await page.waitForTimeout(2000);
{
  const dlg = dialog('创建结算单');
  await waitSpin(dlg);
  await searchSelect(dlg.locator('.ant-select').first(), RECON_NO, 2000);
  await clickConfirm('创建结算单');
  const closed = await waitDialogClosed('创建结算单');
  record(
    'O1 创建结算单（已足额付款）',
    closed && Boolean(captured.settlement),
    captured.settlement?.settlement_no ?? '',
  );
}
SETTLEMENT_NO = captured.settlement?.settlement_no ?? '';
if (!SETTLEMENT_NO) throw new Error('未捕获结算单号，中止');
if (!(await waitForRow(SETTLEMENT_NO))) throw new Error('结算单未出现在列表');

await rowAction(SETTLEMENT_NO, /确认结算/, '确认结算单');
await clickConfirm('确认结算单');
await page.waitForTimeout(2000);
record(
  'O2 确认结算 → 已确认',
  (await row(SETTLEMENT_NO).getByText('已确认').count()) > 0,
);

// 对账单应同时关闭
await gotoPage('/finance/reconciliations');
const reconClosed = await waitForRow(RECON_NO);
record(
  'O3 对账单随结算关闭 → 已关闭',
  reconClosed && (await row(RECON_NO).getByText('已关闭').count()) > 0,
  RECON_NO,
);
await page.screenshot({ path: `${OUT}/finance-O-closed.png` });

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
