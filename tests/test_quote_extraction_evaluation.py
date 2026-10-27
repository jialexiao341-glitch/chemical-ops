"""评测器必须区分解析、抽取和来源校验；不能把有效引句等同字段真实。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace as NS
import sys

import pytest

from scripts import evaluate_quote_extraction as evaluation


def test_oracle_rejects_supported_quote_with_unsupported_values():
    sample=evaluation.cases()['unsupported_fields']
    observed=deepcopy(sample['prediction'])
    observed['items'][0]['source_quote']=observed['items'][0].pop('quote')
    checks=evaluation.check_candidate(observed,sample['expected'])
    assert checks['items[0].unit_price'] is True
    assert checks['items[0].tax_rate'] is False
    assert checks['items[0].lead_days'] is False


def test_real_pdf_and_xlsx_parsers_preserve_locations():
    from app.modules.files.parser import parse_file_content
    for extension,location in [('pdf','第 2 页'),('xlsx','工作表：Quote · 第 6 行')]:
        content=evaluation.sample_bytes(extension)
        parsed=parse_file_content('quote.'+extension,'application/octet-stream',content)
        assert parsed.status=='SUCCEEDED'
        assert evaluation.quote_extraction._source_location(parsed.text,evaluation.ITEM_LINE) == location


def test_oracle_accepts_equivalent_decimal_representation_but_not_wrong_numbers():
    expected=evaluation.base_expected()
    candidate=deepcopy(expected)
    candidate['items'][0]['unit_price']='12.500000'
    assert all(evaluation.check_candidate(candidate,expected).values())
    candidate['items'][0]['unit_price']='125.0'
    assert not evaluation.check_candidate(candidate,expected)['items[0].unit_price']


def test_expected_fields_are_independent_of_simulated_model_output(monkeypatch):
    changed=evaluation.base_prediction()
    changed['items'][0]['unit_price']='999'
    changed['currency_code']='USD'
    monkeypatch.setattr(evaluation,'base_prediction',lambda:changed)
    expected=evaluation.base_expected()
    assert expected['items'][0]['unit_price']=='12.50'
    assert expected['currency_code']=='CNY'


def test_cli_refuses_to_replace_historical_evidence(tmp_path,monkeypatch):
    output=tmp_path/'original.json'
    output.write_text('original evidence',encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['evaluate_quote_extraction.py','--output',str(output)])
    with pytest.raises(SystemExit) as caught: evaluation.main()
    assert caught.value.code==2
    assert output.read_text(encoding='utf-8')=='original evidence'


def test_scan_fixture_has_no_selectable_text():
    from app.modules.files.parser import parse_file_content
    parsed=parse_file_content('scan.pdf','application/pdf',evaluation.sample_bytes('scan'))
    assert parsed.status!='SUCCEEDED' and not parsed.text.strip()


def test_offline_suite_distinguishes_regressions_from_real_model_quality():
    report=evaluation.run_offline()
    assert report['real_model_evaluated'] is False
    assert report['real_ocr_evaluated'] is False
    assert report['business_writes'] is False
    rows={row['id']:row for row in report['cases']}
    assert report['summary']['failed']==sum(not row['passed'] for row in rows.values())
    assert rows['pdf']['passed'] and rows['xlsx']['passed']
    assert rows['scan_without_ocr']['passed']
    assert rows['fabricated_quote']['passed']
    assert rows['unsupported_fields']['expected']['items'][0]['tax_rate'] is None
    assert rows['header_mismatch']['expected']['currency_code'] is None
    assert rows['wrong_existing_rfq_line']['expected']['items'][0]['rfq_item_id'] is None
    assert report['summary']=={'total':12,'passed':12,'failed':0}


def test_manual_corrections_reach_quote_and_total_cost_without_being_replaced_by_candidates(monkeypatch):
    from app.modules.rfqs import service
    from app.modules.rfqs.schema import SupplierQuoteCreate
    from app.modules.rfqs.total_cost import calculate_total_cost
    candidate=evaluation.run_case('csv',evaluation.cases()['csv'])['candidate']
    item=candidate['items'][0]
    # 人工复核主动修订单价、税率、数量与账期，并明确录入无运费。
    data=SupplierQuoteCreate(supplier_id=8,source_file_id=candidate['file_id'],currency_code='CNY',items=[{
        'rfq_item_id':item['rfq_item_id'],'unit_id':1,'unit_price':'14.25','quoted_quantity':'20',
        'tax_rate':'9','tax_included':False,'moq_quantity':item['moq_quantity'],'moq_unit_id':1,
        'freight_amount':'0','freight_tax_rate':'0','freight_tax_included':True,'payment_terms':'net 45 days'}])
    class Db:
        quote=None
        commits=0
        def get(self,*_): return NS(uploader_id=1,file_category='SUPPLIER_QUOTE')
        def scalar(self,*_): return None
        def add(self,quote): self.quote=quote
        def flush(self): self.quote.id=201
        def commit(self): self.commits+=1
    db=Db(); rfq=NS(id=14,status='RESPONDING',items=[NS(id=31)])
    monkeypatch.setattr(service.crud,'get_supplier',lambda *_:NS(status='ACTIVE',supplier_code='DEMO'))
    monkeypatch.setattr(service.crud,'get_invitation',lambda *_:NS(response_status='PENDING'))
    monkeypatch.setattr(service.crud,'get_unit',lambda *_:NS(status='ACTIVE'))
    monkeypatch.setattr(service.crud,'get_by_id',lambda *_:rfq)
    monkeypatch.setattr(service,'add_audit_log',lambda *_,**kw:None)
    service.create_quote_for_supplier(db,NS(id=1),rfq,8,data)
    saved=db.quote.items[0]
    assert db.commits==1 and db.quote.source_file_id==candidate['file_id']
    assert saved.unit_price==Decimal('14.25') and saved.tax_rate==Decimal('9')
    assert saved.payment_terms=='net 45 days'
    cost=calculate_total_cost(requested_quantity=Decimal('10'),requested_unit_id=1,quoted_unit_id=saved.unit_id,
        unit_price=saved.unit_price,tax_rate=saved.tax_rate,tax_included=saved.tax_included,
        moq_quantity=saved.moq_quantity,moq_unit_id=saved.moq_unit_id,freight_amount=saved.freight_amount,
        freight_tax_rate=saved.freight_tax_rate,freight_tax_included=saved.freight_tax_included)
    assert cost.complete and cost.total_cost==Decimal('310.65')
