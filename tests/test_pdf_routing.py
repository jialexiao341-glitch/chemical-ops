"""PDF 页级路由：文字本地提取，扫描和混合内容交由远程解析。"""

from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from app.core.config import Settings
from app.modules.files_storage import mineru, parser
from app.modules.files_storage.parser import ParsedFile


def make_pdf(*kinds: str) -> bytes:
    """构造包含文字页和图片页的真实 PDF 样本。"""
    image = BytesIO()
    Image.new("RGB", (200, 200), "gray").save(image, format="PNG")
    document = pymupdf.open()
    for kind in kinds:
        page = document.new_page(width=300, height=300)
        if kind in {"text", "overlay"}:
            page.insert_text((25, 30), "Purchase order 123")
        if kind in {"scan", "overlay"}:
            page.insert_image(pymupdf.Rect(30, 45, 270, 285), stream=image.getvalue())
    result = document.tobytes()
    document.close()
    return result


def test_text_pdf_uses_local_parser_without_remote(monkeypatch):
    """有文字的 PDF 本地解析并保留页码，不发送至 MinerU。"""
    monkeypatch.setattr(mineru, "parse_bytes", lambda *_: pytest.fail("不应调用远程解析"))
    result = parser.parse_pdf_routed("text.pdf", make_pdf("text"), Settings(mineru_enabled=True))
    assert result.status == "SUCCEEDED"
    assert "Purchase order 123" in result.text
    assert result.references == [{"type": "page", "page": 1}]


def test_text_pdf_uses_pymupdf_if_pdfplumber_returns_no_text(monkeypatch):
    """pdfplumber 未提取到文字时，使用 PyMuPDF 的结果再判断。"""
    import pdfplumber

    monkeypatch.setattr(pdfplumber.page.Page, "extract_text", lambda *_args, **_kwargs: "")
    result = parser.parse_pdf_routed("text.pdf", make_pdf("text"), Settings(mineru_enabled=False))
    assert result.status == "SUCCEEDED"
    assert "Purchase order 123" in result.text


def test_empty_page_does_not_force_ocr_for_text_pdf(monkeypatch):
    """文字型 PDF 中的空白页不应导致整份文件上传。"""
    monkeypatch.setattr(mineru, "parse_bytes", lambda *_: pytest.fail("空白页不应触发远程解析"))
    result = parser.parse_pdf_routed("text.pdf", make_pdf("text", "blank"), Settings(mineru_enabled=True))
    assert result.status == "SUCCEEDED"
    assert "Purchase order 123" in result.text


@pytest.mark.parametrize("pages", [("scan",), ("text", "scan"), ("overlay",)])
def test_scan_and_mixed_pdf_use_mineru(monkeypatch, pages):
    """整页扫描、跨页混合及同页图文混合都交给 MinerU。"""
    expected = ParsedFile("SUCCEEDED", "远程完整结果", "mineru", [])
    monkeypatch.setattr(mineru, "parse_bytes", lambda *_: expected)
    assert parser.parse_pdf_routed("sample.pdf", make_pdf(*pages), Settings(mineru_enabled=True)) == expected


def test_mixed_pdf_without_mineru_does_not_return_partial_success():
    """远程服务关闭时不能把混合 PDF 的局部文字当作完整结果。"""
    result = parser.parse_pdf_routed("mixed.pdf", make_pdf("text", "scan"), Settings(mineru_enabled=False))
    assert result.status == "OCR_REQUIRED"
    assert not result.text


def test_mineru_failure_does_not_return_partial_text(monkeypatch):
    """远程解析失败时不将混合文件的部分文字标记为成功。"""
    def fail(*_args):
        raise mineru.MinerUParseError("远程不可用")

    monkeypatch.setattr(mineru, "parse_bytes", fail)
    result = parser.parse_pdf_routed("mixed.pdf", make_pdf("text", "scan"), Settings(mineru_enabled=True))
    assert result.status == "OCR_REQUIRED"
    assert not result.text
    assert "远程解析失败" in result.error


def test_pdf_over_limit_is_not_sent_to_mineru(monkeypatch):
    """文件超过本地解析上限时不能绕过限制上传到远程。"""
    monkeypatch.setattr(mineru, "parse_bytes", lambda *_: pytest.fail("超限文件不得上传"))
    result = parser.parse_pdf_routed("large.pdf", b"x" * (parser.MAX_PARSE_BYTES + 1), Settings(mineru_enabled=True))
    assert result.status == "TOO_LARGE"


def test_quote_pdf_keeps_page_locator_for_business_extraction():
    """报价样本通过路由后仍可按页定位字段的原文证据。"""
    from scripts import evaluate_quote_extraction as evaluation

    result = parser.parse_pdf_routed("quote.pdf", evaluation.sample_bytes("pdf"), Settings(mineru_enabled=False))
    assert result.status == "SUCCEEDED"
    assert evaluation.quote_extraction._source_location(result.text, evaluation.ITEM_LINE) == "第 2 页"
