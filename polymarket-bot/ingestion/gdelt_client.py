"""
GDELT news ingestion client.
Uses gdeltdoc (Doc API) for article search and gdelt (gdeltPyR) for GKG themes.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Article:
    article_id: str          # URL-based ID
    url: str
    title: str
    summary: str = ""
    source_country: str = ""
    language: str = "English"
    tone: float = 0.0        # GDELT sentiment score (negative = negative tone)
    themes: list[str] = field(default_factory=list)
    published_at: str = ""   # ISO datetime string
    domain: str = ""


@dataclass
class GKGRecord:
    record_id: str
    themes: list[str]
    persons: list[str]
    organizations: list[str]
    locations: list[str]
    tone: float
    source_url: str


class GDELTClient:
    """
    Fetches geopolitical articles and GKG records from GDELT.
    gdeltdoc handles the Doc API (article search).
    gdeltPyR handles the GKG (theme/entity extraction).
    """

    def __init__(self) -> None:
        self._cfg = settings.gdelt
        # Lazy imports — gdelt packages have slow import times
        self._gdeltdoc = None
        self._gdelt = None

    def _get_gdeltdoc(self):
        if self._gdeltdoc is None:
            try:
                from gdeltdoc import GdeltDoc
                self._gdeltdoc = GdeltDoc()
            except ImportError:
                logger.warning("gdeltdoc not installed — article search unavailable")
        return self._gdeltdoc

    def _get_gdelt(self):
        if self._gdelt is None:
            try:
                import gdelt as gdelt_lib
                self._gdelt = gdelt_lib
            except ImportError:
                logger.warning("gdelt (gdeltPyR) not installed — GKG unavailable")
        return self._gdelt

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_recent_articles(self, hours_back: float = 0.25) -> list[Article]:
        """Fetch articles published in the last `hours_back` hours."""
        return await asyncio.to_thread(self._fetch_recent_articles_sync, hours_back)

    async def fetch_gkg_themes(self, keywords: list[str]) -> list[GKGRecord]:
        """Fetch GKG records matching given keywords."""
        return await asyncio.to_thread(self._fetch_gkg_sync, keywords)

    async def get_geopolitical_articles(self) -> list[Article]:
        """
        Main entry point for the pipeline.
        Fetches recent articles and filters to geopolitically relevant ones.
        Returns empty list (not raises) on any error — pipeline must continue.
        """
        try:
            articles = await self.fetch_recent_articles(
                hours_back=self._cfg.fetch_interval_minutes / 60
            )
            filtered = self._filter_geopolitical(articles)
            logger.info("GDELT: %d total → %d geopolitical articles", len(articles), len(filtered))
            return filtered
        except Exception as exc:
            logger.error("GDELT fetch failed (non-fatal): %s", exc)
            return []

    # ------------------------------------------------------------------
    # Sync implementations (run in thread pool via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _fetch_recent_articles_sync(self, hours_back: float) -> list[Article]:
        client = self._get_gdeltdoc()
        if client is None:
            return []

        try:
            from gdeltdoc import Filters, near, repeat

            # Build time window
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=hours_back)

            # Build theme filter — OR any geopolitical GDELT theme
            theme_filter = "|".join(self._cfg.target_themes[:5])  # gdeltdoc supports limited OR

            f = Filters(
                start_date=start_dt.replace(tzinfo=None),
                end_date=end_dt.replace(tzinfo=None),
                num_records=self._cfg.article_limit,
                theme=self._cfg.target_themes[0],  # primary theme; we post-filter below
            )

            df = client.article_search(f)
            if df is None or df.empty:
                return []

            articles = []
            for _, row in df.iterrows():
                articles.append(Article(
                    article_id=str(row.get("url", "")),
                    url=str(row.get("url", "")),
                    title=str(row.get("title", "")),
                    summary="",
                    source_country=str(row.get("sourcecountry", "")),
                    language=str(row.get("language", "English")),
                    tone=float(row.get("tone", 0.0)),
                    themes=str(row.get("themes", "")).split(";") if row.get("themes") else [],
                    published_at=str(row.get("seendate", "")),
                    domain=str(row.get("domain", "")),
                ))
            return articles

        except Exception as exc:
            logger.warning("gdeltdoc article fetch error: %s: %s", type(exc).__name__, exc)
            return []

    def _fetch_gkg_sync(self, keywords: list[str]) -> list[GKGRecord]:
        gdelt = self._get_gdelt()
        if gdelt is None:
            return []

        try:
            # gdeltPyR GKG v2 — last 15 minutes
            gkg = gdelt.gdelt(version=2)
            results = gkg.Search(["gkg"], timespan="15min")

            if results is None or results.empty:
                return []

            records = []
            for _, row in results.iterrows():
                themes_raw = str(row.get("V2Themes", ""))
                themes = [t.split(",")[0] for t in themes_raw.split(";") if t]

                # Only keep records matching at least one target theme
                if not any(
                    any(kw.upper() in t.upper() for t in themes)
                    for kw in keywords
                ):
                    continue

                records.append(GKGRecord(
                    record_id=str(row.get("GKGRECORDID", "")),
                    themes=themes[:20],
                    persons=[p.split(",")[0] for p in str(row.get("V2Persons", "")).split(";") if p][:10],
                    organizations=[o.split(",")[0] for o in str(row.get("V2Organizations", "")).split(";") if o][:10],
                    locations=[loc.split("#")[0] for loc in str(row.get("V2Locations", "")).split(";") if loc][:10],
                    tone=float(str(row.get("V21OverallTone", "0")).split(",")[0] or 0),
                    source_url=str(row.get("DocumentIdentifier", "")),
                ))
            return records

        except Exception as exc:
            logger.warning("gdeltPyR GKG fetch error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _filter_geopolitical(self, articles: list[Article]) -> list[Article]:
        """
        Keep articles that match at least one target theme OR have a strong tone signal.
        Also deduplicate by URL.
        """
        seen_urls: set[str] = set()
        filtered: list[Article] = []

        for art in articles:
            if art.url in seen_urls:
                continue
            seen_urls.add(art.url)

            has_theme = any(
                any(target.upper() in theme.upper() for theme in art.themes)
                for target in self._cfg.target_themes
            )
            has_strong_tone = abs(art.tone) >= self._cfg.tone_threshold

            if has_theme or has_strong_tone or not art.themes:
                # Include articles with no theme data (may still be relevant — let matcher decide)
                filtered.append(art)

        return filtered[: self._cfg.article_limit]
