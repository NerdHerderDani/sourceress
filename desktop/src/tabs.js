// Simple tabs (2-5) for Sourceress

export function createTabs({ openerInvoke, containerTabbar, containerViews }) {
  let tabs = [];
  let activeId = null;

  // Allow embedded pages to ask the shell to open URLs in new tabs.
  window.addEventListener('message', (e) => {
    try {
      if (e?.data?.type === 'SOURCERESS_OPEN_TAB' && typeof e.data.url === 'string') {
        const url = e.data.url;
        if (url.includes('/candidates/')) {
          addTab({ title: 'Profile', url, pinned: false });
        } else {
          addTab({ title: 'Tab', url, pinned: false });
        }
      }
    } catch (_) {}
  });

  function safeHref(iframe){
    if(!iframe) return '';
    try { return String(iframe.contentWindow?.location?.href || iframe.src || ''); } catch (_) { return String(iframe.src || ''); }
  }

  function mkId() { return Math.random().toString(36).slice(2); }

  function addTab({ title, url, pinned = false }) {
    const id = mkId();
    const iframe = document.createElement('iframe');
    iframe.className = 'tabview';
    iframe.referrerPolicy = 'no-referrer';

    // Per-tab navigation stack (because embedded history can be flaky in some webviews)
    const nav = { stack: [], idx: -1, suppress: false };

    function record(){
      if(nav.suppress) return;
      const href = safeHref(iframe);
      if(!href) return;
      const cur = nav.stack[nav.idx];
      if(cur === href) return;
      // drop forward history
      nav.stack = nav.stack.slice(0, nav.idx + 1);
      nav.stack.push(href);
      nav.idx = nav.stack.length - 1;
    }

    function wireSameOriginClicks(){
      try {
        const doc = iframe.contentWindow?.document;
        if (!doc) return;
        if (doc.__sourceressWired) return;
        doc.__sourceressWired = true;

        doc.addEventListener('click', (e) => {
          const a = e.target?.closest ? e.target.closest('a') : null;
          if (!a) return;
          const href = a.getAttribute('href') || '';
          if (!href) return;

          // Only intercept internal profile links; keep everything else default.
          // Accept absolute and relative.
          const abs = (() => {
            try { return new URL(href, iframe.contentWindow.location.href).toString(); } catch (_) { return ''; }
          })();

          // Open candidate profiles in a new tab so the results tab stays put.
          if (abs && (abs.includes('/candidates/') || abs.match(/\/candidates\//))) {
            e.preventDefault();
            e.stopPropagation();
            addTab({ title: 'Profile', url: abs, pinned: false });
          }
        }, true);
      } catch (_) {
        // Cross-origin; ignore.
      }
    }

    iframe.addEventListener('load', () => {
      try { record(); } catch (_) {}
      try { wireSameOriginClicks(); } catch (_) {}

      // Safety net: if navigation lands on a /candidates/ page inside a non-profile tab,
      // open it in a new tab and bounce this tab back to where it was.
      try {
        const href = safeHref(iframe);
        const isProfile = (title || '').toLowerCase().includes('profile');
        if (!isProfile && href && href.includes('/candidates/')) {
          // Open profile in a new tab
          addTab({ title: 'Profile', url: href, pinned: false });

          // Bounce back in this tab if possible
          if (nav.idx > 0) {
            nav.idx -= 1;
            const backHref = nav.stack[nav.idx];
            nav.suppress = true;
            iframe.src = backHref;
            setTimeout(() => { nav.suppress = false; }, 50);
          }
        }
      } catch (_) {}
    });

    iframe.src = url;

    containerViews.appendChild(iframe);
    tabs.push({ id, title, url, pinned, iframe, nav });
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

  function getActiveTab() {
    return tabs.find(x => x.id === activeId) || null;
  }

  function navBack() {
    const t = getActiveTab();
    if(!t) return;
    // Prefer our tracked stack
    if (t.nav && t.nav.idx > 0) {
      t.nav.idx -= 1;
      const href = t.nav.stack[t.nav.idx];
      t.nav.suppress = true;
      t.iframe.src = href;
      // allow load handler to run without creating a new entry
      setTimeout(() => { t.nav.suppress = false; }, 50);
      return;
    }
    try { t.iframe?.contentWindow?.history?.back(); } catch (_) {}
  }
  function navForward() {
    const t = getActiveTab();
    if(!t) return;
    if (t.nav && t.nav.idx >= 0 && t.nav.idx < t.nav.stack.length - 1) {
      t.nav.idx += 1;
      const href = t.nav.stack[t.nav.idx];
      t.nav.suppress = true;
      t.iframe.src = href;
      setTimeout(() => { t.nav.suppress = false; }, 50);
      return;
    }
    try { t.iframe?.contentWindow?.history?.forward(); } catch (_) {}
  }
  function navReload() {
    const t = getActiveTab();
    if(!t) return;
    try { t.iframe?.contentWindow?.location?.reload(); } catch (_) {
      // fallback
      t.iframe.src = safeHref(t.iframe);
    }
  }

  function getActiveUrl() {
    const t = getActiveTab();
    if (!t) return '';
    // Prefer our tracked URL
    if (t.nav && t.nav.idx >= 0 && t.nav.stack[t.nav.idx]) {
      return String(t.nav.stack[t.nav.idx] || '');
    }
    return safeHref(t.iframe);
  }

  function requestActiveUrl(timeoutMs = 1200) {
    const t = getActiveTab();
    const f = t?.iframe;
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
