/* shared/inject.js — runs in the PAGE's MAIN world (injected as a <script>
 * tag by the content scripts at document_start, BEFORE Shopee's own JS).
 *
 * Why MAIN world: MV3 content scripts run in an isolated world and cannot see
 * the page's `window.fetch` — which Shopee's anti-bot SDK patches to attach
 * the x-sap-sec token. This injected script CAN see and wrap fetch, so it
 * observes the fully-authenticated responses the page legitimately fetches.
 *
 * It does NOT call Shopee itself, modify requests, or attach tokens. It only
 * reads responses the page already made (the data the user is viewing), and
 * forwards them to the isolated content script via window.postMessage.
 */
(function () {
  "use strict";

  const TAG = "[ShopeeTH-inject]";
  const RELAY_TYPE = "__SHOPEE_TH_CAPTURE__";

  // URL substrings whose responses we care about. Content scripts register
  // their interest by setting window.__SHOPEE_TH_WATCH__ before this runs
  // (it's set by the inject bootstrap in storefront.js / affiliate.js).
  function _watched() {
    return window.__SHOPEE_TH_WATCH__ || [];
  }

  function _isWatched(url) {
    return _watched().some((sub) => url.includes(sub));
  }

  function _relay(url, body) {
    try {
      window.postMessage({ type: RELAY_TYPE, url, body }, "*");
    } catch (e) {
      // Non-serializable body (image/font/etc.) — silently skip; not useful.
      console.debug(TAG, "skip non-serializable body for", url, e);
    }
  }

  // --- Wrap fetch -------------------------------------------------------
  const _origFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await _origFetch.apply(this, args);
    try {
      const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url) || "";
      if (_isWatched(url) && response.ok) {
        // Clone so the page still gets its own body stream.
        const clone = response.clone();
        clone.text().then((text) => _relay(url, text)).catch(() => {});
      }
    } catch (e) {
      console.debug(TAG, "fetch relay error", e);
    }
    return response;
  };

  // --- Wrap XMLHttpRequest ---------------------------------------------
  const _origOpen = XMLHttpRequest.prototype.open;
  const _origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__shopeeThUrl = url;
    return _origOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      try {
        if (this.__shopeeThUrl && _isWatched(this.__shopeeThUrl) && this.status >= 200 && this.status < 300) {
          _relay(this.__shopeeThUrl, this.responseText);
        }
      } catch (e) {
        console.debug(TAG, "XHR relay error", e);
      }
    });
    return _origSend.apply(this, args);
  };

  console.debug(TAG, "fetch/XHR wrappers installed (MAIN world)");
})();
