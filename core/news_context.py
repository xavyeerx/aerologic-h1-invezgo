from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Iterable, Optional

import pytz

from config.settings import (
    NEWS_CONTEXT_DIRECT_MAX_AGE_DAYS,
    NEWS_CONTEXT_ENABLED,
    NEWS_CONTEXT_MAX_AGE_DAYS,
    NEWS_CONTEXT_MAX_ITEMS_PER_GROUP,
    NEWS_CONTEXT_WORKERS,
)
from core.data_provider import fetch_stock_disclosures, fetch_stock_news

logger = logging.getLogger(__name__)
WIB = pytz.timezone("Asia/Jakarta")

_SOURCE_BRAND_RE = re.compile(r"\binvezgo(?:\s+(?:news|report))?\b[\s,:-]*", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")

_RISK_TERMS = (
    "tidak membagikan dividen",
    "tidak bagi dividen",
    "batalkan dividen",
    "dividen turun",
    "suspensi",
    "disuspensi",
    "hentikan sementara",
    "penghentian sementara",
    "buka kembali perdagangan",
    "volatilitas transaksi",
    "kepemilikan saham terkonsentrasi",
    "gagal bayar",
    "default",
    "pailit",
    "pkpu",
    "delisting",
    "rugi bersih",
    "pendapatan turun",
    "laba turun",
    "penurunan laba",
    "gugatan",
    "sanksi",
    "right issue",
    "rights issue",
)
_POSITIVE_TERMS = (
    "dividen",
    "buyback",
    "pembelian kembali saham",
    "kontrak baru",
    "peroleh kontrak",
    "raih kontrak",
    "laba naik",
    "laba melonjak",
    "pendapatan naik",
    "pendapatan tumbuh",
    "akuisisi",
    "merger",
    "ekspansi",
    "stock split",
    "pemecahan saham",
    "pelunasan utang",
)
_MATERIAL_TERMS = _RISK_TERMS + _POSITIVE_TERMS + (
    "transaksi material",
    "perubahan pengendali",
    "restrukturisasi",
    "paparan publik insidentil",
    "public expose insidentil",
)
_ROUTINE_DISCLOSURE_TERMS = (
    "laporan bulanan registrasi pemegang efek",
    "penyampaian laporan tahunan",
    "laporan tahunan dan keberlanjutan",
)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


class _PostContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.report_title = ""
        self._inside_heading = False
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered == "report":
            self.report_title = dict(attrs).get("title") or ""
        if lowered in {"h1", "h2", "h3", "h4"}:
            self._inside_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"h1", "h2", "h3", "h4"}:
            self._inside_heading = False

    def handle_data(self, data: str) -> None:
        if self._inside_heading:
            self._heading_parts.append(data)

    @property
    def heading(self) -> str:
        return " ".join(self._heading_parts)


@dataclass(frozen=True)
class NewsContextItem:
    title: str
    published_at: datetime
    sentiment: str


@dataclass(frozen=True)
class NewsContext:
    direct: Optional[NewsContextItem]
    positives: tuple[NewsContextItem, ...]
    risks: tuple[NewsContextItem, ...]


def _clean_title(content: object) -> str:
    parser = _PostContentParser()
    try:
        parser.feed(str(content or ""))
    except Exception:
        return ""
    title = parser.report_title or parser.heading
    title = _SOURCE_BRAND_RE.sub("", title)
    return _SPACE_RE.sub(" ", title).strip(" -:,.\n\t")


def _parse_published_at(row: dict) -> Optional[datetime]:
    raw = row.get("created_at") or row.get("updated_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = WIB.localize(parsed)
    return parsed.astimezone(WIB)


def _sentiment(title: str) -> Optional[str]:
    normalized = title.casefold()
    if any(term in normalized for term in _RISK_TERMS):
        return "risk"
    if any(term in normalized for term in _POSITIVE_TERMS):
        return "positive"
    return None


def _is_routine_disclosure(title: str) -> bool:
    normalized = title.casefold()
    return any(term in normalized for term in _ROUTINE_DISCLOSURE_TERMS)


def _iter_recent_items(
    rows: Iterable[dict], alert_at: datetime
) -> Iterable[NewsContextItem]:
    for row in rows:
        title = _clean_title(row.get("content"))
        published_at = _parse_published_at(row)
        if not title or published_at is None:
            continue
        age_seconds = (alert_at - published_at).total_seconds()
        if age_seconds < 0 or age_seconds > NEWS_CONTEXT_MAX_AGE_DAYS * 86400:
            continue
        sentiment = _sentiment(title)
        if sentiment is None:
            continue
        yield NewsContextItem(title, published_at, sentiment)


def build_news_context(
    news_rows: Iterable[dict], disclosure_rows: Iterable[dict], alert_at: datetime
) -> NewsContext:
    if alert_at.tzinfo is None:
        alert_at = WIB.localize(alert_at)
    else:
        alert_at = alert_at.astimezone(WIB)

    items = list(_iter_recent_items(news_rows, alert_at))
    items.extend(_iter_recent_items(disclosure_rows, alert_at))
    items.sort(key=lambda item: item.published_at, reverse=True)

    unique: list[NewsContextItem] = []
    seen = set()
    for item in items:
        key = re.sub(r"\W+", "", item.title.casefold())
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)

    direct = next(
        (
            item
            for item in unique
            if (alert_at - item.published_at).total_seconds()
            <= NEWS_CONTEXT_DIRECT_MAX_AGE_DAYS * 86400
            and not _is_routine_disclosure(item.title)
            and any(term in item.title.casefold() for term in _MATERIAL_TERMS)
        ),
        None,
    )
    remaining = [item for item in unique if item != direct]
    positives = tuple(
        item for item in remaining if item.sentiment == "positive"
    )[:NEWS_CONTEXT_MAX_ITEMS_PER_GROUP]
    risks = tuple(
        item for item in remaining if item.sentiment == "risk"
    )[:NEWS_CONTEXT_MAX_ITEMS_PER_GROUP]
    return NewsContext(direct=direct, positives=positives, risks=risks)


def _fetch_ticker_context(ticker: str, alert_at: datetime) -> Optional[NewsContext]:
    news_rows: list[dict] = []
    disclosure_rows: list[dict] = []
    successful_requests = 0
    try:
        news_rows = fetch_stock_news(ticker)
        successful_requests += 1
    except Exception as exc:
        logger.warning("Gagal mengambil news %s: %s", ticker, exc)
    try:
        disclosure_rows = fetch_stock_disclosures(ticker)
        successful_requests += 1
    except Exception as exc:
        logger.warning("Gagal mengambil disclosure %s: %s", ticker, exc)
    if successful_requests == 0:
        return None
    return build_news_context(news_rows, disclosure_rows, alert_at)


def enrich_signals_with_news(signals: dict, alert_at: Optional[datetime] = None) -> int:
    if not NEWS_CONTEXT_ENABLED:
        return 0
    reference = alert_at or datetime.now(WIB)
    results_by_ticker: dict[str, list] = {}
    for signal_results in signals.values():
        for result in signal_results:
            ticker = str(getattr(result, "ticker", "") or "").replace(".JK", "").upper()
            if ticker:
                results_by_ticker.setdefault(ticker, []).append(result)
    if not results_by_ticker:
        return 0

    enriched = 0
    with ThreadPoolExecutor(max_workers=NEWS_CONTEXT_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_ticker_context, ticker, reference): ticker
            for ticker in results_by_ticker
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                context = future.result()
            except Exception as exc:
                logger.warning("News worker gagal untuk %s: %s", ticker, exc)
                continue
            if context is None:
                continue
            for result in results_by_ticker[ticker]:
                result.news_context = context
            enriched += 1
    return enriched


def format_context_date(value: datetime) -> str:
    local = value.astimezone(WIB)
    return f"{local.day} {_MONTHS[local.month - 1]}"
