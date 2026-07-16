/* background.js — MV3 service worker.
 *
 * Receives parsed Items from content scripts (storefront + affiliate) and
 * POSTs each to the local app's existing idempotent save endpoint. Tracks a
 * capture counter + an on/off toggle in chrome.storage so the popup can show
 * status. Never calls Shopee itself.
 */

const SERVER_URL = "http://127.0.0.1:8000";
const SAVE_ENDPOINT = SERVER_URL + "/api/saved";
const HEALTH_ENDPOINT = SERVER_URL + "/health";

// Defaults written on first install.
const DEFAULTS = {
  captureEnabled: true,
  capturedCount: 0,
  lastError: null,
  lastSurface: null,
  lastSavedAt: null,
};

// --- lifecycle ----------------------------------------------------------

chrome.runtime.onInstalled.addListener(async () => {
  const cur = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const patch = {};
  for (const [k, v] of Object.entries(DEFAULTS)) {
    if (cur[k] === undefined) patch[k] = v;
  }
  if (Object.keys(patch).length) await chrome.storage.local.set(patch);
});

// --- message router -----------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.kind === "SAVE_ITEM") {
    _handleSaveItem(msg).then(
      (r) => sendResponse(r),
      (err) => sendResponse({ ok: false, error: String(err && err.message || err) }),
    );
    return true; // async
  }
  if (msg && msg.kind === "PING_SERVER") {
    _pingServer().then(
      (ok) => sendResponse({ ok }),
      () => sendResponse({ ok: false }),
    );
    return true;
  }
  return false;
});

// --- save handling (single item, from a card Save button) ----------------

async function _handleSaveItem(msg) {
  const { item, query } = msg;
  if (!item || !item.source_id) return { ok: false, error: "missing item.source_id" };

  try {
    const resp = await fetch(SAVE_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item, query }),
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      return { ok: false, error: `server ${resp.status}: ${detail.slice(0, 120)}` };
    }
    // Bump the popup counter.
    const cur = await chrome.storage.local.get({ capturedCount: 0 });
    await chrome.storage.local.set({
      capturedCount: cur.capturedCount + 1,
      lastSurface: "affiliate",
      lastSavedAt: new Date().toISOString(),
      lastError: null,
    });
    return { ok: true };
  } catch (e) {
    const errMsg = String(e && e.message || e);
    await chrome.storage.local.set({ lastError: errMsg });
    return { ok: false, error: errMsg };
  }
}

async function _pingServer() {
  try {
    const resp = await fetch(HEALTH_ENDPOINT, { method: "GET" });
    return resp.ok;
  } catch {
    return false;
  }
}
