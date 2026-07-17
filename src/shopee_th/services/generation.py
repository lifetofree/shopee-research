"""Output generation: caption (Thai + English hashtags) + clip-prompt (English).

Per the `implement-output-templates` ticket body:

- **`OutputGenerator` Protocol** with two methods: ``caption(item) -> str`` and
  ``clip_prompt(item) -> str``.
- **`TemplateGenerator`** (default, env ``stub``) produces a deterministic,
  rule-based caption (Thai body ≤ 180 chars + 4–7 English hashtags, total
  ≤ 250) and a short English 8-second vertical-video brief (≤ 300 chars).
  Handles empty title / missing brand / missing category gracefully.
- **`LLMGenerator`** (env ``llm``) is a no-op skeleton that raises
  ``NotImplementedError`` on every call — explicit slot for a follow-up map
  to drop in a real LLM client.
- **`get_generator() -> OutputGenerator``** factory reads
  ``SHOPEE_TH_GENERATOR`` from the environment (default ``"stub"``); an
  explicit ``name`` argument is supported for tests and for callers that want
  to override the env (e.g. an admin-only "try LLM now" button).

The module has no FastAPI / ORM / app-config imports. It depends only on the
Pydantic ``Item`` DTO and the standard library.
"""

from __future__ import annotations

import os
import re
from typing import Any, Protocol, runtime_checkable

from shopee_th.models.domain import Item

# --- Output caps ------------------------------------------------------------

# Per the ticket body: caption body ≤ 180 chars, total caption ≤ 250 chars,
# clip-prompt ≤ 300 chars.
CAPTION_BODY_MAX = 180
CAPTION_TOTAL_MAX = 250
HASHTAG_MIN = 4
HASHTAG_MAX = 7
CLIP_PROMPT_MAX = 300

# Caps each individual hashtag word. Guarantees HASHTAG_MIN hashtags always
# fit inside CAPTION_TOTAL_MAX even with an empty body, so the length-cap
# and hashtag-count-floor contracts can never conflict.
HASHTAG_WORD_MAX = 20

# --- OutputGenerator Protocol ------------------------------------------------


@runtime_checkable
class OutputGenerator(Protocol):
    """Anything that can turn a saved `Item` into a caption + clip-prompt."""

    def caption(self, item: Item) -> str: ...
    def clip_prompt(self, item: Item) -> str: ...


# --- TemplateGenerator -------------------------------------------------------


# Thai body segments, in order, joined with " | ". Each segment is opt-in
# (e.g. brand is only added when present). Kept short to leave room for
# hashtags in the 250-char total.
_HASHTAG_FALLBACK_TITLE = "สินค้าน่าสนใจ"
_HASHTAG_FALLBACK_BODY = "ของดีแนะนำ"

# Title-stopwords for the "item-derived hashtag" generator. These are the
# common Thai-market filler words that don't make good tags.
_TITLE_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
        "by", "at", "from", "is", "are", "be", "this", "that", "it",
        # Common Thai transliterations that don't tag well.
        "new", "free", "ship", "fast",
    }
)

# Price bands for the `#<price-band>` hashtag. Thresholds are in THB.
_PRICE_BANDS: tuple[tuple[float, str], ...] = (
    (100.0, "under-100"),
    (500.0, "under-500"),
    (1_500.0, "mid-range"),
    (5_000.0, "premium"),
)

# Keyword → category-slug map. Used when `item.raw` doesn't carry a category.
# (Real category from `item.raw["item_basic"]["categories"]` always wins.)
_CATEGORY_KEYWORDS: dict[str, str] = {
    "phone": "phones",
    "case": "phone-accessories",
    "iphone": "phones",
    "samsung": "phones",
    "earbud": "audio",
    "headphone": "audio",
    "speaker": "audio",
    "bluetooth": "audio",
    "watch": "wearables",
    "bag": "fashion-bags",
    "shoe": "fashion-shoes",
    "shirt": "fashion-apparel",
    "dress": "fashion-apparel",
    "skincare": "beauty",
    "makeup": "beauty",
    "lipstick": "beauty",
    "serum": "beauty",
    "kitchen": "home-kitchen",
    "lamp": "home-decor",
    "toy": "toys",
    "book": "books",
    "supplement": "health",
    "vitamin": "health",
    "gym": "fitness",
    "yoga": "fitness",
}


def _format_price(price: float) -> str:
    """Format a THB price as `฿1,290` (no decimals for whole values)."""
    if price == int(price):
        return f"฿{int(price):,}"
    return f"฿{price:,.2f}"


def _price_band_hashtag(price: float) -> str:
    for threshold, slug in _PRICE_BANDS:
        if price < threshold:
            return slug
    return "luxury"


def _category_hashtag(item: Item) -> str:
    """Best-effort category slug: real Shopee category first, then keyword."""
    cats = (item.raw.get("item_basic") or {}).get("categories")
    if isinstance(cats, list) and cats:
        first = cats[0]
        if isinstance(first, str) and first.strip():
            slug = re.sub(r"[^a-z0-9-]+", "-", first.lower()).strip("-") or "finds"
            return slug[:HASHTAG_WORD_MAX]
    title = (item.title or "").lower()
    for keyword, slug in _CATEGORY_KEYWORDS.items():
        if keyword in title:
            return slug
    return "finds"


def _title_word_hashtags(title: str, count: int) -> list[str]:
    """Pick up to `count` distinctive words from the title for hashtags."""
    if not title:
        return ["musthave", "recommend"][:count]
    words = re.findall(r"[a-zA-Z0-9]{3,}", title.lower())
    candidates = [w[:HASHTAG_WORD_MAX] for w in words if w not in _TITLE_STOPWORDS]
    if not candidates:
        return ["musthave", "recommend"][:count]
    # Longest words first — they're more distinctive.
    candidates.sort(key=lambda w: (-len(w), w))
    return candidates[:count]


def _brand(item: Item) -> str | None:
    """Best-effort brand from `item.raw["item_basic"]["brand"]`.

    `item_basic` may be explicitly `null` in the modern storefront schema
    (the live `/api/v4/search/search_items` sets it to null), so `or {}`
    guards the chained `.get()`.
    """
    brand = (item.raw.get("item_basic") or {}).get("brand")
    if isinstance(brand, str) and brand.strip():
        return brand.strip()
    return None


def _caption_body(item: Item) -> str:
    """Build the Thai body (≤ CAPTION_BODY_MAX). Returns empty string on no data.

    The caption is marketing copy — it hooks attention and interest, not a
    spec sheet. Price and sold count are deliberately omitted (they live on
    the product page); the body leads with the product and brand only.

    Note: hashtags (including #ShopeeTH) are appended separately by
    `_all_hashtags` — do NOT put #ShopeeTH here, or it appears twice.
    """
    title = (item.title or "").strip() or _HASHTAG_FALLBACK_TITLE
    brand = _brand(item)
    parts: list[str] = [f"🔥 {title}"]
    if brand:
        parts.append(f"แบรนด์ {brand}")
    parts.append("ส่งฟรี สนใจคลิกดูได้เลย")
    body = " | ".join(parts)
    return body[:CAPTION_BODY_MAX]


def _all_hashtags(item: Item) -> list[str]:
    """Build the deterministic hashtag list (lowest priority last → dropped first)."""
    base: list[str] = ["ShopeeTH", _category_hashtag(item), _price_band_hashtag(item.price)]
    item_tags = _title_word_hashtags(item.title or "", 2)
    return base + item_tags


class TemplateGenerator:
    """Deterministic, rule-based caption + clip-prompt generator.

    No LLM, no network. The output is suitable for a v1 prototype and is
    intentionally replaceable via the `LLMGenerator` slot in a follow-up map.
    """

    def caption(self, item: Item) -> str:
        body = _caption_body(item)
        hashtags = _all_hashtags(item)
        # Shrink the body to fit CAPTION_TOTAL_MAX first, all the way down to
        # empty if needed; only drop a hashtag (and never below HASHTAG_MIN)
        # once an empty body still isn't enough. HASHTAG_WORD_MAX makes that
        # last resort effectively unreachable, but the floor is enforced
        # either way so the 4-7 hashtag contract can't be violated silently.
        for _ in range(CAPTION_BODY_MAX + len(hashtags) + 1):
            text = self._join_caption(body, hashtags)
            if len(text) <= CAPTION_TOTAL_MAX:
                return text
            if body:
                body = body[:-1]
            elif len(hashtags) > HASHTAG_MIN:
                hashtags.pop()
            else:
                return text[:CAPTION_TOTAL_MAX]
        return self._join_caption(body, hashtags)[:CAPTION_TOTAL_MAX]

    @staticmethod
    def _join_caption(body: str, hashtags: list[str]) -> str:
        if not hashtags:
            return body
        return f"{body} {' '.join('#' + h for h in hashtags)}"

    def clip_prompt(self, item: Item) -> str:
        """English 1–2 sentence brief for an 8-second vertical video."""
        title = (item.title or "").strip() or _HASHTAG_FALLBACK_BODY
        brand = _brand(item)
        # Slot the title (or its first chunk) into the standard 8-second brief.
        if len(title) > 60:
            title_slot = title[:57].rstrip() + "..."
        else:
            title_slot = title
        brand_phrase = f" by {brand}" if brand else ""
        prompt = (
            f"Vertical 9:16, 8s, hand-held close-up of {title_slot}{brand_phrase} "
            f"on a clean surface, upbeat Thai-market styling, fast cuts."
        )
        return prompt[:CLIP_PROMPT_MAX]


# --- LLMGenerator (skeleton) -------------------------------------------------


class LLMGenerator:
    """Stub for a future LLM-backed implementation.

    Per the ticket: "A no-op `LLMGenerator` skeleton class that raises
    `NotImplementedError` on every call — explicit slot for a follow-up map
    to drop in a real LLM client."

    The follow-up map is expected to:
    - implement `caption(item)` and `clip_prompt(item)` (likely via a remote
      completion API),
    - keep the same return-type contract (str, ≤ the documented caps), and
    - gate any cloud-call costs behind `SHOPEE_TH_GENERATOR=llm` (the env
      var the factory reads) so the v1 prototype isn't accidentally billed.
    """

    def caption(self, item: Item) -> str:  # pragma: no cover - always raises
        raise NotImplementedError(
            "LLMGenerator.caption is not implemented in this map; "
            "fill in a follow-up map (see wayfinder) or use SHOPEE_TH_GENERATOR=stub."
        )

    def clip_prompt(self, item: Item) -> str:  # pragma: no cover - always raises
        raise NotImplementedError(
            "LLMGenerator.clip_prompt is not implemented in this map; "
            "fill in a follow-up map (see wayfinder) or use SHOPEE_TH_GENERATOR=stub."
        )


# --- Factory ----------------------------------------------------------------


def get_generator(name: str | None = None) -> OutputGenerator:
    """Resolve the configured `OutputGenerator`.

    The factory reads `SHOPEE_TH_GENERATOR` from the environment (default
    `"stub"`) when `name` is not supplied. Tests can pass `name` explicitly
    to avoid touching the environment.

    Args:
        name: explicit generator selector. One of `"stub"` (default),
            `"llm"`. Unknown values are treated as `"stub"` so a typo in
            the env var doesn't break the app — log once and continue.

    Returns:
        An `OutputGenerator` instance. The `TemplateGenerator` is the v1
        default; `LLMGenerator` raises on every call in this map.
    """
    if name is None:
        name = os.environ.get("SHOPEE_TH_GENERATOR", "stub") or "stub"
    if name == "llm":
        return LLMGenerator()
    if name != "stub":
        # Unknown value — fall back to the safe default. The HTTP layer can
        # log this; the generator itself stays side-effect-free.
        pass
    return TemplateGenerator()
