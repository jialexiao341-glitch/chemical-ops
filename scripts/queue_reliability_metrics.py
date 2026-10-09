"""Statistics for archived queue reliability evidence; no broker or database access."""
import math

GROUPS = {'normal': 200, 'duplicate_delivery': 200, 'ack_lost': 150,
          'publisher_crash': 150, 'worker_crash': 100, 'broker_outage': 100, 'stage_retry': 100}


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*fraction)-1)] if values else None


def metrics(rows):
    groups = {}
    for group in GROUPS:
        selected = [r for r in rows if r['group'] == group]
        recovery = [r['recovery_seconds'] for r in selected if r.get('recovery_seconds') is not None]
        groups[group] = dict(unique_tasks=len(selected), correct=sum(r['correct'] for r in selected),
            duplicate_side_effects=sum(r['duplicate_side_effects'] for r in selected),
            missing_side_effects=sum(r['missing_side_effects'] for r in selected),
            recovery_samples=len(recovery), recovery_p50_seconds=percentile(recovery,.5), recovery_p95_seconds=percentile(recovery,.95))
    return dict(unique_tasks=len(rows), correct=sum(r['correct'] for r in rows),
        success_rate=sum(r['correct'] for r in rows)/len(rows) if rows else None,
        duplicate_side_effects=sum(r['duplicate_side_effects'] for r in rows),
        unrecovered=sum(not r['correct'] for r in rows), groups=groups)


