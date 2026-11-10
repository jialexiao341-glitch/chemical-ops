"""检查原表配对关系并标记需要核实的化学品身份。"""

from collections import Counter, defaultdict
from pathlib import Path
import csv
import json


def audit(msds: list[dict], tds: list[dict]) -> dict:
    files = {item['file'] for item in msds}
    pairs = Counter(item['msds_draft_file'] for item in tds)
    names, cas = defaultdict(list), defaultdict(list)
    for item in msds:
        names[item['name_from_heading']].append(item['file'])
        if item['cas_candidate']:
            cas[item['cas_candidate']].append(item['file'])
    return {
        'source_tables': len(msds), 'technical_drafts': len(tds),
        'missing_pairs': sorted(files - pairs.keys()),
        'duplicate_pairs': sorted(key for key, count in pairs.items() if count > 1),
        'orphan_pairs': sorted(pairs.keys() - files),
        'missing_cas': sorted(item['file'] for item in msds if not item['cas_candidate']),
        'invalid_cas': sorted(item['file'] for item in msds if item['cas_valid_checksum'] is False),
        'duplicate_names': {key: sorted(value) for key, value in sorted(names.items()) if len(value) > 1},
        'duplicate_cas': {key: sorted(value) for key, value in sorted(cas.items()) if len(value) > 1},
    }


def main():
    root = Path('data/msds-drafts/records')
    candidates = Path('data/technical-candidates/records')
    msds = [{**json.loads(path.read_text(encoding='utf-8')), 'file': path.name} for path in root.glob('*.json')]
    tds = [json.loads(path.read_text(encoding='utf-8')) for path in candidates.glob('*.json')]
    report = audit(msds, tds)
    Path('data/technical-candidates/配对与身份核对.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    duplicate_names = set(report['duplicate_names'])
    duplicate_cas = set(report['duplicate_cas'])
    with Path('data/technical-candidates/身份复核清单.csv').open('w', encoding='utf-8-sig', newline='') as target:
        columns = ['原表序号', '原表标题', '原文CAS', 'CAS候选', '检查项', 'MSDS文件', '技术草稿文件', '审核结论']
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for item in sorted(msds, key=lambda value: value['source_table']):
            reasons = []
            if not item['cas_candidate']:
                reasons.append('缺少CAS')
            elif item['cas_valid_checksum'] is False:
                reasons.append('CAS校验失败')
            if item['name_from_heading'] in duplicate_names:
                reasons.append('名称重复')
            if item['cas_candidate'] in duplicate_cas:
                reasons.append('CAS重复')
            writer.writerow({'原表序号': item['source_table'], '原表标题': item['source_heading'],
                '原文CAS': item['cas_raw'] or '', 'CAS候选': item['cas_candidate'] or '',
                '检查项': '；'.join(reasons) or '待人工确认身份', 'MSDS文件': item['file'],
                '技术草稿文件': item['file'], '审核结论': ''})
    print(f"{len(msds)} MSDS tables, {len(tds)} derived drafts; identity review required")


if __name__ == '__main__':
    main()
