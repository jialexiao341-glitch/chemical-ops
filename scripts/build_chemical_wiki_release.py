"""从已配对资料构建具有原文依据的百科版本。"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.modules.jobs import wiki_drafts  # noqa: E402


def main():
    root = ROOT / 'data'
    records = wiki_drafts.list_pairs(root)
    target = root / 'chemical-wiki' / 'current'
    target.mkdir(parents=True, exist_ok=True)
    source_file = root / 'msds-drafts' / '原始资料.docx'
    canonical_source = target.parent / 'source.docx'
    expected = wiki_drafts.get_pair(root, records[0]['id'])['msds']['source']['sha256']
    if hashlib.sha256(source_file.read_bytes()).hexdigest() != expected:
        raise ValueError('原始资料与已抽取内容的哈希不一致')
    if canonical_source.exists() and hashlib.sha256(canonical_source.read_bytes()).hexdigest() != expected:
        raise ValueError('保存的来源文件已变化，拒绝覆盖')
    if not canonical_source.exists():
        shutil.copyfile(source_file, canonical_source)
    for item in records:
        pair = wiki_drafts.get_pair(root, item['id'])
        for doc in pair.values():
            doc.pop('status', None)
            doc.pop('published', None)
        (target / f"{item['id']:03d}.json").write_text(
            json.dumps(pair, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Built {len(records)} source-backed wiki entries")


if __name__ == '__main__':
    main()
