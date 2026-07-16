/* popup/popup.js — shows capture status + server health, toggles capture. */
(function () {
  "use strict";

  const SERVER_URL = "http://127.0.0.1:8000";

  const els = {
    serverStatus: document.getElementById("server-status"),
    capturedCount: document.getElementById("captured-count"),
    lastSurface: document.getElementById("last-surface"),
    lastSavedAt: document.getElementById("last-saved-at"),
    errorRow: document.getElementById("error-row"),
    lastError: document.getElementById("last-error"),
    toggle: document.getElementById("capture-toggle"),
    appLink: document.getElementById("app-link"),
  };

  els.appLink.href = SERVER_URL + "/";

  // --- load stored status ----------------------------------------------
  async function refreshStatus() {
    const s = await chrome.storage.local.get({
      capturedCount: 0,
      lastSurface: null,
      lastSavedAt: null,
      lastError: null,
      captureEnabled: true,
    });
    els.capturedCount.textContent = String(s.capturedCount);
    els.lastSurface.textContent = s.lastSurface || "—";
    els.lastSavedAt.textContent = s.lastSavedAt ? _fmtTime(s.lastSavedAt) : "—";
    els.toggle.checked = s.captureEnabled;
    if (s.lastError) {
      els.errorRow.classList.remove("hidden");
      els.lastError.textContent = s.lastError;
    } else {
      els.errorRow.classList.add("hidden");
    }
  }

  // --- server health (direct fetch — popup has host_permission for 127.0.0.1) ---
  async function pingServer() {
    els.serverStatus.textContent = "checking…";
    els.serverStatus.className = "value checking";
    try {
      const resp = await fetch(SERVER_URL + "/health", { method: "GET" });
      if (resp.ok) {
        els.serverStatus.textContent = "online";
        els.serverStatus.className = "value ok";
        return;
      }
    } catch {
      // server not running / refused
    }
    els.serverStatus.textContent = "offline (run `make run`)";
    els.serverStatus.className = "value bad";
  }

  // --- toggle -----------------------------------------------------------
  els.toggle.addEventListener("change", async () => {
    await chrome.storage.local.set({ captureEnabled: els.toggle.checked });
  });

  function _fmtTime(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return iso;
    }
  }

  refreshStatus();
  pingServer();
})();
