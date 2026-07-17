/* shopee-th SPA — vanilla JS, no framework, no build step.
 *
 * This view shows items captured by the Shopee TH Capture browser extension
 * (which saves them via POST /api/saved). The old server-side search box is
 * gone — capture happens in the extension now. Here you browse saved items,
 * generate Thai captions + English clip prompts, and copy them out.
 *
 * Architecture:
 *   - IIFE module: no globals leak; only `window.ShopeeTH` is exposed.
 *   - Layered: Constants → State → API → Format → Render → Handlers → Init.
 *   - Auto-refresh: re-fetches saved items on window focus so newly-captured
 *     items appear without a manual reload.
 *   - Errors surface as a dismissible banner with the server-supplied
 *     `detail.message` (and `guidance` when present). No silent failures.
 *
 * API contract (do not change without updating the FastAPI routes):
 *   GET  /api/saved                           -> { items: [SavedItemDTO] }
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

  const FETCH_TIMEOUT_MS = 15000;
  const POLL_INTERVAL_MS = 5000; // poll for newly-captured items while focused

  // ---- State ------------------------------------------------------------

  /**
   * In-memory state. The server is the source of truth; we mirror enough to
   * render without round-tripping on every action.
   */
  const state = {
    /** @type {Array<Object>} saved items, newest first. */
    savedItems: [],
    /** @type {Set<number>} saved-item ids with a generation or remove in flight. */
    inflight: new Set(),
    /** @type {number|null} poll interval id (set when window is focused). */
    pollTimer: null,
  };

  // ---- DOM refs (populated in `init`). -------------------------------

  const dom = {};

  // ---- API helpers ------------------------------------------------------

  /**
   * Wrap fetch with a timeout and a uniform error shape. Throws an `Error`
   * whose `.message` is the human-readable server message so callers can
   * route it to the error banner without inspecting the response.
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
      if (err.url) throw err; // already structured
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
    listSaved() {
      return request("/api/saved", { method: "GET" });
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

  /** Format sold count in compact form: `1.2K`, `12K`, `1,234`, `0`, or `—`
   *  when the count is genuinely unknown (null/undefined). */
  function formatSold(sold) {
    if (sold == null) return "—"; // unknown, not zero
    const n = Number(sold) || 0;
    if (n >= 1000) {
      if (n < 10000) return `${(n / 1000).toFixed(1)}K`;
      return `${Math.floor(n / 1000)}K`;
    }
    return `${n}`;
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

  // ---- Rendering --------------------------------------------------------

  function showError(message, guidance) {
    dom.errorBanner.hidden = false;
    dom.errorMessage.textContent = guidance ? `${message} — ${guidance}` : message;
  }

  function hideError() {
    dom.errorBanner.hidden = true;
    dom.errorMessage.textContent = "";
  }

  function renderSavedItems() {
    dom.savedList.replaceChildren();
    const n = state.savedItems.length;
    dom.savedCount.textContent = n === 1 ? "1 item" : `${n} items`;
    dom.hintSection.hidden = n > 0;
    dom.savedSection.hidden = n === 0;
    if (n === 0) return;

    const tpl = document.getElementById("tpl-saved-item");
    for (const item of state.savedItems) {
      const node = tpl.content.firstElementChild.cloneNode(true);
      const id = item.id;
      node.dataset.savedId = String(id);

      // Image + commission badge (the focal point).
      const img = node.querySelector(".item-thumb");
      img.src = item.item.image || "";
      img.alt = item.item.title || "";
      const commBadge = node.querySelector(".commission-badge");
      const commission = formatCommission(item.item.commission);
      commBadge.textContent = commission ? `${commission} commission` : "";

      // Title + stats.
      node.querySelector(".item-title").textContent = item.item.title || "(untitled)";
      node.querySelector(".price").textContent = formatPrice(item.item.price);
      node.querySelector(".sold").textContent = formatSold(item.item.sold);
      const commStat = node.querySelector(".commission");
      commStat.textContent = commission || "";

      // Buttons.
      const captionBtn = node.querySelector(".btn-caption");
      const clipBtn = node.querySelector(".btn-clip");
      const removeBtn = node.querySelector(".btn-remove");
      const statusEl = node.querySelector(".item-status");
      if (state.inflight.has(id)) {
        for (const b of [captionBtn, clipBtn, removeBtn]) b.disabled = true;
        statusEl.textContent = "Working…";
      }
      captionBtn.addEventListener("click", () => handleGenerate(id, "caption", node, statusEl));
      clipBtn.addEventListener("click", () => handleGenerate(id, "clip_prompt", node, statusEl));
      removeBtn.addEventListener("click", () => handleRemove(id, node, statusEl));

      dom.savedList.appendChild(node);
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
      // Reveal the outputs section only if there's at least one output.
      const hasAny =
        (captionResult.outputs && captionResult.outputs.length) ||
        (clipResult.outputs && clipResult.outputs.length);
      if (hasAny) {
        containerNode.querySelector(".item-outputs").hidden = false;
      }
    } catch (err) {
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
      node.querySelector(".output-body").textContent = out.body;
      node.querySelector(".output-time").textContent = formatTime(out.generated_at);
      node.querySelector(".btn-copy").addEventListener("click", (e) =>
        handleCopy(out.body, e.currentTarget),
      );
      listEl.appendChild(node);
    }
  }

  // ---- Handlers ---------------------------------------------------------

  async function handleRemove(id, containerNode, statusEl) {
    if (state.inflight.has(id)) return;
    if (!window.confirm("Remove this saved item and its generation history?")) return;
    state.inflight.add(id);
    setButtonsDisabled(containerNode, true);
    statusEl.textContent = "Removing…";
    hideError();
    try {
      await api.removeSaved(id);
      state.savedItems = state.savedItems.filter((s) => s.id !== id);
      renderSavedItems();
    } catch (err) {
      setButtonsDisabled(containerNode, false);
      statusEl.textContent = "";
      showError(err.message, err.guidance);
    } finally {
      state.inflight.delete(id);
    }
  }

  async function handleGenerate(id, kind, containerNode, statusEl) {
    if (state.inflight.has(id)) return;
    state.inflight.add(id);
    setButtonsDisabled(containerNode, true);
    statusEl.textContent = kind === "caption" ? "Generating caption…" : "Generating clip prompt…";
    hideError();
    try {
      const result =
        kind === "caption" ? await api.generateCaption(id) : await api.generateClipPrompt(id);
      const listSel = kind === "caption" ? ".caption-list" : ".clip-list";
      const listEl = containerNode.querySelector(listSel);
      prependOutputRow(listEl, { body: result.body, generated_at: result.generated_at });
      containerNode.querySelector(".item-outputs").hidden = false;
      statusEl.textContent = "Done ✓";
    } catch (err) {
      statusEl.textContent = "";
      showError(err.message, err.guidance);
    } finally {
      setButtonsDisabled(containerNode, false);
      state.inflight.delete(id);
    }
  }

  function prependOutputRow(listEl, out) {
    const placeholder = listEl.querySelector(".muted.small");
    if (placeholder) listEl.replaceChildren();
    const tpl = document.getElementById("tpl-output-row");
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".output-body").textContent = out.body;
    node.querySelector(".output-time").textContent = formatTime(out.generated_at);
    node.querySelector(".btn-copy").addEventListener("click", (e) =>
      handleCopy(out.body, e.currentTarget),
    );
    listEl.prepend(node);
  }

  async function handleCopy(text, copyBtn) {
    hideError();
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
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
      setTimeout(() => { copyBtn.textContent = original; }, 1500);
    } catch (err) {
      showError(`Copy failed: ${err.message || err}`);
    }
  }

  function setButtonsDisabled(containerNode, disabled) {
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
      // eslint-disable-next-line no-console
      console.warn("Failed to refresh saved items", err);
    }
  }

  // --- Auto-refresh: poll for newly-captured items while the tab is focused,
  //     so items saved from the extension appear without a manual reload. ---
  function startPolling() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(refreshSaved, POLL_INTERVAL_MS);
  }
  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  // ---- Init -------------------------------------------------------------

  function cacheDom() {
    dom.errorBanner = document.getElementById("error-banner");
    dom.errorMessage = document.getElementById("error-message");
    dom.errorDismiss = document.getElementById("error-dismiss");
    dom.hintSection = document.getElementById("hint-section");
    dom.savedSection = document.getElementById("saved-section");
    dom.savedList = document.getElementById("saved-list");
    dom.savedCount = document.getElementById("saved-count");
    dom.refreshBtn = document.getElementById("refresh-btn");
  }

  function bindEvents() {
    dom.errorDismiss.addEventListener("click", hideError);
    dom.refreshBtn.addEventListener("click", refreshSaved);
    // Poll while focused; stop when backgrounded to avoid wasted requests.
    window.addEventListener("focus", () => { refreshSaved(); startPolling(); });
    window.addEventListener("blur", stopPolling);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopPolling();
      else { refreshSaved(); startPolling(); }
    });
  }

  function init() {
    cacheDom();
    bindEvents();
    refreshSaved();
    startPolling();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Smoke-test hook for `tests/test_ui.py`.
  window.ShopeeTH = { version: "0.2.0", api, formatPrice, formatSold, state };
})();
