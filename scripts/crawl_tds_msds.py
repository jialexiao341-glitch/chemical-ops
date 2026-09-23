"""按 CAS 号从 ChemicalBook 抓取 TDS / MSDS 文档并分桶存入 MinIO。

数据源（已实测可用，robots.txt 未禁用这些路径）：
    MSDS 页   GET https://www.chemicalbook.com/MSDS/{cas}.htm   → 完整 MSDS 的 HTML
    MSDS PDF  GET https://www.chemicalbook.com/msds/{cas}.pdf   → 站点多数返回 404，成功才存
    TDS  PDF  从 MSDS 页 title 取英文名 → slug → GET /tds-coa/{slug}.pdf
    物性页    从 MSDS 页提取本物质 CB 号（keyword=CBxxx）→ GET
              /ChemicalProductProperty_EN_{CB}.htm（title 含 CAS 才收）→
              富 TDS 内容：物性表、风险安全声明、性质/用途/制备长文

存储（分桶，桶不存在时自动创建）：
    chemicalops-msds/{cas}.html|.pdf
    chemicalops-tds/{cas}.pdf|.html|-property.html

示例：
    python scripts/crawl_tds_msds.py --cas 64-17-5 64-19-7
    python scripts/crawl_tds_msds.py --from-chemicals --limit 20
    python scripts/crawl_tds_msds.py --cas 64-17-5 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib import robotparser
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402


BASE_URL = "https://www.chemicalbook.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 ChemicalOps-Crawler/1.0"
)
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRIES = 2
CAS_PATTERN = re.compile(r"\d{2,7}-\d{2}-\d")
RUN_ROOT = ROOT / "storage" / "imports" / "tds_msds"
MANIFEST_PATH = RUN_ROOT / "manifest.jsonl"
MSDS_BUCKET_SUFFIX = "chemicalops-msds"
TDS_BUCKET_SUFFIX = "chemicalops-tds"


def valid_cas(cas: str) -> bool:
    """CAS 号格式预检（结构校验；校验码交给站点 404 兜底）。"""

    return bool(CAS_PATTERN.fullmatch(cas))


@dataclass
class Document:
    """一份抓取到的文档（内存中的字节 + 元数据）。"""

    cas: str
    doc_type: str  # msds | tds
    ext: str  # .html | .pdf
    source_url: str
    content: bytes
    content_type: str
    # 同 CAS 同扩展名的多份文档用后缀区分，如物性页 "-property"
    name_suffix: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def bucket(self) -> str:
        return MSDS_BUCKET_SUFFIX if self.doc_type == "msds" else TDS_BUCKET_SUFFIX

    @property
    def object_key(self) -> str:
        return f"{self.cas}{self.name_suffix}{self.ext}"


@dataclass
class CrawlResult:
    """单个 CAS 的抓取结果。"""

    cas: str
    documents: list[Document] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class Fetcher(Protocol):
    """HTTP 抓取器：返回 (status_code, body, content_type)。"""

    def get(self, url: str) -> tuple[int, bytes, str]: ...


class Store(Protocol):
    """文档存储器。"""

    def exists(self, bucket: str, key: str) -> bool: ...

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None: ...


# ---------- 纯函数（单测覆盖） ----------


def slugify(name: str) -> str:
    """英文名 → TDS URL slug：小写、非字母数字折叠为连字符。"""

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def extract_msds_title(html: bytes) -> str | None:
    """从 MSDS 页提取英文名（title 形如 `Ethanol - Safety Data Sheet`）。"""

    match = re.search(rb"<title>([^<]+)</title>", html, re.IGNORECASE)
    if not match:
        return None
    title = match.group(1).decode("utf-8", errors="ignore").strip()
    marker = " - Safety Data Sheet"
    index = title.lower().find(marker.lower())
    if index >= 0:
        return title[:index].strip() or None
    return None


def validate_msds_html(content: bytes) -> bool:
    """MSDS HTML 必须包含安全数据表标识，避免把 404 页当文档存。"""

    lowered = content.lower()
    return b"safety data sheet" in lowered and b"<html" in lowered


def is_pdf(content: bytes) -> bool:
    return content[:5] == b"%PDF-"


def extract_cas_cb(html: bytes) -> str | None:
    """从 MSDS 页提取本物质的 ChemicalBook 编号（View more versions 链接的 keyword）。"""

    match = re.search(rb"keyword=(CB\d{5,})", html)
    if match:
        return match.group(1).decode("ascii")
    return None


def validate_property_html(html: bytes, cas: str) -> bool:
    """物性页标题必须包含目标 CAS，防止把模板里的示例物质页面当正文。"""

    match = re.search(rb"<title>([^<]+)</title>", html, re.IGNORECASE)
    if not match:
        return False
    return cas in match.group(1).decode("utf-8", errors="ignore")


def build_documents(
    cas: str,
    msds_html: bytes,
    msds_pdf: tuple[int, bytes] | None,
    tds_payload: tuple[str, bytes] | None,
    property_payload: tuple[str, bytes] | None = None,
) -> CrawlResult:
    """把原始响应组装成文档列表（纯组装，便于单测）。"""

    result = CrawlResult(cas=cas)
    if not validate_msds_html(msds_html):
        result.failures.append("MSDS 页内容不像 Safety Data Sheet，已跳过")
        return result
    result.documents.append(
        Document(
            cas=cas,
            doc_type="msds",
            ext=".html",
            source_url=f"{BASE_URL}/MSDS/{cas}.htm",
            content=msds_html,
            content_type="text/html; charset=utf-8",
        )
    )
    if msds_pdf is not None:
        status, body = msds_pdf
        if status == 200 and is_pdf(body):
            result.documents.append(
                Document(
                    cas=cas,
                    doc_type="msds",
                    ext=".pdf",
                    source_url=f"{BASE_URL}/msds/{cas}.pdf",
                    content=body,
                    content_type="application/pdf",
                )
            )
    if tds_payload is not None:
        url, body = tds_payload
        if url.endswith(".pdf") and is_pdf(body):
            result.documents.append(
                Document(cas=cas, doc_type="tds", ext=".pdf", source_url=url, content=body, content_type="application/pdf")
            )
        elif b"<html" in body[:2048].lower():
            # PDF 拿不到时回退存 TDS 页 HTML
            result.documents.append(
                Document(cas=cas, doc_type="tds", ext=".html", source_url=url, content=body, content_type="text/html; charset=utf-8")
            )
        else:
            result.failures.append("TDS 响应既不是 PDF 也不是 HTML，已跳过")
    else:
        result.failures.append("未找到可用的 TDS 文档")
    if property_payload is not None:
        property_url, property_body = property_payload
        if b"<html" in property_body[:2048].lower() and validate_property_html(property_body, cas):
            result.documents.append(
                Document(
                    cas=cas,
                    doc_type="tds",
                    ext=".html",
                    name_suffix="-property",
                    source_url=property_url,
                    content=property_body,
                    content_type="text/html; charset=utf-8",
                )
            )
        else:
            result.failures.append("物性页标题不含目标 CAS，已跳过")
    else:
        result.failures.append("未找到可用的物性页")
    if not result.documents:
        result.failures.append("没有任何可存储的文档")
    return result


def manifest_row(doc: Document) -> dict[str, Any]:
    return {
        "cas": doc.cas,
        "doc_type": doc.doc_type,
        "ext": doc.ext,
        "source_url": doc.source_url,
        "bucket": doc.bucket,
        "object_key": doc.object_key,
        "content_type": doc.content_type,
        "bytes": len(doc.content),
        "sha256": doc.sha256,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------- robots 合规 ----------


class RobotsGate:
    """按 robots.txt 判定 URL 是否允许抓取；抓取失败时按行业惯例放行。"""

    def __init__(self, origin: str) -> None:
        self._parser = robotparser.RobotFileParser()
        self._available = False
        try:
            response = httpx.get(urljoin(origin, "/robots.txt"), headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True)
            if response.status_code == 200:
                self._parser.parse(response.text.splitlines())
                self._available = True
        except httpx.HTTPError:
            self._available = False

    def allowed(self, url: str) -> bool:
        return (not self._available) or self._parser.can_fetch(USER_AGENT, url)


# ---------- 抓取实现 ----------


class HttpxFetcher:
    """带瞬时故障重试的 HTTP 抓取器（4xx 不重试，5xx/网络错误退避重试）。"""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES, client: httpx.Client | None = None) -> None:
        self._retries = max(0, retries)
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        )

    def get(self, url: str) -> tuple[int, bytes, str]:
        last_error: httpx.HTTPError | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.get(url)
                if response.status_code >= 500 and attempt < self._retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                content_type = response.headers.get("content-type", "")
                return response.status_code, response.content, content_type
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self._retries:
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise last_error if last_error else RuntimeError("HTTP 抓取失败")

    def close(self) -> None:
        self._client.close()


def crawl_cas(cas: str, fetch: Fetcher, gate: RobotsGate | None = None) -> CrawlResult:
    """抓取单个 CAS 的 MSDS 与 TDS 文档。"""

    result = CrawlResult(cas=cas)
    msds_page_url = f"{BASE_URL}/MSDS/{cas}.htm"
    if gate is not None and not gate.allowed(msds_page_url):
        result.failures.append("robots.txt 禁止抓取该路径")
        return result

    status, msds_html, _ctype = fetch.get(msds_page_url)
    if status != 200:
        result.failures.append(f"MSDS 页 HTTP {status}")
        return result

    # MSDS PDF 直链（站点多数情况 404，拿到真 PDF 才收）
    msds_pdf: tuple[int, bytes] | None = None
    pdf_url = f"{BASE_URL}/msds/{cas}.pdf"
    if gate is None or gate.allowed(pdf_url):
        pdf_status, pdf_body, _ = fetch.get(pdf_url)
        msds_pdf = (pdf_status, pdf_body)

    # TDS：MSDS 页 title 取英文名 → slug → /tds-coa/{slug}.pdf，404 则回退 .htm
    tds_payload: tuple[str, bytes] | None = None
    name = extract_msds_title(msds_html)
    if name:
        slug = slugify(name)
        if slug:
            pdf_tds_url = f"{BASE_URL}/tds-coa/{slug}.pdf"
            if gate is None or gate.allowed(pdf_tds_url):
                tds_status, tds_body, _ = fetch.get(pdf_tds_url)
                if tds_status == 200 and is_pdf(tds_body):
                    tds_payload = (pdf_tds_url, tds_body)
                else:
                    htm_url = f"{BASE_URL}/tds-coa/{slug}.htm"
                    if gate is None or gate.allowed(htm_url):
                        htm_status, htm_body, _ = fetch.get(htm_url)
                        if htm_status == 200:
                            tds_payload = (htm_url, htm_body)
    else:
        result.failures.append("无法从 MSDS 页解析英文名，跳过 TDS")

    # 物性页：MSDS 页里的 keyword=CBxxx 是本物质编号；页面模板还带若干
    # 示例 CB（安全段落的固定外链），逐个尝试并用「title 含 CAS」兜底校验。
    property_payload: tuple[str, bytes] | None = None
    cb_candidates: list[str] = []
    own_cb = extract_cas_cb(msds_html)
    if own_cb:
        cb_candidates.append(own_cb)
    for match in re.finditer(rb"\bCB\d{5,}\b", msds_html):
        token = match.group(0).decode("ascii")
        if token not in cb_candidates:
            cb_candidates.append(token)
        if len(cb_candidates) >= 5:
            break
    for token in cb_candidates[:5]:
        property_url = f"{BASE_URL}/ChemicalProductProperty_EN_{token}.htm"
        if gate is not None and not gate.allowed(property_url):
            continue
        prop_status, prop_body, _ = fetch.get(property_url)
        if prop_status == 200 and validate_property_html(prop_body, cas):
            property_payload = (property_url, prop_body)
            break

    return build_documents(cas, msds_html, msds_pdf, tds_payload, property_payload)


# ---------- 存储实现 ----------


class MinioStore:
    """MinIO 存储；桶不存在时自动创建。"""

    def __init__(self, buckets: tuple[str, str]) -> None:
        settings = get_settings()
        if not settings.minio_access_key or not settings.minio_secret_key:
            raise RuntimeError("MinIO 访问密钥未配置（检查 .env 的 MINIO_ACCESS_KEY / MINIO_SECRET_KEY）")
        from minio import Minio

        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            region=settings.minio_region,
        )
        self._buckets = buckets
        for bucket in buckets:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket, location=settings.minio_region)

    def exists(self, bucket: str, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(bucket, key)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None:
        from io import BytesIO

        self._client.put_object(bucket, key, BytesIO(content), length=len(content), content_type=content_type)


class LocalStore:
    """dry-run 用：写入 storage/imports/tds_msds/local/{bucket}/{key}。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    def exists(self, bucket: str, key: str) -> bool:
        return (self._root / bucket / key).exists()

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None:
        target = self._root / bucket / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


# ---------- 主流程 ----------


def resolve_cas_list(args: argparse.Namespace) -> list[str]:
    """解析 CAS 来源：命令行 / 文件 / 数据库。"""

    if args.cas:
        return list(dict.fromkeys(args.cas))
    if args.cas_file:
        lines = Path(args.cas_file).read_text(encoding="utf-8").splitlines()
        return list(dict.fromkeys(line.strip() for line in lines if line.strip() and not line.startswith("#")))
    if args.from_chemicals:
        from sqlalchemy import select

        from app.core.db import SessionLocal
        from app.modules.chemicals.model import Chemical

        db = SessionLocal()
        try:
            statement = select(Chemical.cas_no).where(Chemical.status == "ACTIVE").order_by(Chemical.id)
            if args.limit > 0:
                statement = statement.limit(args.limit)
            return list(db.scalars(statement).all())
        finally:
            db.close()
    return []


def append_manifest(rows: list[dict[str, Any]], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def crawl(args: argparse.Namespace) -> dict[str, int]:
    cas_list = resolve_cas_list(args)
    if not cas_list:
        raise SystemExit("未提供任何 CAS（--cas / --cas-file / --from-chemicals）")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    store: Store
    if args.dry_run:
        store = LocalStore(run_dir / "local")
    else:
        store = MinioStore((MSDS_BUCKET_SUFFIX, TDS_BUCKET_SUFFIX))

    fetch = HttpxFetcher(timeout=args.timeout)
    gate = None if args.ignore_robots else RobotsGate(BASE_URL)

    stats = {"requested": len(cas_list), "uploaded": 0, "skipped_existing": 0, "failed_cas": 0, "failed_docs": 0}
    stored_by_kind: dict[str, int] = {}
    run_manifest: list[dict[str, Any]] = []
    failures: list[str] = []

    try:
        for index, cas in enumerate(cas_list, start=1):
            print(f"[{index}/{len(cas_list)}] cas={cas}")
            # 格式不合法的 CAS（如演示数据后缀）直接跳过，不浪费请求
            if not valid_cas(cas):
                stats["failed_cas"] += 1
                failures.append(f"{cas}: CAS 格式不合法，已跳过")
                print("  failed: CAS 格式不合法，已跳过")
                continue
            try:
                result = crawl_cas(cas, fetch, gate)
            except httpx.HTTPError as exc:
                stats["failed_cas"] += 1
                failures.append(f"{cas}: 网络错误 {exc}")
                print(f"  failed network: {exc}")
                time.sleep(args.delay)
                continue
            except Exception as exc:  # 单个 CAS 的意外错误不中断整批
                stats["failed_cas"] += 1
                failures.append(f"{cas}: 未预期错误 {type(exc).__name__}: {exc}")
                print(f"  failed unexpected: {type(exc).__name__}: {exc}")
                time.sleep(args.delay)
                continue

            if not result.documents:
                stats["failed_cas"] += 1
                failures.extend(f"{cas}: {item}" for item in result.failures)
                print(f"  failed: {'; '.join(result.failures)}")
                time.sleep(args.delay)
                continue

            for doc in result.documents:
                if store.exists(doc.bucket, doc.object_key) and not args.force:
                    stats["skipped_existing"] += 1
                    print(f"  skip existing {doc.bucket}/{doc.object_key}")
                    continue
                store.put(doc.bucket, doc.object_key, doc.content, doc.content_type)
                row = manifest_row(doc)
                run_manifest.append(row)
                stats["uploaded"] += 1
                kind = "_".join(
                    part for part in (doc.doc_type, doc.name_suffix.strip("-"), doc.ext.lstrip(".")) if part
                )
                stored_by_kind[kind] = stored_by_kind.get(kind, 0) + 1
                print(f"  stored {doc.bucket}/{doc.object_key} ({len(doc.content)} bytes, {doc.doc_type})")
            failures.extend(f"{cas}: {item}" for item in result.failures)
            stats["failed_docs"] += len(result.failures)
            time.sleep(args.delay)
    finally:
        fetch.close()

    stats["stored_by_kind"] = stored_by_kind

    (run_dir / "stats.json").write_text(
        json.dumps({**stats, "failures": failures, "dry_run": args.dry_run}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in run_manifest),
        encoding="utf-8",
    )
    if run_manifest and not args.dry_run:
        append_manifest(run_manifest, MANIFEST_PATH)

    print(f"run_dir={run_dir}")
    print(f"requested={stats['requested']} uploaded={stats['uploaded']} skipped={stats['skipped_existing']} failed_cas={stats['failed_cas']} failed_docs={stats['failed_docs']} dry_run={args.dry_run}")
    if stored_by_kind:
        breakdown = " ".join(f"{kind}={count}" for kind, count in sorted(stored_by_kind.items()))
        print(f"stored_by_kind: {breakdown}")
    if failures:
        print("failures:")
        for item in failures:
            print(f"  - {item}")
    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取 TDS/MSDS 文档并分桶存入 MinIO（chemicalops-msds / chemicalops-tds）")
    parser.add_argument("--cas", nargs="*", help="CAS 号列表，如 --cas 64-17-5 64-19-7")
    parser.add_argument("--cas-file", help="每行一个 CAS 的文本文件（# 开头为注释）")
    parser.add_argument("--from-chemicals", action="store_true", help="从 md_chemicals 表读取 ACTIVE 化学品的 CAS")
    parser.add_argument("--limit", type=int, default=20, help="--from-chemicals 时最多取多少条，0 表示全库，默认 20")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="每次抓取后的间隔秒数，默认 1.0")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="单请求超时秒数，默认 20")
    parser.add_argument("--dry-run", action="store_true", help="只下载到本地 run 目录，不写 MinIO")
    parser.add_argument("--force", action="store_true", help="对象已存在时覆盖")
    parser.add_argument("--ignore-robots", action="store_true", help="跳过 robots.txt 检查（不建议）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.delay < 0.5 and not args.dry_run:
        raise SystemExit("为降低对目标站点的压力，--delay 不能小于 0.5 秒")
    crawl(args)


if __name__ == "__main__":
    main()
