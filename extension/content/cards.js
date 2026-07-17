/* content/cards.js — injects a "Save" button onto each affiliate product card.
 *
 * Runs in the ISOLATED world on affiliate.shopee.co.th. A MutationObserver
 * watches for .AffiliateItemCard elements appearing (the portal is an SPA, so
 * cards render asynchronously as you scroll/search). For each card, reads the
 * product data directly from the card's DOM and appends a Save button.
 *
 * Why read from the DOM (not the cached API response)? The affiliate card
 * already renders every field we need — title, price, commission ("Comm Rate
 * 5%"), and the itemid is in the card's href. No cache lookup, no race, no
 * dependency on the MAIN-world interceptor. Simpler and always in sync with
 * what the user actually sees.
 *
 * On click → parse the card → send { kind: "SAVE_ITEM", item, query } to the
 * background → button flips to "Saved ✓" (green) on success.
 */
(function () {
  "use strict";

  const CARD_SELECTOR = ".AffiliateItemCard";
  const DECORATED_ATTR = "data-sth-decorated";
  const IMAGE_PREFIX = "https://cf.shopee.co.th/file/";

  // --- bootstrap --------------------------------------------------------

  decorateAll();
  const observer = new MutationObserver(() => decorateAll());
  observer.observe(document.documentElement, { childList: true, subtree: true });

  // --- decoration -------------------------------------------------------

  function decorateAll() {
    const cards = document.querySelectorAll(CARD_SELECTOR);
    cards.forEach((card) => {
      if (card.hasAttribute(DECORATED_ATTR)) return;
      // At decoration time we only need the itemid (from the card href) to
      // attach a Save button. The full data read (with API-cache enrichment)
      // happens at CLICK time — by then the API response that rendered the
      // card has definitely been intercepted and cached. Reading the cache at
      // decoration time races the API response and usually misses.
      const itemid = itemIdFromCard(card);
      if (!itemid) return;
      addSaveButton(card, itemid);
      card.setAttribute(DECORATED_ATTR, "1");
    });
  }

  /** Pull the numeric itemid out of a card's product-offer href. */
  function itemIdFromCard(card) {
    const anchor = card.querySelector('a[href*="/offer/product_offer/"]');
    if (!anchor) return null;
    const href = anchor.getAttribute("href") || "";
    const m = href.match(/\/offer\/product_offer\/(\d+)/);
    return m ? m[1] : null;
  }

  /** Read full product data for a card, merged with the API cache if present.
   *  Called at CLICK time so the cache (filled by affiliate_relay.js when the
   *  list API responded) is reliably populated. The API cache carries richer
   *  fields than the DOM — real sold count, full price, clean image id. */
  function readCard(card, itemid) {
    // DOM-read values (always available — this is what the user sees).
    const title = textOf(card, ".ItemCard__name") || "";
    const priceText = textOf(card, ".ItemCardPrice__wrap .price");
    const price = parsePrice(priceText);
    const commission = parseCommission(textOf(card, ".commRate"));
    const imageId = readImageId(card);
    const anchor = card.querySelector('a[href*="/offer/product_offer/"]');
    const href = anchor ? anchor.getAttribute("href") || "" : "";

    // API-cached values (richer, filled when the list response was intercepted).
    const cached = (window.__ShopeeTHCache__ && window.__ShopeeTHCache__.get(itemid)) || null;

    // Prefer cached (structured) data; fall back to DOM-read values.
    return {
      source_id: cached ? cached.source_id : `.${itemid}`,
      title: (cached && cached.title) || title,
      image: (cached && cached.image) || (imageId ? IMAGE_PREFIX + imageId : null),
      price: cached && cached.price != null ? cached.price : price,
      sold: cached ? cached.sold : null, // DOM has no sold count; cache is the only source
      commission: cached && cached.commission != null ? cached.commission : commission,
      raw: { itemid, href, surface: "affiliate" },
    };
  }

  function textOf(root, selector) {
    const el = root.querySelector(selector);
    return el ? (el.textContent || "").trim() : "";
  }

  function readImageId(card) {
    const img = card.querySelector(".ItemCard__image img");
    if (!img || !img.src) return null;
    // src like https://down-bs-th.img.susercontent.com/<imageId>.webp
    const m = img.src.match(/susercontent\.com\/([^./]+(?:-[^./]+)*)/);
    return m ? m[1] : null;
  }

  /** "265.00" → 265.0 ; "1,299" → 1299.0 */
  function parsePrice(text) {
    if (!text) return null;
    const n = parseFloat(text.replace(/[^0-9.]/g, ""));
    return isNaN(n) ? null : n;
  }

  /** "Comm Rate 5%" → 0.05 ; "Comm Rate 4.5%" → 0.045 ; "" → null */
  function parseCommission(text) {
    if (!text) return null;
    const m = text.match(/([\d.]+)\s*%/);
    if (!m) return null;
    const n = parseFloat(m[1]);
    return isNaN(n) ? null : n / 100;
  }

  // --- button -----------------------------------------------------------

  function addSaveButton(card, itemid) {
    // Attach into the custom section, next to "Get Link" if present; else the card root.
    const host =
      card.querySelector(".ItemCard__custom") ||
      card.querySelector(".AffiliateItemCard__gelinkSection") ||
      card;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sth-save-btn";
    btn.textContent = "Save";
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      // Read the card + cache at CLICK time (not decoration time) so the API
      // enrichment cache has had time to populate.
      const data = readCard(card, itemid);
      onSaveClick(btn, data);
    });
    host.appendChild(btn);
  }

  async function onSaveClick(btn, data) {
    if (btn.classList.contains("sth-saved")) return; // already saved
    btn.classList.add("sth-saving");
    btn.disabled = true;
    btn.textContent = "Saving…";
    const query = currentQuery();

    // Route through the background service worker (it can fetch 127.0.0.1
    // because it runs in the extension context — no page-CSP block, unlike a
    // content-script fetch). MV3 workers sleep, and the first message may hit
    // "receiving end does not exist" before the worker wakes — so retry a few
    // times with a short delay; the wake takes ~50-200ms.
    const result = await _sendWithRetry(
      { kind: "SAVE_ITEM", item: data, query },
      { tries: 5, delayMs: 250 },
    );
    _finish(btn, !!(result && result.ok), result && result.error);
  }

  /** Send a message to the background, retrying on the "no receiver" error
   *  that occurs while the MV3 service worker is waking up. */
  function _sendWithRetry(msg, { tries, delayMs }) {
    return new Promise((resolve) => {
      let attempt = 0;
      const tryOnce = () => {
        attempt++;
        try {
          chrome.runtime.sendMessage(msg, (resp) => {
            const le = chrome.runtime.lastError;
            if (le && /Receiving end does not exist|could not establish/i.test(le.message)) {
              // Worker not awake yet — retry if we have attempts left.
              if (attempt < tries) {
                setTimeout(tryOnce, delayMs);
              } else {
                resolve({ ok: false, error: "worker asleep" });
              }
              return;
            }
            resolve(resp || { ok: false, error: le ? le.message : "no response" });
          });
        } catch (e) {
          if (attempt < tries) {
            setTimeout(tryOnce, delayMs);
          } else {
            resolve({ ok: false, error: String(e && e.message || e) });
          }
        }
      };
      tryOnce();
    });
  }

  function _finish(btn, ok, err) {
    btn.classList.remove("sth-saving");
    btn.disabled = false;
    if (ok) {
      btn.classList.add("sth-saved");
      btn.textContent = "Saved ✓";
    } else {
      btn.classList.add("sth-error");
      btn.title = err || "save failed";
      btn.textContent = err ? `✗ ${String(err).slice(0, 24)}` : "Failed ✗";
      setTimeout(() => {
        btn.classList.remove("sth-error");
        btn.textContent = "Save";
      }, 4000);
    }
  }

  function currentQuery() {
    // Best-effort keyword: from the URL's keyword param, else the page title.
    try {
      const kw = new URL(location.href).searchParams.get("keyword");
      if (kw) return kw;
    } catch {}
    return document.title || "(affiliate browse)";
  }
})();
