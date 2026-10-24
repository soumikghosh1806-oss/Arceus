/*
 * ARCEUS HUD — state model.
 *
 * Pure functions only (no DOM, no bridge) so the same file runs in the
 * browser and under `node --test`.  Everything shown on screen comes from
 * events sent by the Python backend; unknown values are null and render as
 * "N/A".  Nothing here fabricates data.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) { module.exports = factory(); }
  else { root.HudModel = factory(); }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var NA = 'N/A';
  var MAX_MESSAGES = 500;
  var MAX_ACTIVITY = 200;
  // Must match the detail text the backend sends when generation starts.
  var GENERATING = 'GENERATING RESPONSE';
  var STATES = ['STANDBY', 'LISTENING', 'PROCESSING', 'SPEAKING', 'ERROR'];
  var BRIDGE_DOWN_MESSAGE = 'Interface bridge unavailable. Start ARCEUS with: python main.py --hud';

  function initialState() {
    return {
      seq: 0, ready: false, version: '', bridge: 'connecting',
      appState: 'STANDBY', detail: '', busy: false,
      messages: [], activity: [],
      backend: { kind: null, label: null, model: null, host: null, connection: 'UNKNOWN',
                 model_installed: null, residency: { state: NA, gpu_percent: null }, error: '' },
      devices: { mic: 'UNKNOWN', mic_detail: '', last_capture: null },
      voice: { loaded: false, stt_engine: null, stt_online: null, tts_engine: null },
      metrics: { cpu_percent: null, ram_used_gb: null, ram_total_gb: null, ram_percent: null, uptime_s: 0 },
      fullscreen: false,
      generationStartedAt: null, lastResponseMs: null
    };
  }

  function clone(o) { return Object.assign({}, o); }
  function capped(list, item, max) {
    var next = list.concat([item]);
    return next.length > max ? next.slice(next.length - max) : next;
  }

  // reduce(state, event, nowMs) -> new state.  Stale events (seq <= snapshot seq) are ignored.
  function reduce(state, event, nowMs) {
    var s = clone(state);
    if (!event || typeof event.type !== 'string') { return state; }

    if (event.type === 'bridge') { s.bridge = event.status; return s; }

    if (event.type === 'snapshot') {
      var fresh = initialState();
      fresh.seq = event.seq; fresh.ready = true; fresh.bridge = 'connected';
      fresh.version = event.version || '';
      fresh.fullscreen = !!(event.app && event.app.fullscreen);
      fresh.appState = event.state; fresh.detail = event.detail || ''; fresh.busy = !!event.busy;
      fresh.messages = (event.messages || []).slice(-MAX_MESSAGES);
      fresh.activity = (event.activity || []).slice(-MAX_ACTIVITY);
      fresh.backend = Object.assign(fresh.backend, event.backend || {});
      fresh.devices = Object.assign(fresh.devices, event.devices || {});
      fresh.voice = Object.assign(fresh.voice, event.voice || {});
      fresh.metrics = Object.assign(fresh.metrics, event.metrics || {});
      fresh.lastResponseMs = state.lastResponseMs;
      return fresh;
    }

    if (typeof event.seq === 'number' && event.seq <= state.seq) { return state; }
    if (typeof event.seq === 'number') { s.seq = event.seq; }

    switch (event.type) {
      case 'state':
        s.appState = event.state; s.detail = event.detail || ''; s.busy = !!event.busy;
        if (event.state === 'PROCESSING' && s.detail === GENERATING) {
          if (s.generationStartedAt === null) { s.generationStartedAt = nowMs; }
        } else if (event.state === 'ERROR' || event.state === 'STANDBY') {
          s.generationStartedAt = null;
        }
        return s;
      case 'message':
        s.messages = capped(state.messages, event, MAX_MESSAGES);
        if (event.role === 'assistant' && s.generationStartedAt !== null) {
          s.lastResponseMs = Math.max(0, nowMs - s.generationStartedAt);
          s.generationStartedAt = null;
        }
        return s;
      case 'activity': s.activity = capped(state.activity, event, MAX_ACTIVITY); return s;
      case 'backend': s.backend = Object.assign(clone(state.backend), event); return s;
      case 'devices': s.devices = Object.assign(clone(state.devices), event); return s;
      case 'voice': s.voice = Object.assign(clone(state.voice), event); return s;
      case 'metrics': s.metrics = Object.assign(clone(state.metrics), event); return s;
      case 'reset': s.messages = []; s.lastResponseMs = null; s.generationStartedAt = null; return s;
      default: return state;
    }
  }

  // What the core should display; a dead bridge is shown as an honest ERROR.
  function coreView(state) {
    if (state.bridge === 'unavailable') {
      return { state: 'ERROR', detail: BRIDGE_DOWN_MESSAGE };
    }
    if (state.bridge === 'connecting' && !state.ready) {
      return { state: 'STANDBY', detail: 'CONNECTING TO ARCEUS' };
    }
    return { state: STATES.indexOf(state.appState) >= 0 ? state.appState : 'ERROR', detail: state.detail || '' };
  }

  function coreIdentifier(backend) {
    var label = backend && backend.label ? backend.label : NA;
    return 'ARCEUS CORE / ' + label;
  }

  function canSend(state, text) {
    return state.bridge === 'connected' && !state.busy && typeof text === 'string' && text.trim().length > 0;
  }
  function canUseVoice(state) { return state.bridge === 'connected' && !state.busy; }

  function voiceIndicator(state) {
    if (state.bridge !== 'connected') { return { text: 'VOICE N/A', tone: 'dim' }; }
    if (state.appState === 'LISTENING') { return { text: 'LISTENING', tone: 'active' }; }
    if (state.appState === 'SPEAKING') { return { text: 'SPEAKING', tone: 'active' }; }
    if (state.busy && state.detail === 'TRANSCRIBING') { return { text: 'TRANSCRIBING', tone: 'active' }; }
    if (state.busy) { return { text: 'VOICE BUSY', tone: 'dim' }; }
    if (state.devices.mic === 'NOT DETECTED') { return { text: 'MIC NOT DETECTED', tone: 'warn' }; }
    if (state.devices.mic === NA) { return { text: 'VOICE N/A', tone: 'dim' }; }
    if (state.devices.mic === 'AVAILABLE') { return { text: 'VOICE READY', tone: 'ok' }; }
    return { text: 'CHECKING MIC', tone: 'dim' };
  }

  // ── Formatters: null / unknown always becomes N/A ──────────────
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function fmtPercent(v) { return typeof v === 'number' ? Math.round(v) + '%' : NA; }
  function fmtRam(used, total) {
    return (typeof used === 'number' && typeof total === 'number') ? used.toFixed(1) + ' / ' + total.toFixed(1) + ' GB' : NA;
  }
  function fmtUptime(seconds) {
    if (typeof seconds !== 'number' || seconds < 0) { return NA; }
    var s = Math.floor(seconds);
    return pad2(Math.floor(s / 3600)) + ':' + pad2(Math.floor((s % 3600) / 60)) + ':' + pad2(s % 60);
  }
  function fmtClock(tsSeconds) {
    if (typeof tsSeconds !== 'number') { return '--:--:--'; }
    var d = new Date(tsSeconds * 1000);
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  function fmtDbfs(capture) {
    if (!capture || typeof capture.peak_dbfs !== 'number') { return 'NONE YET'; }
    return 'PEAK ' + capture.peak_dbfs.toFixed(1) + ' dBFS';
  }
  function fmtResidency(res) {
    if (!res) { return NA; }
    switch (res.state) {
      case 'GPU': return 'GPU 100%';
      case 'CPU': return 'CPU ONLY';
      case 'SPLIT': return 'SPLIT ' + Math.round(res.gpu_percent) + '% GPU';
      case 'IDLE': return 'NOT LOADED';
      default: return NA;
    }
  }
  function fmtInstalled(v) { return v === true ? 'INSTALLED' : v === false ? 'NOT INSTALLED' : NA; }
  function fmtResponse(ms, generating) {
    if (generating) { return 'GENERATING'; }
    if (typeof ms !== 'number') { return 'AWAITING INPUT'; }
    return 'LAST RESPONSE ' + (ms / 1000).toFixed(1) + ' S';
  }
  function connectionTone(connection) {
    return connection === 'CONNECTED' ? 'ok' : connection === 'DISCONNECTED' ? 'warn' : 'dim';
  }

  // Decorative visualiser level (0..1).  It is NOT audio data: the speech
  // engines expose no live level, so this is a restrained per-state animation.
  function barLevel(state, i, n, t) {
    var x = (i / n) * Math.PI * 2;
    var v;
    switch (state) {
      case 'LISTENING': v = 0.20 + 0.12 * Math.sin(t * 3.2 + x * 3) + 0.07 * Math.sin(t * 5.1 - x * 5); break;
      case 'PROCESSING': var d = (((i / n) - t * 0.7) % 1 + 1) % 1; v = 0.12 + 0.6 * Math.max(0, 1 - d * 5); break;
      case 'SPEAKING': v = 0.26 + 0.26 * Math.abs(Math.sin(t * 5.5 + x * 4)) * (0.6 + 0.4 * Math.sin(t * 2 + x)); break;
      case 'ERROR': v = 0.04; break;
      default: v = 0.09 + 0.05 * Math.sin(t * 0.9 + x * 2);
    }
    return Math.max(0, Math.min(1, v));
  }

  return {
    NA: NA, STATES: STATES, GENERATING: GENERATING, BRIDGE_DOWN_MESSAGE: BRIDGE_DOWN_MESSAGE,
    initialState: initialState, reduce: reduce, coreView: coreView, coreIdentifier: coreIdentifier,
    canSend: canSend, canUseVoice: canUseVoice, voiceIndicator: voiceIndicator,
    fmtPercent: fmtPercent, fmtRam: fmtRam, fmtUptime: fmtUptime, fmtClock: fmtClock, fmtDbfs: fmtDbfs,
    fmtResidency: fmtResidency, fmtInstalled: fmtInstalled, fmtResponse: fmtResponse,
    connectionTone: connectionTone, barLevel: barLevel
  };
});
