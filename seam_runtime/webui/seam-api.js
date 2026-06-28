/**
 * SEAM API Service Layer
 * ---------------------
 * Injected before the main dashboard script.
 * Provides window.SeamAPI for all REST API interactions.
 * Falls back gracefully when the API is unreachable.
 */
(function () {
  'use strict';

  const BASE_KEY = 'seam-webui-api-url';
  const TOKEN_KEY = 'seam-webui-api-token';
  const DEFAULT_BASE_URL = '';  // empty = same origin (proxied by Vite)

  function getBaseUrl() {
    try {
      return (localStorage.getItem(BASE_KEY) || DEFAULT_BASE_URL).replace(/\/$/, '');
    } catch {
      return DEFAULT_BASE_URL;
    }
  }

  function getToken() {
    try {
      localStorage.removeItem(TOKEN_KEY);
      return sessionStorage.getItem(TOKEN_KEY) || '';
    } catch {
      return '';
    }
  }

  async function _fetch(path, init) {
    init = init || {};
    const baseUrl = getBaseUrl();
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (init.headers) Object.assign(headers, init.headers);

    const url = baseUrl + path;
    try {
      const res = await fetch(url, Object.assign({}, init, { headers: headers }));
      if (res.status === 401) {
        const err = new Error('Unauthorized');
        err.code = 'UNAUTHORIZED';
        throw err;
      }
      if (res.status === 429) {
        const err = new Error('Rate limited');
        err.code = 'RATE_LIMITED';
        throw err;
      }
      if (!res.ok) {
        const body = await res.text().catch(function () { return ''; });
        throw new Error('API error ' + res.status + ': ' + body);
      }
      return await res.json();
    } catch (err) {
      if (err instanceof TypeError) {
        // Network error — API unreachable
        const networkErr = new Error('Disconnected');
        networkErr.code = 'DISCONNECTED';
        throw networkErr;
      }
      throw err;
    }
  }

  // ── Connection state tracking ──────────────────────────────────────────
  var _connected = false;
  var _lastCheck = 0;
  var _listeners = [];

  function onConnectionChange(fn) {
    _listeners.push(fn);
    return function () {
      _listeners = _listeners.filter(function (f) { return f !== fn; });
    };
  }

  function _notifyListeners(connected) {
    if (connected !== _connected) {
      _connected = connected;
      _listeners.forEach(function (fn) {
        try { fn(connected); } catch (_) { /* ignore */ }
      });
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────

  window.SeamAPI = {
    // Connection state
    get connected() { return _connected; },
    onConnectionChange: onConnectionChange,

    // Health check
    health: async function () {
      try {
        const data = await _fetch('/health');
        _notifyListeners(true);
        _lastCheck = Date.now();
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Runtime stats (total_records, store_path, etc.)
    stats: async function () {
      try {
        const data = await _fetch('/stats');
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Fetch file tree
    tree: async function (path) {
      try {
        const url = path ? '/tree?path=' + encodeURIComponent(path) : '/tree';
        const data = await _fetch(url);
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Run benchmarks
    benchmark: async function (suite, persist, holdout) {
      try {
        const payload = { suite: suite || 'all', persist: !!persist, holdout: !!holdout };
        const data = await _fetch('/benchmark', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Get system metrics
    sysMetrics: async function () {
      try {
        const data = await _fetch('/sys-metrics');
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Search memory records
    search: async function (query, budget, scope, lens) {
      budget = budget || 5;
      lens = lens || 'general';
      var params = 'query=' + encodeURIComponent(query) + '&budget=' + budget + '&lens=' + lens;
      if (scope) params += '&scope=' + encodeURIComponent(scope);
      try {
        const data = await _fetch('/search?' + params);
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Fetch memory graph trace
    trace: async function (rootId) {
      try {
        const data = await _fetch('/trace?root_id=' + encodeURIComponent(rootId));
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Compile text into MIRL records
    compile: async function (text, persist, sourceRef, ns, scope) {
      var payload = { text: text };
      if (persist) payload.persist = true;
      if (sourceRef) payload.source_ref = sourceRef;
      if (ns) payload.ns = ns;
      if (scope) payload.scope = scope;
      try {
        const data = await _fetch('/compile', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Get context pack for a query
    context: async function (query, budget, scope, lens, packBudget, mode) {
      var payload = { query: query };
      if (budget) payload.budget = budget;
      if (scope) payload.scope = scope;
      if (lens) payload.lens = lens;
      if (packBudget) payload.pack_budget = packBudget;
      if (mode) payload.mode = mode;
      try {
        const data = await _fetch('/context', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // SEAM-augmented chat: retrieve memory + call the selected model via the server.
    // opts: { model, provider, baseUrl, apiKey, history, useMemory, persistChat, budget }
    chat: async function (message, opts) {
      opts = opts || {};
      var payload = {
        message: message,
        model: opts.model || '',
        provider: opts.provider || '',
        base_url: opts.baseUrl || '',
        env_key: opts.envKey || '',
        api_key: opts.apiKey || '',
        history: opts.history || [],
        use_memory: opts.useMemory !== false,
        persist_chat: opts.persistChat !== false
      };
      if (opts.budget) payload.budget = opts.budget;
      try {
        const data = await _fetch('/chat', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Persist compiled records
    persist: async function (records) {
      try {
        const data = await _fetch('/persist', {
          method: 'POST',
          body: JSON.stringify({ records: records })
        });
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Lossless compress text
    compress: async function (text, opts) {
      opts = opts || {};
      var payload = { text: text };
      if (opts.codec) payload.codec = opts.codec;
      if (opts.transform) payload.transform = opts.transform;
      if (opts.tokenizer) payload.tokenizer = opts.tokenizer;
      if (opts.min_token_savings !== undefined) payload.min_token_savings = opts.min_token_savings;
      if (opts.include_machine_text) payload.include_machine_text = true;
      try {
        const data = await _fetch('/lossless-compress', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Utility: configure API URL and token
    configure: function (baseUrl, token) {
      try {
        if (baseUrl !== undefined) localStorage.setItem(BASE_KEY, baseUrl || '');
        localStorage.removeItem(TOKEN_KEY);
        if (token !== undefined) sessionStorage.setItem(TOKEN_KEY, token || '');
      } catch (_) { /* storage unavailable */ }
    },

    // Utility: get current config
    getConfig: function () {
      return { baseUrl: getBaseUrl() || window.location.origin, token: getToken() ? '••••••••' : '' };
    }
  };

  // Initial connectivity check (non-blocking)
  window.SeamAPI.health().catch(function () { /* silent initial check */ });

  console.log('[SEAM API] Service layer initialized');
})();
