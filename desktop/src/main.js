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
    els.panelSettings.style.display = "block";
    setStatus("needs token", "Open Settings and paste your GitHub token.");
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
    setStatus("error", String(e));
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
  els.panelStatus = $("panelStatus");
  els.panelTabs = $("panelTabs");
  els.panelApp = $("panelApp");
  els.tabbar = $("tabbar");
  els.tabViews = $("tabViews");
  els.topbar = $("topbar");

  $("btnStart").addEventListener("click", start);
  $("btnStop").addEventListener("click", stop);

  // Nav controls removed (keep topbar clean; navigation happens inside the app UI)

  $("btnSettings").addEventListener("click", async () => {
    els.panelSettings.style.display = els.panelSettings.style.display === "none" ? "block" : "none";
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

  // basic refresh
  await refresh();
});
