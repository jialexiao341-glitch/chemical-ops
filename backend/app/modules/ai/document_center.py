"""业务文件只读聚合；每次读取都重新检查单据和文件权限。"""

from sqlalchemy import exists, func, or_, select

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.files import service as files
from app.modules.finance import service as finance
from app.modules.finance.model import FinanceInvoice
from app.modules.quality_acceptances import service as quality
from app.modules.quality_acceptances.model import QualityAcceptance, QualityReportReviewRecord
from app.modules.quality_acceptances.scope import acceptance_read_condition
from app.modules.rfqs import service as rfqs
from app.modules.rfqs.model import RFQ, SupplierQuote
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.file_model import SysFile, SysFileAttachment


def review_references(review, file_name, acceptance_id):
    return [{"file_id": review.file_id, "file_name": file_name,
             "object_type": "quality_acceptance", "object_id": acceptance_id,
             "field": check.get("item_name"), "quote": check.get("source_quote"),
             "location": check.get("source_location")}
            for check in (review.result_json or {}).get("checks", [])]


def _collect(db, user, *, kind=None, object_id=None, file_id=None, keyword=None):
    permissions = set(get_user_permission_codes(db, user.id))
    roles = set(get_user_role_codes(db, user.id))
    admin = "SYS_ADMIN" in roles
    rows = []
    if kind in (None, 'quote') and (admin or "procurement.rfqs.read" in permissions):
        query = select(SupplierQuote, RFQ).join(RFQ, RFQ.id == SupplierQuote.rfq_id)
        if keyword:
            needle = keyword.casefold()
            query = query.outerjoin(SysFile, SysFile.id == SupplierQuote.source_file_id).where(or_(
                func.lower(SupplierQuote.quote_no).contains(needle, autoescape=True),
                func.lower(RFQ.rfq_no).contains(needle, autoescape=True),
                func.lower(func.coalesce(SysFile.file_name, '未关联文件')).contains(needle, autoescape=True),
            ))
        if object_id is not None:
            query = query.where(RFQ.id == object_id)
        if file_id is not None:
            query = query.where(SupplierQuote.source_file_id == file_id)
        from app.modules.rfqs.scope import rfq_read_condition
        query = query.where(rfq_read_condition(user, roles))
        for quote, rfq in db.execute(query):
            rows.append(dict(type="quote", object_id=rfq.id, file_id=quote.source_file_id,
                             document_no=quote.quote_no, parent_no=rfq.rfq_no, status=quote.status))
    if kind in (None, 'invoice') and (admin or "finance.invoices.read" in permissions):
        query = select(FinanceInvoice).where(finance._scope_condition(db, user, FinanceInvoice))
        if keyword:
            needle = keyword.casefold()
            query = query.outerjoin(SysFile, SysFile.id == FinanceInvoice.source_file_id).where(or_(
                func.lower(FinanceInvoice.invoice_no).contains(needle, autoescape=True),
                func.lower(func.coalesce(SysFile.file_name, '未关联文件')).contains(needle, autoescape=True),
            ))
        if object_id is not None:
            query = query.where(FinanceInvoice.id == object_id)
        if file_id is not None:
            query = query.where(FinanceInvoice.source_file_id == file_id)
        for invoice in db.scalars(query):
            rows.append(dict(type="invoice", object_id=invoice.id, file_id=invoice.source_file_id,
                             document_no=invoice.invoice_no, parent_no=None, status=invoice.status))
    if kind in (None, 'quality') and (admin or "quality.acceptances.read" in permissions):
        scope = acceptance_read_condition(user, roles)
        direct = select(QualityAcceptance).where(scope)
        attachments = select(SysFileAttachment.resource_id, SysFileAttachment.file_id).join(QualityAcceptance, QualityAcceptance.id == SysFileAttachment.resource_id).where(SysFileAttachment.resource_type == "QUALITY_ACCEPTANCE", scope)
        if keyword:
            needle = keyword.casefold()
            attached_match = exists(select(SysFileAttachment.id).join(SysFile, SysFile.id == SysFileAttachment.file_id).where(
                SysFileAttachment.resource_type == 'QUALITY_ACCEPTANCE', SysFileAttachment.resource_id == QualityAcceptance.id,
                func.lower(SysFile.file_name).contains(needle, autoescape=True),
            ))
            direct_match = exists(select(SysFile.id).where(SysFile.id == QualityAcceptance.report_file_id,
                func.lower(SysFile.file_name).contains(needle, autoescape=True)))
            missing_match = QualityAcceptance.report_file_id.is_(None) if needle in '未关联文件' else False
            condition = or_(func.lower(QualityAcceptance.acceptance_no).contains(needle, autoescape=True), attached_match, direct_match, missing_match)
            direct = direct.where(condition)
            attachments = attachments.where(condition)
        if object_id is not None:
            direct = direct.where(QualityAcceptance.id == object_id)
            attachments = attachments.where(QualityAcceptance.id == object_id)
        if file_id is not None:
            direct = direct.where(QualityAcceptance.report_file_id == file_id)
            attachments = attachments.where(SysFileAttachment.file_id == file_id)
        acceptances = list(db.scalars(direct))
        pairs = {(a.id, a.report_file_id) for a in acceptances if a.report_file_id is not None}
        pairs.update(db.execute(attachments).all())
        if file_id is None:
            linked = {pair[0] for pair in pairs}
            pairs.update((a.id, None) for a in acceptances if a.id not in linked)
        for acceptance_id, file_id in pairs:
            acceptance = db.get(QualityAcceptance, acceptance_id)
            if acceptance is not None:
                rows.append(dict(type="quality", object_id=acceptance.id, file_id=file_id,
                                 document_no=acceptance.acceptance_no, parent_no=None, status=acceptance.result))
    ids = list({row['file_id'] for row in rows if row['file_id'] is not None})
    files_by_id = {}
    for start in range(0, len(ids), 500):
        for file in db.scalars(select(SysFile).where(SysFile.id.in_(ids[start:start + 500]))):
            files_by_id[file.id] = file
    for row in rows:
        file = files_by_id.get(row['file_id'])
        row["file_name"] = file.file_name if file else ('未关联文件' if row['file_id'] is None else None)
        row["file_parse_status"] = file.parse_status if file else None
        row["id"] = f'{row["type"]}:{row["object_id"]}:{row["file_id"]}:{row["document_no"]}'
    return rows


def _visible(db, user, row):
    try:
        {"quote": rfqs.get_rfq, "invoice": finance.get_invoice, "quality": quality.get_acceptance}[row["type"]](db, user, row["object_id"])
        if row["file_id"] is not None:
            files.get_file(db, user, row["file_id"])
        return True
    except (AuthorizationError, BusinessValidationError, ResourceNotFoundError):
        return False


def list_documents(db, user, *, kind, keyword, page, page_size):
    rows = []
    for row in _collect(db, user, kind=kind, keyword=keyword):
        if kind and row["type"] != kind:
            continue
        if keyword and keyword.casefold() not in " ".join(str(row.get(k) or "") for k in ("file_name", "document_no", "parent_no")).casefold():
            continue
        if not _visible(db, user, row):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row["file_id"] or 0, row["type"], row["object_id"]), reverse=True)
    total = len(rows)
    page_rows = rows[(page - 1) * page_size:page * page_size]
    for row in page_rows:
        if row['type'] == 'quality' and row['file_id'] is not None:
            review = db.scalar(select(QualityReportReviewRecord).where(
                QualityReportReviewRecord.acceptance_id == row['object_id'],
                QualityReportReviewRecord.file_id == row['file_id'],
            ).order_by(QualityReportReviewRecord.id.desc()).limit(1))
            row['review_status'] = review.status if review else None
    return {"items": page_rows, "total": total, "page": page, "page_size": page_size}


def references(db, user, kind, object_id, file_id):
    row = next((row for row in _collect(db, user, kind=kind, object_id=object_id, file_id=file_id) if row["type"] == kind and row["object_id"] == object_id and row["file_id"] == file_id), None)
    if row is None or not _visible(db, user, row):
        raise ResourceNotFoundError("文档不存在")
    if kind != "quality":
        return {"references": [], "message": "未保存解析依据"}
    reviews = list(db.scalars(select(QualityReportReviewRecord).where(QualityReportReviewRecord.acceptance_id == object_id, QualityReportReviewRecord.file_id == file_id).order_by(QualityReportReviewRecord.id.desc()).limit(101)).all())
    if not reviews:
        return {"references": [], "message": "未保存报告核对依据"}
    items = []
    for review in reviews[:100]:
        for item in review_references(review, row["file_name"], object_id):
            item.update(review_id=review.id, delivery_item_id=review.delivery_item_id, review_status=review.status)
            items.append(item)
    message = "仅显示最近 100 条核对记录" if len(reviews) > 100 else (None if items else "核对记录未保存原文依据")
    return {"references": items, "message": message}
