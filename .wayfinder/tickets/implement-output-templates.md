---
name: Implement caption + clip-prompt templated stubs
labels: [wayfinder:task]
status: open
assignee: unassigned
blocked_by: []
parent: map
created: 2026-07-16
---

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
