import json
import hashlib

import pytest

from app.modules.jobs import wiki_release


def test_release_exposes_current_pair_with_provenance_and_no_approval_state(tmp_path):
    release = tmp_path / 'chemical-wiki' / 'current'
    release.mkdir(parents=True)
    pair = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'}, 'name_from_heading': '乙醇',
                     'cas_candidate': '64-17-5', 'cas_valid_checksum': True, 'rows': []},
            'technical': {'msds_draft_file': '001.json', 'source': {'sha256': 'abc', 'table': 1}, 'items': []}}
    (release / '001.json').write_text(json.dumps(pair, ensure_ascii=False), encoding='utf-8')
    directory = wiki_release.list_entries(tmp_path)
    assert directory[0]['name'] == '乙醇'
    assert directory[0]['source_type'] == 'msds'
    assert wiki_release.get_entry(tmp_path, 1)['technical']['source']['table'] == 1


def test_release_rejects_mismatched_source_identity(tmp_path):
    release = tmp_path / 'chemical-wiki' / 'current'
    release.mkdir(parents=True)
    pair = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'}},
            'technical': {'source': {'sha256': 'other', 'table': 1}}}
    (release / '001.json').write_text(json.dumps(pair), encoding='utf-8')
    with pytest.raises(ValueError):
        wiki_release.get_entry(tmp_path, 1)


def test_release_rejects_technical_text_not_matching_original_cell(tmp_path):
    release = tmp_path / 'chemical-wiki' / 'current'
    release.mkdir(parents=True)
    pair = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'},
                     'rows': [{'row': 1, 'cells': ['理化性质', '沸点：78']}]},
            'technical': {'source': {'sha256': 'abc', 'table': 1},
                          'items': [{'source_row': 1, 'source_cell': 2, 'text': '沸点：79'}]}}
    (release / '001.json').write_text(json.dumps(pair), encoding='utf-8')
    with pytest.raises(ValueError):
        wiki_release.get_entry(tmp_path, 1)


def test_wiki_endpoints_enforce_existing_technical_role(monkeypatch):
    from app.modules.jobs import controller
    from fastapi import HTTPException

    def deny(*_args):
        raise HTTPException(status_code=403, detail='forbidden')

    monkeypatch.setattr(controller.technical_documents, 'require_technical_or_admin', deny)
    with pytest.raises(HTTPException) as listing:
        controller.chemical_wiki_list(db=object(), user=object())
    assert listing.value.status_code == 403
    with pytest.raises(HTTPException) as detail:
        controller.chemical_wiki_detail(1, db=object(), user=object())
    assert detail.value.status_code == 403


def test_source_status_distinguishes_missing_changed_and_current(tmp_path):
    root = tmp_path / 'chemical-wiki'
    root.mkdir()
    digest = hashlib.sha256(b'original').hexdigest()
    assert wiki_release.source_status(tmp_path, digest) == 'UNAVAILABLE'
    (root / 'source.docx').write_bytes(b'original')
    assert wiki_release.source_status(tmp_path, digest) == 'CURRENT'
    (root / 'source.docx').write_bytes(b'changed')
    assert wiki_release.source_status(tmp_path, digest) == 'CHANGED'
