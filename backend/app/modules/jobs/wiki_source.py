"""为百科保存和校验用户选定的原始文档快照。"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.doc_kb.model import AiDocument, AiDocumentSection


def fingerprint(document, sections) -> str:
    value = {'id': document.id, 'cas_no': document.cas_no, 'doc_type': document.doc_type,
             'parse_status': document.parse_status, 'sha256': document.sha256,
             'title': document.title, 'source_url': document.source_url, 'object_key': document.object_key,
             'sections': [{'id': s.id, 'section_no': s.section_no, 'section_key': s.section_key,
                           'title': s.title, 'content': s.content} for s in sections]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def load_source(db: Session, document_id: int, *, lock: bool = False):
    query = select(AiDocument).where(AiDocument.id == document_id)
    if lock:
        query = query.with_for_update()
    document = db.scalar(query)
    if document is None:
        return None, []
    sections = list(db.scalars(select(AiDocumentSection).where(AiDocumentSection.document_id == document_id)
                               .order_by(AiDocumentSection.section_no, AiDocumentSection.id)).all())
    return document, sections


def build_source_pair(old: dict, document, sections) -> dict:
    original = old['msds']
    cas = original.get('cas_candidate')
    if (not cas or original.get('cas_valid_checksum') is not True or document.cas_no != cas
            or document.doc_type != 'msds' or document.parse_status != 'PARSED' or not sections):
        raise ValueError('来源必须是同 CAS 且解析成功的 MSDS，并包含正文')
    digest = fingerprint(document, sections)
    source = {'kind': 'database_document', 'document_id': document.id, 'content_sha256': digest,
              'filename': document.title or document.object_key, 'sha256': document.sha256 or digest,
              'source_url': document.source_url, 'object_key': document.object_key}
    rows = [{'row': i, 'cells': [section.title or section.section_key, section.content],
             'source_section_id': section.id, 'source_section_key': section.section_key}
            for i, section in enumerate(sections, 1)]
    msds = {**original, 'source': source, 'source_heading': document.title or document.object_key, 'rows': rows}
    technical = {'source': {**source, 'table': original['source_table']},
                 'sections': list(old['technical']['sections']), 'items': [], 'source_type': 'msds'}
    return {'msds': msds, 'technical': technical}


def current_source_status(db: Session, content: dict, root) -> str:
    source = content['msds']['source']
    if source.get('kind') != 'database_document':
        from app.modules.jobs.wiki_release import source_status
        return source_status(root, source['sha256'])
    document, sections = load_source(db, source['document_id'])
    if document is None:
        return 'UNAVAILABLE'
    if document.parse_status != 'PARSED':
        return 'CHANGED'
    return 'CURRENT' if fingerprint(document, sections) == source['content_sha256'] else 'CHANGED'
