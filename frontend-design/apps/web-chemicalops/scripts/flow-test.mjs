/**
 * 写路径全流程实测：采购申请 → 询价 → 报价比价 → 采购订单 → 到货收货 →
 * 质量验收 → 库存入库 → 冻结/解冻。
 *
 * 覆盖（对应 docs/新版前端说明.md「尚未验证的部分」）：
 *   A 采购申请：新建 → 提交 → 驳回 → 重新提交 → 审批通过 → （另单）取消
 *   B 询价：新建（关联已批申请 + 产品）→ 发送 → 录入报价 → 生成比价
 *        → 确认中选 → 依据中选报价生成订单
 *   C 采购订单：提交审批 → 审批通过 → 正式下单
 *   D 到货：登记计划 → 收货（故意短交 1 件，验证短交预警）
 *   E 质量：创建验收 → 点「录入结果」→ 选「合格」→ 确认
 *   F 库存：入库 → 冻结 → 解冻
 *
 * 交互约定（实测踩坑总结）：
 * - Vben Modal/Drawer 底层是 reka-ui Dialog（role="dialog"），
 *   antd Modal.confirm 也是 role="dialog"，统一用 [role="dialog"] 圈定。
 * - 确认按钮一律在**目标弹层内部**查找，绝不做页面级 .last()——
 *   否则会点到残留弹层的同名按钮（曾把「提交」误点成取消流程的确认）。
 * - 行操作菜单 portal 到 body，点击前先 Escape 关掉可能残留的下拉，
 *   点击后打印菜单全部条目，便于失败时定位。
 *
 * 前置：后端 8888 与前端 3000 均在运行。
 * 用法：
 *   $env:SMOKE_PASSWORD='你的密码'; node scripts/flow-test.mjs
 *   （密码只从环境变量读取，不写入仓库）
 */
import { mkdirSync } from 'node:fs';

import { chromium } from 'playwright';

const BASE = process.env.SMOKE_BASE ?? 'http://localhost:3000';
const USER = process.env.SMOKE_USER ?? 'system_admin';
const PASSWORD = process.env.SMOKE_PASSWORD;
if (!PASSWORD) {
  console.error(
    '请通过环境变量 SMOKE_PASSWORD 提供登录密码（不写入仓库）。\n' +
      "PowerShell: $env:SMOKE_PASSWORD='***'; node scripts/flow-test.mjs",
  );
  process.exit(1);
}
const OUT = 'C:/self_project/ChemicalOps/.cache/shots';

mkdirSync(OUT, { recursive: true });

const stamp = Date.now().toString().slice(-8);
const PURPOSE = `全流程测试申请${stamp}`;
const CANCEL_PURPOSE = `待取消申请${stamp}`;
const MATERIAL = `全流程物料${stamp}`;
const QTY = 10;

const steps = [];
function record(name, ok, detail = '') {
  steps.push({ name, ok });
  console.log(`${ok ? ' ok ' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

const writes = [];
/** 关键写接口的最新响应体，用于拿到 po_no / delivery_no 等 */
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
    if (path === '/purchase-requests') captured.request = json;
    if (path === '/rfqs') captured.rfq = json;
    if (path === '/purchase-orders') captured.order = json;
    if (path === '/deliveries') captured.delivery = json;
    if (path === '/quality-acceptances') captured.acceptance = json;
    if (path.endsWith('/receive')) captured.receive = json;
    if (path === '/inventory/inbounds') captured.inbound = json;
  } catch {
    // 非 JSON 响应忽略
  }
});

// ---------- 通用工具 ----------

const CONFIRM_NAME = /^(确\s*认|确\s*定|提\s*交|发\s*送|确认下单|保\s*存)$/;

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

async function search(keyword) {
  await page.fill('input[name="keyword"]', keyword);
  await page.getByRole('button', { name: /搜\s*索/ }).click();
  await page.waitForTimeout(2500);
}

function row(text) {
  return page.locator('tr', { hasText: text }).first();
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
 * 打开某行的操作下拉并点击菜单项。
 * 点击前 Escape 清掉可能残留的下拉；点击后打印菜单全部条目。
 * 传 expectedTitle 时校验目标弹层确实打开。
 */
/**
 * 点击列表行的操作。
 * 两种列模式：
 * - 内联按钮（到货/库存/质量等）：目标按钮直接在行内，点了就触发动作
 * - 下拉菜单（采购申请/询价/订单，renderMode: 'menu'）：行内只有「更多」，
 *   需要先展开下拉再点菜单项
 */
async function rowAction(rowText, itemRe, expectedTitle = null) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const r = row(rowText);
  const rowCount = await r.count();
  if (rowCount === 0) {
    await dumpDialogs(`row-missing:${rowText.slice(0, 20)}`);
    throw new Error(`列表里找不到「${rowText}」所在的行`);
  }

  // 优先找行内直接匹配的按钮（内联模式）
  const inlineBtn = r
    .locator('.table-operations button')
    .filter({ hasText: itemRe })
    .first();
  const hasInline = (await inlineBtn.count()) > 0;
  console.log(
    `       [rowAction] 目标="${rowText.slice(0, 24)}" 模式=${hasInline ? '内联' : '下拉'}`,
  );

  let clickedText;
  if (hasInline) {
    clickedText = ((await inlineBtn.textContent()) ?? '').trim();
    await inlineBtn.click();
  } else {
    const opBtn = r.locator('.table-operations button').last();
    if ((await r.locator('.table-operations button').count()) === 0) {
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
 * 在指定弹层内点主按钮。必须传 titleRe 圈定弹层——
 * 页面级查找会误点残留弹层的同名按钮。
 */
async function clickConfirm(titleRe) {
  const dlg = dialog(titleRe);
  const count = await dlg.count();
  if (count === 0) {
    await dumpDialogs(`confirm-missing:${titleRe}`);
    throw new Error(`找不到弹层：${titleRe}`);
  }
  const allDialogs = await page
    .locator('[role="dialog"]:visible')
    .count();
  if (allDialogs > 1) {
    console.log(`       [warn] 可见弹层 ${allDialogs} 个，已限定「${titleRe}」`);
  }
  await dlg.getByRole('button', { name: CONFIRM_NAME }).last().click();
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

/**
 * 等待弹层内的 Spin 加载结束。
 * antd Spin 加载中会给内容加 pointer-events:none，过早点下拉会被遮罩吞掉。
 */
async function waitSpin(dlg) {
  try {
    await dlg
      .locator('.ant-spin-spinning')
      .waitFor({ state: 'hidden', timeout: 10_000 });
  } catch {
    // 没有 Spin 或一直不出现时不阻塞
  }
}

// ---------- 登录 ----------
await login();
record('登录成功', true, page.url());

// ============================================================
// A. 采购申请：新建 → 提交 → 驳回 → 重提 → 通过；另一单取消
// ============================================================
await gotoPage('/procurement/requests');

await page.getByRole('button', { name: '新建采购申请' }).click();
await page.waitForTimeout(2000);
await page.fill('textarea[name="purpose"]', PURPOSE);

const prRow1 = dialog('新建采购申请').locator('.ant-table-tbody tr').first();
await prRow1.locator('input[placeholder="物料名称"]').fill(MATERIAL);
await prRow1.locator('.ant-input-number-input').first().fill(String(QTY));
await prRow1.locator('.ant-select').nth(1).click();
await page.waitForTimeout(900);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first()
  .click();
await page.waitForTimeout(400);
await page.keyboard.press('Escape');

await clickConfirm('新建采购申请');
const prDrawerClosed = await waitDialogClosed('新建采购申请');
await page.waitForTimeout(1500);
await search(PURPOSE);
const prCreated = (await row(PURPOSE).count()) > 0;
record(
  'A1 新建采购申请',
  prDrawerClosed && prCreated,
  `抽屉关闭=${prDrawerClosed} 列表可见=${prCreated}`,
);

// 提交
await rowAction(PURPOSE, /提\s*交(?!审批)/, '提交采购申请');
await clickConfirm('提交采购申请');
await page.waitForTimeout(2000);
const afterSubmit1 = (await row(PURPOSE).getByText(/审批中|已提交/).count()) > 0;
record('A2 提交后进入审批', afterSubmit1);

// 驳回（必须填意见）
await rowAction(PURPOSE, /驳\s*回/, '驳回采购申请');
await fillDialogTextarea('驳回采购申请', '流程测试驳回意见');
await clickConfirm('驳回采购申请');
await page.waitForTimeout(2000);
const afterReject = (await row(PURPOSE).getByText('已驳回').count()) > 0;
record('A3 驳回后状态=已驳回', afterReject);

// 重新提交
await rowAction(PURPOSE, /提\s*交(?!审批)/, '提交采购申请');
await clickConfirm('提交采购申请');
await page.waitForTimeout(2000);
const afterSubmit2 = (await row(PURPOSE).getByText(/审批中|已提交/).count()) > 0;
record('A4 驳回后可重新提交', afterSubmit2);

// 审批通过（意见选填）
await rowAction(PURPOSE, /审批通过/, '审批通过采购申请');
await clickConfirm('审批通过采购申请');
await page.waitForTimeout(2000);
const afterApprove = (await row(PURPOSE).getByText('已批准').count()) > 0;
record('A5 审批通过后状态=已批准', afterApprove);
// 立刻记下单号：A6 另建的取消单会覆盖 captured.request
const REQ_NO = captured.request?.request_no ?? '';
await page.screenshot({ path: `${OUT}/flow-A-request-approved.png` });

// 另建一单测取消
await page.getByRole('button', { name: '新建采购申请' }).click();
await page.waitForTimeout(2000);
await page.fill('textarea[name="purpose"]', CANCEL_PURPOSE);
const prRow2 = dialog('新建采购申请').locator('.ant-table-tbody tr').first();
await prRow2.locator('input[placeholder="物料名称"]').fill(`取消物料${stamp}`);
await prRow2.locator('.ant-input-number-input').first().fill('1');
await prRow2.locator('.ant-select').nth(1).click();
await page.waitForTimeout(900);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first()
  .click();
await page.keyboard.press('Escape');
await clickConfirm('新建采购申请');
await page.waitForTimeout(1500);
await search(CANCEL_PURPOSE);
await rowAction(CANCEL_PURPOSE, /取\s*消/, '取消采购申请');
writes.length = 0;
await fillDialogTextarea('取消采购申请', '流程测试取消');
await clickConfirm('取消采购申请');
await page.waitForTimeout(2000);
const cancelReqSent = writes.some((w) => w.includes('/cancel'));
const afterCancel = (await row(CANCEL_PURPOSE).getByText('已取消').count()) > 0;
record(
  'A6 草稿可取消',
  afterCancel && cancelReqSent,
  `cancel请求=${cancelReqSent}`,
);

// ============================================================
// B. 询价：新建（关联 A5 的申请）→ 发送 → 录报价 → 比价 → 中选 → 生成订单
// ============================================================
await gotoPage('/procurement/rfqs');
await page.getByRole('button', { name: '新建询价单' }).click();
await page.waitForTimeout(2500);

const rfqDrawer = dialog('新建询价单');

// 来源采购申请：APPROVED 列表按 id 倒序，刚批准的就是第一条
await rfqDrawer.locator('.ant-select').first().click();
await page.waitForTimeout(500);
const srcOption = page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first();
try {
  await srcOption.waitFor({ state: 'visible', timeout: 10_000 });
} catch {
  await dumpDialogs('B0-options-never-loaded');
}
const srcPicked = (await srcOption.count()) > 0;
const SRC_LABEL = srcPicked ? ((await srcOption.textContent()) ?? '').trim() : '';
const srcIsOurs = REQ_NO ? SRC_LABEL.includes(REQ_NO) : true;
if (srcPicked) await srcOption.click();
await page.keyboard.press('Escape');
record(
  'B0 关联到刚批准的采购申请',
  srcPicked && srcIsOurs,
  SRC_LABEL.slice(0, 60),
);
if (!srcPicked) throw new Error('未关联来源申请，后续无法生成订单，中止');

// 明细行：物料 + 关联产品（生成订单的硬性要求）+ 数量 + 单位
const rfqRow = rfqDrawer.locator('.ant-table-tbody tr').first();
await rfqRow.locator('input[placeholder="物料名称"]').fill(MATERIAL);
await rfqRow.locator('.ant-input-number-input').first().fill(String(QTY));

await rfqRow.locator('.ant-select').nth(0).click();
await page.waitForTimeout(1200);
const productOpt = page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first();
const PRODUCT_NAME = ((await productOpt.textContent()) ?? '').trim();
await productOpt.click();
await page.waitForTimeout(400);

await rfqRow.locator('.ant-select').nth(1).click();
await page.waitForTimeout(900);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first()
  .click();
await page.keyboard.press('Escape');
record('B1 询价明细已填写', true, `关联产品=${PRODUCT_NAME}`);

// 邀请 2 家供应商（表单已过滤 ACTIVE）
const supplierSelect = rfqDrawer
  .locator('.ant-select')
  .filter({ hasText: '请选择需要询价的供应商' })
  .first();
await supplierSelect.click();
await page.waitForTimeout(1200);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .nth(0)
  .click();
await page.waitForTimeout(400);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .nth(1)
  .click();
await page.waitForTimeout(400);
await page.keyboard.press('Escape');
record('B2 已邀请 2 家供应商', true);

await clickConfirm('新建询价单');
const rfqDrawerClosed = await waitDialogClosed('新建询价单');
await page.waitForTimeout(1500);

const RFQ_NO = captured.rfq?.rfq_no ?? '';
record('B3 新建询价单', rfqDrawerClosed && Boolean(RFQ_NO), RFQ_NO);
if (!RFQ_NO) throw new Error('未捕获到询价单号，中止');
await search(RFQ_NO);

// 发送
await rowAction(RFQ_NO, /发\s*送询价/, '发送询价单');
await clickConfirm('发送询价单');
await page.waitForTimeout(2000);
const rfqSent = (await row(RFQ_NO).getByText('已发送').count()) > 0;
record('B4 发送后状态=已发送', rfqSent);

// 打开详情 → 录入报价
await rowAction(RFQ_NO, /详情与比价/);
await page.waitForTimeout(2500);
const quoteBtn = dialog(RFQ_NO).getByRole('button', { name: '录入报价' });
const quoteBtnVisible = (await quoteBtn.count()) > 0;
record('B5 详情抽屉有「录入报价」入口', quoteBtnVisible);
if (!quoteBtnVisible) throw new Error('缺少录入报价按钮，后续流程无法继续');

await quoteBtn.click();
await page.waitForTimeout(2500);
const quoteDialog = dialog('录入报价 ·');
await waitSpin(quoteDialog);

await quoteDialog
  .locator('.ant-select')
  .filter({ hasText: '请选择受邀供应商' })
  .first()
  .click();
await page.waitForTimeout(900);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first()
  .click();
await page.waitForTimeout(400);

// 单价列（行内 input-number 顺序：报价数量、单价、税率、交期、最小起订量）
await quoteDialog.locator('.ant-input-number-input').nth(1).fill('19.5');
await clickConfirm('录入报价 ·');
// 标题带「 · 单号」后缀，避免与详情抽屉里的「录入报价」按钮文案混淆
const quoteClosed = await waitDialogClosed('录入报价 ·', 6000);
record('B6 录入报价成功', quoteClosed);

// 生成比价
await dialog(RFQ_NO).getByRole('button', { name: '生成比价' }).click();
await page.waitForTimeout(3000);
const comparisonVisible = (await page.getByText(/比价单：QC/).count()) > 0;
record('B7 生成比价', comparisonVisible);

// 报价比较 tab → 选为中标
await page.getByRole('tab', { name: /报价比较/ }).click();
await page.waitForTimeout(1200);
const selectBtn = page.getByRole('button', { name: '选为中标' }).first();
const selectBtnVisible = (await selectBtn.count()) > 0;
record('B8 比价表可选中标', selectBtnVisible);
if (!selectBtnVisible) throw new Error('比价表缺少「选为中标」按钮');
await selectBtn.click();
await page.waitForTimeout(1000);
await fillDialogTextarea('确认中选', '流程测试：综合评估后中选');
await clickConfirm('确认中选');
await page.waitForTimeout(2500);
const selectedShown = (await page.getByText(/已中选：/).count()) > 0;
record('B9 确认中选', selectedShown);
await page.screenshot({ path: `${OUT}/flow-B-selected.png` });

// 生成订单
const genOrderBtn = dialog(RFQ_NO).getByRole('button', {
  name: '依据中选报价生成采购订单',
});
const genVisible = (await genOrderBtn.count()) > 0;
record('B10 出现「生成采购订单」按钮', genVisible);
if (!genVisible) throw new Error('中选后未出现生成订单按钮');
await genOrderBtn.click();
await page.waitForTimeout(3000);
const PO_NO = captured.order?.po_no ?? '';
record('B11 采购订单草稿已生成', Boolean(PO_NO), PO_NO);
if (!PO_NO) throw new Error('未捕获到采购订单号，中止');

await page.keyboard.press('Escape');
await page.waitForTimeout(800);

// ============================================================
// C. 采购订单：提交 → 审批 → 正式下单
// ============================================================
await gotoPage('/procurement/orders');
await search(PO_NO);

await rowAction(PO_NO, /提\s*交审批/, '提交采购订单审批');
await clickConfirm('提交采购订单审批');
await page.waitForTimeout(2000);
const poApproving = (await row(PO_NO).getByText('审批中').count()) > 0;
record('C1 订单提交后=审批中', poApproving);

await rowAction(PO_NO, /审批通过/, '审批通过');
await clickConfirm('审批通过');
await page.waitForTimeout(2000);
const poApproved = (await row(PO_NO).getByText('已批准').count()) > 0;
record('C2 订单审批通过=已批准', poApproved);

await rowAction(PO_NO, /正式下单/, '正式下单');
await clickConfirm('正式下单');
await page.waitForTimeout(2500);
const poOrdered = (await row(PO_NO).getByText('已下单').count()) > 0;
record('C3 正式下单=已下单', poOrdered);
await page.screenshot({ path: `${OUT}/flow-C-ordered.png` });

// ============================================================
// D. 到货：登记计划 → 短交收货
// ============================================================
await gotoPage('/warehouse/deliveries');
await page.getByRole('button', { name: '登记到货计划' }).click();
await page.waitForTimeout(2000);

const createDeliveryDialog = dialog('登记到货计划');
await waitSpin(createDeliveryDialog); // 等订单选项加载完，否则点击被 Spin 遮罩吞掉

// ORDERED 列表按 id 倒序，刚下单的就是第一条，直接选，不做搜索过滤
//（过滤依赖焦点进入搜索框，时序不稳）
const poSelect = createDeliveryDialog
  .locator('.ant-select')
  .filter({ hasText: '请选择采购订单' })
  .first();
await poSelect.click();
const poOption = page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first();
try {
  await poOption.waitFor({ state: 'visible', timeout: 10_000 });
} catch {
  await dumpDialogs('D1-po-options-never-loaded');
  const dd = await page.evaluate(() =>
    [...document.querySelectorAll('.ant-select-dropdown')].map((d) => ({
      cls: d.className,
      visible: !!(d.offsetWidth || d.offsetHeight),
      text: d.textContent?.slice(0, 120),
    })),
  );
  console.log('       [diag:D1-dropdowns]', JSON.stringify(dd));
  throw new Error('到货计划的订单下拉选项未加载出来');
}
const PO_OPT_LABEL = ((await poOption.textContent()) ?? '').trim();
await poOption.click();
await page.waitForTimeout(2000); // 等明细加载
console.log(`       [D1] 选中订单选项=${PO_OPT_LABEL.slice(0, 50)}`);

const deliveryRow = createDeliveryDialog
  .locator('.ant-table-tbody tr')
  .first();
const deliveryRowVisible = (await deliveryRow.count()) > 0;
record('D1 选中订单后带出明细', deliveryRowVisible);
if (!deliveryRowVisible) throw new Error('到货明细未加载');

await clickConfirm('登记到货计划');
await page.waitForTimeout(2500);
const DL_NO = captured.delivery?.delivery_no ?? '';
record('D2 到货计划登记成功', Boolean(DL_NO), DL_NO);
if (!DL_NO) throw new Error('未捕获到到货单号，中止');
await search(DL_NO);

// 收货：实收 9（计划 10）→ 短交 1
await rowAction(DL_NO, /确认收货/, '确认收货');
await page.waitForTimeout(2500);
const receiveDialog = dialog('确认收货');
await waitSpin(receiveDialog);
await receiveDialog
  .locator('.ant-input-number-input')
  .first()
  .fill(String(QTY - 1));
await page.waitForTimeout(800);
const shortAlert = (await receiveDialog.getByText(/存在短交/).count()) > 0;
record('D3 修改实收后出现短交预警', shortAlert);

await clickConfirm('确认收货');
await page.waitForTimeout(3000);
const receiveOk = captured.receive?.status === 'RECEIVED';
record('D4 收货确认成功', receiveOk, `status=${captured.receive?.status ?? '?'}`);
await page.screenshot({ path: `${OUT}/flow-D-received.png` });

// ============================================================
// E. 质量验收：创建 → 录入合格
// ============================================================
const DELIVERY_ID = captured.delivery?.id;
await gotoPage('/quality/acceptances');
await page.getByRole('button', { name: '创建验收' }).click();
await page.waitForTimeout(2000);
const acceptDialog = dialog('创建质量验收');
await waitSpin(acceptDialog);
await acceptDialog
  .locator('.ant-select')
  .filter({ hasText: '请选择待送检的到货单' })
  .first()
  .click();
// RECEIVED 列表按 id 倒序，本流程刚收货的到货单就是第一条；不做搜索过滤
const acceptOpt = page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first();
try {
  await acceptOpt.waitFor({ state: 'visible', timeout: 10_000 });
} catch {
  await dumpDialogs('E1-options-never-loaded');
  throw new Error('送检下拉选项未加载出来');
}
const ACCEPT_LABEL = ((await acceptOpt.textContent()) ?? '').trim();
const acceptIsOurs = ACCEPT_LABEL.includes(DL_NO);
await acceptOpt.click();
await page.keyboard.press('Escape');
record('E1 送检下拉第一条是本流程到货单', acceptIsOurs, ACCEPT_LABEL.slice(0, 50));

await clickConfirm('创建质量验收');
await page.waitForTimeout(2500);
const ACC_NO = captured.acceptance?.acceptance_no ?? '';
record('E2 创建质量验收', Boolean(ACC_NO), ACC_NO);

// 定位本流程到货单对应的验收行；列表按 id 倒序，本流程的就在第一行
let accRow =
  DELIVERY_ID != null
    ? page.locator(`tr:has(td:text-is("${DELIVERY_ID}"))`).first()
    : page.locator('tr', { hasText: ACC_NO }).first();
let resultBtn = accRow.getByRole('button', { name: '录入结果' });
let resultBtnVisible = (await resultBtn.count()) > 0;
if (!resultBtnVisible) {
  const firstRowText = (await page.locator('tbody tr').first().innerText().catch(() => '(无)')).slice(0, 120);
  const totalBtns = await page.getByRole('button', { name: '录入结果' }).count();
  console.log(
    `       [diag:E3] 首行="${firstRowText}" 全页录入结果按钮=${totalBtns}`,
  );
  await page.screenshot({ path: `${OUT}/flow-E3-fail.png` }).catch(() => {});
  // 兜底：新单在第一行，断言行同步切换，避免后续断言还用定位失败的死行
  accRow = page.locator('tbody tr').first();
  resultBtn = accRow.getByRole('button', { name: '录入结果' });
  resultBtnVisible = (await resultBtn.count()) > 0;
}
record('E3 本流程验收单出现「录入结果」', resultBtnVisible);
if (!resultBtnVisible) throw new Error('找不到录入结果按钮');
await resultBtn.click();
await page.waitForTimeout(2000);

const resultDrawer = dialog('录入验收结果');
await resultDrawer
  .locator('.ant-radio-button-wrapper')
  .filter({ hasText: /^合格$/ })
  .first()
  .click();
await page.waitForTimeout(400);
const conclusion = resultDrawer.locator('textarea[name="conclusion"]');
if ((await conclusion.count()) > 0) {
  await conclusion.fill('流程测试：各项指标符合要求');
}
await clickConfirm('录入验收结果');
const resultClosed = await waitDialogClosed('录入验收结果');
await page.waitForTimeout(1500);
// 提交成功后列表会刷新，用验收单号重新定位行再断言结果
const accRowAfter = page.locator('tr', { hasText: ACC_NO }).first();
const passedShown =
  (await accRowAfter.count()) > 0 &&
  (await accRowAfter.getByText('合格', { exact: true }).count()) > 0;
record(
  'E4 录入合格结果',
  resultClosed && passedShown,
  `抽屉关闭=${resultClosed} 行内合格=${passedShown}`,
);
await page.screenshot({ path: `${OUT}/flow-E-quality.png` });

// ============================================================
// F. 库存：入库 → 冻结 → 解冻
// ============================================================
await gotoPage('/warehouse/inventory');
await page.getByRole('button', { name: '库存入库' }).click();
await page.waitForTimeout(2000);

const inboundDialog = dialog('库存入库');
await waitSpin(inboundDialog);
await inboundDialog
  .locator('.ant-select')
  .filter({ hasText: '请选择待入库的到货单' })
  .first()
  .click();
// ACCEPTED 列表按 id 倒序，本流程验收通过的到货单就是第一条
const inboundOpt = page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first();
try {
  await inboundOpt.waitFor({ state: 'visible', timeout: 10_000 });
} catch {
  await dumpDialogs('F1-options-never-loaded');
  throw new Error('入库下拉选项未加载出来');
}
const INBOUND_LABEL = ((await inboundOpt.textContent()) ?? '').trim();
record(
  'F0 入库下拉第一条是本流程到货单',
  INBOUND_LABEL.includes(DL_NO),
  INBOUND_LABEL.slice(0, 50),
);
await inboundOpt.click();
await page.waitForTimeout(400);

await inboundDialog
  .locator('.ant-select')
  .filter({ hasText: '请选择仓库' })
  .first()
  .click();
await page.waitForTimeout(900);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first()
  .click();
await page.waitForTimeout(800);

await inboundDialog
  .locator('.ant-select')
  .filter({ hasText: '请选择库位' })
  .first()
  .click();
await page.waitForTimeout(900);
await page
  .locator('.ant-select-dropdown:visible .ant-select-item-option')
  .first()
  .click();
await page.waitForTimeout(400);

await clickConfirm('库存入库');
await page.waitForTimeout(3000);
const inboundCount = Number(captured.inbound?.transaction_count ?? 0);
record('F1 库存入库', inboundCount > 0, `流水=${inboundCount || '?'}`);

// 冻结：按产品筛选（B1 记录的关联产品）
if (PRODUCT_NAME) {
  const productFilter = page
    .locator('.ant-select')
    .filter({ hasText: '全部产品' })
    .first();
  await productFilter.click();
  await page.waitForTimeout(1200);
  await page.keyboard.type(PRODUCT_NAME);
  await page.waitForTimeout(1200);
  const pOpt = page
    .locator('.ant-select-dropdown:visible .ant-select-item-option')
    .first();
  if ((await pOpt.count()) > 0) await pOpt.click();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: /搜\s*索/ }).click();
  await page.waitForTimeout(2500);
}

const targetRow = PRODUCT_NAME
  ? row(PRODUCT_NAME)
  : page.locator('tbody tr').first();
const hasTarget = (await targetRow.count()) > 0;
record('F2 列表定位到本流程库存行', hasTarget, PRODUCT_NAME);
if (hasTarget) {
  await rowAction(PRODUCT_NAME ?? '', /冻\s*结/, '冻结库存');
  await fillDialogTextarea('冻结库存', '流程测试冻结');
  await clickConfirm('冻结库存');
  await page.waitForTimeout(2500);
  const frozenShown = (await targetRow.getByText('冻结', { exact: true }).count()) > 0;
  record('F3 冻结成功', frozenShown);

  await rowAction(PRODUCT_NAME ?? '', /解\s*冻/, '解冻库存');
  await fillDialogTextarea('解冻库存', '流程测试解冻');
  await clickConfirm('解冻库存');
  await page.waitForTimeout(2500);
  const backToAvailable =
    (await targetRow.getByText('可用', { exact: true }).count()) > 0;
  record('F4 解冻成功', backToAvailable);
}
await page.screenshot({ path: `${OUT}/flow-F-inventory.png` });

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
