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
   * response.
   *
   * IMPORTANT: the live Thai storefront no longer uses the 2022 `item_basic`
   * shape this research was based on. The modern response (verified 2026-07-16
   * by capturing real traffic) spreads fields across two nested objects:
   *   - `item_data` → itemid, shopid, price (in item_card_display_price),
   *                   sold (in item_card_display_sold_count), catid, brand...
   *   - `item_card_displayed_asset` → name, image, images[]
   * `entry` is one element of the response's top-level `items[]` array.
   *
   * Surface A never carries commission → `commission: null`.
   */
  function parseStorefrontItem(entry) {
    const itemData = (entry && entry.item_data) || {};
    const asset = (entry && entry.item_card_displayed_asset) || {};

    const itemid = itemData.itemid ?? entry.itemid ?? entry.item_id;
    const shopid = itemData.shopid ?? entry.shopid;

    // Name + image live under item_card_displayed_asset.
    const name = asset.name || itemData.name || "";
    const imageId = asset.image || itemData.image;
    const image = imageId ? IMAGE_PREFIX + imageId : null;

    // Price: nested under item_data.item_card_display_price.price (micro-units).
    const priceObj = itemData.item_card_display_price || {};
    const soldObj = itemData.item_card_display_sold_count || {};

    return {
      source_id: `${shopid}.${itemid}`,
      title: name,
      image,
      price: _extractPriceFromValue(priceObj.price),
      sold: _hasSold(soldObj) ? Number(soldObj.historical_sold_count) : null,
      commission: null, // Surface A has no commission
      raw: entry,
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

  /** Extract a THB price from a raw micro-unit value (int or string). */
  function _extractPriceFromValue(rawPrice, fallbackRaw) {
    let value = Number(rawPrice);
    if ((!value || value <= 0) && fallbackRaw != null) value = Number(fallbackRaw);
    if (!value || value <= 0) return null;
    return Math.round((value / PRICE_DIVISOR) * 100) / 100; // 2dp, matches Python round(x,2)
  }

  /** Legacy: extract price from a basic/item_basic object (price/price_min). */
  function _extractPrice(basic) {
    return _extractPriceFromValue(basic && basic.price, basic && basic.price_min);
  }

  function _hasSold(soldObj) {
    return (
      soldObj != null &&
      soldObj.historical_sold_count != null &&
      Number(soldObj.historical_sold_count) > 0
    );
  }

  function _hasHistoricalSold(basic) {
    return (
      basic != null &&
      basic.historical_sold != null &&
      Number(basic.historical_sold) > 0
    );
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
