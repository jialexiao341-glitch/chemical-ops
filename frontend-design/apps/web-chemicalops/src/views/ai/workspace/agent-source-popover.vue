<script setup lang="ts">
import type { AgentApi } from '#/api';
import { computed, ref, watch } from 'vue';
import { useAccess } from '@vben/access';
import { Popover } from 'antdv-next';
import { formatDateTime } from '#/utils/format';
import { agentSourcePreview } from './task-view';
import type { AnswerSource } from './answer-sources';
const props = defineProps<{ result?: AgentApi.Result; entries?: AnswerSource[]; sourceLabel?: string }>();
const emit = defineEmits<{ openRecord: [record: NonNullable<AnswerSource['record']>]; openDataset: [dataset: string] }>();
const { hasAccessByCodes } = useAccess();
const canOpenSource = computed(() => !props.result || hasAccessByCodes([props.result.tool === 'inventory.query_available' ? 'warehouse.inventory.read' : props.result.tool === 'catalog.search_products' ? 'master.products.read' : 'procurement.rfqs.read']));
const open = ref(false);
const index = ref(0);
const entries = computed<AnswerSource[]>(() => props.entries ?? (props.result?.sources ?? []).map((source) => ({
  ...agentSourcePreview(props.result!, source), key: `${source.resource}:${source.record_id}`, label: '', observedAt: props.result && 'observed_at' in props.result ? props.result.observed_at : undefined,
})));
const preview = computed(() => entries.value[index.value]);
const label = computed(() => props.sourceLabel || (props.result ? props.result.tool === 'inventory.query_available' ? '库存记录' : props.result.tool === 'supplier_quotes.compare' ? '供应商报价' : props.result.tool === 'catalog.search_products' ? '产品资料' : '询价记录' : '回答依据'));
watch(() => [props.result, props.entries], () => { index.value = 0; open.value = false; });
</script>
<template>
  <Popover v-if="entries.length" v-model:open="open" :trigger="['hover', 'click']" placement="bottom" :auto-adjust-overflow="true" :arrow="false" :styles="{ container: { padding: '0', borderRadius: '14px' } }">
    <button class="source-pill" type="button" :aria-expanded="open" aria-haspopup="dialog" @keydown.esc="open = false">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 3.5h8l2 2V17H5zM13 3.5V6h2M8 9h4M8 12h4"/></svg>
      <span>{{ label }}</span><span v-if="entries.length > 1" class="source-extra">+{{ entries.length - 1 }}</span>
    </button>
    <template #content>
      <section v-if="preview" class="source-preview" role="dialog" :aria-label="`${label}来源详情`" @keydown.esc="open = false">
        <div class="source-nav">
          <div class="source-arrows"><button type="button" aria-label="上一条来源" :disabled="index === 0" @click="index -= 1"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M16 10H4m6-6-6 6 6 6"/></svg></button><button type="button" aria-label="下一条来源" :disabled="index === entries.length - 1" @click="index += 1"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 10h12m-6-6 6 6-6 6"/></svg></button></div>
          <span aria-live="polite">{{ index + 1 }}/{{ entries.length }}</span>
          <button class="source-close" type="button" aria-label="关闭来源详情" @click="open = false">×</button>
        </div>
        <div class="source-brand"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 3.5h8l2 2V17H5zM13 3.5V6h2M8 9h4M8 12h4"/></svg><span>{{ label }}</span></div>
        <h3>{{ preview.title }}</h3>
        <p v-if="preview.status" class="source-meta" role="status">{{ preview.status }}</p>
        <p class="source-description">{{ preview.description }}</p>
        <p class="source-meta">{{ preview.reference }}</p>
        <div class="source-footer">
          <span v-if="preview.observedAt">{{ formatDateTime(preview.observedAt) }} {{ preview.timeLabel || '查询' }}</span>
          <RouterLink v-if="preview.to && canOpenSource" :to="preview.to" @click="open = false">{{ preview.linkLabel }} ↗</RouterLink>
          <a v-else-if="preview.url && !preview.status" :href="preview.url" target="_blank" rel="noopener noreferrer">{{ preview.linkLabel || '打开原始来源' }} ↗</a>
          <button v-else-if="preview.record" type="button" @click="emit('openRecord', preview.record); open = false">定位业务记录 ↗</button>
          <button v-else-if="preview.dataset" type="button" @click="emit('openDataset', preview.dataset); open = false">打开对应业务列表 ↗</button>
        </div>
      </section>
    </template>
  </Popover>
</template>
<style scoped>
.source-pill { display: inline-flex; align-items: center; gap: 5px; border: 0; border-radius: 999px; padding: 3px 8px; background: hsl(var(--muted)); color: hsl(var(--muted-foreground)); cursor: pointer; font: inherit; font-size: 11px; line-height: 1.5; }
.source-pill > svg, .source-brand > svg { width: 15px; height: 15px; color: hsl(var(--primary)); flex: none; }
.source-pill:hover, .source-pill[aria-expanded="true"] { background: hsl(var(--primary) / .08); color: hsl(var(--foreground)); }
.source-extra { font-size: 10px; }
.source-preview { width: min(352px, calc(100vw - 48px)); padding: 14px 16px 16px; color: hsl(var(--foreground)); font-size: 13px; }
.source-nav { display: flex; align-items: center; gap: 8px; margin: -4px -4px 14px; color: hsl(var(--muted-foreground)); }
.source-nav > span { margin-left: auto; font-size: 12px; font-variant-numeric: tabular-nums; }
.source-arrows { display: flex; gap: 4px; }
.source-nav button { display: grid; place-items: center; width: 28px; height: 28px; border: 0; border-radius: 6px; background: transparent; color: inherit; cursor: pointer; }
.source-nav button:hover:not(:disabled) { background: hsl(var(--muted)); color: hsl(var(--foreground)); }
.source-nav button:disabled { opacity: .3; cursor: default; }
.source-nav svg { width: 18px; height: 18px; }
.source-close { font-size: 20px; }
.source-brand { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; font-size: 12px; }
h3 { margin: 0 0 8px; font-size: 14px; font-weight: 600; line-height: 1.5; }
.source-description { margin: 0 0 10px; font-size: 13px; line-height: 1.6; white-space: pre-wrap; max-height: 240px; overflow-y: auto; }
.source-meta { margin: 0; font-size: 11px; color: hsl(var(--muted-foreground)); }
.source-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-top: 14px; font-size: 12px; color: hsl(var(--muted-foreground)); }
.source-footer a, .source-footer button { color: hsl(var(--primary)); text-decoration: none; }
.source-footer button { padding: 0; border: 0; background: transparent; cursor: pointer; font: inherit; }
.source-footer a:hover { text-decoration: underline; }
button:focus-visible, a:focus-visible { outline: 2px solid hsl(var(--primary)); outline-offset: 2px; }
</style>
