<script setup lang="ts">
import { ref } from 'vue';
import { Button, Tag } from 'antdv-next';
import { formatDateTime } from '#/utils/format';
import QueryCharts from './query-charts.vue';
// 复用工作台原有查询链路和来源模板；父组件按当前权限筛选来源。
defineProps<{ trace?: any; sourceRecords: any[] }>();
const emit = defineEmits<{ openDataset: [dataset: string]; openSourceRecord: [record: any] }>();
const traceOpen = ref(false);
function openDataset(dataset: string) { emit('openDataset', dataset); }
function openSourceRecord(record: any) { emit('openSourceRecord', record); }
</script>
<template>
                <QueryCharts v-if="trace?.rows?.length" :trace="trace" />
                <div
                v-if="trace"
                  class="border-border/50 mt-2 border-t pt-2 text-xs opacity-80"
                >
                  <div class="mb-2 rounded-md border border-border/70 bg-background/70 p-2">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span class="font-medium">数据来源：</span>
                        {{ trace.dataset_label || trace.dataset || '业务数据' }}
                        <span v-if="trace.executed_at" class="text-muted-foreground ml-2">
                          查询于 {{ formatDateTime(trace.executed_at) }}
                        </span>
                      </div>
                      <Button
                        v-if="trace.dataset"
                        size="small"
                        type="link"
                        @click="openDataset(trace.dataset)"
                      >打开对应业务列表</Button>
                    </div>
                    <div v-if="trace.unit_note" class="text-muted-foreground mt-1">
                      口径：{{ trace.unit_note }}
                    </div>
                  </div>
                  <!-- 默认收起：标题行常驻摘要，点击展开槽位与 SQL -->
                  <button
                    class="flex w-full cursor-pointer items-center gap-1 text-left select-none"
                    type="button"
                    @click="traceOpen = !traceOpen"
                  >
                    <span
                      class="transition-transform"
                      :class="traceOpen ? 'rotate-90' : ''"
                    >▸</span>
                    <span>
                      查询链路 ·
                      {{ trace.dataset_label || trace.dataset || '-' }} ·
                      命中 {{ trace.row_count }} 行
                    </span>
                    <span class="text-muted-foreground">
                      {{ traceOpen ? '收起' : '查看' }}
                    </span>
                  </button>
                  <template v-if="traceOpen">
                    <!-- 已抽取槽位：label: display_value，empty 状态降透明度区分 -->
                    <div
                      v-if="trace.slots?.length"
                      class="mt-2 flex flex-wrap gap-1"
                    >
                      <Tag
                        v-for="slot in trace.slots"
                        :key="slot.name"
                        class="!mr-0"
                        :class="slot.status === 'filled' ? '' : 'opacity-50'"
                        :color="slot.status === 'filled' ? 'blue' : undefined"
                      >
                        {{ slot.label }}：{{ slot.display_value }}
                      </Tag>
                    </div>
                    <pre
                      class="mt-2 max-h-32 overflow-auto whitespace-pre-wrap"
                    >{{ trace.sql }}</pre>
                  </template>
                </div>
                <details v-if="sourceRecords.length" class="mt-2 border-t border-border/50 pt-2">
                  <summary class="text-muted-foreground cursor-pointer select-none text-xs font-medium">
                    来源记录（{{ sourceRecords.length }}）
                  </summary>
                  <div class="mt-2 space-y-1">
                    <div
                      v-for="(record, index) in sourceRecords"
                      :key="`${record.dataset}-${record.record_id ?? index}`"
                      class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/70 bg-background/70 px-2 py-1.5 text-xs"
                    >
                      <span>{{ record.label }}</span>
                      <Button size="small" type="link" @click="openSourceRecord(record)">定位业务记录</Button>
                    </div>
                  </div>
                </details>

</template>
