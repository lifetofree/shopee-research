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
  if (msg && msg.kind === "CAPTURED_ITEMS") {
    _handleCaptured(msg, sender).then(
      (n) => sendResponse({ saved: n }),
      (err) => sendResponse({ saved: 0, error: String(err && err.message || err) }),
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

// --- capture handling ---------------------------------------------------

async function _handleCaptured(msg, sender) {
  const { captureEnabled } = await chrome.storage.local.get({ captureEnabled: true });
  if (!captureEnabled) return 0;

  const { items = [], query, surface } = msg;
  if (items.length) {
    // Debug: log the first parsed item so we can see the actual shape the
    // content script produced (visible in the extension's service-worker console).
    console.log("[ShopeeTH] captured", items.length, "items from", surface, "— first:", JSON.stringify(items[0]).slice(0, 300));
  }
  let saved = 0;
  let lastError = null;

  for (const item of items) {
    try {
      const resp = await fetch(SAVE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item, query }),
      });
      if (resp.ok) {
        saved++;
      } else {
        lastError = `server ${resp.status}`;
      }
    } catch (e) {
      // Server not running / refused — record once, keep going.
      lastError = String(e && e.message || e);
    }
  }

  // Update counters + status for the popup.
  const cur = await chrome.storage.local.get({ capturedCount: 0 });
  await chrome.storage.local.set({
    capturedCount: cur.capturedCount + saved,
    lastSurface: surface || null,
    lastSavedAt: saved > 0 ? new Date().toISOString() : null,
    lastError,
  });

  return saved;
}

async function _pingServer() {
  try {
    const resp = await fetch(HEALTH_ENDPOINT, { method: "GET" });
    return resp.ok;
  } catch {
    return false;
  }
}
