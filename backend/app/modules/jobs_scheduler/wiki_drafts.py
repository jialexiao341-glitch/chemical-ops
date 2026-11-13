"""只读访问初始原表与派生技术资料。"""

import json
from pathlib import Path


DATA_ROOT = Path(__file__).resolve().parents[4] / 'data'


def _paths(root: Path, source_id: int) -> tuple[Path, Path]:
    if source_id < 1:
        raise FileNotFoundError(source_id)
    paths = list((root / 'msds-drafts' / 'records').glob(f'{source_id:03d}-*.json'))
    if not paths:
        # 导入数据也可使用不含名称的编号文件。
        candidate = root / 'msds-drafts' / 'records' / f'{source_id:03d}.json'
        paths = [candidate] if candidate.is_file() else []
    if len(paths) != 1:
        raise FileNotFoundError(source_id)
    return paths[0], root / 'technical-candidates' / 'records' / paths[0].name


def get_pair(root: Path, source_id: int) -> dict:
    original_path, technical_path = _paths(root, source_id)
    original = json.loads(original_path.read_text(encoding='utf-8'))
    technical = json.loads(technical_path.read_text(encoding='utf-8'))
    if (original['source_table'] != source_id or technical['msds_draft_file'] != original_path.name
            or technical['source']['table'] != source_id
            or technical['source']['sha256'] != original['source']['sha256']):
        raise ValueError('MSDS 与技术草稿来源不一致')
    return {'msds': original, 'technical': technical}


def list_pairs(root: Path) -> list[dict]:
    directory = root / 'msds-drafts' / 'records'
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    records = []
    for path in sorted(directory.glob('*.json')):
        original = json.loads(path.read_text(encoding='utf-8'))
        # 配对缺失或来源不一致时不作为可用资料展示。
        get_pair(root, original['source_table'])
        records.append({'id': original['source_table'], 'name': original['name_from_heading'],
                        'cas_no': original['cas_candidate'], 'cas_valid_checksum': original['cas_valid_checksum'],
                        'status': 'DRAFT', 'identity_review_required': True})
    return records
