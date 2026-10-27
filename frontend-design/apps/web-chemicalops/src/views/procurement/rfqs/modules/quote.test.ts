import { createApp, defineComponent, h, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  hooks: {} as any,
  data: { id: 14, rfqNo: 'RFQ-14' },
  confirmation: undefined as any,
  parse: vi.fn(), create: vi.fn(), getRfq: vi.fn(), confirm: vi.fn(),
}));

vi.mock('@vben/access', () => ({ useAccess: () => ({ hasAccessByCodes: () => true }) }));
vi.mock('@vben/common-ui', () => ({ useVbenModal: (hooks: any) => {
  mocks.hooks = hooks;
  return [defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) }), {
    getData: () => mocks.data, lock: vi.fn(), unlock: vi.fn(), close: vi.fn(),
  }];
} }));
vi.mock('#/api', () => ({
  createQuoteApi: mocks.create, getRfqApi: mocks.getRfq, parseQuoteFileApi: mocks.parse,
  getUnitListApi: async () => [{ id: 1, unit_name: 'L', status: 'ACTIVE' }],
}));
vi.mock('#/utils/lookup', () => ({ getSupplierNameMap: async () => new Map([[8, '供应商']]) }));
vi.mock('#/utils/format', () => ({ formatQuantity: (value: unknown) => String(value) }));
vi.mock('antdv-next', () => {
  const wrapper = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
  const control = (kind: string) => defineComponent({
    inheritAttrs: false,
    props: ['value', 'disabled', 'maxlength', 'options'], emits: ['update:value'],
    setup: (props, { emit }) => () => h('input', {
      'data-control': kind, value: props.value ?? '', disabled: props.disabled,
      maxlength: props.maxlength,
      onInput: (event: Event) => emit('update:value', (event.target as HTMLInputElement).value),
    }),
  });
  return {
    Alert: wrapper, Empty: wrapper, Spin: wrapper,
    Button: defineComponent({ setup: (_, { slots, attrs }) => () => h('button', attrs, slots.default?.()) }),
    Input: control('Input'), InputNumber: control('InputNumber'), Select: control('Select'), DatePicker: control('DatePicker'),
    Table: defineComponent({ props: ['dataSource'], setup: (props) => () => h('pre', { 'data-rows': '' }, JSON.stringify(props.dataSource)) }),
    Modal: { confirm: (options: any) => {
      mocks.confirm(options); mocks.confirmation = options;
      return { destroy: vi.fn(), update: vi.fn() };
    } },
    message: { success: vi.fn(), warning: vi.fn() },
  };
});

import Quote from './quote.vue';

let app: ReturnType<typeof createApp>;
let host: HTMLDivElement;
const settle = async () => { await new Promise((resolve) => setTimeout(resolve, 0)); await nextTick(); };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function candidate(fileId = 1) {
  return { file_id: fileId, file_name: `${fileId}.csv`, currency_code: 'CNY', evidence: [], warnings: [],
    items: [{ rfq_item_id: 31, unit_name: 'L', quoted_quantity: '10', unit_price: '12.5', tax_rate: '13', tax_included: false }] };
}
async function upload() {
  const input = host.querySelector<HTMLInputElement>('input[type=file]')!;
  Object.defineProperty(input, 'files', { configurable: true, value: [new File(['quote'], 'quote.csv')] });
  input.dispatchEvent(new Event('change', { bubbles: true }));
  await settle();
}
const rows = () => JSON.parse(host.querySelector('[data-rows]')!.textContent!);

beforeEach(async () => {
  vi.clearAllMocks(); mocks.confirmation = undefined;
  mocks.getRfq.mockResolvedValue({ suppliers: [{ supplier_id: 8 }],
    items: [{ id: 31, requested_name: '乙醇', quantity: '10', unit_id: 1 }] });
  mocks.data = { id: 14, rfqNo: 'RFQ-14' };
  host = document.createElement('div'); document.body.append(host);
  app = createApp(Quote); app.mount(host);
  await mocks.hooks.onOpenChange(true); await settle();
});
afterEach(() => { app.unmount(); host.remove(); });

describe('quote import lifecycle', () => {
  it('cancels replacement and preserves the original form after a failed confirmed import', async () => {
    mocks.parse.mockResolvedValueOnce(candidate()); await upload();
    await upload();
    expect(mocks.parse).toHaveBeenCalledTimes(1);
    mocks.confirmation.onCancel(); await settle();
    expect(rows()[0].unit_price).toBe(12.5);
    mocks.parse.mockRejectedValueOnce(new Error('parse failed'));
    await upload(); await mocks.confirmation.onOk(); await settle();
    expect(rows()[0].unit_price).toBe(12.5);
    expect(host.textContent).toContain('1.csv');
    expect(host.querySelector<HTMLButtonElement>('button')!.disabled).toBe(false);
  });

  it('ignores parsing responses after closing and reopening for a different RFQ', async () => {
    const pending = deferred<ReturnType<typeof candidate>>(); mocks.parse.mockReturnValueOnce(pending.promise);
    await upload();
    await mocks.hooks.onOpenChange(false);
    mocks.data = { id: 15, rfqNo: 'RFQ-15' };
    await mocks.hooks.onOpenChange(true);
    pending.resolve(candidate()); await settle();
    expect(rows()[0].unit_price).toBeUndefined();
    expect(host.textContent).not.toContain('1.csv');
    expect(host.querySelector<HTMLButtonElement>('button')!.disabled).toBe(false);
  });

  it('ignores an older inquiry load and keeps the current inquiry rows', async () => {
    const pending = deferred<any>(); mocks.getRfq.mockReturnValueOnce(pending.promise);
    const opening = mocks.hooks.onOpenChange(true);
    await mocks.hooks.onOpenChange(false);
    mocks.getRfq.mockResolvedValueOnce({ suppliers: [], items: [{ id: 99, requested_name: '甲醇', quantity: '20', unit_id: 1 }] });
    await mocks.hooks.onOpenChange(true);
    pending.resolve({ suppliers: [], items: [{ id: 88, requested_name: '旧物料', quantity: '1', unit_id: 1 }] });
    await opening; await settle();
    expect(rows()[0].rfq_item_id).toBe(99);
  });

  it('blocks duplicate uploads, field edits and submit while parsing', async () => {
    const pending = deferred<ReturnType<typeof candidate>>(); mocks.parse.mockReturnValueOnce(pending.promise);
    await upload(); await upload();
    expect(mocks.parse).toHaveBeenCalledTimes(1);
    expect([...host.querySelectorAll<HTMLInputElement>('input[data-control]')].every((input) => input.disabled)).toBe(true);
    await mocks.hooks.onConfirm(); expect(mocks.create).not.toHaveBeenCalled();
    pending.resolve(candidate()); await settle();
    expect(host.querySelector<HTMLInputElement>('input[data-control]')!.disabled).toBe(false);
  });
});
