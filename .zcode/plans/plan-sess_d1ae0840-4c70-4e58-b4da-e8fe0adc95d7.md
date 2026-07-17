## Redesign: "Save" button on each Shopee product card (replaces auto-capture)

### The problem
Current extension auto-captures every item from every Shopee API response → floods saved-items with junk → you have to switch tabs to curate. You picked all three pain points: too much auto-capture, hate switching tabs, hard to curate.

### The fix
Flip from "firehose auto-save" to "click-to-save per card." A Save button appears on each product card directly on the Shopee page. You click the ones you want. Saved ones flip to "Saved ✓". No tab-switching; curation happens at the moment of capture.

### Architecture (Approach A — keep interception, cache instead of auto-save)

The working API-interception pipeline stays (it gives clean structured data: micro-unit prices, exact commission). What changes is what happens after parsing:

```
NOW:   MAIN-world intercept → relay parses → SENDS ALL to background → server saves (firehose)
NEW:   MAIN-world intercept → relay parses → CACHES by source_id (no save)
                                         → MutationObserver injects "Save" btn per card
                                         → on click: lookup cached item by source_id → save ONE
```

### Why cache-and-lookup, not DOM-scrape
- API gives clean data (price `94200000` → `฿942`, exact commission). DOM shows locale-formatted text (`"฿939"`, `"1.2k sold"`, Thai numerals) — fragile.
- The interception pipeline is already built, tested against live traffic, and `parse.js` produces the exact server payload. No reason to throw it away.
- By the time a card is visible, the API response that rendered it is already cached — no race.

### Files to change

**1. `extension/shared/parse.js`** — add `itemid` and `shopid` as top-level fields on the returned object (alongside the existing fused `source_id`). One-line change; makes card→cache lookup clean instead of string-parsing `source_id`.

**2. `extension/content/storefront_relay.js`** (and `affiliate_relay.js`) — the core change:
- Stop sending `CAPTURED_ITEMS` (delete the auto-save firehose).
- Instead, store parsed items in a module-level `Map<shopid+"."+itemid, item>`. Keep the last ~500 to bound memory.
- Expose a `window.__ShopeeTHGet__(source_id)` lookup for the button click handler.

**3. NEW `extension/content/cards.js`** (ISOLATED world, loaded on both surfaces) — the Save-button injector:
- A `MutationObserver` watches for product card anchors (`a[href*="-i."]` on storefront, offer cards on affiliate).
- For each card not already decorated, append a "Save" button (absolutely-positioned, styled to not break Shopee's layout).
- On click: parse `shopid.itemid` from the card's `href` (storefront: `-i.<shopid>.<itemid>`; affiliate cards link to `/product/<shopid>/<itemid>`), look up the cached item, send `{ kind: "SAVE_ITEM", item, query }` to background. Flip button to "Saved ✓".
- Cache-miss handling: button shows "capturing…" briefly, or a toast "browse this item first." (Rare — the API response lands before the card renders.)

**4. `extension/background.js`** — change message handling:
- Remove `CAPTURED_ITEMS` batch handler.
- Add `SAVE_ITEM` handler: POSTs one item to `/api/saved`, responds with success/duplicate/error so the button can update.
- Keep the popup status counter (increment on save).

**5. `extension/manifest.json`** — add `content/cards.js` to both surfaces' ISOLATED-world content script sets (after parse.js + the relay, so the cache is populated before the observer runs). Add a new CSS file for the button styling.

**6. NEW `extension/content/cards.css`** — minimal button styling (small, non-intrusive, Shopee-orange to feel native). Injected via the manifest as a content-script CSS resource, or `chrome.scripting.insertCSS` — manifest is simpler.

**7. `extension/popup/popup.html` + `popup.js`** — remove the "capture on/off" toggle (no more auto-capture). Keep: server status, saved count, link to the app. Add a one-line hint: "Click Save on any product to capture it."

### What does NOT change
- The MAIN-world interceptor scripts (`storefront.js`, `affiliate.js`) — unchanged, still wrap fetch/XHR.
- `parse.js`'s field-extraction logic — unchanged (just adds two output fields).
- The server, persistence, generation, and the `static/` UI at `127.0.0.1:8000` — unchanged. The local app remains the place to view saved items + generate captions. (You still go there to generate captions, but capture/selection now happens on the Shopee page — that's the tab-switching we're eliminating.)

### The one unknown to verify first
I've never inspected a live Shopee card's DOM. The `-i.<shopid>.<itemid>` href pattern is well-established externally but unconfirmed in this repo. **Step 1 of the build is a 2-minute DevTools check**: open a shopee.co.th search, inspect a product card's `<a>`, confirm the href shape and find a stable selector to attach the button to. If the pattern differs, the card-injector adapts — but I build that after seeing the real DOM, not before.

### What I won't do without checking back
- I won't touch the working capture pipeline until the Save-button path is proven (the auto-capture stays as a fallback until you confirm the button works).
- I won't remove the popup toggle until the new flow is verified end-to-end.
- I'll keep the changes isolated to the `extension/` directory — no server-side changes needed for this redesign.

### Result
You browse Shopee/affiliate as normal. Save buttons appear on products. Click the ones you want → they save (with commission on affiliate items). No junk, no tab-switching to capture, curation at the point of decision.