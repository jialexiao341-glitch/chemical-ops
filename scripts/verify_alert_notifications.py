"""本地 Prometheus → Alertmanager → webhook 触发、去重和恢复验收。"""

from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "deploy/observability/alerts.yml"


def reload_prometheus():
    subprocess.run(["docker", "exec", "chemicalops-observability-prometheus-1", "promtool", "check", "rules", "/etc/prometheus/alerts.yml"], check=True, capture_output=True)
    subprocess.run(["docker", "kill", "--signal=HUP", "chemicalops-observability-prometheus-1"], check=True, capture_output=True)


def main(output):
    identifier = uuid.uuid4().hex[:12]
    report = {"scope": "本机真实 Prometheus/Alertmanager 与本地专用 webhook；不代表外部生产通知送达", "acceptance_id": identifier}
    snippet = f'''\n  - name: chemicalops-notification-acceptance-{identifier}
    interval: 5s
    rules:
      - alert: ChemicalOpsNotificationAcceptance
        expr: vector(1) == 1
        labels:
          severity: info
          acceptance_id: "{identifier}"
        annotations:
          summary: "Local notification acceptance only"
'''
    false_snippet = snippet.replace("vector(1) == 1", "vector(0) == 1")
    with httpx.Client(timeout=10, trust_env=False) as client:
        def events():
            response = client.get("http://127.0.0.1:19093/events")
            response.raise_for_status()
            return [event for event in response.json() if event["payload"].get("commonLabels", {}).get("acceptance_id") == identifier]

        def wait_status(status):
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                found = events()
                if any(event["payload"]["status"] == status for event in found):
                    return found
                time.sleep(2)
            raise RuntimeError(f"No {status} notification received")

        try:
            RULES.write_text(RULES.read_text(encoding="utf-8") + snippet, encoding="utf-8")
            reload_prometheus()
            firing = wait_status("firing")
            print("firing received", flush=True)
            report["firing_received"] = True
            # 同一 fingerprint/startsAt 重复提交，不制造新告警或依赖重置状态。
            alert = firing[0]["payload"]["alerts"][0]
            duplicate = {key: alert[key] for key in ("labels", "annotations", "startsAt")}
            duplicate["endsAt"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            statuses = []
            for _ in range(3):
                response = client.post("http://127.0.0.1:9093/api/v2/alerts", json=[duplicate])
                response.raise_for_status()
                statuses.append(response.status_code)
            time.sleep(25)  # 超过两次 group_interval，低于 repeat_interval。
            report["duplicate_http_statuses"] = statuses
            report["dedup_observation_seconds"] = 25
            report["firing_notifications_after_duplicates"] = sum(event["payload"]["status"] == "firing" for event in events())
            assert report["firing_notifications_after_duplicates"] == 1
            print("duplicate suppression verified", flush=True)
            RULES.write_text(RULES.read_text(encoding="utf-8").replace(snippet, false_snippet), encoding="utf-8")
            reload_prometheus()
            received = wait_status("resolved")
            report["resolved_received"] = True
            report["events"] = received
            report["same_fingerprint"] = len({alert["fingerprint"] for event in received for alert in event["payload"]["alerts"]}) == 1
            assert report["same_fingerprint"]
            report["passed"] = True
            print("resolved received", flush=True)
        except Exception as exc:
            report.update(passed=False, error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            content = RULES.read_text(encoding="utf-8").replace(snippet, "").replace(false_snippet, "")
            RULES.write_text(content, encoding="utf-8")
            reload_prometheus()
            report["temporary_rule_removed"] = True
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="本次验收的新报告路径")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("输出文件已存在，请选择新路径以保留历史证据")
    main(args.output)
