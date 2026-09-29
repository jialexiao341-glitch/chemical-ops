import { requestClient } from '#/api/request';

export namespace BusinessInsightApi {
  export interface Evidence {
    label: string;
    value: string;
    source: string;
    path: null | string;
  }

  export interface Insight {
    kind: string;
    title: string;
    audience: string;
    summary: string;
    evidence: Evidence[];
    suggestions: string[];
    limitations: string[];
  }
}

/** 获取指定业务对象的只读分析结果。 */
export async function getBusinessInsightApi(kind: string, objectId: number) {
  return requestClient.get<BusinessInsightApi.Insight>(
    `/insights/${kind}/${objectId}`,
  );
}
