"""引用必须来自当前可用文档；向量 payload 不能充当已核验事实。"""
import asyncio
from types import SimpleNamespace

import pytest

from app.modules.doc_kb import retrieve


@pytest.mark.parametrize('status,exists,expected', [('PARSED', True, 1), ('FAILED', True, 0), ('PARSED', False, 0)])
def test_vector_sources_are_revalidated_and_use_current_excerpt(monkeypatch, status, exists, expected):
    async def targets(*_args):
        return []

    async def embed(*_args):
        return [[0.1]]

    section = SimpleNamespace(id=1, cas_no='67-56-1', doc_type='msds', section_no=9,
                              section_key='SECTION 9', title='物理性质', content='数据库当前摘录：沸点64.7℃')
    rows = [(section, 7, '甲醇 MSDS', '甲醇', 'https://example.com/msds', status, None)] if exists else []
    db = SimpleNamespace(execute=lambda *_args: SimpleNamespace(all=lambda: rows), commit=lambda: None)
    monkeypatch.setattr(retrieve, 'resolve_doc_targets', targets)
    monkeypatch.setattr(retrieve, 'embed_texts', embed)
    monkeypatch.setattr(retrieve.vector_store, 'get_client', lambda: object())
    monkeypatch.setattr(retrieve.vector_store, 'search_sections', lambda *_args, **_kwargs: [
        {'id': 1, 'score': 0.9, 'payload': {'cas_no': 'FAKE', 'name_zh': '错误名称', 'content': '过期或伪造的向量内容'}}])
    hits = asyncio.run(retrieve.retrieve_sections(db, '查询物性'))
    assert len(hits) == expected
    if hits:
        assert hits[0].content == section.content and hits[0].name_zh == '甲醇'
        assert hits[0].cas_no == '67-56-1' and hits[0].document_id == 7
        context, citations = retrieve.build_doc_context(hits)
        assert section.content in context
        assert citations[0]['content'] == section.content
        assert citations[0]['context_included'] is True
        assert '每个事实段落' in context
