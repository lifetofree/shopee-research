/* content/affiliate_relay.js — runs in the ISOLATED world on affiliate.shopee.co.th.
 *
 * Paired with content/affiliate.js (MAIN world). Receives captured Surface B
 * (product-list) responses, parses each via parseAffiliateItem (which fills
 * commission!), and forwards to the background service worker.
 */
(function () {
  "use strict";

  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";
  const LIST_ENDPOINT = "/api/v3/offer/product/list";

  window.addEventListener("message", function (event) {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.type !== RELAY_TYPE) return;
    if (data.surface !== "affiliate") return;
    if (!data.url.includes(LIST_ENDPOINT)) return;

    const items = extractItems(data.body);
    if (items.length === 0) return;

    const query = queryFromUrl(data.url);
    chrome.runtime.sendMessage(
      { kind: "CAPTURED_ITEMS", surface: "affiliate", query, items },
      () => void chrome.runtime.lastError,
    );
  });

  function extractItems(rawBody) {
    let parsed;
    try {
      parsed = JSON.parse(rawBody);
    } catch {
      return [];
    }
    const list = parsed && parsed.data && parsed.data.list ? parsed.data.list : [];
    if (!Array.isArray(list)) return [];

    const out = [];
    for (const listItem of list) {
      try {
        const item = window.ShopeeTHParse.parseAffiliateItem(listItem);
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
      const kw = new URL(url).searchParams.get("keyword");
      return kw || "(affiliate browse)";
    } catch {
      return "(affiliate browse)";
    }
  }
})();
