/**
 * 图表配色。
 *
 * 取自 ChemicalOps 的视觉方向：以化学青为主色，配合琥珀/珊瑚表达风险，
 * 保证同一张图里相邻序列有足够对比度，同时对色盲友好（不单靠红绿区分）。
 */
export const CHART_COLORS = {
  /** 主色：化学青 */
  primary: '#0D9B91',
  primarySoft: '#7FCFC7',
  /** 次要：深墨蓝 */
  ink: '#0D2133',
  /** 中性 */
  neutral: '#62737A',
  neutralSoft: '#C7D2D6',
  /** 风险色 */
  amber: '#D98C22',
  coral: '#D9534F',
  mint: '#E8F7F3',
} as const;

/** 订单状态等分类序列的固定配色 */
export const CATEGORICAL_COLORS = [
  CHART_COLORS.primary,
  CHART_COLORS.amber,
  CHART_COLORS.coral,
  CHART_COLORS.primarySoft,
  CHART_COLORS.ink,
  CHART_COLORS.neutral,
  CHART_COLORS.neutralSoft,
];

/**
 * 图表通用字体与网格样式。
 *
 * 使用 `as const` 保留字面量类型，避免 ECharts 选项校验时
 * 把 'dashed' 这类联合类型放宽成 string 而报错。
 */
export const CHART_BASE = {
  axisLabel: { color: CHART_COLORS.neutral, fontSize: 11 },
  axisLine: { lineStyle: { color: CHART_COLORS.neutralSoft } },
  splitLine: {
    lineStyle: { color: CHART_COLORS.neutralSoft, type: 'dashed' as const },
  },
};
