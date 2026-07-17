/* content/storefront.js — runs in the PAGE's MAIN world on shopee.co.th.
 *
 * Declared in manifest.json with "world": "MAIN" (Chrome 111+), so Chrome
 * injects it directly — bypassing the page's Content-Security-Policy, which
 * would block a manually-appended <script> tag. Runs at document_start,
 * BEFORE Shopee's own SDK, so the fetch/XHR wrappers land first.
 *
 * This script observes the fully-authenticated responses the page
 * legitimately fetches (the SDK has already attached x-sap-sec). It does NOT
 * call Shopee itself or attach any tokens — only reads what the page made,
 * and relays it to the isolated-world relay script via window.postMessage.
 *
 * The actual fetch/XHR wrapping lives in shared/intercept.js (loaded first
 * in this same content_scripts entry) since it's identical to
 * content/affiliate.js's — only the watched endpoint and surface name differ.
 */
window.ShopeeTHIntercept.install({
  watch: ["/api/v4/search/search_items"], // Surface A
  surface: "storefront",
});
