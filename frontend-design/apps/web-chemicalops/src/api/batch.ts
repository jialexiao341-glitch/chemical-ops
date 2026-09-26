import { requestClient } from '#/api/request';

/** 列表批量操作共用接口。资源名对应后端白名单及权限码。 */
export async function batchDeleteApi(resource: string, ids: number[]) {
  return requestClient.post<{ action: 'deleted' | 'disabled'; count: number }>(
    `/batch/${resource}/delete`,
    { ids },
  );
}

export async function batchExportApi(resource: string, ids: number[]) {
  return requestClient.download<Blob>(`/batch/${resource}/export`, {
    data: { ids },
    method: 'POST',
  });
}

export async function batchImportApi(resource: string, file: File) {
  const data = new FormData();
  data.append('file', file);
  return requestClient.post<{ count: number }>(`/batch/${resource}/import`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}
