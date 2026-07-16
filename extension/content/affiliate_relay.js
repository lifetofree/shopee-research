/* content/affiliate_relay.js — runs in the ISOLATED world on affiliate.shopee.co.th.
 *
 * Paired with content/affiliate.js (MAIN world). Receives captured Surface B
 * (product-list) responses, parses each via parseAffiliateItem, and stores them
 * in a Map keyed by itemid (window.__ShopeeTHCache__). cards.js reads this
 * cache when a Save button is clicked, to enrich the card-DOM data with the
 * richer API fields (real sold count, full price, clean image id).
 *
 * This is an ENRICHMENT cache, not a firehose: nothing is auto-saved. Items
 * only save when the user clicks a Save button.
 */
(function () {
  "use strict";

  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";
  const CACHE_LIMIT = 500;

  // Exposed for cards.js to read. Keyed by string itemid.
  window.__ShopeeTHCache__ = window.__ShopeeTHCache__ || new Map();

  window.addEventListener("message", function (event) {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.type !== RELAY_TYPE || data.surface !== "affiliate") return;

    let parsed;
    try {
      parsed = JSON.parse(data.body);
    } catch {
      return;
    }
    const list = parsed && parsed.data && parsed.data.list ? parsed.data.list : [];
    if (!Array.isArray(list)) return;

    for (const listItem of list) {
      try {
        const item = window.ShopeeTHParse.parseAffiliateItem(listItem);
        if (!item || !item.source_id) continue;
        // Key by itemid (the tail of source_id "shopid.itemid", or raw.itemid).
        const itemid = String(item.raw && (item.raw.itemid || item.raw.item_id) || "");
        if (!itemid) continue;
        window.__ShopeeTHCache__.set(itemid, item);
      } catch (e) {
        // skip unparseable entry
      }
    }

    // Bound memory: drop oldest entries past the limit.
    if (window.__ShopeeTHCache__.size > CACHE_LIMIT) {
      const drop = window.__ShopeeTHCache__.size - CACHE_LIMIT;
      let i = 0;
      for (const key of window.__ShopeeTHCache__.keys()) {
        window.__ShopeeTHCache__.delete(key);
        if (++i >= drop) break;
      }
    }
  });
})();
