from types import SimpleNamespace

import pytest

from app.modules.jobs.wiki_source import build_source_pair, fingerprint


def test_new_source_pair_preserves_old_identity_and_full_section():
    old = {'msds': {'source_table': 4, 'name_from_heading': '乙醇', 'cas_candidate': '64-17-5',
                    'cas_valid_checksum': True},
           'technical': {'sections': ['产品标识', '理化性质']}}
    document = SimpleNamespace(id=9, cas_no='64-17-5', doc_type='msds', parse_status='PARSED',
                               sha256='rawhash', title='乙醇 SDS', source_url=None, object_key='x')
    sections = [SimpleNamespace(id=10, section_no=1, section_key='s1', title='标识', content='乙醇原文')]
    pair = build_source_pair(old, document, sections)
    assert pair['msds']['rows'][0]['cells'] == ['标识', '乙醇原文']
    assert pair['technical']['items'] == []
    assert pair['msds']['source']['content_sha256'] == fingerprint(document, sections)
    assert pair['msds']['source']['document_id'] == 9
    assert pair['msds']['source_table'] == 4


def test_new_source_rejects_wrong_cas_and_unparsed_documents():
    old = {'msds': {'source_table': 4, 'cas_candidate': '64-17-5', 'cas_valid_checksum': True},
           'technical': {'sections': []}}
    wrong = SimpleNamespace(cas_no='67-56-1', doc_type='msds', parse_status='PARSED')
    with pytest.raises(ValueError):
        build_source_pair(old, wrong, [])
    wrong.cas_no = '64-17-5'
    wrong.parse_status = 'REJECTED'
    with pytest.raises(ValueError):
        build_source_pair(old, wrong, [])


def test_changed_source_keeps_old_snapshot_and_reports_change(monkeypatch):
    from app.modules.jobs import wiki_source

    original = {'msds': {'source_table': 4, 'name_from_heading': '乙醇', 'cas_candidate': '64-17-5',
                         'cas_valid_checksum': True}, 'technical': {'sections': []}}
    document = SimpleNamespace(id=9, cas_no='64-17-5', doc_type='msds', parse_status='PARSED',
                               sha256='rawhash', title='乙醇 SDS', source_url=None, object_key='x')
    section = SimpleNamespace(id=10, section_no=1, section_key='s1', title='标识', content='旧内容')
    pair = build_source_pair(original, document, [section])
    monkeypatch.setattr(wiki_source, 'load_source', lambda *_args, **_kwargs: (document, [section]))
    assert wiki_source.current_source_status(None, pair, None) == 'CURRENT'
    section.content = '新内容'
    assert wiki_source.current_source_status(None, pair, None) == 'CHANGED'
    assert pair['msds']['rows'][0]['cells'][1] == '旧内容'
