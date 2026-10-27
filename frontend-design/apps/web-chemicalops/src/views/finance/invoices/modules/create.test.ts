import { createApp, defineComponent, h, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ hooks: {} as any, confirmation: undefined as any, parse: vi.fn(), create: vi.fn() }));
vi.mock('@vben/access', () => ({ useAccess: () => ({ hasAccessByCodes: () => true }) }));
vi.mock('@vben/common-ui', () => ({ useVbenModal: (hooks: any) => {
  mocks.hooks = hooks;
  return [defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }), { lock: vi.fn(), unlock: vi.fn(), close: vi.fn() }];
} }));
vi.mock('#/api', () => ({ createInvoiceApi: mocks.create, parseInvoiceFileApi: mocks.parse,
  getReconciliationListApi: async () => ({ items: [{ id: 8, status: 'CONFIRMED', reconciliation_no: 'FR-8', total_amount: '500', currency_code: 'CNY' }] }) }));
vi.mock('#/utils/format', () => ({ formatAmount: (v: unknown) => String(v), formatDate: (v: unknown) => String(v) }));
vi.mock('antdv-next', () => {
  const wrapper = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
  const control = (kind: string) => defineComponent({ inheritAttrs: false, props: ['value', 'disabled', 'format'], emits: ['update:value'],
    setup: (props, { emit }) => () => h('input', { 'data-control': kind, 'data-format': props.format, value: props.value ?? '', disabled: props.disabled,
      onInput: (event: Event) => { const value = (event.target as HTMLInputElement).value; emit('update:value', kind === 'Select' || kind === 'InputNumber' ? Number(value) : value); } }) });
  return { Alert: wrapper, Empty: wrapper, Spin: wrapper, Input: Object.assign(control('Input'), { TextArea: control('TextArea') }),
    InputNumber: control('InputNumber'), Select: control('Select'), DatePicker: control('DatePicker'),
    Button: defineComponent({ setup: (_, { slots, attrs }) => () => h('button', attrs, slots.default?.()) }),
    Modal: { confirm: (options: any) => { mocks.confirmation = options; } }, message: { success: vi.fn(), warning: vi.fn() } };
});
import Create from './create.vue';
let app: ReturnType<typeof createApp>;
let host: HTMLDivElement;
const settle = async () => { await new Promise((resolve) => setTimeout(resolve, 0)); await nextTick(); };
const candidate = { file_id: 31, file_name: '发票.txt', invoice_code: null, invoice_number: '000123', invoice_date: '2026-10-20', amount_excl_tax: '100', tax_amount: '13', amount_incl_tax: '113', warnings: [], evidence: [{ field: 'invoice_number', value: '000123', source_location: '正文', source_quote: '发票号码：000123' }] };
function input(selector: string, value: string) { const el = host.querySelector<HTMLInputElement>(selector)!; el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); }
async function upload() { const el = host.querySelector<HTMLInputElement>('input[type=file]')!; Object.defineProperty(el, 'files', { configurable: true, value: [new File(['invoice'], 'invoice.txt')] }); el.dispatchEvent(new Event('change', { bubbles: true })); await settle(); }
beforeEach(async () => { vi.clearAllMocks(); mocks.confirmation = undefined; host = document.createElement('div'); document.body.append(host); app = createApp(Create); app.mount(host); await mocks.hooks.onOpenChange(true); input('[data-control=Select]', '8'); await settle(); });
afterEach(() => { app.unmount(); host.remove(); });
describe('发票候选人工复核', () => {
  it('日期选择器使用原生日期格式配置', () => {
    expect(host.querySelector('[data-control=DatePicker]')?.getAttribute('data-format')).toBe('YYYY-MM-DD');
  });
  it('先展示证据，确认带入后才能提交草稿', async () => {
    mocks.parse.mockResolvedValueOnce(candidate); await upload();
    expect(host.textContent).toContain('发票号码：000123');
    expect(host.querySelector<HTMLInputElement>('[data-control=Input]')!.value).toBe('');
    await mocks.hooks.onConfirm(); expect(mocks.create).not.toHaveBeenCalled();
    const button = [...host.querySelectorAll('button')].find((el) => el.textContent?.includes('带入候选字段'))!;
    button.click(); expect(mocks.confirmation).toBeTruthy();
    await mocks.confirmation.onOk(); await settle();
    expect(host.querySelector<HTMLInputElement>('[data-control=Input]')!.value).toBe('000123');
    mocks.create.mockResolvedValueOnce({}); await mocks.hooks.onConfirm();
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ source_file_id: 31, invoice_number: '000123', tax_amount: 13 }));
  });
  it('关闭弹窗后丢弃迟到的解析结果', async () => {
    let resolve!: (value: typeof candidate) => void;
    mocks.parse.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    await upload(); await mocks.hooks.onConfirm(); expect(mocks.create).not.toHaveBeenCalled();
    await mocks.hooks.onOpenChange(false); await mocks.hooks.onOpenChange(true);
    resolve(candidate); await settle();
    expect(host.textContent).not.toContain('发票号码：000123');
  });
});
