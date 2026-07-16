/* shared/parse.js — Shopee item parsing, ported from src/shopee_th/services/search.py.
 *
 * Loaded as a content script (isolated world) BEFORE the page's own JS.
 * Exposes the parsers on `window.ShopeeTHParse` (the content script's own
 * isolated window — not the page's). Both content scripts import this file.
 *
 * Constants must match the Python reference exactly:
 *   - IMAGE_PREFIX  → https://cf.shopee.co.th/file/
 *   - PRICE_DIVISOR → 100000  (Shopee stores price in micro-units)
 */

(function () {
  "use strict";

  const IMAGE_PREFIX = "https://cf.shopee.co.th/file/";
  const PRICE_DIVISOR = 100000;

  /**
   * Parse one Surface A (storefront) item from a /api/v4/search/search_items
   * response. `entry` is one element of the response's `items[]` array, i.e.
   * `{ item_basic: { itemid, shopid, name, image, price, price_min,
   *                  historical_sold, ... } }`.
   *
   * Surface A never carries commission → `commission: null`.
   */
  function parseStorefrontItem(entry) {
    const basic = (entry && entry.item_basic) || entry || {};
    const itemid = basic.itemid ?? basic.item_id;
    const shopid = basic.shopid;

    const imageId = basic.image;
    const image = imageId ? IMAGE_PREFIX + imageId : null;

    return {
      source_id: `${shopid}.${itemid}`,
      title: basic.name || basic.title || "",
      image,
      price: _extractPrice(basic),
      sold: _hasHistoricalSold(basic) ? Number(basic.historical_sold) : null,
      commission: null, // Surface A has no commission; Phase 2 fills this via affiliate capture
      raw: basic,
    };
  }

  /**
   * Parse one Surface B (affiliate) item from a /api/v3/offer/product/list
   * response. `listItem` is one element of `data.list[]`, carrying commission
   * rates at the top level and the full product card nested under
   * `batch_item_for_item_card_full`.
   *
   * Commission: prefer seller_commission_rate, fall back to
   * default_commission_rate. Both are strings like "7%" → parse to 0.07.
   */
  function parseAffiliateItem(listItem) {
    const card = listItem.batch_item_for_item_card_full || {};
    const itemid = card.itemid ?? card.item_id ?? listItem.item_id;
    const shopid = card.shopid;

    const imageId = card.image;
    const image = imageId ? IMAGE_PREFIX + imageId : null;

    return {
      source_id: `${shopid}.${itemid}`,
      title: card.name || card.title || "",
      image,
      price: _extractPrice(card),
      sold: _hasHistoricalSold(card) ? Number(card.historical_sold) : null,
      commission: _parseCommission(listItem),
      raw: card,
    };
  }

  // --- internals --------------------------------------------------------

  function _extractPrice(basic) {
    // Shopee stores price in micro-units (÷100000). Surface A: int; Surface B:
    // string ("102600000"). `price` may be IP-tampered → fall back to price_min.
    let value = Number(basic.price);
    if (!value || value <= 0) value = Number(basic.price_min);
    if (!value || value <= 0) return null;
    return Math.round((value / PRICE_DIVISOR) * 100) / 100; // 2dp, matches Python round(x,2)
  }

  function _hasHistoricalSold(basic) {
    return basic.historical_sold != null && Number(basic.historical_sold) > 0;
  }

  function _parseCommission(listItem) {
    // "7%" → 0.07 ; "0%" → 0 ; missing/empty → null
    const raw =
      listItem.seller_commission_rate ??
      listItem.default_commission_rate ??
      null;
    if (raw == null || raw === "") return null;
    const n = parseFloat(String(raw));
    if (isNaN(n)) return null;
    return n / 100;
  }

  // Expose on the isolated content-script window.
  window.ShopeeTHParse = { parseStorefrontItem, parseAffiliateItem };
})();
