<script lang="ts" setup>
import type { TechnicalDocumentPreview, TechnicalDocumentSource } from '#/api';

import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';

import { computed, nextTick, onBeforeUnmount, ref, shallowRef } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';
import { Alert, Button, Empty, Spin, Tag } from 'antdv-next';
import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

import { getTechnicalDocumentPreviewApi, getTechnicalDocumentSourceFileApi } from '#/api';
import { formatDateTime } from '#/utils/format';

const source = ref<TechnicalDocumentSource>();
const document = ref<TechnicalDocumentPreview>();
const loading = ref(false);
const fileError = ref('');
const dataError = ref('');
const htmlText = ref('');
const pdfDocument = shallowRef<PDFDocumentProxy>();
const pdfCanvas = ref<HTMLCanvasElement>();
const pdfContainer = ref<HTMLDivElement>();
const pdfPageNumber = ref(1);
const pdfPageCount = ref(0);
const pdfRenderTask = shallowRef<RenderTask>();
const metadata = computed(() => Object.entries(document.value?.meta_json || {})
  .filter(([key]) => !/(quality|reject|质检)/i.test(key)));
const drawerTitle = computed(() => source.value ? `${source.value.doc_type.toUpperCase()} 文件预览` : '技术资料预览');

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

function clearPdfPreview() {
  pdfRenderTask.value?.cancel();
  pdfRenderTask.value = undefined;
  if (pdfDocument.value) void pdfDocument.value.destroy();
  pdfDocument.value = undefined;
  pdfPageNumber.value = 1;
  pdfPageCount.value = 0;
}

async function renderPdfPage() {
  const pdf = pdfDocument.value;
  const canvas = pdfCanvas.value;
  const container = pdfContainer.value;
  if (!pdf || !canvas || !container) return;

  pdfRenderTask.value?.cancel();
  const page = await pdf.getPage(pdfPageNumber.value);
  const baseViewport = page.getViewport({ scale: 1 });
  const scale = Math.min(container.clientWidth / baseViewport.width, 1.5);
  const viewport = page.getViewport({ scale });
  const outputScale = window.devicePixelRatio || 1;
  const context = canvas.getContext('2d');
  if (!context) return;

  canvas.width = Math.ceil(viewport.width * outputScale);
  canvas.height = Math.ceil(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  const task = page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
  });
  pdfRenderTask.value = task;
  try {
    await task.promise;
  } catch (error) {
    if (!(error instanceof Error) || error.name !== 'RenderingCancelledException') throw error;
  }
}

async function changePdfPage(step: number) {
  const nextPage = pdfPageNumber.value + step;
  if (nextPage < 1 || nextPage > pdfPageCount.value) return;
  pdfPageNumber.value = nextPage;
  await nextTick();
  await renderPdfPage();
}

const [Drawer, drawerApi] = useVbenDrawer<TechnicalDocumentSource>({
  footer: false,
  async onOpenChange(open) {
    if (!open) {
      clearPdfPreview();
      return;
    }
    source.value = drawerApi.getData();
    document.value = undefined;
    htmlText.value = '';
    fileError.value = '';
    dataError.value = '';
    if (!source.value) return;
    loading.value = true;
    try {
      const blob = await getTechnicalDocumentSourceFileApi(source.value);
      if (source.value.extension === 'pdf') {
        pdfDocument.value = await pdfjsLib.getDocument({ data: await blob.arrayBuffer() }).promise;
        pdfPageCount.value = pdfDocument.value.numPages;
        await nextTick();
        await renderPdfPage();
      } else htmlText.value = await blob.text();
    } catch {
      fileError.value = '原始文件预览失败，请检查 MinIO 文件是否可读取。';
    }
    if (source.value.doc_id) {
      try {
        document.value = await getTechnicalDocumentPreviewApi(source.value.doc_id);
      } catch {
        dataError.value = '结构化数据加载失败。';
      }
    }
    loading.value = false;
  },
});

defineExpose({ drawerApi });
onBeforeUnmount(clearPdfPreview);

function displayValue(value: unknown) {
  return Array.isArray(value) ? value.join('、') : typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '—');
}
</script>

<template>
  <Drawer :title="drawerTitle" class="w-[900px] max-w-[100vw]" :footer="false">
    <Spin :spinning="loading">
      <div v-if="source" class="space-y-5 pb-5">
        <section class="rounded-lg border border-border p-4">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="m-0 text-base font-semibold">{{ source.name_zh || source.title || source.cas_no }}</h2>
            <Tag color="blue">{{ source.doc_type.toUpperCase() }} · {{ source.extension.toUpperCase() }}</Tag>
            <Tag :color="source.parse_status === 'PARSED' ? 'success' : source.parse_status === 'PENDING' ? 'default' : 'warning'">
              {{ source.parse_status === 'PARSED' ? '已写入知识库' : source.parse_status === 'PENDING' ? '尚未写入知识库' : source.parse_status }}
            </Tag>
          </div>
          <dl class="mt-4 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div><dt class="text-muted-foreground">CAS 号</dt><dd class="mb-0 mt-1">{{ source.cas_no }}</dd></div>
            <div><dt class="text-muted-foreground">MinIO 对象</dt><dd class="mb-0 mt-1 break-all">{{ source.source_bucket }}/{{ source.object_key }}</dd></div>
            <div><dt class="text-muted-foreground">文件大小</dt><dd class="mb-0 mt-1">{{ (source.file_size / 1024).toFixed(1) }} KB</dd></div>
            <div><dt class="text-muted-foreground">文件更新时间</dt><dd class="mb-0 mt-1">{{ formatDateTime(source.updated_at) }}</dd></div>
          </dl>
        </section>

        <section class="space-y-3">
          <div class="flex items-center justify-between gap-3">
            <h3 class="m-0 text-sm font-semibold">MinIO 原始文件</h3>
            <div class="flex items-center gap-2">
              <template v-if="source.extension === 'pdf' && pdfPageCount">
                <Button size="small" :disabled="pdfPageNumber <= 1" @click="changePdfPage(-1)">上一页</Button>
                <span class="whitespace-nowrap text-xs text-muted-foreground">{{ pdfPageNumber }} / {{ pdfPageCount }}</span>
                <Button size="small" :disabled="pdfPageNumber >= pdfPageCount" @click="changePdfPage(1)">下一页</Button>
              </template>
              <span class="max-w-60 truncate text-xs text-muted-foreground">{{ source.object_key }}</span>
            </div>
          </div>
          <Alert v-if="fileError" type="error" show-icon :message="fileError" />
          <div v-else-if="source.extension === 'pdf' && pdfDocument" ref="pdfContainer" class="flex h-[62vh] min-h-[420px] w-full justify-center overflow-auto rounded border border-border bg-muted/20 p-3">
            <canvas ref="pdfCanvas" class="my-auto shadow-sm" :aria-label="`${source.object_key} 第 ${pdfPageNumber} 页`" />
          </div>
          <pre v-else-if="source.extension === 'html' && htmlText" class="m-0 max-h-[62vh] min-h-[240px] overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-muted/20 p-4 font-sans text-sm leading-6">{{ htmlText }}</pre>
          <Empty v-else-if="!loading && !fileError" description="文件内容为空" />
        </section>

        <section v-if="document" class="space-y-4 border-t border-border pt-4">
          <div class="flex items-center gap-2">
            <h3 class="m-0 text-sm font-semibold">结构化知识库预览</h3>
          </div>
          <Alert v-if="dataError" type="error" show-icon :message="dataError" />
          <section v-if="metadata.length" class="space-y-3">
            <h4 class="m-0 text-sm font-medium">结构化字段</h4>
            <div class="grid gap-3 sm:grid-cols-2">
              <div v-for="[key, value] in metadata" :key="key" class="rounded border border-border p-3">
                <div class="text-xs text-muted-foreground">{{ key }}</div>
                <div class="mt-1 break-words text-sm">{{ displayValue(value) }}</div>
              </div>
            </div>
          </section>
          <section class="space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="m-0 text-sm font-medium">解析章节</h4>
              <span class="text-xs text-muted-foreground">{{ document.sections.length }} 节</span>
            </div>
            <div v-if="document.sections.length" class="space-y-3">
              <article v-for="section in document.sections" :key="section.id" class="rounded-lg border border-border p-4">
                <div class="mb-2 flex items-center justify-between gap-3">
                  <h5 class="m-0 text-sm font-medium">{{ section.title || section.section_key }}</h5>
                  <span class="shrink-0 text-xs text-muted-foreground">{{ section.char_count }} 字符</span>
                </div>
                <pre class="m-0 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-6">{{ section.content }}</pre>
              </article>
            </div>
            <Empty v-else description="尚无可预览的结构化章节" />
          </section>
        </section>
      </div>
    </Spin>
  </Drawer>
</template>
