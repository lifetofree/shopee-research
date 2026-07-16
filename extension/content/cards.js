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
      try {
        const data = readCard(card);
        if (!data || !data.source_id) return;
        addSaveButton(card, data);
        card.setAttribute(DECORATED_ATTR, "1");
      } catch (e) {
        // Skip a card that doesn't match the expected shape; don't break others.
      }
    });
  }

  /** Read product data from a card's DOM. Returns an Item-shaped object. */
  function readCard(card) {
    const anchor = card.querySelector('a[href*="/offer/product_offer/"]');
    if (!anchor) return null;

    // itemid is the numeric tail of /offer/product_offer/<itemid>
    const href = anchor.getAttribute("href") || "";
    const m = href.match(/\/offer\/product_offer\/(\d+)/);
    if (!m) return null;
    const itemid = m[1];

    const title = textOf(card, ".ItemCard__name") || "";
    const priceText = textOf(card, ".ItemCardPrice__wrap .price");
    const price = parsePrice(priceText);
    const commission = parseCommission(textOf(card, ".commRate"));
    const imageId = readImageId(card);

    return {
      source_id: `.${itemid}`, // shopid unknown from DOM; itemid is the key
      title,
      image: imageId ? IMAGE_PREFIX + imageId : null,
      price,
      sold: null, // not shown on affiliate cards in the captured DOM
      commission,
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

  function addSaveButton(card, data) {
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
      onSaveClick(btn, data);
    });
    host.appendChild(btn);
  }

  function onSaveClick(btn, data) {
    if (btn.classList.contains("sth-saved")) return; // already saved
    btn.classList.add("sth-saving");
    btn.textContent = "Saving…";
    const query = currentQuery();
    chrome.runtime.sendMessage(
      { kind: "SAVE_ITEM", item: data, query },
      (resp) => {
        btn.classList.remove("sth-saving");
        if (resp && resp.ok) {
          btn.classList.add("sth-saved");
          btn.textContent = "Saved ✓";
        } else {
          btn.classList.add("sth-error");
          btn.textContent = "Failed ✗";
          setTimeout(() => {
            btn.classList.remove("sth-error");
            btn.textContent = "Save";
          }, 2000);
        }
      },
    );
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
