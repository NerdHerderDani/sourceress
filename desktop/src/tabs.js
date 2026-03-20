// Simple tabs (2-5) for Sourceress

export function createTabs({ openerInvoke, containerTabbar, containerViews }) {
  let tabs = [];
  let activeId = null;

  function mkId() { return Math.random().toString(36).slice(2); }

  function addTab({ title, url, pinned = false }) {
    const id = mkId();
    const iframe = document.createElement('iframe');
    iframe.className = 'tabview';
    iframe.referrerPolicy = 'no-referrer';
    iframe.src = url;

    // Minimal: rely on web app's own __TAURI__ open_url logic.
    // (No cross-origin click interception here.)

    containerViews.appendChild(iframe);
    tabs.push({ id, title, url, pinned, iframe });
    setActive(id);
    render();
    return id;
  }

  function closeTab(id) {
    const t = tabs.find(x => x.id === id);
    if (!t || t.pinned) return;
    t.iframe.remove();
    tabs = tabs.filter(x => x.id !== id);
    if (activeId === id) {
      activeId = tabs.length ? tabs[0].id : null;
    }
    render();
    updateVisibility();
  }

  function setActive(id) {
    activeId = id;
    updateVisibility();
    render();
  }

  function updateVisibility() {
    tabs.forEach(t => {
      t.iframe.style.display = (t.id === activeId) ? 'block' : 'none';
    });
  }

  function getActiveIframe() {
    const t = tabs.find(x => x.id === activeId);
    return t?.iframe;
  }

  function navBack() {
    const f = getActiveIframe();
    try { f?.contentWindow?.history?.back(); } catch (_) {}
  }
  function navForward() {
    const f = getActiveIframe();
    try { f?.contentWindow?.history?.forward(); } catch (_) {}
  }
  function navReload() {
    const f = getActiveIframe();
    try { f?.contentWindow?.location?.reload(); } catch (_) {}
  }

  function getActiveUrl() {
    const f = getActiveIframe();
    if (!f) return '';
    try {
      // Same-origin pages can be read.
      return String(f.contentWindow?.location?.href || f.src || '');
    } catch (_) {
      // Cross-origin fallback
      return String(f.src || '');
    }
  }

  function requestActiveUrl(timeoutMs = 1200) {
    const f = getActiveIframe();
    if (!f) return Promise.resolve('');

    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => {
        if (done) return;
        done = true;
        window.removeEventListener('message', onMsg);
        resolve(v || '');
      };

      const onMsg = (e) => {
        try {
          if (e?.data?.type === 'SOURCERESS_LOCATION' && typeof e.data.href === 'string') {
            finish(e.data.href);
          }
        } catch (_) {}
      };

      window.addEventListener('message', onMsg);

      try {
        f.contentWindow?.postMessage({ type: 'SOURCERESS_GET_LOCATION' }, '*');
      } catch (_) {
        // ignore
      }

      setTimeout(() => finish(''), timeoutMs);
    });
  }

  function render() {
    containerTabbar.innerHTML = '';

    tabs.forEach(t => {
      const btn = document.createElement('button');
      btn.className = 'tab' + (t.id === activeId ? ' active' : '');
      btn.type = 'button';
      btn.textContent = t.title;
      btn.addEventListener('click', () => setActive(t.id));
      // Middle-click to close (non-pinned)
      btn.addEventListener('auxclick', (e) => {
        if (e.button === 1) {
          e.preventDefault();
          closeTab(t.id);
        }
      });

      if (!t.pinned) {
        const x = document.createElement('button');
        x.className = 'x';
        x.type = 'button';
        x.textContent = '✕';
        x.addEventListener('click', (e) => { e.stopPropagation(); closeTab(t.id); });
        btn.appendChild(x);
      }

      containerTabbar.appendChild(btn);
    });

    const plus = document.createElement('button');
    plus.className = 'tab';
    plus.type = 'button';
    plus.textContent = '+ New Search';
    plus.addEventListener('click', () => addTab({ title: 'Search', url: currentBaseUrl() }));
    containerTabbar.appendChild(plus);
  }

  let _baseUrl = null;
  function setBaseUrl(url) {
    _baseUrl = url;
  }

  function currentBaseUrl() {
    return _baseUrl || 'about:blank';
  }
  function baseUrl() { return _baseUrl; }

  function initPinned(baseUrl) {
    // normalize trailing slash
    const b = (baseUrl || '').endsWith('/') ? baseUrl : (baseUrl + '/');
    setBaseUrl(b);
    // Projects pinned tab
    addTab({ title: 'Projects', url: b + 'projects-ui', pinned: true });
    addTab({ title: 'GitHub', url: b, pinned: false });
    addTab({ title: 'Stack', url: b + 'stack', pinned: false });
  }

  return {
    initPinned,
    addTab,
    closeTab,
    setActive,
    navBack,
    navForward,
    navReload,
    getActiveUrl,
    requestActiveUrl,
    baseUrl,
  };
}
