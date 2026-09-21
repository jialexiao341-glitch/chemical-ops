import type {
  ComponentRecordType,
  GenerateMenuAndRoutesOptions,
} from '@vben/types';

import { generateAccessible } from '@vben/access';
import { preferences } from '@vben/preferences';

import { BasicLayout, IFrameView } from '#/layouts';

const forbiddenComponent = () => import('#/views/_core/fallback/forbidden.vue');

/**
 * 生成可访问的路由与菜单。
 *
 * ChemicalOps 后端不提供菜单接口，因此固定使用前端权限模式：
 * 由 `meta.authority` 与当前用户的角色码/权限码求交集来决定可见性。
 */
async function generateAccess(options: GenerateMenuAndRoutesOptions) {
  const pageMap: ComponentRecordType = import.meta.glob('../views/**/*.vue');

  const layoutMap: ComponentRecordType = {
    BasicLayout,
    IFrameView,
  };

  return await generateAccessible(preferences.app.accessMode, {
    ...options,
    forbiddenComponent,
    layoutMap,
    pageMap,
  });
}

export { generateAccess };
