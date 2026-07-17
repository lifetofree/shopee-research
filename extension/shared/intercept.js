/* shared/intercept.js — MAIN-world fetch/XHR interceptor factory.
 *
 * Shared by content/storefront.js and content/affiliate.js (both declared
 * "world": "MAIN" in manifest.json, with this file listed first in the
 * same content_scripts entry so it runs before its caller). Wraps fetch +
 * XMLHttpRequest once per page, relaying any response whose URL matches
 * `watch` to the isolated-world relay via window.postMessage.
 *
 * Does NOT call Shopee itself or attach tokens — only observes responses
 * the page's own (already-authenticated) code produced.
 */
(function () {
  "use strict";

  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";

  function install({ watch, surface }) {
    function isWatched(url) {
      return watch.some((sub) => url.includes(sub));
    }

    function relay(url, body) {
      try {
        window.postMessage({ type: RELAY_TYPE, surface, url, body }, "*");
      } catch (e) {
        // non-serializable body (image/font) — skip
      }
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

    console.debug(`[ShopeeTH] MAIN-world fetch/XHR wrappers installed (${surface})`);
  }

  window.ShopeeTHIntercept = { install };
})();
