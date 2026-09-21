/**
 * 数值与日期展示格式化。
 *
 * 后端 `DECIMAL(18, 6)` 以字符串返回（如 `"19.000000"`），
 * 直接渲染会出现大量无意义的小数位，这里统一处理。
 */

/** 判断是否为可格式化的数字字符串 */
function toNumber(value: null | number | string | undefined): null | number {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * 去除数值字符串末尾多余的 0。
 *
 * `"19.000000"` → `"19"`，`"1.250000"` → `"1.25"`。
 * 无法解析时原样返回。
 */
export function trimDecimal(value: null | number | string | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  const text = String(value);
  if (!text.includes('.')) {
    return text;
  }
  const trimmed = text.replace(/\.?0+$/, '');
  return trimmed === '' ? '0' : trimmed;
}

/**
 * 格式化数量：千分位 + 去除末尾多余 0。
 *
 * @param precision 需要保留的最大小数位，默认不限制（仅去除末尾 0）
 */
export function formatQuantity(
  value: null | number | string | undefined,
  precision?: number,
): string {
  const parsed = toNumber(value);
  if (parsed === null) {
    return '-';
  }
  if (precision === undefined) {
    return parsed.toLocaleString('zh-CN', { maximumFractionDigits: 20 });
  }
  return parsed.toLocaleString('zh-CN', {
    maximumFractionDigits: precision,
    minimumFractionDigits: 0,
  });
}

/** 格式化金额，默认保留 2 位小数 */
export function formatAmount(
  value: null | number | string | undefined,
  precision: number = 2,
): string {
  return formatQuantity(value, precision);
}

/** 格式化百分比数值，`12.5` → `12.5%` */
export function formatPercent(
  value: null | number | string | undefined,
  precision: number = 1,
): string {
  const parsed = toNumber(value);
  if (parsed === null) {
    return '-';
  }
  return `${parsed.toFixed(precision)}%`;
}

/** 格式化为 `YYYY-MM-DD`，兼容后端返回的 ISO 时间戳 */
export function formatDate(value?: null | string): string {
  if (!value) {
    return '-';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value).slice(0, 10);
  }
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 格式化为 `YYYY-MM-DD HH:mm` */
export function formatDateTime(value?: null | string): string {
  if (!value) {
    return '-';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 生成请求级幂等键，用于 FIFO 出库等需要 `request_no` 的接口 */
export function buildRequestNo(prefix: string): string {
  const now = new Date();
  const pad = (part: number) => String(part).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${prefix}-${stamp}-${Math.random().toString(36).slice(2, 8)}`;
}
