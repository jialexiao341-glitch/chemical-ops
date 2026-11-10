"""读取指定版本的化学品百科原文和技术资料。"""

import hashlib
import json
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[4] / 'data'


def source_status(root: Path, expected_sha256: str) -> str:
    source = root / 'chemical-wiki' / 'source.docx'
    try:
        with source.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    except OSError:
        return 'UNAVAILABLE'
    return 'CURRENT' if digest == expected_sha256 else 'CHANGED'


def get_entry(root: Path, source_id: int) -> dict:
    if not 1 <= source_id <= 999999:
        raise FileNotFoundError(source_id)
    path = root / 'chemical-wiki' / 'current' / f'{source_id:03d}.json'
    result = json.loads(path.read_text(encoding='utf-8'))
    validate_pair(result, source_id)
    return result


def validate_pair(result: dict, source_id: int) -> None:
    original, technical = result['msds'], result['technical']
    if (original['source_table'] != source_id or technical['source']['table'] != source_id
            or technical['source']['sha256'] != original['source']['sha256']):
        raise ValueError('MSDS 与技术内容来源不一致')
    rows = {row['row']: row['cells'] for row in original.get('rows', [])}
    for item in technical.get('items', []):
        cells = rows.get(item['source_row'], [])
        index = item['source_cell'] - 1
        if index < 0 or index >= len(cells) or cells[index] != item['text']:
            raise ValueError('技术内容与 MSDS 原文不一致')


def list_entries(root: Path) -> list[dict]:
    directory = root / 'chemical-wiki' / 'current'
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    result = []
    for path in sorted(directory.glob('*.json')):
        if not path.stem.isdecimal():
            continue
        entry = get_entry(root, int(path.stem))
        original = entry['msds']
        result.append({'id': original['source_table'], 'name': original['name_from_heading'],
                       'cas_no': original['cas_candidate'], 'cas_valid_checksum': original['cas_valid_checksum'],
                       'source_type': 'msds'})
    return result
