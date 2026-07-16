---
name: Implement caption + clip-prompt templated stubs
labels: [wayfinder:task]
status: closed
assignee: Mavis
blocked_by: []
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
unblocks: [implement-fastapi-http-layer]
---

## Resolution (2026-07-16)

**Asset:** `src/shopee_th/services/generation.py` + `tests/test_generation.py`. 30 new tests, all green; full suite 63/63.

**Files added:**

- `src/shopee_th/services/generation.py` — `OutputGenerator` Protocol (`@runtime_checkable`), `TemplateGenerator` (default, deterministic), `LLMGenerator` skeleton (raises `NotImplementedError` on every call), `get_generator(name=None) -> OutputGenerator` factory reading `SHOPEE_TH_GENERATOR` from env (default `"stub"`).
- `tests/test_generation.py` — 30 tests (one parametrized over 7 seed inputs for the total-length cap, plus 23 single-case tests). All green.

**Behavior of `TemplateGenerator`:**

- `caption(item)`:
  - Thai body: `🔥 {title} | [แบรนด์ {brand} |] ราคา ฿{price} | ขายแล้ว {sold} ชิ้น | ส่งฟรี #ShopeeTH`. Brand segment is omitted when missing.
  - Sold formatting: `0` → "ยังไม่มียอดขาย"; 1-999 → "ขายแล้ว X ชิ้น"; 1K-10K → "ขายแล้ว X.XK ชิ้น"; 10K+ → "ขายแล้ว XK ชิ้น".
  - Price formatting: `฿1,290` (no decimals for whole values; `฿X.XX` for sub-baht).
  - Hashtags: `#ShopeeTH` (always) + `#<category>` + `#<price-band>` + 2 from title. Category falls back to a keyword map when `item.raw["item_basic"]["categories"]` is missing; price band uses 4 thresholds (`under-100`, `under-500`, `mid-range`, `premium`, `luxury`).
  - Total ≤ 250 chars: iteratively shrink body one char at a time, then drop the lowest-priority hashtag if still over.
  - Body ≤ 180 chars (truncation cap is also applied to the body itself if the title is enormous).
  - Empty title → "สินค้าน่าสนใจ" fallback; no exception.

- `clip_prompt(item)`:
  - English 1-2 sentence brief: `"Vertical 9:16, 8s, hand-held close-up of {title}[ by {brand}] on a clean surface, upbeat Thai-market styling, fast cuts."`
  - Title is truncated to 60 chars with `...` marker when over; brand segment is omitted when missing.
  - Total ≤ 300 chars.
  - Empty title → "ของดีแนะนำ" fallback; no exception.

**Decisions worth surfacing:**

- **Factory reads env directly** (`os.environ.get("SHOPEE_TH_GENERATOR", "stub")`) rather than going through `shopee_th.config.Settings`. This keeps the `generation` module free of app-config imports (matching the search service's "library-importable" discipline) and makes tests trivial to write with `monkeypatch.setenv`. Unknown env values fall back to `"stub"` so a typo in `.env` doesn't break the app.
- **Iterative truncation in `caption`**: simpler than the "compute everything then prune" approach and gives the same result. Worst case is `CAPTION_BODY_MAX + len(hashtags)` loop iterations for a body that's way too long, which is still fast.
- **Title-derived hashtags are the lowest priority** (rightmost in the list), so they're the first to be dropped if the total exceeds 250. The base hashtags (`ShopeeTH`, category, price-band) are always present when there's room.
- **`LLMGenerator` raises with a clear, actionable message** ("fill in a follow-up map (see wayfinder) or use SHOPEE_TH_GENERATOR=stub") so the failure mode is self-documenting if someone accidentally sets the env var to `llm`.
- **Category detection is keyword-based for v1**: 22 keywords across phones / audio / fashion / beauty / home / fitness. Real Shopee category from `item.raw["item_basic"]["categories"]` always wins. When the capture-affiliate-portal-traffic ticket lands and we have richer data, the keyword map is the place to extend — keep it pure (input: title; output: slug).

**Acceptance check (per ticket):**

- ✅ `OutputGenerator` Protocol with `caption` + `clip_prompt` methods.
- ✅ `TemplateGenerator` (env `stub`) is the default; matches all listed contracts (Thai body, English hashtags, ≤250 total, 4-7 hashtags, body contains title or fallback, empty title → no exception + placeholder).
- ✅ `LLMGenerator` skeleton raises `NotImplementedError` on both methods.
- ✅ Factory `get_generator() -> OutputGenerator` reads `SHOPEE_TH_GENERATOR` (default `"stub"`).
- ✅ Total caption length ≤ 250 across 7 seed inputs (parametrized).
- ✅ Hashtag count ∈ [4, 7] for a typical item.
- ✅ Caption body contains item title (or fallback) for both normal and empty titles.
- ✅ Empty title → no exception, sensible placeholder.
- ✅ Clip prompt is English, ≤ 300 chars, contains the title (or fallback).
- ✅ Missing brand and missing category → no exception, generic hashtags.
- ✅ No HTTP, no UI, no real LLM integration.

## Question

Implement an output-generation module behind a clean interface so a future LLM swap is mechanical. Per the F2 recommendation (templated stubs) and L2 (Thai caption + English hashtags ≤250 chars, English clip prompt).

In `src/shopee_th/services/generation.py`:

- Define a `Protocol` interface:
  ```python
  class OutputGenerator(Protocol):
      def caption(self, item: Item) -> str: ...
      def clip_prompt(self, item: Item) -> str: ...
  ```
- Default `TemplateGenerator` (selected when env says `"stub"`):
  - `caption(item)`: builds a **Thai** caption (≤180 chars body) drawing from `item.title`, `item.brand` if present, the price, and the sold count (presented as "ขายแล้ว X ชิ้น" or similar natural Thai). Appends 4–7 English hashtags chosen deterministically (e.g. `#ShopeeTH #<category-slug> #<price-band>` plus 2 derived from the item). Total `len(caption)` ≤ 250. Truncate body if needed; drop lowest-priority hashtags first.
  - `clip_prompt(item)`: returns a 1–2 sentence English brief for an 8-second vertical video: `"Vertical 9:16, 8s, hand-held close-up of {title} on a clean surface, upbeat Thai-market styling, ..."`. Keep it under ~300 chars.
  - Both must handle empty title, missing brand, missing category gracefully (no exceptions; produce a useful placeholder).
- A factory `get_generator() -> OutputGenerator` reading `SHOPEE_TH_GENERATOR` from env (default `"stub"`).
- A no-op `LLMGenerator` skeleton class (raises `NotImplementedError`) so the interface slot is explicit and a follow-up map can fill it in.

Unit tests, against multiple `Item` shapes:

- Total caption length ≤ 250 for many seed inputs.
- Hashtag count in `[4, 7]`.
- Caption body contains the item title (or fallback).
- Empty-title → no exception, sensible placeholder.
- Clip prompt is English, ≤ 300 chars, contains the title (or fallback).

No HTTP, no UI, no real LLM integration in this ticket.
