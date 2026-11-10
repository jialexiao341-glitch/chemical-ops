import { requestClient } from '#/api/request';

export interface ChemicalWikiEntry {
  id: number;
  name: string;
  cas_no: null | string;
  cas_valid_checksum: boolean | null;
  source_type: string;
}

export interface ChemicalWikiDetail {
  version: number;
  note: string;
  source_status: 'CURRENT' | 'CHANGED' | 'UNAVAILABLE';
  msds: {
    source_heading: string;
    source: { filename: string; sha256: string };
    rows: Array<{ row: number; cells: string[] }>;
  };
  technical: {
    sections: string[];
    items: Array<{ section: string; text: string; source_row: number; source_cell: number }>;
  };
}

export interface ChemicalWikiVersion {
  version: number;
  note: string;
  actor_id: number;
  created_at: string;
}

export interface ChemicalWikiSource {
  id: number;
  title: null | string;
  cas_no: string;
  object_key: string;
  source_url: null | string;
  updated_at: string;
}

export interface ChemicalWikiItemReference {
  section: string;
  source_row: number;
  source_cell: number;
}

export function getChemicalWikiEntriesApi() {
  return requestClient.get<ChemicalWikiEntry[]>('/jobs/chemical-wiki');
}

export function getChemicalWikiEntryApi(id: number) {
  return requestClient.get<ChemicalWikiDetail>(`/jobs/chemical-wiki/${id}`);
}

export function getChemicalWikiVersionsApi(id: number) {
  return requestClient.get<ChemicalWikiVersion[]>(`/jobs/chemical-wiki/${id}/versions`);
}

export function getChemicalWikiVersionApi(id: number, version: number) {
  return requestClient.get<ChemicalWikiDetail>(`/jobs/chemical-wiki/${id}/versions/${version}`);
}

export function getChemicalWikiSourcesApi(id: number) {
  return requestClient.get<ChemicalWikiSource[]>(`/jobs/chemical-wiki/${id}/sources`);
}

export function updateChemicalWikiSourceApi(id: number, data: { expected_version: number; document_id: number }) {
  return requestClient.post<{ version: number }>(`/jobs/chemical-wiki/${id}/source`, data);
}

export function saveChemicalWikiVersionApi(id: number, data: { expected_version: number; note: string; items?: ChemicalWikiItemReference[] }) {
  return requestClient.post<{ version: number; note: string }>(`/jobs/chemical-wiki/${id}/versions`, data);
}
