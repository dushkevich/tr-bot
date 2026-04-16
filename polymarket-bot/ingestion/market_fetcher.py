"""
Polymarket market fetcher.
Uses polymarket-apis (Gamma API) for market discovery + py-clob-client for live prices.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from config.settings import settings
from dashboard.db import upsert_market

logger = logging.getLogger(__name__)


@dataclass
class Market:
    condition_id: str
    event_id: str
    question: str
    category: str
    market_price_yes: float
    market_price_no: float
    volume: float
    liquidity: float
    neg_risk: bool
    fees_enabled: bool
    accepting_orders: bool
    resolution_date: str
    resolved: bool = False
    resolution_outcome: str | None = None
    token_id_yes: str = ""
    token_id_no: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class Orderbook:
    bids: list[tuple[float, float]]  # (price, size)
    asks: list[tuple[float, float]]
    best_bid: float = 0.0
    best_ask: float = 0.0
    best_ask_size: float = 0.0


@dataclass
class ResolvedMarket:
    condition_id: str
    question: str
    resolution_outcome: str  # 'YES' or 'NO'
    resolved_at: str


class MarketFetcher:
    """
    Fetches and pre-filters Polymarket markets.

    Pre-filter chain (no LLM cost):
    1. fees_enabled == False
    2. 0.55 <= price_yes <= 0.85
    3. best_ask_size >= min_liquidity_shares
    4. accepting_orders == True
    5. category includes geo keywords
    6. neg_risk == False (skip in Phase 1)
    """

    def __init__(self) -> None:
        self._cfg_market = settings.market
        self._cfg_system = settings.system
        self._gamma_client = None
        self._clob_client = None

    def _get_gamma(self):
        if self._gamma_client is None:
            try:
                from polymarket_apis.clients.gamma_client import PolymarketGammaClient
                self._gamma_client = PolymarketGammaClient()
            except ImportError:
                logger.warning("polymarket-apis not installed")
        return self._gamma_client

    def _get_clob(self):
        if self._clob_client is None:
            try:
                from py_clob_client.client import ClobClient
                from py_clob_client.clob_types import ApiCreds

                host = "https://clob.polymarket.com"
                key = self._cfg_system.poly_private_key
                chain_id = 137  # Polygon

                if key:
                    self._clob_client = ClobClient(
                        host, key=key, chain_id=chain_id
                    )
                else:
                    # Read-only mode for dry run / discovery
                    self._clob_client = ClobClient(host, chain_id=chain_id)
            except ImportError:
                logger.warning("py-clob-client not installed")
        return self._clob_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_active_geo_markets(self) -> list[Market]:
        """
        Fetch + pre-filter geopolitical markets.
        Snapshots results to DB.
        Returns empty list on errors.
        """
        try:
            raw = await asyncio.to_thread(self._fetch_gamma_markets_sync)
            markets = self._prefilter(raw)
            await self._snapshot_to_db(markets)
            logger.info(
                "Markets: %d raw → %d after pre-filter",
                len(raw), len(markets),
            )
            return markets
        except Exception as exc:
            logger.error("Market fetch failed (non-fatal): %s", exc)
            return []

    async def get_market_price(self, condition_id: str) -> tuple[float, float]:
        """Returns (price_yes, price_no). Falls back to (0.5, 0.5) on error."""
        try:
            return await asyncio.to_thread(self._fetch_price_sync, condition_id)
        except Exception as exc:
            logger.warning("Price fetch failed for %s: %s", condition_id, exc)
            return 0.5, 0.5

    async def get_orderbook(self, token_id: str) -> Orderbook:
        try:
            return await asyncio.to_thread(self._fetch_orderbook_sync, token_id)
        except Exception as exc:
            logger.warning("Orderbook fetch failed for %s: %s", token_id, exc)
            return Orderbook(bids=[], asks=[])

    async def is_accepting_orders(self, condition_id: str) -> bool:
        try:
            return await asyncio.to_thread(self._check_accepting_sync, condition_id)
        except Exception:
            return False

    async def get_resolved_markets(self, since: datetime) -> list[ResolvedMarket]:
        """Poll Gamma API for markets resolved since `since`."""
        try:
            return await asyncio.to_thread(self._fetch_resolved_sync, since)
        except Exception as exc:
            logger.warning("Resolved market fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Sync implementations
    # ------------------------------------------------------------------

    def _fetch_gamma_markets_sync(self) -> list[dict[str, Any]]:
        client = self._get_gamma()
        if client is None:
            return self._mock_markets_for_dry_run()

        try:
            now = datetime.now(timezone.utc)
            max_days = self._cfg_market.max_days_to_resolution
            page_limit = self._cfg_market.fetch_limit
            max_pages = self._cfg_market.fetch_max_pages

            base_kwargs: dict = dict(active=True, closed=False, limit=page_limit, end_date_min=now)
            if max_days > 0:
                base_kwargs["end_date_max"] = now + timedelta(days=max_days)

            all_raw: list[dict] = []
            for page in range(max_pages):
                kwargs = {**base_kwargs, "offset": page * page_limit}
                batch = client.get_markets(**kwargs) or []
                all_raw.extend(self._gamma_to_dict(m) for m in batch)
                if len(batch) < page_limit:
                    break  # last page

            logger.debug("Gamma API: fetched %d raw markets across %d page(s)", len(all_raw), page + 1)
            return all_raw
        except Exception as exc:
            logger.warning("Gamma API error: %s — using empty market list", exc)
            return []

    def _gamma_to_dict(self, m: Any) -> dict[str, Any]:
        """Convert a GammaMarket Pydantic object to the dict format _parse_market expects."""
        prices = m.outcome_prices or [0.5, 0.5]
        token_ids = list(m.token_ids or [])
        tags = m.tags or []
        tag_labels = [{"label": t.get("label", str(t))} if isinstance(t, dict) else {"label": str(t)} for t in tags]
        event_id = str(m.events[0]["id"] if m.events and isinstance(m.events[0], dict) else
                       (m.events[0].id if m.events else ""))
        end_date = m.end_date.isoformat() if m.end_date else ""
        return {
            "conditionId": str(m.condition_id or ""),
            "groupItemId": event_id,
            "question": str(m.question or ""),
            "category": str(m.category or ""),
            "outcomePrices": [str(p) for p in prices],
            "volume": float(m.volume_num or 0),
            "liquidity": float(m.liquidity_num or m.liquidity or 0),
            "negRisk": bool(m.neg_risk or False),
            "fees_enabled": bool(m.fees_enabled or False),
            "acceptingOrders": bool(m.accepting_orders if m.accepting_orders is not None else True),
            "endDate": end_date,
            "resolved": bool(m.closed or False),
            "resolution": None,
            "clobTokenIds": token_ids,
            "tags": tag_labels,
            "description": str(m.description or ""),
        }

    def _prefilter(self, raw_markets: list[dict[str, Any]]) -> list[Market]:
        """Apply all pre-filter rules. Returns typed Market objects."""
        result: list[Market] = []

        for m in raw_markets:
            try:
                market = self._parse_market(m)
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug("Market parse error: %s", exc)
                continue

            # 1. Must be fee-free
            if market.fees_enabled:
                continue
            # 2. Price in pre-filter range
            if not (self._cfg_market.price_range_min <= market.market_price_yes <= self._cfg_market.price_range_max):
                continue
            # 3. Minimum liquidity
            if market.liquidity < self._cfg_market.min_liquidity_shares:
                continue
            # 4. Must accept orders
            if not market.accepting_orders:
                continue
            # Topic relevance is handled by the LLM matcher, not keywords

            result.append(market)

        return result

    def _parse_market(self, m: dict[str, Any]) -> Market:
        """Parse raw Gamma API dict into Market dataclass."""
        # Handle polymarket-apis response format
        outcomes = m.get("outcomePrices", m.get("outcome_prices", ["0.5", "0.5"]))
        if isinstance(outcomes, list) and len(outcomes) >= 2:
            price_yes = float(outcomes[0])
            price_no = float(outcomes[1])
        else:
            price_yes = float(m.get("lastTradePrice", 0.5))
            price_no = 1.0 - price_yes

        tags = m.get("tags", [])
        if isinstance(tags, list):
            tag_strings = [t.get("label", t) if isinstance(t, dict) else str(t) for t in tags]
        else:
            tag_strings = []

        return Market(
            condition_id=str(m.get("conditionId", m.get("condition_id", ""))),
            event_id=str(m.get("groupItemId", m.get("event_id", ""))),
            question=str(m.get("question", "")),
            category=str(m.get("category", "")),
            market_price_yes=price_yes,
            market_price_no=price_no,
            volume=float(m.get("volume", 0)),
            liquidity=float(m.get("liquidity", 0)),
            neg_risk=bool(m.get("negRisk", m.get("neg_risk", False))),
            fees_enabled=bool(m.get("fees_enabled", m.get("enableOrderBook", False) and m.get("fee", 0) > 0)),
            accepting_orders=bool(m.get("acceptingOrders", m.get("accepting_orders", True))),
            resolution_date=str(m.get("endDate", m.get("resolution_date", ""))),
            resolved=bool(m.get("resolved", False)),
            resolution_outcome=m.get("resolution"),
            token_id_yes=str(m.get("clobTokenIds", [""])[0] if m.get("clobTokenIds") else ""),
            token_id_no=str(m.get("clobTokenIds", ["", ""])[1] if m.get("clobTokenIds") and len(m.get("clobTokenIds", [])) > 1 else ""),
            description=str(m.get("description", "")),
            tags=tag_strings,
        )

    def _is_geo_relevant(self, market: Market) -> bool:
        text = (market.question + " " + market.category + " " + " ".join(market.tags)).lower()
        return any(kw.lower() in text for kw in self._cfg_market.geo_keywords)

    def _fetch_price_sync(self, condition_id: str) -> tuple[float, float]:
        client = self._get_clob()
        if client is None:
            return 0.5, 0.5
        market = client.get_market(condition_id)
        prices = market.get("outcomePrices", ["0.5", "0.5"])
        return float(prices[0]), float(prices[1])

    def _fetch_orderbook_sync(self, token_id: str) -> Orderbook:
        client = self._get_clob()
        if client is None:
            return Orderbook(bids=[], asks=[])

        book = client.get_order_book(token_id)
        bids = [(float(b["price"]), float(b["size"])) for b in (book.get("bids") or [])]
        asks = [(float(a["price"]), float(a["size"])) for a in (book.get("asks") or [])]

        best_ask = asks[0][0] if asks else 0.0
        best_ask_size = asks[0][1] if asks else 0.0
        best_bid = bids[0][0] if bids else 0.0

        return Orderbook(bids=bids, asks=asks, best_bid=best_bid,
                         best_ask=best_ask, best_ask_size=best_ask_size)

    def _check_accepting_sync(self, condition_id: str) -> bool:
        client = self._get_clob()
        if client is None:
            return True
        market = client.get_market(condition_id)
        return bool(market.get("acceptingOrders", True))

    def _fetch_resolved_sync(self, since: datetime) -> list[ResolvedMarket]:
        client = self._get_gamma()
        if client is None:
            return []

        try:
            resolved = client.get_markets(
                active=False,
                closed=True,
                limit=200,
            )
            results = []
            for m in (resolved or []):
                if not m.get("resolved"):
                    continue
                # Filter by resolution date
                end_date = m.get("endDate", "")
                if end_date:
                    try:
                        resolved_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        if resolved_dt < since:
                            continue
                    except ValueError:
                        pass

                outcome = m.get("resolution")
                if outcome not in ("YES", "NO"):
                    continue

                results.append(ResolvedMarket(
                    condition_id=str(m.get("conditionId", "")),
                    question=str(m.get("question", "")),
                    resolution_outcome=outcome,
                    resolved_at=str(m.get("endDate", "")),
                ))
            return results
        except Exception as exc:
            logger.warning("Resolved market fetch error: %s", exc)
            return []

    async def _snapshot_to_db(self, markets: list[Market]) -> None:
        for m in markets:
            try:
                await upsert_market({
                    "condition_id": m.condition_id,
                    "event_id": m.event_id,
                    "question": m.question,
                    "category": m.category,
                    "market_price_yes": m.market_price_yes,
                    "market_price_no": m.market_price_no,
                    "volume": m.volume,
                    "liquidity": m.liquidity,
                    "neg_risk": m.neg_risk,
                    "fees_enabled": m.fees_enabled,
                    "accepting_orders": m.accepting_orders,
                    "resolution_date": m.resolution_date,
                    "resolved": m.resolved,
                    "resolution_outcome": m.resolution_outcome,
                })
            except Exception as exc:
                logger.debug("DB snapshot error for %s: %s", m.condition_id, exc)

    def _mock_markets_for_dry_run(self) -> list[dict[str, Any]]:
        """Return mock markets for testing without API keys."""
        from datetime import timedelta
        soon = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        return [
            {
                "conditionId": "mock-001",
                "groupItemId": "event-001",
                "question": "Will there be a ceasefire agreement in the ongoing conflict this week?",
                "category": "Geopolitics",
                "outcomePrices": ["0.72", "0.28"],
                "volume": 50000,
                "liquidity": 15000,
                "fees_enabled": False,
                "acceptingOrders": True,
                "endDate": soon,
                "resolved": False,
                "negRisk": False,
                "tags": [],
            },
        ]
