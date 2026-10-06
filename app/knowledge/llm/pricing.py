"""APIMaster market-price snapshots for CURRENT_MARKET_ESTIMATE cost.

Two cost concepts stay strictly separate:

- ``ACTUAL_PROVIDER_COST`` — only what the provider reports in a response
  (``usage.cost``). Persisted on each telemetry row; never estimated.
- ``CURRENT_MARKET_ESTIMATE`` — token usage × current marketplace pricing,
  computed at report time from a timestamped snapshot. Always labeled.

The snapshot comes from the public APIMaster marketplace endpoints:

- ``GET /api/pricing`` — canonical ratio catalog (machine-readable, same
  feed the site renders). ``model_ratio`` is priced at ``$2 per unit per
  1M tokens``; ``completion_ratio`` multiplies input for output price;
  ``cache_ratio`` discounts cached input tokens; ``billing_expr`` carries
  explicit tiered per-1M rates for tiered models; ``group_ratio``
  scales everything for the caller's key group.
- the homepage route cards — per-route prices when rendered (currently
  only some models). Where route billing is unknown, callers report a
  LOW..HIGH range instead of pretending one price is exact.

No key is required for the catalog; nothing secret is stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import httpx

MARKETPLACE_BASE = "https://apimaster.ai"
_DOLLARS_PER_RATIO_UNIT_PER_MTOK = 2.0
_LONG_CONTEXT_TOKEN_LIMIT = 272_000


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Per-1M-token market prices for one model."""

    model: str
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None
    # Long-context tier (prompt tokens > 272k) where the catalog tiers.
    long_input_per_mtok: float | None = None
    long_output_per_mtok: float | None = None
    # Per-route LOW..HIGH from the marketplace page when rendered.
    route_input_low: float | None = None
    route_input_high: float | None = None
    route_output_low: float | None = None
    route_output_high: float | None = None


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """Timestamped non-secret market snapshot."""

    retrieved_at: str
    pricing_version: str
    group: str
    group_ratio: float
    source: str
    models: dict[str, ModelPrice] = field(default_factory=dict)

    def price_for(self, model: str) -> ModelPrice | None:
        """Catalog price for a routed model ID, namespaced or bare."""

        return self.models.get(model) or self.models.get(model.rsplit("/", 1)[-1])


_TIER_EXPR = re.compile(
    r'len\s*<=\s*\d+\s*\?\s*tier\("standard",\s*'
    r"p\s*\*\s*([\d.]+)\s*\+\s*c\s*\*\s*([\d.]+)"
    r"(?:\s*\+\s*cr\s*\*\s*([\d.]+))?(?:\s*\+\s*cc\s*\*\s*[\d.]+)?\s*\)\s*"
    r':\s*tier\("long_context",\s*'
    r"p\s*\*\s*([\d.]+)\s*\+\s*c\s*\*\s*([\d.]+)"
)


def _catalog_price(row: dict[str, object], group_ratio: float) -> ModelPrice:
    model = str(row.get("model_name") or "")
    expr = str(row.get("billing_expr") or "")
    cached_ratio = float(str(row.get("cache_ratio") or 0)) or None
    match = _TIER_EXPR.search(expr)
    if match:
        inp, outp, cache_r, linp, lout = match.groups()
        cache_val = float(cache_r) if cache_r else None
        return ModelPrice(
            model=model,
            input_per_mtok=round(float(inp) * group_ratio, 6),
            output_per_mtok=round(float(outp) * group_ratio, 6),
            cached_input_per_mtok=(
                round(cache_val * group_ratio, 6) if cache_val else None
            ),
            long_input_per_mtok=round(float(linp) * group_ratio, 6),
            long_output_per_mtok=round(float(lout) * group_ratio, 6),
        )
    ratio = float(str(row.get("model_ratio") or 0))
    completion = float(str(row.get("completion_ratio") or 1))
    input_rate = ratio * _DOLLARS_PER_RATIO_UNIT_PER_MTOK * group_ratio
    return ModelPrice(
        model=model,
        input_per_mtok=round(input_rate, 6),
        output_per_mtok=round(input_rate * completion, 6),
        cached_input_per_mtok=(
            round(input_rate * cached_ratio, 6) if cached_ratio else None
        ),
    )


def _route_prices(html: str) -> dict[str, dict[str, float]]:
    """Parse per-route IN/OUT cards from the rendered marketplace page."""

    card = re.compile(
        r">(\d+)</div>.*?font-mono[^>]*>([a-z0-9._-]+)</span>.*?"
        r"IN</span><span[^>]*>\$<!-- -->([\d.]+)<!-- -->/M.*?"
        r"OUT</span><span[^>]*>\$<!-- -->([\d.]+)<!-- -->/M",
        re.S,
    )
    routes: dict[str, list[tuple[float, float]]] = {}
    for _prov, model, pin, pout in card.findall(html):
        routes.setdefault(model, []).append((float(pin), float(pout)))
    return {
        model: {
            "route_input_low": min(p[0] for p in prices),
            "route_input_high": max(p[0] for p in prices),
            "route_output_low": min(p[1] for p in prices),
            "route_output_high": max(p[1] for p in prices),
        }
        for model, prices in routes.items()
    }


def fetch_price_snapshot(
    models: set[str] | None = None,
    *,
    group: str = "default",
    timeout_seconds: float = 30.0,
    base_url: str = MARKETPLACE_BASE,
    client: httpx.Client | None = None,
) -> PriceSnapshot:
    """Fetch the current public APIMaster price snapshot.

    ``group`` is the key's billing group (``group_ratio`` scales rates).
    Raises on transport failure — estimates are never silently stale.
    """

    owns = client is None
    client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        pricing = client.get(f"{base_url}/api/pricing").json()
        group_ratios = pricing.get("group_ratio") or {}
        group_ratio = float(group_ratios.get(group) or 1.0)
        snapshot = PriceSnapshot(
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            pricing_version=str(pricing.get("pricing_version") or ""),
            group=group,
            group_ratio=group_ratio,
            source=f"{base_url}/api/pricing",
        )
        wanted = models or set()
        for row in pricing.get("data") or []:
            name = str(row.get("model_name") or "")
            if wanted and name not in wanted:
                continue
            snapshot.models[name] = _catalog_price(row, group_ratio)
        # Route-level prices enrich the LOW..HIGH range where rendered.
        try:
            html = client.get(f"{base_url}/").text
        except httpx.HTTPError:
            html = ""
        routes = _route_prices(html)
        for name, span in routes.items():
            if wanted and name not in wanted:
                continue
            price = snapshot.models.get(name)
            if price is not None:
                snapshot.models[name] = replace(
                    price,
                    route_input_low=span["route_input_low"],
                    route_input_high=span["route_input_high"],
                    route_output_low=span["route_output_low"],
                    route_output_high=span["route_output_high"],
                )
        return snapshot
    finally:
        if owns:
            client.close()


def estimate_cost_usd(
    price: ModelPrice,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> dict[str, float | None]:
    """CURRENT_MARKET_ESTIMATE for one call's usage.

    Returns ``low``/``high`` USD. ``low`` uses the cheapest known route
    price when available (else catalog rate); ``high`` uses the catalog
    (official) rate. When no route data exists both equal the catalog
    estimate — callers may collapse the range.
    """

    long_ctx = prompt_tokens > _LONG_CONTEXT_TOKEN_LIMIT
    in_rate = (
        price.long_input_per_mtok
        if long_ctx and price.long_input_per_mtok is not None
        else price.input_per_mtok
    )
    out_rate = (
        price.long_output_per_mtok
        if long_ctx and price.long_output_per_mtok is not None
        else price.output_per_mtok
    )
    uncached = max(prompt_tokens - cached_tokens, 0)
    catalog = (
        uncached * in_rate
        + (cached_tokens * (price.cached_input_per_mtok or in_rate))
        + completion_tokens * out_rate
    ) / 1_000_000
    low_in = price.route_input_low or in_rate
    low_out = price.route_output_low or out_rate
    low = (
        uncached * low_in
        + (cached_tokens * (price.cached_input_per_mtok or low_in))
        + completion_tokens * low_out
    ) / 1_000_000
    return {"low": round(low, 6), "high": round(catalog, 6)}


def write_snapshot_artifact(snapshot: PriceSnapshot, path: str) -> None:
    """Persist the timestamped snapshot alongside benchmark artifacts."""

    from dataclasses import asdict
    from pathlib import Path

    Path(path).write_text(json.dumps(asdict(snapshot), indent=2) + "\n")
