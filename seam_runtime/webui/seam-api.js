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

    // Query the canonical, self-building knowledge graph.
    knowledgeGraph: async function (opts) {
      opts = opts || {};
      var params = new URLSearchParams();
      if (opts.query) params.set('query', opts.query);
      if (opts.rootId) params.set('root_id', opts.rootId);
      if (opts.namespace) params.set('namespace', opts.namespace);
      if (opts.scope) params.set('scope', opts.scope);
      if (opts.agentId) params.set('agent_id', opts.agentId);
      if (opts.kinds && opts.kinds.length) params.set('kinds', opts.kinds.join(','));
      if (opts.at) params.set('at', opts.at);
      if (opts.includeHistory) params.set('include_history', 'true');
      params.set('limit', String(opts.limit || 300));
      params.set('hops', String(opts.hops == null ? 2 : opts.hops));
      try {
        const data = await _fetch('/knowledge-graph?' + params.toString());
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    knowledgeNode: async function (nodeId, includeHistory, at) {
      var params = new URLSearchParams();
      params.set('node_id', nodeId);
      params.set('include_history', includeHistory === false ? 'false' : 'true');
      if (at) params.set('at', at);
      try {
        const data = await _fetch('/knowledge-node?' + params.toString());
        _notifyListeners(true);
        return data;
      } catch (err) {
        if (err.code === 'DISCONNECTED') _notifyListeners(false);
        throw err;
      }
    },

    // Discover optional live-workspace and activation capabilities. Older
    // runtimes may not expose this endpoint; callers should treat 404/405 as
    // an unavailable capability rather than a graph failure.
    workspaceCapabilities: async function () {
      return await _fetch('/workspace/capabilities');
    },

    // Read append-only workspace events for passive LIVE observation or
    // replay. `after` is an opaque monotonic cursor returned by the server.
    workspaceEvents: async function (opts) {
      opts = opts || {};
      var params = new URLSearchParams();
      if (opts.runId) params.set('run_id', opts.runId);
      if (opts.after !== undefined && opts.after !== null && opts.after !== '') params.set('after', String(opts.after));
      params.set('limit', String(opts.limit || 200));
      return await _fetch('/workspace/events?' + params.toString());
    },

    workspaceRun: async function (runId) {
      return await _fetch('/workspace/runs/' + encodeURIComponent(runId));
    },

    // POST-backed SSE stream used by chat surfaces that opt into structured
    // workspace telemetry. This exposes summaries, tool/retrieval events, and
    // activation-derived concepts when supported; it does not claim access to
    // hidden chain-of-thought. Returns { abort, done } immediately.
    streamChat: function (payload, handlers) {
      handlers = handlers || {};
      var controller = new AbortController();
      var baseUrl = getBaseUrl();
      var token = getToken();
      var headers = { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' };
      if (token) headers.Authorization = 'Bearer ' + token;

      var done = (async function () {
        var response;
        try {
          response = await fetch(baseUrl + '/chat/stream', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(payload || {}),
            signal: controller.signal
          });
          if (!response.ok) {
            var body = await response.text().catch(function () { return ''; });
            var error = new Error('API error ' + response.status + ': ' + body);
            error.status = response.status;
            throw error;
          }
          if (!response.body || !response.body.getReader) throw new Error('Streaming responses are not supported by this browser');
          _notifyListeners(true);
          if (handlers.onOpen) handlers.onOpen(response);

          var reader = response.body.getReader();
          var decoder = new TextDecoder();
          var buffer = '';
          var terminalCount = 0;
          var dispatch = function (block) {
            if (!block.trim()) return;
            var eventName = 'message';
            var eventId = '';
            var dataLines = [];
            block.split(/\r?\n/).forEach(function (line) {
              if (line.startsWith('event:')) eventName = line.slice(6).trim();
              else if (line.startsWith('id:')) eventId = line.slice(3).trim();
              else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
            });
            var raw = dataLines.join('\n');
            var data = raw;
            if (raw) {
              try { data = JSON.parse(raw); } catch (_) { /* retain text frame */ }
            }
            if (data && typeof data === 'object') {
              if (!data.event_type && eventName !== 'message') data.event_type = eventName;
              if (!data.event_id && eventId) data.event_id = eventId;
            }
            var resolvedType = String(data && typeof data === 'object' && data.event_type || eventName).toLowerCase();
            if (resolvedType === 'completion' || resolvedType === 'failure') {
              terminalCount += 1;
              if (terminalCount > 1) {
                var duplicateTerminal = new Error('Invalid SSE stream: duplicate terminal event');
                duplicateTerminal.code = 'SSE_PROTOCOL';
                throw duplicateTerminal;
              }
            }
            if (handlers.onEvent) handlers.onEvent(data, { event: eventName, id: eventId });
          };

          while (true) {
            var next = await reader.read();
            if (next.done) break;
            buffer += decoder.decode(next.value, { stream: true });
            var boundary;
            while ((boundary = buffer.search(/\r?\n\r?\n/)) !== -1) {
              var block = buffer.slice(0, boundary);
              var match = buffer.slice(boundary).match(/^\r?\n\r?\n/);
              buffer = buffer.slice(boundary + (match ? match[0].length : 2));
              dispatch(block);
            }
          }
          buffer += decoder.decode();
          dispatch(buffer);
          if (terminalCount !== 1) {
            var missingTerminal = new Error('Invalid SSE stream: expected exactly one completion or failure terminal event');
            missingTerminal.code = 'SSE_PROTOCOL';
            throw missingTerminal;
          }
          if (handlers.onDone) handlers.onDone();
        } catch (error) {
          if (error && error.name === 'AbortError') return;
          if (error && error.code === 'DISCONNECTED') _notifyListeners(false);
          if (handlers.onError) handlers.onError(error);
          throw error;
        }
      })();

      // Prevent an unhandled rejection when a UI only uses callbacks.
      done.catch(function () {});
      return { abort: function () { controller.abort(); }, done: done };
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
