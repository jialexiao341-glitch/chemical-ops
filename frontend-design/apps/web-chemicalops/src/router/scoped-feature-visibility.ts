import type { RouteRecordRaw } from 'vue-router';

import {
  getBalanceListApi,
  getDeliveryListApi,
  getExpiryAlertsApi,
  getIssueListApi,
  getInventoryReturnsApi,
  getStocktakeListApi,
  getTransactionListApi,
  getTransferListApi,
} from '#/api';

type ScopedFeatureProbe = {
  path: string;
  read: string;
  writes: string[];
  hasVisibleData: () => Promise<boolean>;
};

const warehouseFeatureProbes: ScopedFeatureProbe[] = [
  {
    path: '/warehouse/returns',
    read: 'warehouse.inventory.return.read',
    writes: ['warehouse.inventory.return.write', 'warehouse.inventory.return.approve'],
    hasVisibleData: async () =>
      (await getInventoryReturnsApi({ page: 1, page_size: 1 })).total > 0,
  },
  {
    path: '/warehouse/deliveries',
    read: 'warehouse.deliveries.read',
    writes: ['warehouse.deliveries.write'],
    hasVisibleData: async () =>
      (await getDeliveryListApi({ page: 1, page_size: 1 })).total > 0,
  },
  {
    path: '/warehouse/inventory',
    read: 'warehouse.inventory.read',
    writes: ['warehouse.inventory.write'],
    hasVisibleData: async () =>
      (await getBalanceListApi({ page: 1, page_size: 1 })).total > 0,
  },
  {
    path: '/warehouse/transactions',
    read: 'warehouse.inventory.read',
    writes: ['warehouse.inventory.write'],
    hasVisibleData: async () =>
      (await getTransactionListApi({ page: 1, page_size: 1 })).total > 0,
  },
  {
    path: '/warehouse/expiry-alerts',
    read: 'warehouse.inventory.read',
    writes: ['warehouse.inventory.write'],
    hasVisibleData: async () => (await getExpiryAlertsApi()).length > 0,
  },
  {
    path: '/warehouse/issue-requests',
    read: 'warehouse.inventory.issue.read',
    writes: ['warehouse.inventory.issue.write', 'warehouse.inventory.issue.approve'],
    hasVisibleData: async () =>
      (await getIssueListApi({ page: 1, page_size: 1 })).total > 0,
  },
  {
    path: '/warehouse/transfers',
    read: 'warehouse.inventory.transfer.read',
    writes: ['warehouse.inventory.transfer.write', 'warehouse.inventory.transfer.approve'],
    hasVisibleData: async () =>
      (await getTransferListApi({ page: 1, page_size: 1 })).total > 0,
  },
  {
    path: '/warehouse/stocktakes',
    read: 'warehouse.inventory.stocktake.read',
    writes: ['warehouse.inventory.stocktake.write', 'warehouse.inventory.stocktake.approve'],
    hasVisibleData: async () =>
      (await getStocktakeListApi({ page: 1, page_size: 1 })).total > 0,
  },
];

/**
 * 只读仓储入口只有在当前账号的数据范围内存在记录时才展示。
 * 有写/审批权限的入口始终保留，避免空数据时阻断新建或待办处理。
 * 探测请求失败时保留入口，避免短暂网络故障导致功能区消失。
 */
export async function getEmptyReadOnlyWarehousePaths(
  permissionCodes: string[],
): Promise<Set<string>> {
  const codes = new Set(permissionCodes);
  const checks = warehouseFeatureProbes
    .filter(
      ({ read, writes }) =>
        codes.has(read) && !writes.some((code) => codes.has(code)),
    )
    .map(async ({ hasVisibleData, path }) => {
      try {
        return (await hasVisibleData()) ? null : path;
      } catch {
        return null;
      }
    });

  return new Set((await Promise.all(checks)).filter((path): path is string => Boolean(path)));
}

/** 从动态路由中移除只读且当前数据范围为空的仓储页面。 */
export function filterRoutesByVisibleData(
  routes: RouteRecordRaw[],
  hiddenPaths: Set<string>,
): RouteRecordRaw[] {
  function filterTree(
    records: RouteRecordRaw[],
    parentPath = '',
  ): RouteRecordRaw[] {
    return records.flatMap((record) => {
      const path = record.path.startsWith('/')
        ? record.path
        : `${parentPath.replace(/\/$/, '')}/${record.path}`;
      if (hiddenPaths.has(path)) {
        return [];
      }

      const children = record.children
        ? filterTree(record.children, path)
        : undefined;
      if (record.children?.length && children?.length === 0) {
        return [];
      }
      const filteredRecord = { ...record } as RouteRecordRaw;
      if (children) {
        filteredRecord.children = children;
      }
      return [filteredRecord];
    });
  }

  return filterTree(routes);
}
