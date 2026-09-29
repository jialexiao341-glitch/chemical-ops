<script lang="ts" setup>
import type { BusinessInsightApi } from '#/api';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { useVbenDrawer } from '@vben/common-ui';

import { Alert, Button, Empty, Spin, Tag } from 'antdv-next';

import { getBusinessInsightApi } from '#/api';

const router = useRouter();
const result = ref<BusinessInsightApi.Insight>();
const loading = ref(false);
const loadError = ref(false);

const [Drawer, drawerApi] = useVbenDrawer<{ kind: string; objectId: number }>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const target = drawerApi.getData();
    result.value = undefined;
    loadError.value = false;
    if (!target) return;
    loading.value = true;
    try {
      result.value = await getBusinessInsightApi(target.kind, target.objectId);
    } catch {
      loadError.value = true;
    } finally {
      loading.value = false;
    }
  },
});

/** 从分析结果跳回对应业务页面继续核实来源。 */
function openSource(path?: null | string) {
  if (path) void router.push(path);
}

/** 打开指定业务对象的分析抽屉。 */
function open(kind: string, objectId: number) {
  drawerApi.setData({ kind, objectId }).open();
}

/** 将证据、建议和范围说明导出为本地 CSV 核查清单。 */
function exportChecklist() {
  if (!result.value) return;
  const rows = [
    ['类别', '内容', '来源'],
    ...result.value.evidence.map((item) => ['核查依据', `${item.label}：${item.value}`, item.source]),
    ...result.value.suggestions.map((item) => ['建议核查', item, '']),
    ...result.value.limitations.map((item) => ['数据范围', item, '']),
  ];
  const cell = (value: string) => {
    const safe = /^[=+\-@]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const csv = `\uFEFF${rows.map((row) => row.map(cell).join(',')).join('\r\n')}`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${result.value.kind}-核查清单.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

defineExpose({ open });
</script>

<template>
  <Drawer :title="result?.title ?? '业务分析'" class="w-[760px] max-w-[100vw]">
    <Spin :spinning="loading">
      <Empty v-if="loadError" description="分析暂时无法加载，请检查权限或稍后重试" />
      <Empty v-else-if="!result && !loading" description="没有可展示的分析结果" />
      <div v-else-if="result" class="space-y-4 pb-6">
        <Alert show-icon type="info" :message="result.summary" :description="`适用人员：${result.audience}；结果为只读信息，正式处理仍在原单据完成。`" />
        <div class="flex justify-end">
          <Button size="small" @click="exportChecklist">导出核查清单</Button>
        </div>

        <section>
          <h3 class="mb-2 font-medium">核查依据</h3>
          <div v-if="result.evidence.length" class="divide-y rounded-lg border">
            <div v-for="(item, index) in result.evidence" :key="`${item.source}-${index}`" class="flex flex-wrap items-start justify-between gap-3 px-3 py-3 text-sm">
              <div class="min-w-0 flex-1">
                <div class="font-medium">{{ item.label }}</div>
                <div class="mt-1 whitespace-pre-wrap break-words text-muted-foreground">{{ item.value }}</div>
                <div class="mt-1 text-xs text-muted-foreground">来源：{{ item.source }}</div>
              </div>
              <Button v-if="item.path" size="small" type="link" @click="openSource(item.path)">打开来源</Button>
            </div>
          </div>
          <Empty v-else description="当前没有可核查记录" />
        </section>

        <section v-if="result.suggestions.length">
          <h3 class="mb-2 font-medium">建议核查</h3>
          <ul class="list-disc space-y-1 pl-5 text-sm">
            <li v-for="item in result.suggestions" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-if="result.limitations.length" class="space-y-2">
          <h3 class="font-medium">数据范围</h3>
          <div v-for="item in result.limitations" :key="item" class="text-sm text-muted-foreground">
            <Tag color="gold">需留意</Tag>{{ item }}
          </div>
        </section>
      </div>
    </Spin>
  </Drawer>
</template>
