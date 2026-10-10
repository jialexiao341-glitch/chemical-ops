import type {
  ComponentRecordType,
  GenerateMenuAndRoutesOptions,
} from '@vben/types';
import type { RouteRecordRaw } from 'vue-router';

import { generateAccessible } from '@vben/access';
import { preferences } from '@vben/preferences';

import { BasicLayout, IFrameView } from '#/layouts';

const forbiddenComponent = () => import('#/views/_core/fallback/forbidden.vue');

/**
 * 一级菜单是子页面的分组，不单独授予菜单权限。只保留至少包含一个
 * 当前用户可见子页面的分组，避免权限列表维护不一致时显示空标题。
 * hideInMenu 路由仍保留用于详情页等内部跳转，但不单独撑起菜单分组。
 */
function filterRoutesByVisibleChildren(
  routes: GenerateMenuAndRoutesOptions['routes'],
  authorities: string[],
): GenerateMenuAndRoutesOptions['routes'] {
  const filtered: RouteRecordRaw[] = [];
  for (const route of routes) {
    // 管理员在内部业务页面管理供应商，不展示供应商本人使用的门户入口。
    if (route.name === 'SupplierPortal' && authorities.includes('SYS_ADMIN')) {
      continue;
    }
    if (!route.children?.length) {
      const routeAuthorities = route.meta?.authority;
      const hasAuthority =
        !routeAuthorities ||
        routeAuthorities.some((authority) => authorities.includes(authority));
      const visibleWithForbidden =
        route.meta?.menuVisibleWithForbidden === true;

      if (!hasAuthority && !visibleWithForbidden) {
        continue;
      }
      filtered.push(route);
      continue;
    }

    let children = filterRoutesByVisibleChildren(route.children, authorities);
    const isTechnicalApplicant =
      authorities.includes('TECHNICAL') &&
      authorities.includes('warehouse.inventory.issue.read') &&
      !authorities.includes('warehouse.inventory.read');
    if (route.name === 'Warehouse' && isTechnicalApplicant) {
      children = children.map((child) =>
        child.name === 'IssueRequestList'
          ? {
              ...child,
              meta: { ...child.meta, title: '我的领用申请' },
            }
          : child,
      );
    }
    if (children.length === 0) {
      continue;
    }

    const hasVisibleChild = children.some(
      (child) => !child.meta?.hideInMenu,
    );
    const meta = { ...route.meta };
    if (route.name === 'Warehouse' && isTechnicalApplicant) {
      meta.title = '研发协作';
    }

    // Structural group permissions follow its accessible children; the child
    // route remains the source of truth for page access.
    delete meta.authority;
    if (!hasVisibleChild) {
      meta.hideInMenu = true;
    }

    filtered.push({ ...route, children, meta } as RouteRecordRaw);
  }
  return filtered;
}

/**
 * 生成可访问的路由与菜单。
 *
 * ChemicalOps 后端不提供菜单接口，因此固定使用前端权限模式：
 * 由 `meta.authority` 与当前用户的角色码/权限码求交集来决定可见性。
 */
async function generateAccess(options: GenerateMenuAndRoutesOptions) {
  const pageMap: ComponentRecordType = import.meta.glob('../views/**/*.vue');
  const routes = filterRoutesByVisibleChildren(
    options.routes,
    options.roles ?? [],
  );

  const layoutMap: ComponentRecordType = {
    BasicLayout,
    IFrameView,
  };

  return await generateAccessible(preferences.app.accessMode, {
    ...options,
    routes,
    forbiddenComponent,
    layoutMap,
    pageMap,
  });
}

export { generateAccess };
