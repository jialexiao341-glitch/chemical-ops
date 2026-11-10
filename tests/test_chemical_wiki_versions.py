import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.modules.jobs.wiki_versions import WikiVersion, create_version, history


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    WikiVersion.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def test_versions_keep_history_and_reject_stale_revision(db):
    pair = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'}, 'rows': []},
            'technical': {'source': {'table': 1, 'sha256': 'abc'}, 'items': []}}
    first = create_version(db, 1, 0, pair, '备注一', actor_id=1)
    assert first.version == 1
    second = create_version(db, 1, 1, pair, '备注二', actor_id=2)
    assert second.version == 2
    assert [v.note for v in history(db, 1)] == ['备注二', '备注一', '']
    with pytest.raises(ValueError, match='版本'):
        create_version(db, 1, 1, pair, '覆盖', actor_id=1)


def test_source_replacement_preserves_original_version_snapshot(db):
    old = {'msds': {'source_table': 1, 'source': {'sha256': 'old'}, 'rows': []},
           'technical': {'source': {'table': 1, 'sha256': 'old'}, 'items': []}}
    new = {'msds': {'source_table': 1, 'source': {'sha256': 'new'}, 'rows': []},
           'technical': {'source': {'table': 1, 'sha256': 'new'}, 'items': []}}
    create_version(db, 1, 0, new, '', actor_id=1, baseline=old)
    versions = history(db, 1)
    assert [(v.version, v.content['msds']['source']['sha256']) for v in versions] == [(1, 'new'), (0, 'old')]


def test_version_rejects_technical_text_without_matching_evidence(db):
    pair = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'},
                     'rows': [{'row': 1, 'cells': ['性质', '沸点：78']}]},
            'technical': {'source': {'table': 1, 'sha256': 'abc'},
                          'items': [{'source_row': 1, 'source_cell': 2, 'text': '沸点：99'}]}}
    with pytest.raises(ValueError, match='原文'):
        create_version(db, 1, 0, pair, '', actor_id=1)


def test_note_endpoint_uses_server_owned_source_not_client_data(db, monkeypatch):
    from types import SimpleNamespace
    from app.modules.jobs import controller, wiki_release
    baseline = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'}, 'rows': []},
                'technical': {'source': {'table': 1, 'sha256': 'abc'}, 'items': []}}
    monkeypatch.setattr(controller.technical_documents, 'require_technical_or_admin', lambda *_: None)
    monkeypatch.setattr(wiki_release, 'get_entry', lambda *_: baseline)
    user = SimpleNamespace(id=42)
    result = controller.chemical_wiki_add_version(1, controller.WikiVersionCreate(expected_version=0, note='说明'), db, user)
    assert result['version'] == 1
    assert history(db, 1)[0].content == baseline


def test_technical_edit_uses_only_exact_original_cells(db, monkeypatch):
    from types import SimpleNamespace
    from app.modules.jobs import controller, wiki_release
    baseline = {'msds': {'source_table': 1, 'source': {'sha256': 'abc'},
                         'rows': [{'row': 1, 'cells': ['理化性质', '沸点：78']} ]},
                'technical': {'source': {'table': 1, 'sha256': 'abc'}, 'items': [], 'sections': ['理化性质']}}
    monkeypatch.setattr(controller.technical_documents, 'require_technical_or_admin', lambda *_: None)
    monkeypatch.setattr(wiki_release, 'get_entry', lambda *_: baseline)
    data = controller.WikiVersionCreate(expected_version=0, note='', items=[{'section': '理化性质', 'source_row': 1, 'source_cell': 2}])
    controller.chemical_wiki_add_version(1, data, db, SimpleNamespace(id=42))
    item = history(db, 1)[0].content['technical']['items'][0]
    assert item['text'] == '沸点：78'


def test_technical_edit_rejects_forged_text():
    from pydantic import ValidationError
    from app.modules.jobs.schema import WikiVersionCreate

    with pytest.raises(ValidationError):
        WikiVersionCreate(expected_version=0, note='', items=[{'section': '理化性质', 'source_row': 1,
                          'source_cell': 2, 'text': '伪造内容'}])


def test_source_update_keeps_initial_version(db, monkeypatch):
    from types import SimpleNamespace
    from app.modules.jobs import controller, wiki_release, wiki_source

    original = {'msds': {'source_table': 1, 'source': {'sha256': 'old'}, 'rows': []},
                'technical': {'source': {'table': 1, 'sha256': 'old'}, 'items': []}}
    updated = {'msds': {'source_table': 1, 'source': {'sha256': 'new'}, 'rows': []},
               'technical': {'source': {'table': 1, 'sha256': 'new'}, 'items': []}}
    monkeypatch.setattr(controller.technical_documents, 'require_technical_or_admin', lambda *_: None)
    monkeypatch.setattr(wiki_release, 'get_entry', lambda *_: original)
    monkeypatch.setattr(wiki_source, 'load_source', lambda *_args, **_kwargs: (object(), []))
    monkeypatch.setattr(wiki_source, 'build_source_pair', lambda *_: updated)
    response = controller.chemical_wiki_update_source(1, controller.WikiSourceUpdate(expected_version=0, document_id=8),
                                                       db, SimpleNamespace(id=1))
    assert response['version'] == 1
    assert [(item.version, item.content['msds']['source']['sha256']) for item in history(db, 1)] == [(1, 'new'), (0, 'old')]


@pytest.mark.integration
def test_mysql_version_snapshot_roundtrip_is_transactional(db_session):
    from app.modules.jobs import wiki_release
    from app.modules.system.model import User
    from sqlalchemy import select

    user = db_session.scalar(select(User).limit(1))
    if user is None:
        pytest.skip('测试数据库没有用户')
    pair = wiki_release.get_entry(wiki_release.DATA_ROOT, 71)
    existing = history(db_session, 71)
    expected = existing[0].version if existing else 0
    result = create_version(db_session, 71, expected, pair, '事务测试', actor_id=user.id)
    assert result.version == expected + 1
    assert history(db_session, 71)[0].content['msds']['source_table'] == 71
