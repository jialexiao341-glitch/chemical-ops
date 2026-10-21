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

/** 只转换来源明确的时间戳；历史 naive 时间不能猜测为 UTC。 */
function businessTimestamp(value: string): string | undefined {
  if (!/[T ]\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const part = (name: string) => parts.find((item) => item.type === name)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`;
}

/** 显式时区时间转换业务日期，date-only/naive 保持墙上日期。 */
export function formatDate(value?: null | string): string {
  if (!value) return '-';
  return (businessTimestamp(value) ?? value).slice(0, 10);
}

/** 格式化为 YYYY-MM-DD HH:mm；纯日期不添加午夜。 */
export function formatDateTime(value?: null | string): string {
  if (!value) return '-';
  const converted = businessTimestamp(value);
  if (converted) return converted;
  if (/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?/.test(value)) return value.replace('T', ' ').slice(0, 16);
  return value;
}
