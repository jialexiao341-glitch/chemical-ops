<script lang="ts" setup>
import type { AiApi } from '#/api';

import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import PageCopilotDrawer from './page-copilot-drawer.vue';
import { activePageCopilotContext } from '#/utils/page-copilot-context';

const router = useRouter();
const route = useRoute();
const drawer = ref<{
  open: (objectType: AiApi.ContextObjectType, id: number, question?: string) => void;
}>();
const panelOpen = ref(false);
const button = ref<HTMLButtonElement>();
const position = ref({ right: 24, bottom: 112 });
const dragging = ref(false);
let pointerStart: { x: number; y: number; right: number; bottom: number } | undefined;
let moved = false;
let suppressClick = false;

const label = computed(() => {
  const context = activePageCopilotContext.value;
  if (!context) return '化工助手';
  const labels: Record<AiApi.ContextObjectType, string> = {
    delivery: '到货单',
    finance_reconciliation: '财务对账单',
    inventory_balance: '库存余额',
    purchase_order: '采购订单',
    purchase_request: '采购申请',
    quality_acceptance: '质量验收单',
    rfq: '询价单',
    supplier: '供应商',
  };
  const type = labels[context.objectType] ?? '当前单据';
  return `化工助手 · ${type}`;
});
const isWorkspace = computed(() => route.name === 'AiWorkspace');

function restorePosition() {
  try {
    const saved = localStorage.getItem('chemicalops-agent-position');
    const parsed = saved ? JSON.parse(saved) : null;
    if (parsed && Number.isFinite(parsed.right) && Number.isFinite(parsed.bottom)) {
      position.value = parsed;
    }
  } catch {
    // 忽略损坏的本地位置，使用默认位置。
  }
  clampPosition();
}

function clampPosition() {
  const width = button.value?.offsetWidth ?? 64;
  const height = button.value?.offsetHeight ?? 64;
  position.value = {
    right: Math.max(8, Math.min(position.value.right, window.innerWidth - width - 8)),
    bottom: Math.max(8, Math.min(position.value.bottom, window.innerHeight - height - 8)),
  };
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return;
  pointerStart = {
    x: event.clientX,
    y: event.clientY,
    right: position.value.right,
    bottom: position.value.bottom,
  };
  moved = false;
  button.value?.setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent) {
  if (!pointerStart) return;
  const dx = event.clientX - pointerStart.x;
  const dy = event.clientY - pointerStart.y;
  if (Math.abs(dx) + Math.abs(dy) > 5) {
    moved = true;
    dragging.value = true;
  }
  if (!moved) return;
  position.value = { right: pointerStart.right - dx, bottom: pointerStart.bottom - dy };
  clampPosition();
}

function onPointerUp() {
  if (!pointerStart) return;
  pointerStart = undefined;
  dragging.value = false;
  if (moved) {
    suppressClick = true;
    try {
      localStorage.setItem('chemicalops-agent-position', JSON.stringify(position.value));
    } catch {
      // 无法保存时仍保留当前页面的拖动位置。
    }
    window.setTimeout(() => { suppressClick = false; }, 0);
  }
}

function moveByKeyboard(dx: number, dy: number) {
  position.value = { right: position.value.right - dx, bottom: position.value.bottom - dy };
  clampPosition();
  try {
    localStorage.setItem('chemicalops-agent-position', JSON.stringify(position.value));
  } catch {
    // 无法保存时仍保留当前页面的位置。
  }
}

function openAssistant() {
  if (suppressClick) return;
  const context = activePageCopilotContext.value;
  if (context) {
    drawer.value?.open(context.objectType, context.objectId, context.question);
    return;
  }
  void router.push({ name: 'AiWorkspace' });
}

onMounted(() => {
  restorePosition();
  window.addEventListener('resize', clampPosition);
});
onBeforeUnmount(() => window.removeEventListener('resize', clampPosition));
</script>

<template>
  <Teleport to="body">
    <button
      v-if="!panelOpen && !isWorkspace"
      ref="button"
      class="chemical-agent"
      :class="{ 'chemical-agent--dragging': dragging }"
      :style="{ right: `${position.right}px`, bottom: `${position.bottom}px` }"
      type="button"
      :aria-label="`${label}，可拖动或使用方向键调整位置，点击打开`"
      :title="`${label} · 拖动调整位置`"
      @click="openAssistant"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @keydown.arrow-up.prevent="moveByKeyboard(0, 12)"
      @keydown.arrow-down.prevent="moveByKeyboard(0, -12)"
      @keydown.arrow-left.prevent="moveByKeyboard(-12, 0)"
      @keydown.arrow-right.prevent="moveByKeyboard(12, 0)"
    >
      <span class="chemical-agent__bot" aria-hidden="true">
        <svg viewBox="0 0 48 48" fill="none">
          <path d="M24 5v5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
          <circle cx="24" cy="4" r="2" fill="#59C7D7" />
          <rect x="8" y="11" width="32" height="25" rx="10" fill="white" />
          <path d="M8 21H5a3 3 0 0 0 0 6h3m32-6h3a3 3 0 0 1 0 6h-3" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
          <rect x="14" y="17" width="20" height="11" rx="5.5" fill="#183B82" />
          <circle cx="19.5" cy="22.5" r="1.8" fill="#8FE7EE" />
          <circle cx="28.5" cy="22.5" r="1.8" fill="#8FE7EE" />
          <path d="M20 32h8" stroke="#4568F5" stroke-width="2" stroke-linecap="round" />
          <path d="M17 36v4m14-4v4" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
          <path d="M23 39h2l-1 2 2 1-3 3 .5-2-2-1 1.5-3Z" fill="#59C7D7" />
        </svg>
      </span>
    </button>
  </Teleport>
  <PageCopilotDrawer ref="drawer" @open-change="panelOpen = $event" />
</template>

<style scoped>
.chemical-agent {
  position: fixed;
  z-index: 2100;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 60px;
  height: 60px;
  padding: 4px;
  color: #fff;
  background: linear-gradient(145deg, #4568f5, #2746b5);
  border: 1px solid rgb(255 255 255 / 50%);
  border-radius: 50%;
  box-shadow: 0 8px 24px rgb(31 59 142 / 28%), 0 2px 6px rgb(20 34 82 / 18%);
  cursor: grab;
  touch-action: none;
  user-select: none;
  transition: box-shadow 160ms ease, transform 160ms ease;
}

.chemical-agent:hover {
  box-shadow: 0 12px 30px rgb(31 59 142 / 34%), 0 3px 8px rgb(20 34 82 / 20%);
  transform: translateY(-2px);
}

.chemical-agent:focus-visible {
  outline: 3px solid #59c7d7;
  outline-offset: 3px;
}

.chemical-agent--dragging {
  cursor: grabbing;
  transition: none;
}

.chemical-agent__bot {
  display: grid;
  width: 50px;
  height: 50px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  background: rgb(255 255 255 / 14%);
  border: 1px solid rgb(255 255 255 / 30%);
  border-radius: 50%;
}

.chemical-agent__bot svg {
  width: 44px;
  height: 44px;
}

@media (max-width: 640px) {
  .chemical-agent {
    width: 56px;
    height: 56px;
  }

  .chemical-agent__bot {
    width: 46px;
    height: 46px;
  }

  .chemical-agent__bot svg {
    width: 40px;
    height: 40px;
  }
}
</style>
