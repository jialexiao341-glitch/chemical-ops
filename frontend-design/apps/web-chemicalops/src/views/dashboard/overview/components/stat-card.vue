<script lang="ts" setup>
/**
 * 指标卡片。
 *
 * 用于运营总览首屏的 KPI 行：图标、标题、数值和一行辅助说明。
 * 图标使用 iconify 图标名（与路由菜单保持一致），通过 IconifyIcon 渲染。
 * 传 `to` 时整卡可点击跳转到对应明细页。
 */
import { useRouter } from 'vue-router';

import { IconifyIcon } from '@vben/icons';

import { Card } from 'antdv-next';

withDefaults(
  defineProps<{
    /** 辅助说明，例如「较上月 +12%」 */
    hint?: string;
    /** iconify 图标名，例如 lucide:truck */
    icon?: string;
    /** 数值的语义色 */
    tone?: 'danger' | 'default' | 'success' | 'warning';
    title: string;
    /** 点击跳转的路由路径，为空则不可点击 */
    to?: string;
    value: number | string;
  }>(),
  {
    hint: '',
    icon: '',
    tone: 'default',
    to: '',
    value: '-',
  },
);

const router = useRouter();

const TONE_CLASS: Record<string, string> = {
  danger: 'bg-red-50 text-red-600',
  default: 'bg-teal-50 text-teal-700',
  success: 'bg-emerald-50 text-emerald-600',
  warning: 'bg-amber-50 text-amber-600',
};

const VALUE_TONE_CLASS: Record<string, string> = {
  danger: 'text-red-600',
  // 显式指定前景色，保证所有「无语义色」卡片取值完全一致
  default: 'text-foreground',
  success: 'text-emerald-600',
  warning: 'text-amber-600',
};
</script>

<template>
  <Card
    class="h-full"
    :class="to ? 'cursor-pointer transition-shadow hover:shadow-md' : ''"
    :styles="{ body: { padding: '18px 20px' } }"
    @click="to && router.push(to)"
  >
    <div class="flex items-start gap-4">
      <div
        v-if="icon"
        class="flex size-11 shrink-0 items-center justify-center rounded-lg"
        :class="TONE_CLASS[tone]"
      >
        <IconifyIcon :icon="icon" class="size-6" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="text-muted-foreground flex items-center gap-1 truncate text-sm">
          {{ title }}
          <IconifyIcon
            v-if="to"
            icon="lucide:arrow-right"
            class="size-3.5 shrink-0 opacity-60"
          />
        </div>
        <!--
          数值区固定两行高（h-16/leading-8）：单数值卡片与多行卡片等高，
          行与行之间的卡片高度、辅助文案基线完全对齐；
          允许通过 #value 插槽自定义内部结构（如数量 + 小字号单位）。
        -->
        <div
          class="mt-1 h-16 overflow-hidden text-2xl font-semibold leading-8 tracking-tight"
          :class="VALUE_TONE_CLASS[tone]"
        >
          <slot name="value">{{ value }}</slot>
        </div>
        <div v-if="hint" class="text-muted-foreground mt-1 truncate text-xs">
          {{ hint }}
        </div>
      </div>
    </div>
  </Card>
</template>
