"""TDS/MSDS 解析清洗与质检测试（不访问 MinIO 与外网）。"""

import pytest

from app.modules.doc_kb import service
from app.modules.doc_kb.model import AiDocumentSection

# 贴近真实 ChemicalBook 结构的 SDS 夹具：h2 SECTION、li 元数据、样板尾巴、脚本噪声
FILLER = "Ethanol safety detail. " * 220  # 撑过 4000 字符门禁
MSDS_FIXTURE = f"""<!DOCTYPE html><html><head><title>Ethanol - Safety Data Sheet</title>
<script>var track = 1;</script><style>.x{{color:red}}</style></head><body>
<div class="searchbox">SEARCH MSDS</div>
<div class="sds">
<h2 id="1">SECTION 1: Identification of the substance/mixture</h2>
<div class="opentext"><ul>
<li><span>Synonyms</span> Ethanol,ETHYL ALCOHOL</li>
<li><span>MF</span> C2H6O</li><li><span>MW</span> 46.07</li>
</ul></div>
<h2 id="2">SECTION 2: Hazards identification</h2>
<div>Signal wordDanger H225 Highly Flammable liquid and vapour P210 Keep away from heat</div>
<h2 id="3">SECTION 3: Composition</h2><div>{FILLER}</div>
<h2 id="4">SECTION 4: First aid measures</h2><div>{FILLER}</div>
<h2 id="5">SECTION 5: Firefighting measures</h2><div>{FILLER}</div>
<h2 id="6">SECTION 6: Accidental release measures</h2><div>{FILLER}</div>
<h2 id="7">SECTION 7: Handling and storage</h2><div>{FILLER}</div>
<h2 id="8">SECTION 8: Exposure controls</h2><div>{FILLER}</div>
<h2 id="9">SECTION 9: Physical and chemical properties</h2>
<div>Flash point13 °C - closed cup Upper explosion limit: 13,5 %(V) Boiling point 78 °C</div>
<h2 id="10">SECTION 10: Stability and reactivity</h2><div>{FILLER}</div>
<h2 id="11">SECTION 11: Toxicological information</h2><div>{FILLER}</div>
<h2 id="12">SECTION 12: Ecological information</h2><div>{FILLER}</div>
<h2 id="13">SECTION 13: Disposal considerations</h2><div>{FILLER}</div>
<h2 id="14">SECTION 14: Transport information</h2>
<div>UN number ADR/RID: 1170 IMDG: 1170 Transport hazard class(es) ADR/RID: 3</div>
<h2 id="15">SECTION 15: Regulatory information</h2><div>{FILLER}</div>
<h2 id="16">SECTION 16: Other information</h2><div>{FILLER}</div>
</div>
<footer>ChemicalBook footer address beijing</footer>
<div class="recompro2"><a>Recommended Products</a> Methanol SDS Acetaldehyde SDS</div>
<p>Disclaimer: The information in this MSDS is only applicable to the specified product.</p>
</body></html>"""

PROPERTY_FIXTURE = """<!DOCTYPE html><html><head><title>Methanol | 67-56-1</title></head><body>
<div class="searchbox">SEARCH</div>
<h2>Methanol Properties</h2><div>Boiling point: 64.7 °C; Flash point: 13 °C; Density 0.791 g/mL.</div>
<h2>SAFETY</h2><h3 class="safteh3">Risk and Safety Statements</h3>
<div>R11 Highly flammable; S16 Keep away from sources of ignition.</div>
<h2>Methanol Chemical Properties, Uses, Production</h2>
<h3>Introduction</h3><div>""" + ("Methanol is a polar solvent used widely in industry. " * 80) + """</div>
<h3>Uses</h3><div>Used as solvent, fuel and feedstock. """ + ("Detail text. " * 60) + """</div>
<footer>ChemicalBook</footer>
<div class="recompro2">Recommended Products</div><p>Disclaimer: blah</p>
</body></html>"""

THIN_PROPERTY_FIXTURE = """<!DOCTYPE html><html><head><title>Acetone | 67-64-1</title></head>
<body><h2>Acetone</h2><div>no body</div></body></html>"""


def test_html_to_text_strips_script_style_and_footer():
    text = service.html_to_text("<p>keep</p><script>bad()</script><style>.a{}</style><footer>foot</footer>")
    assert "keep" in text
    assert "bad()" not in text
    assert "foot" not in text


def test_html_to_text_skips_recommended_products_box():
    text = service.html_to_text('<div class="recompro2"><a>Recommended Products</a> junk</div><p>body</p>')
    assert "Recommended" not in text
    assert "body" in text


def test_extract_msds_sections_and_meta():
    doc = service.extract_msds("64-17-5", MSDS_FIXTURE)

    assert doc.status == "PARSED", doc.reasons
    assert doc.title == "Ethanol"
    nos = {section.section_no for section in doc.sections}
    assert nos == set(range(1, 17))
    # 章节标题与正文分离
    section9 = next(section for section in doc.sections if section.section_no == 9)
    assert "SECTION 9" in (section9.title or "")
    assert "Flash point" in section9.content
    # 样板与噪声被清除
    all_text = "\n".join(section.content for section in doc.sections)
    assert "var track" not in all_text
    assert "ChemicalBook footer" not in all_text
    assert "Recommended Products" not in all_text
    assert "Disclaimer" not in all_text
    # 元数据抽取
    assert doc.meta["chemical_formula"] == "C2H6O"
    assert doc.meta["molecular_weight"] == "46.07"
    assert doc.meta["synonyms"] == ["Ethanol", "ETHYL ALCOHOL"]
    assert doc.meta["signal_word"] == "DANGER"
    assert "H225" in doc.meta["h_statements"]
    assert "P210" in doc.meta["p_statements"]
    assert doc.meta["un_number"] == "1170"
    assert doc.meta["transport_class"] == "3"
    # 欧式小数逗号保留原样（盲转会破坏千分位，已在文档中说明）
    assert "13,5" in section9.content


def test_parse_tds_html_source_into_previewable_section():
    html = f"""<!doctype html><html><head><title>Acetone Technical Data Sheet</title></head>
    <body><h1>Technical Data Sheet</h1><h2>Product information</h2>
    <p>{'Acetone is a clear, volatile solvent used in coatings and chemical manufacturing. ' * 20}</p>
    <footer>Recommended Products</footer></body></html>"""

    doc = service.parse_document("67-64-1", "tds", html.encode())

    assert doc.status == "PARSED", doc.reasons
    assert doc.sections
    assert doc.sections[0].section_key == "html-document"
    assert "Acetone is a clear" in doc.sections[0].content
    assert "Recommended Products" not in doc.sections[0].content


def test_qc_msds_rejects_missing_core_section():
    broken = MSDS_FIXTURE.replace(
        "<h2 id=\"9\">SECTION 9: Physical and chemical properties</h2>\n<div>Flash point13 °C - closed cup Upper explosion limit: 13,5 %(V) Boiling point 78 °C</div>",
        "",
    )
    doc = service.extract_msds("64-17-5", broken)

    assert doc.status == "REJECTED", doc.reasons
    assert any("SECTION 9" in reason for reason in doc.reasons)


def test_qc_msds_thin_when_too_short():
    short = """<html><head><title>X - Safety Data Sheet</title></head><body>
    <h2 id="1">SECTION 1: Identification</h2><div>tiny</div>
    <h2 id="2">SECTION 2: Hazards</h2><div>tiny</div>
    <h2 id="9">SECTION 9: Physical</h2><div>tiny</div>
    <h2 id="14">SECTION 14: Transport</h2><div>tiny</div>
    </body></html>"""
    doc = service.extract_msds("1-1-1", short)

    assert doc.status == "THIN"
    assert any("过短" in reason for reason in doc.reasons)
    # 质检不过的文档章节仍解析出来了（store 时才决定是否入库）
    assert doc.sections


def test_extract_property_sections_and_qc():
    doc = service.extract_property("67-56-1", PROPERTY_FIXTURE)

    assert doc.status == "PARSED", doc.reasons
    titles = [section.title for section in doc.sections]
    assert "Methanol Properties" in titles
    assert "Uses" in titles
    all_text = "\n".join(section.content for section in doc.sections)
    assert "Recommended Products" not in all_text
    assert "Disclaimer" not in all_text


def test_extract_property_thin_shell_detected():
    """标题含 CAS 但正文极短的薄壳页必须被门禁拦下（实测7个26KB页的场景）。"""

    doc = service.extract_property("67-64-1", THIN_PROPERTY_FIXTURE)

    assert doc.status == "THIN"
    assert any("过短" in reason for reason in doc.reasons)


def test_extract_property_rejects_title_without_cas():
    doc = service.extract_property("99-99-9", PROPERTY_FIXTURE)

    assert doc.status == "REJECTED"
    assert any("CAS" in reason for reason in doc.reasons)


def test_sections_from_pdf_pages_drops_disclaimer_page():
    pages = [
        # 规格页正文必须过 100 字的单页地板
        "Technical Data Sheet\nMethanol\npurity NLT 99.5%\n" + "specification line. " * 10,
        "Disclaimer: This information relates only to the specific material...",
    ]
    sections = service.sections_from_pdf_pages(pages)

    assert len(sections) == 1
    assert sections[0].section_no == 1
    assert "Methanol" in sections[0].content


def test_sections_from_pdf_pages_drops_footer_junk_page():
    """先 logo/页码、后 Disclaimer 的页脚页：裁尾后只剩垃圾字，必须整页丢弃。"""

    pages = [
        "Technical Data Sheet\nPhenol\npurity 99.9% " + "spec detail. " * 60,
        "ChemicalBook\nChemical Book\n2\nDisclaimer: This information relates only to the specified product and may not be valid for any other use.",
    ]
    sections = service.sections_from_pdf_pages(pages)

    assert len(sections) == 1
    all_text = "\n".join(section.content for section in sections)
    assert "ChemicalBook" not in all_text
    assert "Disclaimer" not in all_text


def test_parse_document_dispatch():
    doc = service.parse_document("64-17-5", "msds", MSDS_FIXTURE.encode())
    assert doc.doc_type == "msds"
    assert doc.status == "PARSED"

    unknown = service.parse_document("64-17-5", "other", b"x")
    assert unknown.reasons


def test_store_and_load_roundtrip_idempotent(db_session):
    cas = "64-17-5"
    parsed = service.extract_msds(cas, MSDS_FIXTURE)

    doc1 = service.store_parsed(
        db_session,
        cas=cas,
        doc_type="msds",
        bucket="chemicalops-msds",
        object_key=f"{cas}.html",
        parsed=parsed,
        name_zh="乙醇",
        sha256="a" * 64,
    )
    assert doc1.parse_status == "PARSED"
    assert doc1.name_zh == "乙醇"
    assert doc1.section_count == 16

    # 幂等：重复入库不产生重复章节
    service.store_parsed(
        db_session,
        cas=cas,
        doc_type="msds",
        bucket="chemicalops-msds",
        object_key=f"{cas}.html",
        parsed=parsed,
        name_zh="乙醇",
    )
    from sqlalchemy import func, select

    # 只统计 msds 类型（同 CAS 还有 tds/property 的章节在同一张表里）
    section_count = db_session.scalar(
        select(func.count(AiDocumentSection.id)).where(
            AiDocumentSection.cas_no == cas,
            AiDocumentSection.doc_type == "msds",
        )
    )
    assert section_count == 16

    loaded = service.load_sections(db_session, cas, "msds")
    assert len(loaded) == 16
    assert any("Flash point" in section.content for section in loaded)


def test_store_thin_doc_clears_sections(db_session):
    cas = "67-64-1"
    thin = service.extract_property(cas, THIN_PROPERTY_FIXTURE)

    document = service.store_parsed(
        db_session,
        cas=cas,
        doc_type="property",
        bucket="chemicalops-tds",
        object_key=f"{cas}-property.html",
        parsed=thin,
    )

    assert document.parse_status == "THIN"
    assert document.section_count == 0
    assert document.reject_reason and "过短" in document.reject_reason
    assert service.load_sections(db_session, cas, "property") == []


def test_classify_and_group_object_keys():
    from scripts.parse_tds_msds import classify_object, group_objects

    assert classify_object("chemicalops-msds", "64-17-5.html") == ("64-17-5", "msds")
    assert classify_object("chemicalops-tds", "64-17-5.pdf") == ("64-17-5", "tds")
    assert classify_object("chemicalops-tds", "64-17-5-property.html") == ("64-17-5", "property")
    assert classify_object("chemicalops-tds", "readme.txt") is None

    grouped = group_objects(
        [
            ("chemicalops-msds", "64-17-5.html"),
            ("chemicalops-tds", "64-17-5.pdf"),
            ("chemicalops-tds", "64-17-5-property.html"),
            ("chemicalops-msds", "junk.bin"),
        ]
    )
    assert grouped == {"64-17-5": {"msds": "64-17-5.html", "tds": "64-17-5.pdf", "property": "64-17-5-property.html"}}


def test_normalize_text_collapses_whitespace():
    text = service.normalize_text("a  b\r\n\r\n\r\nc\t d\n")
    assert text == "a b\n\nc d"


def test_extract_meta_handles_colon_prefixed_values():
    """真实页结构是 <span>MF</span><span>: C2H6O</span>，值前带冒号。"""

    meta = service.extract_meta("MF: C2H6O\nMW: 46.07\nSignal wordDanger", None)
    assert meta["chemical_formula"] == "C2H6O"
    assert meta["molecular_weight"] == "46.07"
    assert meta["signal_word"] == "DANGER"
