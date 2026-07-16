/* shopee-th SPA — vanilla JS, no framework, no build step.
 *
 * Architecture:
 *   - IIFE module: no globals leak; only `window.ShopeeTH` is exposed
 *     for the e2e test's smoke check (gated on `NODE_ENV !== "production"`
 *     in the future; for now it's always exposed).
 *   - Layered: Constants → State → API → Format → Render → Handlers → Init.
 *   - Event delegation: the saved list delegates clicks to a single
 *     listener, so dynamically inserted items work without rebinding.
 *   - Idempotent save: a Set of in-flight source_ids blocks double-clicks
 *     before the server sees them; the server is already idempotent on
 *     source_id (per the persistence ticket), so even races are safe.
 *   - Errors surface as a dismissible banner with the server-supplied
 *     `detail.message` (and `guidance` when present). No silent failures.
 *
 * API contract (do not change without updating the FastAPI routes):
 *   POST /api/search                          { query, limit } -> { items }
 *   GET  /api/saved                           -> { items: [SavedItemDTO] }
 *   POST /api/saved                           { item, query }    -> SavedItemDTO
 *   DELETE /api/saved/{id}                    -> 204
 *   POST /api/saved/{id}/caption              -> { body, generated_at }
 *   POST /api/saved/{id}/clip-prompt          -> { body, generated_at }
 *   GET  /api/saved/{id}/outputs?kind=...     -> { outputs: [...] }
 *
 * Error body (uniform):
 *   { detail: { error: "<code>", message: "<msg>", guidance?: "<hint>" } }
 */

(function () {
  "use strict";

  // ---- Constants --------------------------------------------------------

  const MAX_LIMIT = 20;
  const DEFAULT_LIMIT = 20;
  const FETCH_TIMEOUT_MS = 15000;

  // ---- State ------------------------------------------------------------

  /**
   * In-memory state for the SPA. Kept minimal — the server is the source
   * of truth. We mirror enough to render without round-tripping every
   * action, but every mutation re-fetches or re-derives from the response.
   */
  const state = {
    /** @type {Array<Object>} last search result items (the search service's `Item` shape). */
    lastResults: [],
    /** @type {Array<Object>} saved items, newest first. */
    savedItems: [],
    /** @type {Set<string>} source_ids with a save in flight. */
    saving: new Set(),
    /** @type {Set<number>} saved-item ids with a generation or remove in flight. */
    inflight: new Set(),
  };

  // ---- DOM refs (populated in `init`). -------------------------------

  const dom = {};

  // ---- API helpers ------------------------------------------------------

  /**
   * Wrap fetch with a timeout and a uniform error shape. Throws an
   * `Error` whose `.message` is the human-readable server message (or a
   * network error description) so callers can route it to the error
   * banner without inspecting the response.
   *
   * @param {string} url
   * @param {RequestInit} options
   * @returns {Promise<any>} parsed JSON body, or `null` for 204
   */
  async function request(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const resp = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(options.body && !(options.body instanceof FormData)
            ? { "Content-Type": "application/json" }
            : {}),
          ...(options.headers || {}),
        },
      });
      if (resp.status === 204) return null;
      const text = await resp.text();
      const body = text ? safeJson(text) : null;
      if (!resp.ok) {
        // FastAPI wraps HTTPException(detail=...) under `detail`. Hoist
        // detail.message / detail.guidance to the Error so the banner
        // shows the right text.
        const detail = (body && body.detail) || {};
        const msg =
          (typeof detail === "object" && detail.message) ||
          (typeof detail === "string" && detail) ||
          `Request failed: HTTP ${resp.status}`;
        const err = new Error(msg);
        err.url = url;
        err.status = resp.status;
        err.guidance = detail.guidance || null;
        err.code = detail.error || null;
        throw err;
      }
      return body;
    } catch (err) {
      if (err.name === "AbortError") {
        throw new Error(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s`);
      }
      // Already a structured error from the !ok branch — rethrow.
      if (err.url) throw err;
      // Network error (offline, DNS, CORS, etc.).
      throw new Error(`Network error: ${err.message || err}`);
    } finally {
      clearTimeout(timeout);
    }
  }

  function safeJson(text) {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  const api = {
    search(query, limit) {
      return request("/api/search", {
        method: "POST",
        body: JSON.stringify({ query, limit: limit ?? DEFAULT_LIMIT }),
      });
    },
    listSaved() {
      return request("/api/saved", { method: "GET" });
    },
    saveItem(item, query) {
      return request("/api/saved", {
        method: "POST",
        body: JSON.stringify({ item, query }),
      });
    },
    removeSaved(id) {
      return request(`/api/saved/${id}`, { method: "DELETE" });
    },
    generateCaption(id) {
      return request(`/api/saved/${id}/caption`, { method: "POST" });
    },
    generateClipPrompt(id) {
      return request(`/api/saved/${id}/clip-prompt`, { method: "POST" });
    },
    listOutputs(id, kind) {
      return request(
        `/api/saved/${id}/outputs?kind=${encodeURIComponent(kind)}`,
        { method: "GET" },
      );
    },
  };

  // ---- Formatting -------------------------------------------------------

  /** Format THB price as `฿1,290` (or `฿1,290.50` if sub-baht). */
  function formatPrice(price) {
    const n = Number(price) || 0;
    if (Number.isInteger(n)) return `฿${n.toLocaleString("en-US")}`;
    return `฿${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  }

  /** Format sold count in compact form: `1.2K`, `12K`, `1,234`, or `0`. */
  function formatSold(sold) {
    const n = Number(sold) || 0;
    if (n >= 1000) {
      if (n < 10000) return `${(n / 1000).toFixed(1)}K sold`;
      return `${Math.floor(n / 1000)}K sold`;
    }
    return `${n} sold`;
  }

  /** Format commission rate as `6%` or empty string when null. */
  function formatCommission(rate) {
    if (rate == null) return "";
    const pct = (Number(rate) * 100).toFixed(rate < 0.1 ? 1 : 0);
    return `${pct}%`;
  }

  /** Format a server timestamp (ISO-8601) into a short, readable form. */
  function formatTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  }

  /** Escape a string before putting it inside a `<pre>` or text node. */
  function escapeText(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  // ---- Rendering --------------------------------------------------------

  function showError(message, guidance) {
    dom.errorBanner.hidden = false;
    dom.errorMessage.textContent = guidance
      ? `${message} — ${guidance}`
      : message;
  }

  function hideError() {
    dom.errorBanner.hidden = true;
    dom.errorMessage.textContent = "";
  }

  function setStatus(text) {
    if (text) {
      dom.searchStatus.textContent = text;
      dom.searchStatus.hidden = false;
    } else {
      dom.searchStatus.hidden = true;
      dom.searchStatus.textContent = "";
    }
  }

  function renderResults(items) {
    dom.resultsGrid.replaceChildren();
    dom.resultsCount.textContent = items.length ? `(${items.length})` : "";
    dom.resultsSection.hidden = items.length === 0 && !state.lastResults.length;
    if (items.length === 0) return;
    const tpl = document.getElementById("tpl-result-card");
    for (const item of items) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const img = node.querySelector(".card-thumb");
      img.src = item.image || "";
      img.alt = item.title || "";
      node.querySelector(".card-title").textContent = item.title || "(untitled)";
      node.querySelector(".price").textContent = formatPrice(item.price);
      node.querySelector(".sold").textContent = formatSold(item.sold);
      const commission = formatCommission(item.commission);
      const commissionEl = node.querySelector(".commission");
      if (commission) {
        commissionEl.textContent = `${commission} commission`;
      } else {
        commissionEl.remove();
      }
      const saveBtn = node.querySelector(".btn-save");
      const saveStatus = node.querySelector(".save-status");
      const sourceId = item.source_id;
      if (state.saving.has(sourceId)) {
        saveBtn.disabled = true;
        saveStatus.textContent = "Saving…";
      }
      saveBtn.addEventListener("click", () => handleSave(item, saveBtn, saveStatus));
      dom.resultsGrid.appendChild(node);
    }
  }

  function renderSavedItems() {
    dom.savedList.replaceChildren();
    dom.savedCount.textContent = state.savedItems.length
      ? `(${state.savedItems.length})`
      : "";
    dom.savedEmpty.hidden = state.savedItems.length > 0;
    if (state.savedItems.length === 0) return;
    const tpl = document.getElementById("tpl-saved-item");
    for (const item of state.savedItems) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const id = item.id;
      node.dataset.savedId = String(id);
      const img = node.querySelector(".saved-thumb");
      img.src = item.item.image || "";
      img.alt = item.item.title || "";
      node.querySelector(".saved-title").textContent = item.item.title || "(untitled)";
      node.querySelector(".price").textContent = formatPrice(item.item.price);
      node.querySelector(".sold").textContent = formatSold(item.item.sold);
      const commission = formatCommission(item.item.commission);
      const commissionEl = node.querySelector(".commission");
      if (commission) {
        commissionEl.textContent = `${commission} commission`;
      } else {
        commissionEl.remove();
      }
      const captionBtn = node.querySelector(".btn-caption");
      const clipBtn = node.querySelector(".btn-clip");
      const removeBtn = node.querySelector(".btn-remove");
      const statusEl = node.querySelector(".saved-status");
      if (state.inflight.has(id)) {
        for (const b of [captionBtn, clipBtn, removeBtn]) b.disabled = true;
        statusEl.textContent = "Working…";
      }
      captionBtn.addEventListener("click", () => handleGenerate(id, "caption", node, statusEl));
      clipBtn.addEventListener("click", () => handleGenerate(id, "clip_prompt", node, statusEl));
      removeBtn.addEventListener("click", () => handleRemove(id, node, statusEl));
      dom.savedList.appendChild(node);
      // Load outputs asynchronously; render in place when ready.
      loadAndRenderOutputs(id, node);
    }
  }

  async function loadAndRenderOutputs(savedId, containerNode) {
    try {
      const [captionResult, clipResult] = await Promise.all([
        api.listOutputs(savedId, "caption").catch(() => ({ outputs: [] })),
        api.listOutputs(savedId, "clip_prompt").catch(() => ({ outputs: [] })),
      ]);
      const captionList = containerNode.querySelector(".caption-list");
      const clipList = containerNode.querySelector(".clip-list");
      renderOutputList(captionList, captionResult.outputs || []);
      renderOutputList(clipList, clipResult.outputs || []);
    } catch (err) {
      // Non-fatal: outputs just won't show.
      // eslint-disable-next-line no-console
      console.warn("Failed to load outputs for saved id", savedId, err);
    }
  }

  function renderOutputList(listEl, outputs) {
    listEl.replaceChildren();
    if (outputs.length === 0) {
      const empty = document.createElement("li");
      empty.className = "muted small";
      empty.textContent = "No generations yet.";
      listEl.appendChild(empty);
      return;
    }
    const tpl = document.getElementById("tpl-output-row");
    for (const out of outputs) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const body = node.querySelector(".output-body");
      body.textContent = out.body;
      node.querySelector(".output-time").textContent = formatTime(out.generated_at);
      const copyBtn = node.querySelector(".btn-copy");
      copyBtn.addEventListener("click", () => handleCopy(out.body, copyBtn));
      listEl.appendChild(node);
    }
  }

  // ---- Handlers ---------------------------------------------------------

  async function handleSearch(event) {
    event.preventDefault();
    hideError();
    const query = dom.searchInput.value.trim();
    if (!query) {
      setStatus("Type a keyword to search.");
      return;
    }
    setStatus("Searching…");
    dom.searchButton.disabled = true;
    try {
      const result = await api.search(query, DEFAULT_LIMIT);
      state.lastResults = (result && result.items) || [];
      renderResults(state.lastResults);
      setStatus(state.lastResults.length === 0 ? "No results." : "");
    } catch (err) {
      setStatus("");
      showError(err.message, err.guidance);
    } finally {
      dom.searchButton.disabled = false;
    }
  }

  async function handleSave(item, saveBtn, saveStatus) {
    if (!item || !item.source_id) return;
    if (state.saving.has(item.source_id)) return; // idempotent UI guard
    state.saving.add(item.source_id);
    saveBtn.disabled = true;
    saveStatus.textContent = "Saving…";
    hideError();
    try {
      // Use the search-time `query` if we can recover it; otherwise use the title.
      const query = dom.searchInput.value.trim() || item.title || "";
      await api.saveItem(item, query);
      saveStatus.textContent = "Saved ✓";
      // Refresh the saved list so the new item shows up.
      await refreshSaved();
    } catch (err) {
      saveStatus.textContent = "";
      saveBtn.disabled = false;
      showError(err.message, err.guidance);
    } finally {
      state.saving.delete(item.source_id);
    }
  }

  async function handleRemove(id, containerNode, statusEl) {
    if (state.inflight.has(id)) return;
    if (!window.confirm("Remove this saved item and its generation history?")) return;
    state.inflight.add(id);
    setSavedItemDisabled(containerNode, true);
    statusEl.textContent = "Removing…";
    hideError();
    try {
      await api.removeSaved(id);
      // Optimistic remove; then re-sync.
      state.savedItems = state.savedItems.filter((s) => s.id !== id);
      renderSavedItems();
    } catch (err) {
      setSavedItemDisabled(containerNode, false);
      statusEl.textContent = "";
      showError(err.message, err.guidance);
    } finally {
      state.inflight.delete(id);
    }
  }

  async function handleGenerate(id, kind, containerNode, statusEl) {
    if (state.inflight.has(id)) return;
    state.inflight.add(id);
    setSavedItemButtonsDisabled(containerNode, true);
    statusEl.textContent = kind === "caption" ? "Generating caption…" : "Generating clip prompt…";
    hideError();
    try {
      const result =
        kind === "caption" ? await api.generateCaption(id) : await api.generateClipPrompt(id);
      // Prepend the new output to the right list, newest first.
      const listSel = kind === "caption" ? ".caption-list" : ".clip-list";
      const listEl = containerNode.querySelector(listSel);
      prependOutputRow(listEl, {
        body: result.body,
        generated_at: result.generated_at,
      });
      statusEl.textContent = "Done ✓";
    } catch (err) {
      statusEl.textContent = "";
      showError(err.message, err.guidance);
    } finally {
      setSavedItemButtonsDisabled(containerNode, false);
      state.inflight.delete(id);
    }
  }

  function prependOutputRow(listEl, out) {
    // If the list currently shows the "No generations yet" placeholder, clear it.
    const placeholder = listEl.querySelector(".muted.small");
    if (placeholder) listEl.replaceChildren();
    const tpl = document.getElementById("tpl-output-row");
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".output-body").textContent = out.body;
    node.querySelector(".output-time").textContent = formatTime(out.generated_at);
    const copyBtn = node.querySelector(".btn-copy");
    copyBtn.addEventListener("click", () => handleCopy(out.body, copyBtn));
    listEl.prepend(node);
  }

  async function handleCopy(text, copyBtn) {
    hideError();
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback for non-secure contexts.
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      const original = copyBtn.textContent;
      copyBtn.textContent = "Copied ✓";
      setTimeout(() => {
        copyBtn.textContent = original;
      }, 1500);
    } catch (err) {
      showError(`Copy failed: ${err.message || err}`);
    }
  }

  function setSavedItemDisabled(containerNode, disabled) {
    setSavedItemButtonsDisabled(containerNode, disabled);
  }

  function setSavedItemButtonsDisabled(containerNode, disabled) {
    for (const sel of [".btn-caption", ".btn-clip", ".btn-remove"]) {
      const btn = containerNode.querySelector(sel);
      if (btn) btn.disabled = disabled;
    }
  }

  async function refreshSaved() {
    try {
      const result = await api.listSaved();
      state.savedItems = (result && result.items) || [];
      renderSavedItems();
    } catch (err) {
      // Non-fatal; the saved section just won't update.
      // eslint-disable-next-line no-console
      console.warn("Failed to refresh saved items", err);
    }
  }

  // ---- Init -------------------------------------------------------------

  function cacheDom() {
    dom.searchForm = document.getElementById("search-form");
    dom.searchInput = document.getElementById("search-input");
    dom.searchButton = document.getElementById("search-button");
    dom.searchStatus = document.getElementById("search-status");
    dom.errorBanner = document.getElementById("error-banner");
    dom.errorMessage = document.getElementById("error-message");
    dom.errorDismiss = document.getElementById("error-dismiss");
    dom.resultsSection = document.getElementById("results-section");
    dom.resultsGrid = document.getElementById("results-grid");
    dom.resultsCount = document.getElementById("results-count");
    dom.savedSection = document.getElementById("saved-section");
    dom.savedList = document.getElementById("saved-list");
    dom.savedCount = document.getElementById("saved-count");
    dom.savedEmpty = document.getElementById("saved-empty");
  }

  function bindEvents() {
    dom.searchForm.addEventListener("submit", handleSearch);
    dom.errorDismiss.addEventListener("click", hideError);
  }

  function init() {
    cacheDom();
    bindEvents();
    refreshSaved();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Expose a tiny smoke-test hook for `tests/test_ui.py` so a future
  // Playwright/in-browser test (or a console-driven smoke) can verify
  // the module loaded without `eval`-ing the source.
  window.ShopeeTH = { version: "0.1.0", api, formatPrice, formatSold, state };
})();
