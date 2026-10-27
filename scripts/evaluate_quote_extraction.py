"""报价抽取专项评测：合成文件、独立字段预期；不连接业务库或创建报价。"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.config import get_settings
from app.core.errors import BusinessValidationError
from app.modules.files.parser import ParsedFile, parse_file_content
from app.modules.rfqs import quote_extraction

HEADER_LINES=['Supplier: Demo A','Currency: CNY','Quote date: 2026-10-20','Valid until: 2026-11-20']
ITEM_LINE='Ethanol | Model E99 | Quantity 10 L | Unit price 12.50 CNY/L | Tax 13% excluded | MOQ 20 L | Lead 7 days | Payment net 30 days'
TEXT='\n'.join([*HEADER_LINES,ITEM_LINE])


@lru_cache(maxsize=4)
def sample_bytes(kind: str) -> bytes:
    if kind=='csv': return TEXT.encode('utf-8')
    if kind=='xlsx':
        from openpyxl import Workbook
        book=Workbook(); sheet=book.active; sheet.title='Quote'
        for line in HEADER_LINES: sheet.append([line])
        sheet.append(['Product and commercial terms']); sheet.append([ITEM_LINE])
        out=BytesIO(); book.save(out); book.close(); return out.getvalue()
    if kind=='pdf':
        # 使用项目已有 pypdf 构造真实、两页、可选中文本的最小 PDF 测试文件。
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer=PdfWriter()
        for lines in [HEADER_LINES,[ITEM_LINE]]:
            page=writer.add_blank_page(width=1100,height=600)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            escaped=[line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)') for line in lines]
            stream=DecodedStreamObject()
            stream.set_data(('BT /F1 10 Tf 40 550 Td '+' '.join(f'({line}) Tj 0 -24 Td' for line in escaped)+' ET').encode('ascii'))
            page[NameObject('/Contents')]=writer._add_object(stream)
        out=BytesIO(); writer.write(out); return out.getvalue()
    if kind=='scan':
        from PIL import Image, ImageDraw, ImageFont
        image=Image.new('RGB',(1800,700),'white')
        draw=ImageDraw.Draw(image)
        try: font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
        except OSError: font=ImageFont.load_default(size=22)
        lines=[*HEADER_LINES,'Ethanol | Model E99 | Quantity 10 L | Unit price 12.50 CNY/L',
               'Tax 13% excluded | MOQ 20 L | Lead 7 days | Payment net 30 days']
        for i,line in enumerate(lines): draw.text((40,40+i*65),line,fill='black',font=font)
        out=BytesIO(); image.save(out,format='PDF',resolution=144); return out.getvalue()
    raise ValueError('unknown synthetic format')


def base_prediction():
    return {'supplier_name':'Demo A','currency_code':'CNY','quote_date':'2026-10-20','valid_until':'2026-11-20','note':None,
        'evidence':dict(zip(['supplier_name','currency_code','quote_date','valid_until'],HEADER_LINES)),
        'items':[{'rfq_item_id':31,'product_label':'Ethanol','supplier_model':'E99','quoted_quantity':'10',
            'unit_name':'L','unit_price':'12.50','tax_rate':'13','tax_included':False,'moq_quantity':'20',
            'moq_unit_name':'L','lead_days':7,'payment_terms':'net 30 days','freight_amount':None,
            'freight_tax_rate':None,'freight_tax_included':None,'quote':ITEM_LINE,
            'evidence':{'product_label':'Ethanol','supplier_model':'Model E99','quoted_quantity':'Quantity 10 L',
                'unit_name':'Quantity 10 L','unit_price':'Unit price 12.50 CNY/L','tax_rate':'Tax 13%',
                'tax_included':'Tax 13% excluded','moq_quantity':'MOQ 20 L','moq_unit_name':'MOQ 20 L',
                'lead_days':'Lead 7 days','payment_terms':'Payment net 30 days'}}]}


def base_expected():
    # 人工按 HEADER_LINES / ITEM_LINE 标注；不得从被测输出或模拟响应反推评分答案。
    return {'supplier_name':'Demo A','currency_code':'CNY','quote_date':'2026-10-20','valid_until':'2026-11-20','note':None,
        'items':[{'rfq_item_id':31,'product_label':'Ethanol','supplier_model':'E99','quoted_quantity':'10',
            'unit_name':'L','unit_price':'12.50','tax_rate':'13','tax_included':False,'moq_quantity':'20',
            'moq_unit_name':'L','lead_days':7,'payment_terms':'net 30 days','freight_amount':None,
            'freight_tax_rate':None,'freight_tax_included':None}]}


def cases():
    result={kind:{'kind':kind,'prediction':base_prediction(),'expected':base_expected()} for kind in ('csv','pdf','xlsx')}
    result['scan_without_ocr']={'kind':'scan','prediction':base_prediction(),'reject':True}
    result['scan_stub_ocr']={'kind':'scan','prediction':base_prediction(),'expected':base_expected(),'stub_ocr':True}
    result['corrupt_pdf']={'kind':'pdf','bytes':b'%PDF-1.4\nnot a valid document','prediction':base_prediction(),'reject':True}
    result['infected']={'kind':'csv','prediction':base_prediction(),'scan_status':'INFECTED','reject':True}
    result['fabricated_quote']={'kind':'csv','prediction':base_prediction(),'reject':True}
    result['fabricated_quote']['prediction']['items'][0]['quote']='not present in the source'
    missing=base_prediction()
    missing['items'][0]['quote']='Ethanol | Quantity 10 L | Unit price 12.50 CNY/L'
    truth=base_expected()
    for field in ('supplier_model','tax_rate','tax_included','moq_quantity','moq_unit_name','lead_days','payment_terms'):
        truth['items'][0][field]=None
    # 请求限定 E99，但文件没有型号/规格，必须解除绑定，不能猜测匹配。
    truth['items'][0]['rfq_item_id']=None
    result['unsupported_fields']={'kind':'csv','text':'\n'.join([*HEADER_LINES,missing['items'][0]['quote']]),'prediction':missing,'expected':truth}
    wrong_header=base_prediction(); wrong_header['currency_code']='USD'; wrong_header['supplier_name']='Unrelated Vendor'
    safe_header=base_expected(); safe_header['supplier_name']=None; safe_header['currency_code']=None
    result['header_mismatch']={'kind':'csv','prediction':wrong_header,'expected':safe_header}
    wrong_item=base_prediction(); wrong_item['items'][0]['rfq_item_id']=32
    safe_item=base_expected(); safe_item['items'][0]['rfq_item_id']=None
    result['wrong_existing_rfq_line']={'kind':'csv','prediction':wrong_item,'expected':safe_item}
    duplicate=base_prediction(); duplicate['items'].append(deepcopy(duplicate['items'][0]))
    result['duplicate_rfq_candidates']={'kind':'csv','prediction':duplicate,'expected':base_expected()}
    return result


def check_candidate(candidate: dict, expected: dict) -> dict[str,bool]:
    """逐字段比较手工定义的预期；不使用模型自身解释作为评分依据。"""
    checks={field:candidate.get(field)==value for field,value in expected.items() if field!='items'}
    checks['item_count']=len(candidate.get('items',[]))==len(expected['items'])
    for i,item in enumerate(expected['items']):
        actual=candidate.get('items',[])[i] if i<len(candidate.get('items',[])) else {}
        for field,value in item.items():
            observed=actual.get(field)
            if field in {'unit_price','quoted_quantity','tax_rate','moq_quantity','freight_amount','freight_tax_rate'} and value is not None and observed is not None:
                try:
                    left,right=Decimal(str(observed)),Decimal(str(value))
                    equal=left.is_finite() and right.is_finite() and left==right
                except InvalidOperation: equal=False
            else: equal=observed==value
            checks[f'items[{i}].{field}']=equal
    return checks


def _immediate(coroutine):
    try: coroutine.send(None)
    except StopIteration as result: return result.value
    raise AssertionError('offline stub unexpectedly suspended')


def _record(case_id, case, content, candidate, error, model_calls, uploaded, responses=0, ocr_responses=0, parsed_files=None):
    checks={}
    if case.get('reject'):
        checks['rejected_without_upload']=error is not None and uploaded==0
    elif candidate:
        checks=check_candidate(candidate,case['expected'])
        source_text=next((p.text for p in reversed(parsed_files or []) if p.status=='SUCCEEDED'),case.get('text') or TEXT)
        checks['source_quotes_present']=all(item.get('source_quote') in source_text for item in candidate['items'])
        checks['manual_review_warning']=any('候选' in warning for warning in candidate['warnings'])
    else: checks['candidate_returned']=False
    return {'id':case_id,'format':case['kind'],'input_sha256':hashlib.sha256(content).hexdigest(),
        'passed':bool(checks) and all(checks.values()),'checks':checks,'failed_checks':[k for k,v in checks.items() if not v],
        'error_type':error,'model_calls':model_calls,'model_responses':responses,'ocr_responses':ocr_responses,
        'source_file_upload_stub_calls':uploaded,'candidate':candidate,
        'parse_stages':[{'status':p.status,'parser':p.parser,'references':p.references,
                         'text_sha256':hashlib.sha256(p.text.encode()).hexdigest()} for p in parsed_files or []],
        'expected':case.get('expected'),'ocr_stubbed':bool(case.get('stub_ocr'))}


def run_case(case_id, case, *, live_model=False, live_ocr=False):
    extension='pdf' if case['kind']=='scan' else case['kind']
    content=case.get('bytes') or (case['text'].encode() if case.get('text') else sample_bytes(case['kind']))
    settings=get_settings().model_copy(update={'mineru_enabled':live_ocr or bool(case.get('stub_ocr')),
        'llm_max_retries':0,'llm_timeout_seconds':40,'llm_max_tokens':3072,'llm_temperature':0,
        'mineru_timeout_seconds':90,'mineru_max_retries':0,
        'llm_model_profiles_json':'','llm_default_profile':''})
    rfq=NS(id=14,status='RESPONDING',items=[NS(id=31,requested_name='Ethanol',specification='E99',quantity=10),
        NS(id=32,requested_name='Methanol',specification='M99',quantity=20)])
    calls=[]; uploads=[]; responses=[]; ocr_responses=[]; parsed_files=[]; model_outputs=[]
    real_chat=quote_extraction.chat
    real_ocr=quote_extraction.mineru.parse_bytes
    real_parse=quote_extraction.parse_file_content
    async def chat(*args,**kwargs):
        calls.append(True)
        if live_model:
            result=await real_chat(*args,**kwargs)
            responses.append(True)
            # 本评测仅发送合成报价；保留输出以定位模型契约与服务端校验的差异。
            model_outputs.append(result.answer or result.message.content)
            return result
        result=json.dumps(case['prediction'],ensure_ascii=False)
        return NS(answer=result,message=NS(content=result))
    async def immediate_thread(function,*args,**kwargs): return function(*args,**kwargs)
    def upload(*args,**kwargs):
        uploads.append(True)
        return NS(id=1,file_name='synthetic-quote.'+extension)
    def ocr(*args,**kwargs):
        result=real_ocr(*args,**kwargs)
        if result.status=='SUCCEEDED': ocr_responses.append(True)
        parsed_files.append(result)
        return result
    def parse(*args,**kwargs):
        result=real_parse(*args,**kwargs)
        parsed_files.append(result)
        return result
    candidate=None; error=None
    with patch.object(quote_extraction,'get_settings',return_value=settings),\
         patch.object(quote_extraction.rfq_service,'get_rfq',return_value=rfq),\
         patch.object(quote_extraction.file_service,'scan_content',return_value=NS(status=case.get('scan_status','CLEAN'))),\
         patch.object(quote_extraction.file_service,'upload_file',side_effect=upload),\
         patch.object(quote_extraction,'chat',side_effect=chat),\
         patch.object(quote_extraction,'parse_file_content',side_effect=parse),\
         patch.object(quote_extraction.mineru,'parse_bytes',side_effect=ocr):
        async def invoke():
            return await quote_extraction.parse_quote_file(NS(),NS(id=1),14,file_name='synthetic-quote.'+extension,
                mime_type='text/csv' if extension=='csv' else 'application/octet-stream',content=content)
        try:
            if not live_model:
                with patch.object(quote_extraction.asyncio,'to_thread',side_effect=immediate_thread):
                    if case.get('stub_ocr'):
                        with patch.object(quote_extraction.mineru,'parse_bytes',return_value=ParsedFile('SUCCEEDED',TEXT,'stub-ocr',[])):
                            candidate=_immediate(invoke()).model_dump(mode='json')
                    else: candidate=_immediate(invoke()).model_dump(mode='json')
            else: candidate=asyncio.run(invoke()).model_dump(mode='json')
        except BusinessValidationError: error='BusinessValidationError'
        except Exception as exc: error=type(exc).__name__
    row=_record(case_id,case,content,candidate,error,len(calls),len(uploads),len(responses),len(ocr_responses),parsed_files)
    if live_model:
        row['synthetic_model_outputs']=model_outputs
    return row


def report(rows, *, real_model=False, real_ocr=False):
    return {'suite':'quote-extraction-synthetic-v1','created_at':datetime.now(timezone.utc).isoformat(),
        'real_model_requested':real_model,'real_ocr_requested':real_ocr,
        'real_model_evaluated':real_model and any(row['model_responses'] for row in rows),
        'real_ocr_evaluated':real_ocr and any(row['ocr_responses'] for row in rows),'business_writes':False,
        'scope':'合成文档的解析与候选字段契约；上传、业务权限和业务库隔离；不代表真实供应商文件准确率或业务收益',
        'model':get_settings().llm_model if real_model else 'stubbed adversarial model outputs',
        'summary':{'total':len(rows),'passed':sum(r['passed'] for r in rows),'failed':sum(not r['passed'] for r in rows)},'cases':rows}


def run_offline():
    return report([run_case(key,value) for key,value in cases().items()])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='新报告路径，禁止覆盖已有证据')
    parser.add_argument('--live-model',action='store_true',help='最多三份合成文件调用已配置模型；不调用业务库')
    parser.add_argument('--live-ocr',action='store_true',help='额外上传一份合成扫描件到已配置 MinerU；须与 live-model 一起使用')
    parser.add_argument('--case',choices=('csv','pdf','xlsx','scan'),help='真实模型模式仅抽查一种格式，避免重复请求')
    parser.add_argument('--samples-dir',type=Path,help='另存合成输入，目录必须不存在')
    args=parser.parse_args()
    if args.output.exists(): parser.error('输出文件已存在；请使用新路径保留原始结果')
    if args.live_ocr and not args.live_model: parser.error('live-ocr 需要 live-model')
    if args.case and not args.live_model: parser.error('case 仅用于真实模型抽查')
    if args.case=='scan' and not args.live_ocr: parser.error('scan 需要显式 live-ocr')
    if args.samples_dir:
        args.samples_dir.mkdir(parents=True,exist_ok=False)
        for name,case in cases().items():
            extension='pdf' if case['kind']=='scan' else case['kind']
            content=case.get('bytes') or (case['text'].encode() if case.get('text') else sample_bytes(case['kind']))
            (args.samples_dir/(name+'.'+extension)).write_bytes(content)
    if args.live_model:
        selected={key:cases()[key] for key in ('csv','pdf','xlsx') if args.case in (None,key)}
        if args.live_ocr and args.case in (None,'scan'): selected['scan']={'kind':'scan','prediction':base_prediction(),'expected':base_expected()}
        result=report([run_case(k,v,live_model=True,live_ocr=args.live_ocr) for k,v in selected.items()],
            real_model=True,real_ocr=args.live_ocr)
    else: result=run_offline()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as target:
        target.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'summary':result['summary'],'real_model_evaluated':result['real_model_evaluated']},ensure_ascii=False))
    return int(result['summary']['failed']>0)


if __name__=='__main__': raise SystemExit(main())
