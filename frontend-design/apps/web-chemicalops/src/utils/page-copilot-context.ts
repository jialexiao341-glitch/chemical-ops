import { shallowRef } from 'vue';

import type { AiApi } from '#/api';

export interface PageCopilotContext {
  objectId: number;
  objectType: AiApi.ContextObjectType;
  question?: string;
}

/** 当前打开的业务详情对象，供全局化工助手悬浮入口读取。 */
export const activePageCopilotContext = shallowRef<PageCopilotContext | null>(null);

export function setPageCopilotContext(context: PageCopilotContext) {
  activePageCopilotContext.value = context;
}

export function clearPageCopilotContext(objectType: AiApi.ContextObjectType, objectId: number) {
  const current = activePageCopilotContext.value;
  if (current?.objectType === objectType && current.objectId === objectId) {
    activePageCopilotContext.value = null;
  }
}
