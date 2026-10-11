import type { VxeTableGridColumns } from '@vben/plugins/vxe-table';

/** 普通列共同伸展，避免只有一列 minWidth 时独占列表剩余宽度。 */
export function fitBusinessColumns(columns: NonNullable<VxeTableGridColumns>): NonNullable<VxeTableGridColumns> {
  return columns.map((column) => {
    if (column.children?.length) {
      return { ...column, children: fitBusinessColumns(column.children) };
    }
    // 勾选、序号、展开及固定操作区保留原尺寸；百分比/auto 等显式策略不覆盖。
    if (column.type || column.fixed || column.field === 'operation' || column.field === '__action') return column;
    if (typeof column.width !== 'number') return column;
    const { width, ...rest } = column;
    return { ...rest, minWidth: Math.max(width, typeof column.minWidth === 'number' ? column.minWidth : 0) };
  });
}
