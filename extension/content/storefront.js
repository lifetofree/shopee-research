/* content/storefront.js — runs in the ISOLATED world on shopee.co.th.
 *
 * Responsibilities:
 *   1. Bootstrap the MAIN-world inject.js (which wraps fetch/XHR to observe
 *      the page's authenticated API responses).
 *   2. Register the URL substrings to watch (Surface A search endpoint).
 *   3. Listen for relays from inject.js, parse each response into Item
 *      objects via parse.js, and forward them to the background script.
 *
 * Runs at document_start (manifest) so the inject script lands before
 * Shopee's own SDK.
 */
(function () {
  "use strict";

  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";
  const SEARCH_ENDPOINT = "/api/v4/search/search_items";

  // --- 1. Inject the MAIN-world wrapper ---------------------------------
  // Must set the watch-list BEFORE inject.js runs, so it knows what to observe.
  window.__SHOPEE_TH_WATCH__ = [SEARCH_ENDPOINT];

  try {
    const s = document.createElement("script");
    s.src = chrome.runtime.getURL("shared/inject.js");
    s.onload = function () {
      this.remove();
    };
    (document.head || document.documentElement).appendChild(s);
  } catch (e) {
    console.error("[ShopeeTH] failed to inject MAIN-world script:", e);
  }

  // --- 2. Listen for captured responses --------------------------------
  window.addEventListener("message", function (event) {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.type !== RELAY_TYPE) return;
    if (!data.url.includes(SEARCH_ENDPOINT)) return;

    const items = _extractItems(data.body);
    if (items.length === 0) return;

    const query = _queryFromUrl(data.url);
    chrome.runtime.sendMessage(
      { kind: "CAPTURED_ITEMS", surface: "storefront", query, items },
      () => void chrome.runtime.lastError, // swallow "no receiver" when popup closed
    );
  });

  // --- 3. Parse helpers -------------------------------------------------

  function _extractItems(rawBody) {
    let parsed;
    try {
      parsed = JSON.parse(rawBody);
    } catch {
      return [];
    }
    const rawItems = parsed && parsed.items ? parsed.items : [];
    if (!Array.isArray(rawItems)) return [];

    const out = [];
    for (const entry of rawItems) {
      try {
        const item = window.ShopeeTHParse.parseStorefrontItem(entry);
        if (item && item.source_id && !item.source_id.includes("undefined")) {
          out.push(item);
        }
      } catch (e) {
        // Skip unparseable entries; one bad row shouldn't lose the batch.
      }
    }
    return out;
  }

  function _queryFromUrl(url) {
    try {
      const u = new URL(url);
      return u.searchParams.get("keyword") || "(storefront browse)";
    } catch {
      return "(storefront browse)";
    }
  }
})();
