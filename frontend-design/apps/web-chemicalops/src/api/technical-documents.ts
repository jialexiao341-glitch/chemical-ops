import { requestClient } from '#/api/request';

export interface TechnicalDocument {
  cas_no: string;
  char_count: number;
  doc_type: 'msds' | 'tds';
  id: number;
  name_zh?: null | string;
  object_key: string;
  parse_status: string;
  reject_reason?: null | string;
  section_count: number;
  sha256?: null | string;
  source_bucket: string;
  source_url?: null | string;
  title?: null | string;
  updated_at: string;
}

export interface TechnicalDocumentSource {
  cas_no: string;
  char_count: number;
  doc_id: null | number;
  doc_type: 'msds' | 'tds';
  extension: 'html' | 'pdf';
  file_size: number;
  ingestible: boolean;
  name_zh?: null | string;
  object_key: string;
  parse_status: string;
  reject_reason?: null | string;
  section_count: number;
  source_bucket: string;
  title?: null | string;
  updated_at?: null | string;
}

export interface TechnicalDocumentRun {
  attempt_count: number;
  error_type?: null | string;
  finished_at?: null | string;
  id: number;
  result_json?: null | Record<string, any>;
  run_id: string;
  started_at: string;
  status: string;
  task_name: string;
}

export interface TechnicalDocumentPreview extends TechnicalDocument {
  meta_json?: null | Record<string, any>;
  sections: Array<{
    char_count: number;
    content: string;
    id: number;
    section_key: string;
    section_no?: null | number;
    title?: null | string;
  }>;
}

export function getTechnicalDocumentsApi(casNo?: string) {
  return requestClient.get<TechnicalDocumentSource[]>('/jobs/technical-documents', { params: casNo ? { cas_no: casNo } : {} });
}

export function getTechnicalDocumentRunsApi() {
  return requestClient.get<TechnicalDocumentRun[]>('/jobs/technical-documents/runs', { params: { limit: 50 } });
}

export function getTechnicalDocumentPreviewApi(documentId: number) {
  return requestClient.get<TechnicalDocumentPreview>(`/jobs/technical-documents/${documentId}/preview`);
}

export function getTechnicalDocumentSourceFileApi(source: Pick<TechnicalDocumentSource, 'cas_no' | 'doc_type' | 'extension'>) {
  return requestClient.get<Blob>('/jobs/technical-documents/source-file', {
    params: { cas_no: source.cas_no, doc_type: source.doc_type, extension: source.extension },
    responseType: 'blob',
  });
}

export function startTechnicalDocumentFetchApi(data: { cas_no: string; doc_types: string[] }) {
  return requestClient.post<TechnicalDocumentRun>('/jobs/technical-documents/fetch', data);
}

export function startTechnicalDocumentIngestApi(data: { cas_no: string; doc_types: string[] }) {
  return requestClient.post<TechnicalDocumentRun>('/jobs/technical-documents/ingest', data);
}
