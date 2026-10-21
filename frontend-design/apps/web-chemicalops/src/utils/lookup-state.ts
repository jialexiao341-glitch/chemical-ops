/** 主数据缓存状态与请求模块分离，避免 API/名称查询的循环依赖。 */
export const lookupCache = new Map<string, { expires: number; value: Map<number, string> }>();
export let lookupGeneration = 0;
export function clearLookupCache() { lookupCache.clear(); lookupGeneration += 1; }
