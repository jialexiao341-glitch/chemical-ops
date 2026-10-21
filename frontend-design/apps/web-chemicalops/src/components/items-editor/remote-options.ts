export interface RemoteOption { label: string; value: number }
export function createRemoteOptions(
  load: (keyword: string) => Promise<RemoteOption[]>,
  byId: (id: number) => Promise<RemoteOption>,
) {
  let revision = 0;
  let found: RemoteOption[] = [];
  const selected = new Map<number, RemoteOption>();
  return {
    options: () => [...new Map([...selected.values(), ...found].map((item) => [item.value, item])).values()],
    async search(keyword: string) {
      const current = ++revision;
      const result = await load(keyword);
      if (current === revision) found = result;
    },
    async hydrate(ids: number[]) {
      const values = [...new Set(ids)];
      const result = await Promise.all(values.map(async (id) => found.find((item) => item.value === id) ?? selected.get(id) ?? await byId(id)));
      selected.clear();
      for (const item of result) selected.set(item.value, item);
    },
  };
}
