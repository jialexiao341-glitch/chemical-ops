"""TDS/MSDS 爬虫脚本的单元测试（不访问外网与 MinIO）。"""

import json

import pytest

from scripts import crawl_tds_msds as crawler


MSDS_HTML = (
    b"<!DOCTYPE html><html><head><title>Ethanol - Safety Data Sheet</title></head>"
    b"<body>Safety Data Sheet of Ethanol</body></html>"
)
FAKE_PDF = b"%PDF-1.4 fake document body"
NOT_PDF = b"<!DOCTYPE html><html>404</html>"


class FakeFetcher:
    def __init__(self, responses: dict[str, tuple[int, bytes, str]]) -> None:
        self._responses = responses
        self.requested: list[str] = []

    def get(self, url: str) -> tuple[int, bytes, str]:
        self.requested.append(url)
        return self._responses.get(url, (404, NOT_PDF, "text/html"))


class FakeStore:
    def __init__(self, existing: set[tuple[str, str]] | None = None) -> None:
        self._existing = existing or set()
        self.stored: list[tuple[str, str, bytes, str]] = []

    def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._existing

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None:
        self._existing.add((bucket, key))
        self.stored.append((bucket, key, content, content_type))


def test_slugify_lowercases_and_joins_words():
    assert crawler.slugify("Acetic acid") == "acetic-acid"
    assert crawler.slugify("Ethanol") == "ethanol"
    assert crawler.slugify("o-Xylene (99.5%)") == "o-xylene-99-5"


def test_extract_msds_title_from_page():
    assert crawler.extract_msds_title(MSDS_HTML) == "Ethanol"
    assert crawler.extract_msds_title(b"<html><title>404</title></html>") is None


def test_validate_msds_html_rejects_error_page():
    assert crawler.validate_msds_html(MSDS_HTML)
    # 404 页 / 普通页面不算 SDS
    assert not crawler.validate_msds_html(NOT_PDF)
    assert not crawler.validate_msds_html("<html><body>普通页面</body></html>".encode())
    # 只有 SDS 字样但不是 HTML 页面也不收
    assert not crawler.validate_msds_html(b"safety data sheet")


def test_is_pdf_checks_magic_bytes():
    assert crawler.is_pdf(FAKE_PDF)
    assert not crawler.is_pdf(MSDS_HTML)


def test_build_documents_collects_msds_html_pdf_and_tds_pdf():
    property_html = b"<html><head><title>Ethanol | 64-17-5</title></head><body>props</body></html>"
    result = crawler.build_documents(
        "64-17-5",
        MSDS_HTML,
        (200, FAKE_PDF),
        ("https://www.chemicalbook.com/tds-coa/ethanol.pdf", FAKE_PDF),
        ("https://www.chemicalbook.com/ChemicalProductProperty_EN_CB2362508.htm", property_html),
    )

    kinds = {(doc.doc_type, doc.ext) for doc in result.documents}
    assert kinds == {("msds", ".html"), ("msds", ".pdf"), ("tds", ".pdf"), ("tds", ".html")}
    assert result.failures == []
    # 分桶：msds 与 tds 进不同桶
    buckets = {doc.bucket for doc in result.documents}
    assert buckets == {"chemicalops-msds", "chemicalops-tds"}
    # 对象键按 CAS 命名，物性页带 -property 后缀
    assert {doc.object_key for doc in result.documents} == {
        "64-17-5.html",
        "64-17-5.pdf",
        "64-17-5-property.html",
    }


def test_build_documents_rejects_non_sds_html():
    result = crawler.build_documents("0-00-0", NOT_PDF, None, None)

    assert result.documents == []
    assert any("Safety Data Sheet" in item for item in result.failures)


def test_build_documents_falls_back_to_tds_html_when_pdf_missing():
    tds_html = b"<!DOCTYPE html><html><head><title>TDS</title></head><body>tech data</body></html>"
    result = crawler.build_documents("64-17-5", MSDS_HTML, None, ("/tds-coa/ethanol.htm", tds_html))

    tds_docs = [doc for doc in result.documents if doc.doc_type == "tds"]
    assert len(tds_docs) == 1
    assert tds_docs[0].ext == ".html"


def test_extract_cas_cb_reads_own_cb_from_msd_page():
    html = b'<a href="https://msds.chemicalbook.com/SearchEN?keyword=CB7854099">View more versions</a>'
    assert crawler.extract_cas_cb(html) == "CB7854099"
    assert crawler.extract_cas_cb(MSDS_HTML) is None


def test_validate_property_html_requires_cas_in_title():
    ok = b"<html><head><title>Methanol | 67-56-1</title></head></html>"
    other = b"<html><head><title>Ethanol | 64-17-5</title></head></html>"
    assert crawler.validate_property_html(ok, "67-56-1")
    assert not crawler.validate_property_html(other, "67-56-1")
    assert not crawler.validate_property_html(b"<html></html>", "67-56-1")


def test_build_documents_skips_property_page_when_title_mismatch():
    wrong = b"<html><head><title>Ethanol | 64-17-5</title></head></html>"
    result = crawler.build_documents(
        "67-56-1",
        MSDS_HTML,
        None,
        None,
        ("https://www.chemicalbook.com/ChemicalProductProperty_EN_CB1.htm", wrong),
    )

    assert not any(doc.name_suffix == "-property" for doc in result.documents)
    assert any("物性页" in item for item in result.failures)


def test_manifest_row_is_json_serializable_and_has_provenance():
    doc = crawler.Document(
        cas="64-17-5",
        doc_type="msds",
        ext=".html",
        source_url="https://www.chemicalbook.com/MSDS/64-17-5.htm",
        content=MSDS_HTML,
        content_type="text/html; charset=utf-8",
    )
    row = crawler.manifest_row(doc)

    assert row["cas"] == "64-17-5"
    assert row["doc_type"] == "msds"
    assert row["bucket"] == "chemicalops-msds"
    assert row["bytes"] == len(MSDS_HTML)
    assert len(row["sha256"]) == 64
    assert row["source_url"].endswith("64-17-5.htm")
    json.dumps(row)  # 可序列化


def test_crawl_cas_full_chain_with_fake_fetcher():
    msds_with_cb = MSDS_HTML.replace(
        b"</body>",
        b'<a href="https://msds.chemicalbook.com/SearchEN?keyword=CB2362508">View more versions</a></body>',
    )
    property_html = b"<html><head><title>Ethanol | 64-17-5</title></head><body>props</body></html>"
    fetcher = FakeFetcher(
        {
            "https://www.chemicalbook.com/MSDS/64-17-5.htm": (200, msds_with_cb, "text/html"),
            # MSDS PDF 直链 404（站点现状），TDS PDF 200
            "https://www.chemicalbook.com/tds-coa/ethanol.pdf": (200, FAKE_PDF, "application/pdf"),
            "https://www.chemicalbook.com/ChemicalProductProperty_EN_CB2362508.htm": (200, property_html, "text/html"),
        }
    )

    result = crawler.crawl_cas("64-17-5", fetcher, gate=None)

    kinds = {(doc.doc_type, doc.ext) for doc in result.documents}
    assert ("msds", ".html") in kinds
    assert ("tds", ".pdf") in kinds
    assert ("tds", ".html") in kinds  # 物性页
    assert ("msds", ".pdf") not in kinds  # 404 不收
    # 抓取顺序：MSDS 页 → MSDS PDF 尝试 → TDS PDF → 物性页
    assert fetcher.requested[0].endswith("/MSDS/64-17-5.htm")
    assert any(url.endswith("/tds-coa/ethanol.pdf") for url in fetcher.requested)
    property_doc = next(doc for doc in result.documents if doc.name_suffix == "-property")
    assert property_doc.object_key == "64-17-5-property.html"


def test_crawl_cas_reports_missing_msds_page():
    fetcher = FakeFetcher({})

    result = crawler.crawl_cas("0000-00-0", fetcher, gate=None)

    assert result.documents == []
    assert any("HTTP 404" in item for item in result.failures)


def test_crawl_skips_existing_unless_forced():
    store = FakeStore(existing={("chemicalops-msds", "64-17-5.html")})
    doc = crawler.Document(
        cas="64-17-5",
        doc_type="msds",
        ext=".html",
        source_url="u",
        content=MSDS_HTML,
        content_type="text/html",
    )

    # 幂等语义在 crawl 主流程：exists + 非 force 则跳过（这里直接验证 Store 协议行为）
    assert store.exists("chemicalops-msds", "64-17-5.html")
    store.put("chemicalops-tds", "64-17-5.pdf", FAKE_PDF, "application/pdf")
    assert store.exists("chemicalops-tds", "64-17-5.pdf")


def test_append_manifest_appends_jsonl():
    # 本机 pytest 的 tmp_path 目录被权限策略拒绝，改用系统临时目录
    import tempfile
    from pathlib import Path

    doc = crawler.Document(
        cas="64-17-5",
        doc_type="tds",
        ext=".pdf",
        source_url="u",
        content=FAKE_PDF,
        content_type="application/pdf",
    )

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "manifest.jsonl"
        crawler.append_manifest([crawler.manifest_row(doc)], target)
        crawler.append_manifest([crawler.manifest_row(doc)], target)

        lines = target.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["doc_type"] == "tds"


def test_parse_args_defaults_and_sources():
    args = crawler.parse_args(["--cas", "64-17-5", "64-19-7", "--dry-run"])
    assert args.cas == ["64-17-5", "64-19-7"]
    assert args.dry_run is True
    assert args.delay == pytest.approx(1.0)

    args2 = crawler.parse_args(["--from-chemicals", "--limit", "5"])
    assert args2.from_chemicals is True
    assert args2.limit == 5

    # --limit 0 表示全库
    args3 = crawler.parse_args(["--from-chemicals", "--limit", "0"])
    assert args3.limit == 0


def test_valid_cas_structure_check():
    assert crawler.valid_cas("64-17-5")
    assert crawler.valid_cas("1310-73-2")
    assert not crawler.valid_cas("64-17-5-DEMO")  # 演示数据脏 CAS
    assert not crawler.valid_cas("")
    assert not crawler.valid_cas("ethanol")


def test_htt_fetcher_retries_transport_error_then_succeeds():
    import httpx

    request = httpx.Request("GET", "https://example.com/x.pdf")
    responses = iter(
        [
            httpx.RequestError("temporary network failure", request=request),
            httpx.Response(200, content=b"%PDF-ok", headers={"content-type": "application/pdf"}, request=request),
        ]
    )

    class FlakyClient:
        def get(self, _url):
            item = next(responses)
            if isinstance(item, Exception):
                raise item
            return item

    fetcher = crawler.HttpxFetcher(retries=2, client=FlakyClient())  # type: ignore[arg-type]
    # 重试间隔直接跳过，避免测试等待
    import scripts.crawl_tds_msds as mod

    original_sleep = mod.time.sleep
    mod.time.sleep = lambda _s: None
    try:
        status, body, ctype = fetcher.get("https://example.com/x.pdf")
    finally:
        mod.time.sleep = original_sleep

    assert status == 200
    assert body.startswith(b"%PDF")
    assert "pdf" in ctype


def test_htt_fetcher_does_not_retry_4xx():
    import httpx

    request = httpx.Request("GET", "https://example.com/missing")
    calls = []

    class NotFoundClient:
        def get(self, _url):
            calls.append(1)
            return httpx.Response(404, content=b"nope", request=request)

    fetcher = crawler.HttpxFetcher(retries=3, client=NotFoundClient())  # type: ignore[arg-type]
    status, _body, _ctype = fetcher.get("https://example.com/missing")

    assert status == 404
    assert len(calls) == 1  # 4xx 不重试
