"""TDS/MSDS 文档的解析、清洗、质检与入库。

设计要点：
- 原件在 MinIO 不回写；本模块只产出结构化章节与质检状态，可重复执行（幂等 upsert）。
- HTML 用标准库 html.parser 提取正文（跳过 script/style/footer/导航与推荐位），
  MSDS 按 SECTION 1–16 切节，物性页按 h2/h3 切节，TDS PDF 按页切（pypdf）。
- 质检门禁：正文长度 + MSDS 核心节完整性 + 标题含 CAS；不达标标 THIN/REJECTED，
  章节清空，避免薄壳页污染检索。
- 元数据补全：英文名、同义词、分子式/分子量、信号词、H/P 危险声明码、UN 号、
  运输类项，外加按 CAS 关联出的中文名（英文文档 ↔ 中文提问的桥）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.doc_kb.model import AiDocument, AiDocumentSection

# 这些标签整块跳过（脚本/样式/页脚/导航）
_SKIP_TAGS = frozenset({"script", "style", "footer", "nav", "aside", "noscript", "iframe"})
# class/id 命中即整块跳过（ChemicalBook 的搜索框与推荐位）
_SKIP_CLASS_HINTS = ("recompro2", "searchbox", "search", "copyright", "sidebar", "banner")
# 块级标签产生换行，作为章节内部分段依据
_BLOCK_TAGS = frozenset(
    {"p", "div", "li", "br", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "section", "dd", "dt"}
)

# MSDS 章节切分（h2 id="N" SECTION N: ...）
_MSDS_HEADING_RE = re.compile(r'<h2[^>]*>\s*SECTION\s*(\d+)\s*[:：]?', re.IGNORECASE)
# 物性页 h2/h3 标题
_PROPERTY_HEADING_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)

# 正文尾部样板：跨文档重复，检索必污染，直接截断
_TAIL_MARKERS = ("Recommended Products", "Disclaimer:")

# 质检阈值
# TDS 实测结构为「规格表正文数百字 + 尾部 Disclaimer 样板」，裁样板后 300 字即可信；
# 真正的空壳/图片型 PDF 会远低于此值。
MSDS_MIN_CHARS = 4000
MSDS_REQUIRED_SECTIONS = frozenset({1, 2, 9, 14})
MSDS_MIN_SECTIONS = 10
PROPERTY_MIN_CHARS = 2000
TDS_MIN_CHARS = 300
# 单页地板：裁掉 Disclaimer/Recommended 样板后不足此长度的 PDF 页视为页脚垃圾
TDS_PAGE_MIN_CHARS = 100


@dataclass
class ParsedSection:
    """一个清洗后的章节。"""

    section_no: int | None
    section_key: str
    title: str | None
    content: str

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass
class ParsedDoc:
    """一次解析的完整产物：元数据、章节、质检结论。"""

    cas: str
    doc_type: str  # msds | tds | property
    title: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    sections: list[ParsedSection] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.reasons:
            return "PARSED"
        return "THIN" if any("过短" in reason for reason in self.reasons) else "REJECTED"

    @property
    def char_count(self) -> int:
        return sum(section.char_count for section in self.sections)


# ---------- 文本提取与清洗 ----------


class _TextExtractor(HTMLParser):
    """按块级标签换行地提取可见文本，跳过脚本/样式/页脚/导航/推荐位。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_stack: list[str] = []
        self._parts: list[str] = []

    def _in_skip(self) -> bool:
        return bool(self._skip_stack)

    @staticmethod
    def _should_skip_tag(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in _SKIP_TAGS:
            return True
        for _name, value in attrs:
            if not value:
                continue
            lowered = value.lower()
            if any(hint in lowered for hint in _SKIP_CLASS_HINTS):
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._should_skip_tag(tag, attrs):
            self._skip_stack.append(tag)
            return
        if self._in_skip():
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "li":
            self._parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_stack and tag == self._skip_stack[-1]:
            self._skip_stack.pop()
            return
        if self._in_skip():
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_skip():
            return
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """HTML → 清洗后的纯文本（保留换行分段）。"""

    parser = _TextExtractor()
    parser.feed(html)
    return normalize_text(parser.text())


def normalize_text(text: str) -> str:
    """统一空白：去 CR、压尾随空格、连续空行压成一个空行。

    注意：不做欧式小数逗号（13,5）到点的全局替换——英语千分位（1,500）
    与欧式小数（0,791）外形无法可靠区分，盲改会损坏数值，宁可保留原样。
    """

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1] != "":
            compact.append("")
    return "\n".join(compact).strip()


def cut_tail_boilerplate(text: str) -> str:
    """截掉正文尾部的推荐位与免责声明样板。"""

    cut = len(text)
    for marker in _TAIL_MARKERS:
        index = text.rfind(marker)
        if index != -1:
            cut = min(cut, index)
    return text[:cut].strip()


def _strip_tags(html: str) -> str:
    return normalize_text(html_to_text(html))


# ---------- 元数据抽取 ----------


def _first_line_after(text: str, keyword: str) -> str | None:
    match = re.search(rf"{keyword}[ \t]*([^\n]+)", text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip(" :-")
    return value[:200] if value else None


def extract_meta(text: str, title: str | None) -> dict[str, Any]:
    """从正文抽取结构化元数据（同义式、分子式、分子量、GHS、UN 号等）。"""

    meta: dict[str, Any] = {}
    synonyms = _first_line_after(text, "Synonyms")
    if synonyms:
        meta["synonyms"] = [item.strip() for item in re.split(r"[,;，；]", synonyms) if item.strip()][:10]
    # 真实页值带冒号（MF: C2H6O），夹具可能不带，两种都兼容
    mf = re.search(r"\bMF[\s:]*([A-Za-z0-9·•\-\(\)]+)", text)
    if mf:
        meta["chemical_formula"] = mf.group(1)
    mw = re.search(r"\bMW[\s:]*([\d.]+)", text)
    if mw:
        meta["molecular_weight"] = mw.group(1)
    signal = re.search(r"Signal[ \t]*word[ \t]*(Danger|Warning)", text, re.IGNORECASE)
    if signal:
        meta["signal_word"] = signal.group(1).upper() if signal.group(1).lower() == "danger" else "WARNING"
    h_codes = sorted(set(re.findall(r"\bH\d{3}\b", text)))
    if h_codes:
        meta["h_statements"] = h_codes
    p_codes = sorted(set(re.findall(r"\bP\d{3}\b", text)))
    if p_codes:
        meta["p_statements"] = p_codes
    un = re.search(r"UN[ \t]+number[^\d]{0,48}(\d{3,4})", text, re.IGNORECASE)
    if un:
        meta["un_number"] = un.group(1)
    # 注意：不能加 re.IGNORECASE——它会把 [^A-Z] 变成排除所有字母，跨不过 "(es)"
    transport = re.search(r"[Tt]ransport [Hh]azard class[^A-Z]{0,12}ADR/RID:\s*(\d+)", text)
    if transport:
        meta["transport_class"] = transport.group(1)
    if title:
        meta["name_en"] = title
    return meta


def extract_title(html: str, doc_type: str, cas: str) -> str | None:
    """页面标题 → 英文名：`Ethanol - Safety Data Sheet` / `Methanol | 67-56-1`。"""

    match = _TITLE_RE.search(html)
    if not match:
        return None
    raw = match.group(1).strip()
    if doc_type == "msds":
        marker = "- Safety Data Sheet"
        index = raw.lower().find(marker.lower())
        return raw[:index].strip() if index >= 0 else (raw or None)
    # 物性页：`Ethanol | 64-17-5`
    head = raw.split("|")[0].strip()
    return head or None


# ---------- MSDS HTML ----------


def extract_msds(cas: str, html: str) -> ParsedDoc:
    """MSDS：按 h2 SECTION 切 16 节，抽 GHS/运输元数据，截尾部样板。"""

    title = extract_title(html, "msds", cas)
    doc = ParsedDoc(cas=cas, doc_type="msds", title=title)

    matches = list(_MSDS_HEADING_RE.finditer(html))
    if not matches:
        doc.reasons.append("未解析出任何 SECTION 章节")
        return doc

    for index, match in enumerate(matches):
        section_no = int(match.group(1))
        slice_end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        raw_section = html[match.start() : slice_end]
        content = _strip_tags(raw_section)
        # 首行是标题本身，去掉标题行保留正文
        first_line, _, rest = content.partition("\n")
        body = rest if first_line.upper().startswith("SECTION") else content
        body = cut_tail_boilerplate(body)
        if not body:
            continue
        heading_end = html.find("</h2>", match.start())
        heading_text = _strip_tags(html[match.start() : heading_end + 5] if heading_end != -1 else raw_section[:200])
        doc.sections.append(
            ParsedSection(
                section_no=section_no,
                section_key=f"SECTION {section_no}",
                title=heading_text[:255] if heading_text else f"SECTION {section_no}",
                content=body,
            )
        )

    full_text = "\n".join(section.content for section in doc.sections)
    doc.meta = extract_meta(full_text, title)
    doc.reasons = qc_msds(doc)
    return doc


def qc_msds(doc: ParsedDoc) -> list[str]:
    """MSDS 质检：核心节完整性 + 正文长度。"""

    reasons: list[str] = []
    if not doc.sections:
        return ["未解析出任何 SECTION 章节"]
    total_chars = sum(section.char_count for section in doc.sections)
    if total_chars < MSDS_MIN_CHARS:
        reasons.append(f"正文过短(<{MSDS_MIN_CHARS})")
    found = {section.section_no for section in doc.sections if section.section_no is not None}
    missing = sorted(MSDS_REQUIRED_SECTIONS - found)
    if missing:
        reasons.append(f"缺少核心节 SECTION {'、'.join(str(item) for item in missing)}")
    if len(found) < MSDS_MIN_SECTIONS:
        reasons.append(f"有效 SECTION 节不足{MSDS_MIN_SECTIONS}个")
    return reasons


# ---------- 物性页（Property HTML） ----------


def extract_property(cas: str, html: str) -> ParsedDoc:
    """物性页：按 h2/h3 标题切节，标题不含 CAS 直接拒收。"""

    title = extract_title(html, "property", cas)
    doc = ParsedDoc(cas=cas, doc_type="property", title=title)

    matches = list(_PROPERTY_HEADING_RE.finditer(html))
    if not matches:
        doc.reasons.append("未解析出任何标题章节")
        return doc

    # 首个标题前的导言
    preamble = html[: matches[0].start()]
    preamble_text = cut_tail_boilerplate(_strip_tags(preamble))
    if preamble_text:
        doc.sections.append(
            ParsedSection(section_no=None, section_key="intro", title=title, content=preamble_text)
        )

    for index, match in enumerate(matches):
        level = int(match.group(1))
        slice_end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        heading_title = _strip_tags(match.group(2))[:255]
        raw_section = html[match.end() : slice_end]
        body = cut_tail_boilerplate(_strip_tags(raw_section))
        if not body:
            continue
        doc.sections.append(
            ParsedSection(
                section_no=None,
                section_key=f"h{level}-{index:02d}",
                title=heading_title or None,
                content=body,
            )
        )

    full_text = "\n".join(section.content for section in doc.sections)
    doc.meta = extract_meta(full_text, title)
    doc.reasons = qc_property(doc, html, cas)
    return doc


def qc_property(doc: ParsedDoc, html: str, cas: str) -> list[str]:
    """物性页质检：标题含 CAS + 正文长度（薄壳页门禁）。"""

    reasons: list[str] = []
    title_match = _TITLE_RE.search(html)
    page_title = title_match.group(1) if title_match else ""
    if cas not in page_title:
        reasons.append("页面标题不含目标 CAS")
    if not doc.sections:
        reasons.append("未解析出任何标题章节")
        return reasons
    total_chars = sum(section.char_count for section in doc.sections)
    if total_chars < PROPERTY_MIN_CHARS:
        reasons.append(f"正文过短(<{PROPERTY_MIN_CHARS})")
    return reasons


# ---------- TDS PDF ----------


def sections_from_pdf_pages(pages: list[str]) -> list[ParsedSection]:
    """PDF 逐页成节；跳过免责声明页与页脚垃圾页。

    实测站点模板第 2 页有两种形态：
    1. 整页 Disclaimer 开头 → 裁尾后为空；
    2. 先 logo/页码后 Disclaimer（如 "ChemicalBook\\nChemical Book\\n2"）
       → 裁尾后只剩十几字垃圾。
    统一口径：裁样板后正文不足 100 字的页一律丢弃（真实规格页 ≥500 字）。
    """

    sections: list[ParsedSection] = []
    for page_no, page_text in enumerate(pages, start=1):
        raw = normalize_text(page_text)
        if page_no > 1 and raw.lower().startswith("disclaimer"):
            continue
        content = cut_tail_boilerplate(raw)
        if len(content) < TDS_PAGE_MIN_CHARS:
            continue
        sections.append(
            ParsedSection(
                section_no=page_no,
                section_key=f"page-{page_no}",
                title="Technical Data Sheet",
                content=content,
            )
        )
    return sections


def extract_tds_pdf(cas: str, pdf_bytes: bytes) -> ParsedDoc:
    """TDS PDF：pypdf 提取文本层，按页切节。"""

    doc = ParsedDoc(cas=cas, doc_type="tds")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # PDF 损坏/加密等
        doc.reasons.append(f"PDF 解析失败: {type(exc).__name__}")
        return doc

    doc.sections = sections_from_pdf_pages(pages)
    full_text = "\n".join(section.content for section in doc.sections)
    # 首页标题行形如 Technical Data Sheet \n Methanol
    head_lines = [line.strip() for line in full_text.split("\n") if line.strip()]
    if len(head_lines) >= 2 and "technical data sheet" in head_lines[0].lower():
        doc.title = head_lines[1][:255]
    doc.meta = extract_meta(full_text, doc.title)
    if not doc.sections:
        doc.reasons.append("未解析出任何页面文本")
    elif sum(section.char_count for section in doc.sections) < TDS_MIN_CHARS:
        doc.reasons.append(f"正文过短(<{TDS_MIN_CHARS})")
    return doc


# ---------- 入库 ----------


def store_parsed(
    db: Session,
    *,
    cas: str,
    doc_type: str,
    bucket: str,
    object_key: str,
    parsed: ParsedDoc,
    source_url: str | None = None,
    name_zh: str | None = None,
    sha256: str | None = None,
) -> AiDocument:
    """幂等入库：同 (cas, doc_type) 覆盖更新，章节先删后插；质检不过则清空章节。"""

    document = db.scalar(select(AiDocument).where(AiDocument.cas_no == cas, AiDocument.doc_type == doc_type))
    if document is None:
        document = AiDocument(cas_no=cas, doc_type=doc_type, source_bucket=bucket, object_key=object_key)
        db.add(document)
    document.title = parsed.title
    document.name_zh = name_zh
    document.source_bucket = bucket
    document.object_key = object_key
    document.source_url = source_url
    document.parse_status = parsed.status
    document.reject_reason = "；".join(parsed.reasons)[:255] if parsed.reasons else None
    sections = parsed.sections if parsed.status == "PARSED" else []
    document.section_count = len(sections)
    document.char_count = sum(section.char_count for section in sections)
    document.meta_json = parsed.meta or None
    document.sha256 = sha256
    db.flush()

    db.execute(delete(AiDocumentSection).where(AiDocumentSection.document_id == document.id))
    for section in sections:
        db.add(
            AiDocumentSection(
                document_id=document.id,
                cas_no=cas,
                doc_type=doc_type,
                section_no=section.section_no,
                section_key=section.section_key,
                title=section.title,
                content=section.content,
                char_count=section.char_count,
            )
        )
    db.commit()
    db.refresh(document)
    return document


def load_sections(
    db: Session, cas: str, doc_type: str | None = None, *, only_parsed: bool = True, limit: int = 20
) -> list[AiDocumentSection]:
    """按 CAS 载入可检索章节（供后续 chat 注入用）；只返回质检通过的文档。"""

    statement = select(AiDocumentSection).where(AiDocumentSection.cas_no == cas)
    if doc_type:
        statement = statement.where(AiDocumentSection.doc_type == doc_type)
    if only_parsed:
        statement = statement.join(AiDocument, AiDocument.id == AiDocumentSection.document_id).where(
            AiDocument.parse_status == "PARSED"
        )
    statement = statement.order_by(AiDocumentSection.doc_type, AiDocumentSection.section_no).limit(limit)
    return list(db.scalars(statement).all())


def document_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_document(cas: str, doc_type: str, content: bytes) -> ParsedDoc:
    """按类型分派解析（纯内存函数，便于单测）。"""

    if doc_type == "msds":
        return extract_msds(cas, content.decode("utf-8", errors="ignore"))
    if doc_type == "property":
        return extract_property(cas, content.decode("utf-8", errors="ignore"))
    if doc_type == "tds":
        return extract_tds_pdf(cas, content)
    doc = ParsedDoc(cas=cas, doc_type=doc_type)
    doc.reasons.append(f"未知文档类型 {doc_type}")
    return doc
