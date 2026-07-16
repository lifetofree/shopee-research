/* content/affiliate.js — runs in the PAGE's MAIN world on affiliate.shopee.co.th.
 *
 * Same pattern as content/storefront.js but watches the Surface B product-list
 * endpoint. Declared with "world": "MAIN" in the manifest (CSP-proof).
 */
(function () {
  "use strict";

  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";
  const WATCH = ["/api/v3/offer/product/list"]; // Surface B (commission)

  function isWatched(url) {
    return WATCH.some((sub) => url.includes(sub));
  }

  function relay(url, body) {
    try {
      window.postMessage({ type: RELAY_TYPE, surface: "affiliate", url, body }, "*");
    } catch (e) {}
  }

  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await origFetch.apply(this, args);
    try {
      const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url) || "";
      if (isWatched(url) && response.ok) {
        const clone = response.clone();
        clone.text().then((text) => relay(url, text)).catch(() => {});
      }
    } catch (e) {}
    return response;
  };

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__sthUrl = url;
    return origOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      try {
        if (this.__sthUrl && isWatched(this.__sthUrl) && this.status >= 200 && this.status < 300) {
          relay(this.__sthUrl, this.responseText);
        }
      } catch (e) {}
    });
    return origSend.apply(this, args);
  };

  console.debug("[ShopeeTH] MAIN-world fetch/XHR wrappers installed (affiliate)");
})();
