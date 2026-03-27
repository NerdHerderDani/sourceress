const { invoke } = window.__TAURI__.core;
import { createTabs } from './tabs.js';

const els = {};

function $(id) { return document.getElementById(id); }

function setStatus(text, hint = "") {
  els.statusText.textContent = text;
  els.statusHint.textContent = hint;
}

// External link handling is handled by the web app itself when running inside Tauri.

async function refresh() {
  try {
    const st = await invoke("backend_status");
    if (st.running && st.url) {
      // Hide dev-y status panel when running; tabs are the UI.
      if (els.panelStatus) els.panelStatus.style.display = "none";
      setStatus("", "");
      els.panelTabs.style.display = "block";
      els.panelApp.style.display = "block";

      if (!els.tabsInited) {
        els.tabs = createTabs({
          openerInvoke: (url) => invoke('open_url', { url }),
          containerTabbar: els.tabbar,
          containerViews: els.tabViews,
        });
        els.tabs.initPinned(st.url);
        els.tabsInited = true;
      }

      // show topbar always (tabs live below it)
      els.topbar.style.display = "flex";
    } else {
      if (els.panelStatus) els.panelStatus.style.display = "block";
      setStatus("stopped", "");
      els.panelTabs.style.display = "none";
      els.panelApp.style.display = "none";
      els.tabsInited = false;
      els.tabbar.innerHTML = '';
      els.tabViews.innerHTML = '';
    }
  } catch (e) {
    setStatus("error", String(e));
  }
}

async function ensureTokenExists() {
  try {
    await invoke("token_get");
    return true;
  } catch (_) {
    return false;
  }
}

async function start() {
  const hasToken = await ensureTokenExists();
  if (!hasToken) {
    // Make it impossible to miss.
    els.panelSettings.style.display = "block";
    if (els.panelDiag) els.panelDiag.style.display = "none";
    setStatus("needs GitHub token", "Click Settings → paste token → Save. Then click Start.");
    return;
  }

  setStatus("starting…", "");
  try {
    const url = await invoke("backend_start");
    if (els.panelStatus) els.panelStatus.style.display = "none";
    els.panelTabs.style.display = "block";
    els.panelApp.style.display = "block";
    if (!els.tabsInited) {
      els.tabs = createTabs({
        openerInvoke: (u) => invoke('open_url', { url: u }),
        containerTabbar: els.tabbar,
        containerViews: els.tabViews,
      });
      els.tabs.initPinned(url);
      els.tabsInited = true;
    }
    setStatus("running", url);
  } catch (e) {
    // Make failures self-diagnosing.
    setStatus("backend failed", "Open Diagnostics → Open log folder → attach backend.log");

    try {
      const d = await invoke('diagnostics');
      $("diagText").textContent = JSON.stringify(d, null, 2);
    } catch (_) {
      // ignore
    }

    if (els.panelDiag) {
      els.panelDiag.style.display = "block";
      if (els.panelSettings) els.panelSettings.style.display = "none";
    }
  }
}

async function stop() {
  try {
    await invoke("backend_stop");
  } finally {
    await refresh();
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  els.statusText = $("statusText");
  els.statusHint = $("statusHint");
  els.panelSettings = $("panelSettings");
  els.panelDiag = $("panelDiag");
  els.panelStatus = $("panelStatus");
  els.panelTabs = $("panelTabs");
  els.panelApp = $("panelApp");
  els.tabbar = $("tabbar");
  els.tabViews = $("tabViews");
  els.topbar = $("topbar");

  $("btnStart").addEventListener("click", start);
  $("btnStop").addEventListener("click", stop);

  // Nav controls removed (keep topbar clean; navigation happens inside the app UI)

  function hidePanels() {
    if (els.panelSettings) els.panelSettings.style.display = "none";
    if (els.panelDiag) els.panelDiag.style.display = "none";
  }

  $("btnSettings").addEventListener("click", async () => {
    const on = els.panelSettings.style.display === "none";
    hidePanels();
    els.panelSettings.style.display = on ? "block" : "none";
  });

  $("btnDiag").addEventListener("click", async () => {
    const on = els.panelDiag.style.display === "none";
    hidePanels();
    els.panelDiag.style.display = on ? "block" : "none";
    if (on) {
      try {
        const d = await invoke('diagnostics');
        const txt = JSON.stringify(d, null, 2);
        $("diagText").textContent = txt;
      } catch (e) {
        $("diagText").textContent = String(e);
      }
    }
  });

  $("btnCopyDiag").addEventListener("click", async () => {
    const txt = $("diagText").textContent || '';
    try {
      await navigator.clipboard.writeText(txt);
      setStatus("copied", "diagnostics copied to clipboard");
    } catch (e) {
      setStatus("copy failed", String(e));
    }
  });

  $("btnOpenLogs").addEventListener("click", async () => {
    try {
      await invoke('open_log_folder');
    } catch (e) {
      setStatus('error', String(e));
    }
  });

  $("btnSaveToken").addEventListener("click", async () => {
    const token = $("tokenInput").value.trim();
    if (!token) return;
    try {
      await invoke("token_set", { token });
      $("tokenInput").value = "";
      els.panelSettings.style.display = "none";
      setStatus("token saved", "Now click Start.");
    } catch (e) {
      setStatus("error", String(e));
    }
  });

  $("btnClearToken").addEventListener("click", async () => {
    try {
      await invoke("token_clear");
      setStatus("token cleared", "");
    } catch (e) {
      setStatus("error", String(e));
    }
  });

  // Optional Anthropic key to enable Fubuki (hidden unless enabled)
  const enable = $("enableFubuki");
  const wrap = $("fubukiKeyWrap");

  async function refreshFubukiToggle() {
    try {
      const k = await invoke("anthropic_key_get");
      if (k) {
        if (enable) enable.checked = true;
        if (wrap) wrap.style.display = "block";
      }
    } catch (_) {
      // no key
      if (enable) enable.checked = false;
      if (wrap) wrap.style.display = "none";
    }
  }

  enable?.addEventListener("change", async () => {
    if (!enable.checked) {
      try { await invoke("anthropic_key_clear"); } catch(_) {}
      if (wrap) wrap.style.display = "none";
      setStatus("fubuki disabled", "");
    } else {
      if (wrap) wrap.style.display = "block";
      setStatus("fubuki enabled", "Paste your Anthropic key.");
    }
  });

  $("btnSaveAnthropic")?.addEventListener("click", async () => {
    const key = $("anthropicInput").value.trim();
    if (!key) return;
    try {
      await invoke("anthropic_key_set", { key });
      $("anthropicInput").value = "";
      if (enable) enable.checked = true;
      if (wrap) wrap.style.display = "block";
      setStatus("anthropic key saved", "Fubuki is enabled.");
    } catch (e) {
      setStatus("error", String(e));
    }
  });

  $("btnClearAnthropic")?.addEventListener("click", async () => {
    try {
      await invoke("anthropic_key_clear");
      if (enable) enable.checked = false;
      if (wrap) wrap.style.display = "none";
      setStatus("anthropic key cleared", "Fubuki disabled.");
    } catch (e) {
      setStatus("error", String(e));
    }
  });

  await refreshFubukiToggle();

  // basic refresh
  await refresh();
});
