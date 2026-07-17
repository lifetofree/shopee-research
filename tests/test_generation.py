"""Unit tests for `services.generation` (caption + clip-prompt + factory).

Coverage targets (per the ticket body):
- Total caption length ≤ 250 for many seed inputs.
- Hashtag count in [4, 7].
- Caption body contains the item title (or fallback).
- Empty title → no exception, sensible placeholder.
- Clip prompt is English, ≤ 300 chars, contains the title (or fallback).
- LLMGenerator raises NotImplementedError on both methods.
- get_generator() returns TemplateGenerator for "stub" / unset; LLMGenerator for "llm".
- Missing brand / missing category → no exception, generic hashtags.
"""

from __future__ import annotations

import pytest

from shopee_th.models.domain import Item
from shopee_th.services.generation import (
    CAPTION_TOTAL_MAX,
    CLIP_PROMPT_MAX,
    HASHTAG_MAX,
    HASHTAG_MIN,
    LLMGenerator,
    OutputGenerator,
    TemplateGenerator,
    get_generator,
)


# --- Fixtures -------------------------------------------------------------


def _item(
    *,
    title: str = "iPhone 15 silicone case",
    price: float = 290.0,
    sold: int = 1234,
    brand: str | None = "Apple",
    categories: list[str] | None = None,
) -> Item:
    item_basic: dict = {"name": title, "price": int(price * 100_000), "historical_sold": sold}
    if brand is not None:
        item_basic["brand"] = brand
    if categories is not None:
        item_basic["categories"] = categories
    return Item(
        source_id="shop.1",
        title=title,
        image="https://cf.shopee.co.th/file/abc",
        price=price,
        sold=sold,
        commission=None,
        raw={"item_basic": item_basic},
    )


# --- TemplateGenerator.caption --------------------------------------------


@pytest.mark.parametrize(
    "seed",
    [
        _item(),
        _item(title="ของใช้ในบ้าน", price=89.0, sold=42),
        _item(title="Premium leather bag", price=4_500.0, sold=12),
        _item(title="Sony WH-1000XM5 wireless headphones", price=12_900.0, sold=8500),
        _item(title="ชาบูสูตรเด็ด", price=159.0, sold=200_000),
        _item(title="A" * 200, price=10.0, sold=1),  # very long title
        _item(title="short", price=0.5, sold=0),
    ],
)
def test_caption_total_length_within_cap(seed: Item) -> None:
    gen = TemplateGenerator()
    out = gen.caption(seed)
    assert len(out) <= CAPTION_TOTAL_MAX, f"caption too long ({len(out)} chars): {out!r}"


def test_caption_hashtag_count_in_range() -> None:
    gen = TemplateGenerator()
    out = gen.caption(_item())
    # Hashtags are '#word' tokens. Strip '#' and count distinct words starting with '#'.
    hashtag_count = sum(1 for tok in out.split() if tok.startswith("#"))
    assert HASHTAG_MIN <= hashtag_count <= HASHTAG_MAX


def test_caption_long_title_and_brand_keeps_both_caps() -> None:
    # Regression: a long title + long brand used to shrink the body to a
    # single char and then pop hashtags below HASHTAG_MIN to hit the total
    # cap, satisfying the length contract while violating the count one.
    seed = _item(title="A" * 200, brand="B" * 100, price=999_999.0, sold=999_999)
    out = TemplateGenerator().caption(seed)
    hashtag_count = sum(1 for tok in out.split() if tok.startswith("#"))
    assert len(out) <= CAPTION_TOTAL_MAX
    assert HASHTAG_MIN <= hashtag_count <= HASHTAG_MAX


def test_caption_contains_title_or_fallback() -> None:
    gen = TemplateGenerator()
    out = gen.caption(_item(title="iPhone 15 silicone case"))
    assert "iPhone 15 silicone case" in out


def test_caption_empty_title_uses_fallback() -> None:
    gen = TemplateGenerator()
    out = gen.caption(_item(title=""))
    # No exception, length still under cap, contains the fallback token.
    assert len(out) <= CAPTION_TOTAL_MAX
    # Fallback is the Thai token "สินค้าน่าสนใจ" (interesting product).
    assert "สินค้าน่าสนใจ" in out


def test_caption_empty_title_very_short_title_uses_fallback() -> None:
    gen = TemplateGenerator()
    out = gen.caption(_item(title="   "))
    assert "สินค้าน่าสนใจ" in out
    assert len(out) <= CAPTION_TOTAL_MAX


def test_caption_missing_brand_does_not_break() -> None:
    gen = TemplateGenerator()
    out = gen.caption(_item(brand=None))
    assert "แบรนด์" not in out  # no "brand X" segment
    assert len(out) <= CAPTION_TOTAL_MAX


def test_caption_missing_category_falls_back_to_keyword_or_generic() -> None:
    gen = TemplateGenerator()
    out = gen.caption(_item(categories=None, title="Generic product"))
    # No exception, length under cap. No specific-category hashtag expected.
    assert len(out) <= CAPTION_TOTAL_MAX


def test_caption_omits_price_and_sold() -> None:
    """The caption is marketing copy (hooks attention), not a spec sheet —
    price and sold count are deliberately omitted. They live on the product
    page; the caption leads with the product + brand + a call to action."""
    gen = TemplateGenerator()
    out = gen.caption(_item(price=1290.0, sold=2_345))
    assert "฿" not in out, "price should not appear in the caption"
    assert "ขายแล้ว" not in out, "sold count should not appear in the caption"
    assert "2.3K" not in out, "compact sold count should not appear in the caption"
    # The title and a call-to-action should still be present.
    assert "iPhone 15" in out
    assert "ส่งฟรี" in out


# --- TemplateGenerator.clip_prompt ---------------------------------------


def test_clip_prompt_within_cap() -> None:
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item())
    assert len(out) <= CLIP_PROMPT_MAX


def test_clip_prompt_contains_title() -> None:
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item(title="iPhone 15 silicone case"))
    assert "iPhone 15 silicone case" in out


def test_clip_prompt_empty_title_uses_fallback() -> None:
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item(title=""))
    assert len(out) <= CLIP_PROMPT_MAX
    assert "ของดีแนะนำ" in out


def test_clip_prompt_long_title_is_truncated() -> None:
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item(title="A" * 200))
    assert len(out) <= CLIP_PROMPT_MAX
    # Truncation marker present.
    assert "..." in out


def test_clip_prompt_includes_brand_when_present() -> None:
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item(brand="Apple"))
    assert "by Apple" in out


def test_clip_prompt_omits_brand_clause_when_absent() -> None:
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item(brand=None))
    assert "by " not in out


def test_clip_prompt_is_english() -> None:
    """Spot-check: no Thai script characters in the clip prompt (it's English by design)."""
    gen = TemplateGenerator()
    out = gen.clip_prompt(_item())
    thai_codepoints = sum(1 for ch in out if "ก" <= ch <= "๛")
    # Brand slot is Thai-source so allow it; but the surrounding structure
    # is English. A loose bound: at most a handful of Thai chars from a brand.
    assert thai_codepoints <= 20


# --- LLMGenerator (Google Gemini, mocked — never hits the network) ----------


def test_llm_generator_uses_gemini_response_for_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the Gemini call succeeds, its text is returned (capped to 250)."""
    gen = LLMGenerator(api_key="fake-key")

    def fake_generate(self, _prompt):
        return "🔥 สุดยอดเคส iPhone ราคาเบรค #ShopeeTH #iphone #case #premium"

    monkeypatch.setattr(LLMGenerator, "_generate", fake_generate)
    out = gen.caption(_item())
    assert len(out) <= 250
    assert "#ShopeeTH" in out


def test_llm_generator_caption_falls_back_when_no_api_key() -> None:
    """No API key → the template fallback runs (never raises)."""
    gen = LLMGenerator(api_key="")
    out = gen.caption(_item())
    assert isinstance(out, str)
    assert len(out) <= 250
    assert out  # non-empty placeholder


def test_llm_generator_caption_falls_back_on_call_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the Gemini call raises (quota, network), the template fallback runs."""
    gen = LLMGenerator(api_key="fake-key")

    def boom(self, _prompt):
        raise RuntimeError("429 quota exceeded")

    monkeypatch.setattr(LLMGenerator, "_generate", boom)
    out = gen.caption(_item())
    assert isinstance(out, str)
    assert len(out) <= 250
    assert "#ShopeeTH" in out  # template fallback always includes this


def test_llm_generator_clip_prompt_uses_gemini_response(monkeypatch: pytest.MonkeyPatch) -> None:
    gen = LLMGenerator(api_key="fake-key")

    def fake_generate(self, _prompt):
        return "Vertical 9:16, 8s, close-up of the iPhone case, bright lighting."

    monkeypatch.setattr(LLMGenerator, "_generate", fake_generate)
    out = gen.clip_prompt(_item())
    assert len(out) <= 300


def test_llm_generator_clip_prompt_falls_back_when_no_api_key() -> None:
    gen = LLMGenerator(api_key="")
    out = gen.clip_prompt(_item())
    assert isinstance(out, str)
    assert len(out) <= 300
    assert out


# --- Factory -------------------------------------------------------------


def test_factory_default_is_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHOPEE_TH_GENERATOR", raising=False)
    gen = get_generator()
    assert isinstance(gen, TemplateGenerator)
    assert isinstance(gen, OutputGenerator)  # runtime_checkable Protocol


def test_factory_explicit_stub_is_template() -> None:
    gen = get_generator("stub")
    assert isinstance(gen, TemplateGenerator)


def test_factory_explicit_llm_is_llm() -> None:
    gen = get_generator("llm")
    assert isinstance(gen, LLMGenerator)


def test_factory_env_llm_is_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPEE_TH_GENERATOR", "llm")
    gen = get_generator()
    assert isinstance(gen, LLMGenerator)


def test_factory_unknown_value_falls_back_to_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in the env var must not break the app — fall back to stub."""
    monkeypatch.setenv("SHOPEE_TH_GENERATOR", "definitely-not-a-real-value")
    gen = get_generator()
    assert isinstance(gen, TemplateGenerator)
