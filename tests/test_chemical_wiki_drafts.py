import json

import pytest

from app.modules.jobs import wiki_drafts


def test_paired_draft_directory_and_detail_keep_source(tmp_path):
    msds = tmp_path / 'msds-drafts' / 'records'
    tds = tmp_path / 'technical-candidates' / 'records'
    msds.mkdir(parents=True)
    tds.mkdir(parents=True)
    original = {'source_table': 1, 'source': {'sha256': 'abc'}, 'name_from_heading': '乙醇',
                'cas_candidate': '64-17-5', 'cas_valid_checksum': True,
                'rows': [{'row': 1, 'cells': ['标识', '中文名：乙醇']}]}
    candidate = {'msds_draft_file': '001.json', 'source': {'sha256': 'abc', 'table': 1},
                 'items': [{'section': '产品标识', 'text': '中文名：乙醇', 'source_row': 1, 'source_cell': 2}]}
    (msds / '001.json').write_text(json.dumps(original), encoding='utf-8')
    (tds / '001.json').write_text(json.dumps(candidate), encoding='utf-8')
    directory = wiki_drafts.list_pairs(tmp_path)
    assert directory == [{'id': 1, 'name': '乙醇', 'cas_no': '64-17-5', 'cas_valid_checksum': True,
                          'status': 'DRAFT', 'identity_review_required': True}]
    result = wiki_drafts.get_pair(tmp_path, 1)
    assert result['msds']['rows'] == original['rows']
    assert result['technical']['items'] == candidate['items']


def test_pair_detail_fails_closed_on_wrong_source_or_missing_file(tmp_path):
    msds = tmp_path / 'msds-drafts' / 'records'
    tds = tmp_path / 'technical-candidates' / 'records'
    msds.mkdir(parents=True)
    tds.mkdir(parents=True)
    (msds / '001.json').write_text(json.dumps({'source_table': 1, 'source': {'sha256': 'abc'}}), encoding='utf-8')
    (tds / '001.json').write_text(json.dumps({'msds_draft_file': '001.json', 'source': {'sha256': 'other', 'table': 1}}), encoding='utf-8')
    with pytest.raises(ValueError):
        wiki_drafts.get_pair(tmp_path, 1)
    with pytest.raises(FileNotFoundError):
        wiki_drafts.get_pair(tmp_path, 2)
