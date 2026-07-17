/* content/affiliate.js — runs in the PAGE's MAIN world on affiliate.shopee.co.th.
 *
 * Declared with "world": "MAIN" in the manifest (Chrome 111+), CSP-proof. Wraps
 * fetch + XMLHttpRequest BEFORE Shopee's SDK loads, observes the fully-
 * authenticated /api/v3/offer/product/list responses the page legitimately
 * fetches, and relays them to the isolated-world cache via window.postMessage.
 *
 * Does NOT call Shopee itself or attach tokens — only reads responses the page
 * already made. This data is richer than the card DOM (real sold count, full
 * price breakdown, image id), so the Save button merges it in when present.
 *
 * The actual fetch/XHR wrapping lives in shared/intercept.js (loaded first
 * in this same content_scripts entry) since it's identical to
 * content/storefront.js's — only the watched endpoint and surface name differ.
 */
window.ShopeeTHIntercept.install({
  watch: ["/api/v3/offer/product/list"],
  surface: "affiliate",
});
