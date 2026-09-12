import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytz

from core.news_context import (
    NewsContext,
    NewsContextItem,
    build_news_context,
    enrich_signals_with_news,
)

WIB = pytz.timezone("Asia/Jakarta")


def post(title: str, published_at: str, *, report: bool = False) -> dict:
    content = (
        f'<report title="{title}" code="MDIA">'
        if report
        else f"<h4>{title}</h4><br>Isi berita"
    )
    return {"content": content, "created_at": published_at}


class NewsContextTests(unittest.TestCase):
    def setUp(self):
        self.alert_at = WIB.localize(datetime(2026, 9, 11, 16, 16))

    def test_filters_old_future_routine_and_irrelevant_items(self):
        news = [
            post("BEI Buka Kembali Perdagangan Saham MDIA", "2026-08-24T07:26:55Z"),
            post("Pendapatan MDIA Tumbuh", "2026-08-01T07:00:00Z"),
            post("MDIA Raih Kontrak Baru", "2026-09-12T07:00:00Z"),
            post("MDIA Masuk Daftar Saham Aktif", "2026-09-10T07:00:00Z"),
        ]
        disclosures = [
            post(
                "Laporan Bulanan Registrasi Pemegang Efek",
                "2026-09-09T18:36:15Z",
                report=True,
            ),
            post(
                "Pengumuman Kepemilikan Saham Terkonsentrasi Tinggi",
                "2026-08-14T08:59:05Z",
                report=True,
            ),
        ]

        context = build_news_context(news, disclosures, self.alert_at)

        self.assertIsNone(context.direct)
        self.assertEqual(context.positives, ())
        self.assertEqual(len(context.risks), 2)
        titles = [item.title for item in context.risks]
        self.assertIn("BEI Buka Kembali Perdagangan Saham MDIA", titles)
        self.assertIn("Pengumuman Kepemilikan Saham Terkonsentrasi Tinggi", titles)
        self.assertNotIn("Laporan Bulanan Registrasi Pemegang Efek", titles)

    def test_recent_material_item_becomes_direct_catalyst(self):
        context = build_news_context(
            [post("MDIA Membagikan Dividen", "2026-09-10T07:00:00Z")],
            [],
            self.alert_at,
        )

        self.assertIsNotNone(context.direct)
        self.assertEqual(context.direct.sentiment, "positive")
        self.assertEqual(context.positives, ())

    def test_negative_dividend_phrase_is_not_classified_as_positive(self):
        context = build_news_context(
            [post("MDIA Tidak Membagikan Dividen", "2026-09-10T07:00:00Z")],
            [],
            self.alert_at,
        )

        self.assertIsNotNone(context.direct)
        self.assertEqual(context.direct.sentiment, "risk")

    def test_source_brand_is_removed_from_title(self):
        context = build_news_context(
            [post("Invezgo News - MDIA Raih Kontrak Baru", "2026-09-10T07:00:00Z")],
            [],
            self.alert_at,
        )

        self.assertNotIn("invezgo", context.direct.title.casefold())

    @patch("core.news_context.fetch_stock_disclosures", side_effect=RuntimeError("down"))
    @patch("core.news_context.fetch_stock_news", side_effect=RuntimeError("down"))
    def test_worker_does_not_claim_no_news_when_all_sources_fail(self, *_):
        result = SimpleNamespace(ticker="MDIA.JK")

        enriched = enrich_signals_with_news({"strong_buy": [result]}, self.alert_at)

        self.assertEqual(enriched, 0)
        self.assertFalse(hasattr(result, "news_context"))

    @patch("core.news_context._fetch_ticker_context")
    def test_worker_fetches_once_and_attaches_context_to_same_ticker(self, fetch):
        context = NewsContext(
            direct=None,
            positives=(),
            risks=(
                NewsContextItem(
                    "Buka kembali perdagangan",
                    WIB.localize(datetime(2026, 8, 24, 14, 26)),
                    "risk",
                ),
            ),
        )
        fetch.return_value = context
        first = SimpleNamespace(ticker="MDIA.JK")
        second = SimpleNamespace(ticker="MDIA.JK")

        enriched = enrich_signals_with_news(
            {"strong_buy": [first], "early_entry": [second]}, self.alert_at
        )

        self.assertEqual(enriched, 1)
        fetch.assert_called_once()
        self.assertIs(first.news_context, context)
        self.assertIs(second.news_context, context)


if __name__ == "__main__":
    unittest.main()
