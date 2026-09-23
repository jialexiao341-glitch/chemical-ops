<script lang="ts" setup>
/**
 * 指标卡片。
 *
 * 用于运营总览首屏的 KPI 行：图标、标题和数值。
 * 图标使用 iconify 图标名（与路由菜单保持一致），通过 IconifyIcon 渲染。
 * 传 `to` 时整卡可点击跳转到对应明细页。
 */
import { useRouter } from 'vue-router';

import { IconifyIcon } from '@vben/icons';

import { Card } from 'antdv-next';

withDefaults(
  defineProps<{
    /** iconify 图标名，例如 lucide:truck */
    icon?: string;
    /** 数值的语义色 */
    tone?: 'danger' | 'default' | 'primary' | 'success' | 'warning';
    title: string;
    /** 点击跳转的路由路径，为空则不可点击 */
    to?: string;
    value: number | string;
  }>(),
  {
    icon: '',
    tone: 'default',
    to: '',
    value: '-',
  },
);

const router = useRouter();

const TONE_CLASS: Record<string, string> = {
  danger: 'bg-[#FFF1F2] text-[#EF4444]',
  default: 'bg-[#F1F5F9] text-[#64748B]',
  primary: 'bg-[#EEF2FF] text-[#4F6EF7]',
  success: 'bg-[#ECFDF5] text-[#16A34A]',
  warning: 'bg-[#FFF7ED] text-[#F59E0B]',
};

const VALUE_TONE_CLASS: Record<string, string> = {
  danger: 'text-[#EF4444]',
  default: 'text-[#172033]',
  primary: 'text-[#4F6EF7]',
  success: 'text-[#16A34A]',
  warning: 'text-[#F59E0B]',
};
</script>

<template>
  <Card
    class="h-full rounded-lg border border-[#E8ECF2] shadow-none"
    :class="to ? 'cursor-pointer transition-[box-shadow,border-color] hover:border-slate-300 hover:shadow-[0_4px_16px_rgba(15,23,42,0.06)]' : ''"
    :styles="{ body: { padding: '10px 16px' } }"
    @click="to && router.push(to)"
  >
    <div class="min-h-[68px]">
      <div class="flex items-center justify-between gap-3">
        <div class="min-w-0 truncate text-sm font-medium text-[#64748B]">
          {{ title }}
        </div>
        <div
          v-if="icon"
          class="flex size-9 shrink-0 items-center justify-center rounded-lg"
          :class="TONE_CLASS[tone]"
        >
          <IconifyIcon :icon="icon" class="size-[19px]" />
        </div>
      </div>
      <div
        class="mt-0.5 break-words text-[27px] font-semibold leading-[1.2] tabular-nums tracking-normal"
        :class="VALUE_TONE_CLASS[tone]"
      >
        <slot name="value">{{ value }}</slot>
      </div>
    </div>
  </Card>
</template>
