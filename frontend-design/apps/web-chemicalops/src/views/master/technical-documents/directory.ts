type Source = { readonly doc_type: string; readonly cas_no: string; readonly name_zh?: null | string };

export function directoryChemicals(sources: readonly Source[], type?: string) {
  if (!type) return [];
  const names = new Map<string, string>();
  for (const row of sources) {
    if (row.doc_type !== type) continue;
    if (!names.has(row.cas_no) || (!names.get(row.cas_no) && row.name_zh)) {
      names.set(row.cas_no, row.name_zh || '');
    }
  }
  return [...names.entries()].sort(([a], [b]) => a.localeCompare(b, 'en')).map(([cas, name]) => ({
    label: name ? `${name} · ${cas}` : cas,
    value: cas,
  }));
}

export function filterDirectory<T extends Source>(sources: readonly T[], type?: string, cas?: string): T[] {
  return sources.filter((row) => (!type || row.doc_type === type) && (!cas || row.cas_no === cas));
}
