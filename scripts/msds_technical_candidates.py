"""从 MSDS 原表摘录中生成待核验的技术资料。"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path


IDENTITY_FIELDS = {"中文名", "英文名", "化学名", "商品名", "CAS号"}
MOLECULAR_FIELDS = {"分子式", "分子量"}
COMBUSTION_FIELDS = ("闪点", "燃烧性", "爆炸下限", "爆炸上限", "爆炸极限", "引燃温度", "最小点火能", "燃烧热")
SECTIONS = ("产品标识", "分子信息", "外观与溶解性", "理化性质", "燃烧相关性质", "储存与包装信息", "用途")


def make_candidate(source: dict) -> dict:
    items = []
    for row in source['rows']:
        cells = row['cells']
        if not cells:
            continue
        label = cells[0].strip()
        for index, text in enumerate(cells[1:], 2):
            if not text.strip():
                continue
            head, separator, value = text.partition('：')
            if not separator:
                head, separator, value = text.partition(':')
            field = unicodedata.normalize('NFKC', head).strip()
            if label == '用途':
                section = '用途'
            elif label == '贮运' and ('储运条件' in text or '包装方法' in text):
                section = '储存与包装信息'
            elif not separator or not value.strip():
                continue
            elif label == '标识' and field in IDENTITY_FIELDS:
                section = '产品标识'
            elif label == '标识' and field in MOLECULAR_FIELDS:
                section = '分子信息'
            elif label in {'理化性质', '燃烧爆炸危险性'} and field.startswith(COMBUSTION_FIELDS):
                section = '燃烧相关性质'
            elif label == '理化性质' and field in {'性状', '外观', '颜色', '气味', '溶解性'}:
                section = '外观与溶解性'
            elif label == '理化性质':
                section = '理化性质'
            else:
                continue
            items.append({'section': section, 'text': text, 'source_row': row['row'], 'source_cell': index})
    return {
        'document_type': 'technical_information_candidate',
        'source_type': 'msds',
        'status': 'DRAFT',
        'published': False,
        'identity_review_required': True,
        'name_from_heading': source['name_from_heading'],
        'cas_candidate': source['cas_candidate'],
        'cas_valid_checksum': source['cas_valid_checksum'],
        'source': {**source['source'], 'table': source['source_table'], 'heading': source['source_heading']},
        'sections': list(SECTIONS),
        'items': items,
        'specifications': [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_directory', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    inputs = sorted(args.source_directory.glob('*.json'))
    if not inputs:
        raise SystemExit('No MSDS draft files found')
    args.output_directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path in inputs:
        candidate = make_candidate(json.loads(path.read_text(encoding='utf-8')))
        candidate['msds_draft_file'] = path.name
        (args.output_directory / path.name).write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        manifest.append({'file': path.name, 'name_from_heading': candidate['name_from_heading'],
                         'cas_candidate': candidate['cas_candidate'],
                         'cas_valid_checksum': candidate['cas_valid_checksum'], 'item_count': len(candidate['items'])})
    (args.output_directory.parent / '目录.json').write_text(
        json.dumps({'source_type': 'msds', 'status': 'DRAFT', 'records': manifest}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(f'Prepared {len(manifest)} unpublished candidates')


if __name__ == '__main__':
    main()
