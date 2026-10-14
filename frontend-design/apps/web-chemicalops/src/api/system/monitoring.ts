import { requestClient } from '#/api/request';

export namespace SystemMonitoringApi {
  export interface Alert {
    active_at?: null | string;
    description: string;
    id: string;
    name: string;
    severity: string;
    state: string;
    summary: string;
  }

  export interface Target {
    health: string;
    instance: string;
    job: string;
    last_error: string;
    last_scrape?: null | string;
  }

  export interface Rule {
    health: string;
    id: string;
    last_evaluation?: null | string;
    name: string;
    state: string;
  }

  export interface Overview {
    alerts: Alert[];
    checked_at: string;
    firing_alerts: number;
    healthy_targets: number;
    pending_alerts: number;
    rule_count: number;
    target_count: number;
    targets: Target[];
    rules: Rule[];
  }
}

/** 管理员运行监控概览；Prometheus 凭据与地址由后端持有。 */
export function getSystemMonitoringOverviewApi() {
  return requestClient.get<SystemMonitoringApi.Overview>(
    '/system/monitoring/overview',
  );
}
