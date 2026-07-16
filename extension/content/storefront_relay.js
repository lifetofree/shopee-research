/* content/storefront_relay.js — runs in the ISOLATED world on shopee.co.th.
 *
 * Paired with content/storefront.js (MAIN world). The MAIN-world script wraps
 * fetch/XHR and posts captured responses; this relay receives them, parses
 * each into an Item via shared/parse.js, and forwards to the background
 * service worker (which POSTs to the local server).
 *
 * This file has chrome.* APIs (isolated world only); the MAIN-world file
 * does not.
 */
(function () {
  "use strict";

  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";
  const SEARCH_ENDPOINT = "/api/v4/search/search_items";

  window.addEventListener("message", function (event) {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.type !== RELAY_TYPE) return;
    if (data.surface !== "storefront") return;
    if (!data.url.includes(SEARCH_ENDPOINT)) return;

    const items = extractItems(data.body);
    if (items.length === 0) return;

    const query = queryFromUrl(data.url);
    chrome.runtime.sendMessage(
      { kind: "CAPTURED_ITEMS", surface: "storefront", query, items },
      () => void chrome.runtime.lastError, // swallow "no receiver" when popup closed
    );
  });

  function extractItems(rawBody) {
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
        // skip unparseable entry
      }
    }
    return out;
  }

  function queryFromUrl(url) {
    try {
      return new URL(url).searchParams.get("keyword") || "(storefront browse)";
    } catch {
      return "(storefront browse)";
    }
  }
})();
