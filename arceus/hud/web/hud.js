/*
 * ARCEUS HUD — DOM binding.
 *
 * Talks to Python only through the QWebChannel object `arceus`.  All text
 * from the backend (including model replies) is inserted with textContent,
 * never innerHTML, so model output cannot inject markup.
 */
(function () {
  'use strict';

  var M = window.HudModel;
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var BAR_COUNT = 72, BAR_INNER = 150, BAR_MIN = 3, BAR_MAX = 34, FRAME_MS = 33;
  var RESET_CONFIRM_MS = 5000, ACTIVITY_DOM_LIMIT = 60;

  var state = M.initialState();
  var bridge = null;
  var bars = [];
  var barLevels = [];
  var resetTimer = null;
  var reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function $(id) { return document.getElementById(id); }
  function setText(id, text) { var el = $(id); if (el.textContent !== text) { el.textContent = text; } }
  function setTone(id, tone) { $(id).setAttribute('data-tone', tone); }
  function now() { return (window.performance && performance.now) ? performance.now() : Date.now(); }

  // ── Events from Python ───────────────────────────────────────
  function apply(event) {
    var next = M.reduce(state, event, now());
    if (next === state) { return; }   // stale or unknown event: the model ignored it, so do not render it
    state = next;
    switch (event.type) {
      case 'snapshot': renderAll(); break;
      case 'bridge': renderAll(); break;
      case 'state': renderCore(); renderDeck(); renderResponse(); break;
      case 'message': appendMessage(event); renderResponse(); break;
      case 'activity': appendActivity(event); break;
      case 'backend': renderSystems(); renderDeck(); break;
      case 'devices': renderSystems(); renderDeck(); break;
      case 'voice': renderSystems(); break;
      case 'metrics': renderMetrics(); break;
      case 'reset': renderTranscript(); renderResponse(); break;
      default: break;
    }
  }

  function onEventJson(text) {
    var event;
    try { event = JSON.parse(text); } catch (err) { console.error('ARCEUS: unreadable event', err); return; }
    apply(event);
  }

  // ── Rendering ────────────────────────────────────────────────
  function renderAll() {
    renderLink(); renderCore(); renderSystems(); renderMetrics();
    renderTranscript(); renderActivity(); renderResponse(); renderDeck(); renderFullscreenButton();
    setText('version', state.version ? 'v' + state.version : '');
  }

  function renderLink() {
    var map = { connected: ['LINK ONLINE', 'ok'], connecting: ['LINK CONNECTING', 'dim'], unavailable: ['LINK DOWN', 'warn'] };
    var entry = map[state.bridge] || map.connecting;
    setText('link-status', entry[0]); setTone('link-status', entry[1]);
  }

  function renderCore() {
    var view = M.coreView(state);
    $('core').setAttribute('data-state', view.state);
    setText('core-state', view.state === 'PROCESSING' ? 'PROCESSING' : view.state);
    setText('core-id', M.coreIdentifier(state.backend));
    var show = !!view.detail;
    $('core-detail').hidden = !show;
    setText('core-detail', show ? view.detail : '');
    if (reduceMotion) { drawBars(0, true); }
  }

  function renderSystems() {
    var b = state.backend, d = state.devices, v = state.voice;
    setText('sys-backend', b.connection === 'N/A' ? 'LOCAL ECHO' : b.connection);
    setTone('sys-backend', M.connectionTone(b.connection));
    setText('sys-model', b.model || M.NA);
    setText('sys-model-installed', M.fmtInstalled(b.model_installed));
    setTone('sys-model-installed', b.model_installed === true ? 'ok' : b.model_installed === false ? 'warn' : 'dim');
    setText('sys-memory', M.fmtResidency(b.residency));
    setText('sys-mic', d.mic === 'UNKNOWN' ? 'CHECKING' : d.mic);
    setTone('sys-mic', d.mic === 'AVAILABLE' ? 'ok' : d.mic === 'NOT DETECTED' ? 'warn' : 'dim');
    setText('sys-capture', M.fmtDbfs(d.last_capture));
    setTone('sys-capture', d.last_capture && d.last_capture.peak_dbfs <= -60 ? 'warn' : 'active');
    setText('sys-stt', v.stt_engine || M.NA);
    setTone('sys-stt', v.stt_online === true ? 'warn' : 'active');
    setText('sys-tts', v.tts_engine || M.NA);
  }

  function renderMetrics() {
    var m = state.metrics;
    setText('sys-cpu', M.fmtPercent(m.cpu_percent));
    setText('sys-ram', M.fmtRam(m.ram_used_gb, m.ram_total_gb));
    setText('sys-runtime', M.fmtUptime(m.uptime_s));
    setBar('sys-cpu-bar', m.cpu_percent);
    setBar('sys-ram-bar', m.ram_percent);
  }

  function setBar(id, pct) {
    var el = $(id);
    var value = typeof pct === 'number' ? Math.max(0, Math.min(100, pct)) : 0;
    el.style.width = value + '%';
    el.setAttribute('data-tone', value >= 90 ? 'warn' : 'ok');
  }

  function makeMessage(m) {
    var wrap = document.createElement('article');
    wrap.className = 'msg msg--' + (m.role === 'assistant' ? 'assistant' : 'user');
    var meta = document.createElement('div');
    meta.className = 'msg__meta';
    var who = document.createElement('span');
    who.className = 'who';
    who.textContent = m.role === 'assistant' ? 'ARCEUS' : 'YOU';
    var time = document.createElement('time');
    time.textContent = M.fmtClock(m.ts);
    meta.appendChild(who); meta.appendChild(time);
    if (m.source === 'voice') {
      var src = document.createElement('span');
      src.textContent = 'VOICE';
      meta.appendChild(src);
    }
    var body = document.createElement('p');
    body.className = 'msg__text';
    body.textContent = m.text;
    wrap.appendChild(meta); wrap.appendChild(body);
    return wrap;
  }

  function renderTranscript() {
    var box = $('transcript');
    var children = box.children ? Array.prototype.slice.call(box.children) : [];
    children.forEach(function (c) { if (c.id !== 'transcript-empty') { box.removeChild(c); } });
    state.messages.forEach(function (m) { box.appendChild(makeMessage(m)); });
    $('transcript-empty').hidden = state.messages.length > 0;
    box.scrollTop = box.scrollHeight;
  }

  function appendMessage(m) {
    var box = $('transcript');
    var nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 60;
    $('transcript-empty').hidden = true;
    box.appendChild(makeMessage(m));
    if (nearBottom || m.role === 'user') { box.scrollTop = box.scrollHeight; }
  }

  function makeActivity(a) {
    var li = document.createElement('li');
    li.setAttribute('data-level', a.level || 'info');
    var time = document.createElement('time');
    time.textContent = M.fmtClock(a.ts);
    var text = document.createElement('span');
    text.textContent = a.text;
    li.appendChild(time); li.appendChild(text);
    return li;
  }

  function renderActivity() {
    var list = $('activity');
    var items = list.children ? Array.prototype.slice.call(list.children) : [];
    items.forEach(function (c) { if (c.id !== 'activity-empty') { list.removeChild(c); } });
    state.activity.slice(-ACTIVITY_DOM_LIMIT).forEach(function (a) { list.insertBefore(makeActivity(a), list.firstChild); });
    $('activity-empty').hidden = state.activity.length > 0;
  }

  function appendActivity(a) {
    var list = $('activity');
    $('activity-empty').hidden = true;
    list.insertBefore(makeActivity(a), list.firstChild);
    while (list.children.length > ACTIVITY_DOM_LIMIT + 1) { list.removeChild(list.children[list.children.length - 1]); }
  }

  function renderResponse() {
    var generating = state.busy && state.generationStartedAt !== null;
    setText('resp-status', M.fmtResponse(state.lastResponseMs, generating));
  }

  function renderDeck() {
    var input = $('cmd-input');
    var online = state.bridge === 'connected';
    input.disabled = !online;
    $('btn-send').disabled = !M.canSend(state, input.value);
    $('btn-mic').disabled = !M.canUseVoice(state);
    $('btn-mic').classList.toggle('is-active', state.appState === 'LISTENING');
    $('btn-reset').disabled = !(online && !state.busy);
    var voice = M.voiceIndicator(state);
    setText('mic-state', voice.text); setTone('mic-state', voice.tone);
    var label = state.backend.label || M.NA;
    var conn = state.backend.connection;
    setText('deck-conn', online ? label + ' ' + (conn === 'N/A' ? 'ONLINE' : conn) : 'NO LINK');
    setTone('deck-conn', online ? M.connectionTone(conn === 'N/A' ? 'CONNECTED' : conn) : 'warn');
  }

  function renderFullscreenButton() {
    setText('btn-fullscreen', state.fullscreen ? 'EXIT FULLSCREEN' : 'FULLSCREEN');
  }

  // ── Decorative visualiser (not audio data) ───────────────────
  function buildBars() {
    var group = $('bars');
    for (var i = 0; i < BAR_COUNT; i++) {
      var line = document.createElementNS(SVG_NS, 'line');
      line.setAttribute('x1', '300'); line.setAttribute('y1', String(300 - BAR_INNER));
      line.setAttribute('x2', '300'); line.setAttribute('y2', String(300 - BAR_INNER - BAR_MIN));
      line.setAttribute('transform', 'rotate(' + (i * 360 / BAR_COUNT) + ' 300 300)');
      group.appendChild(line);
      bars.push(line); barLevels.push(0);
    }
  }

  function drawBars(t, instant) {
    var view = M.coreView(state).state;
    for (var i = 0; i < bars.length; i++) {
      var target = M.barLevel(view, i, bars.length, t);
      barLevels[i] = instant ? target : barLevels[i] + (target - barLevels[i]) * 0.35;
      bars[i].setAttribute('y2', (300 - BAR_INNER - (BAR_MIN + barLevels[i] * (BAR_MAX - BAR_MIN))).toFixed(1));
    }
  }

  var lastFrame = 0;
  function loop(ts) {
    if (!reduceMotion && !document.hidden && ts - lastFrame >= FRAME_MS) {
      lastFrame = ts;
      drawBars(ts / 1000, false);
    }
    window.requestAnimationFrame(loop);
  }

  // ── Controls ─────────────────────────────────────────────────
  function send() {
    var input = $('cmd-input');
    if (!bridge || !M.canSend(state, input.value)) { return; }
    bridge.submitText(input.value);
    input.value = '';
    renderDeck();
  }

  function cancelReset() {
    if (resetTimer) { clearTimeout(resetTimer); resetTimer = null; }
    $('btn-reset').textContent = 'RESET';
    $('btn-reset').classList.remove('btn--danger');
    $('btn-reset-cancel').hidden = true;
  }

  function onReset() {
    if (!bridge || state.busy) { return; }
    if (resetTimer) { cancelReset(); bridge.resetConversation(); return; }   // second press = confirm
    $('btn-reset').textContent = 'CONFIRM RESET';
    $('btn-reset').classList.add('btn--danger');
    $('btn-reset-cancel').hidden = false;
    resetTimer = setTimeout(cancelReset, RESET_CONFIRM_MS);
  }

  function updateFullscreenFlag() {
    var full = window.innerWidth >= screen.width && window.innerHeight >= screen.height;
    if (full !== state.fullscreen) { state.fullscreen = full; renderFullscreenButton(); }
  }

  function bind() {
    $('btn-send').addEventListener('click', send);
    $('cmd-input').addEventListener('input', renderDeck);
    $('cmd-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); send(); }
    });
    $('btn-mic').addEventListener('click', function () { if (bridge && M.canUseVoice(state)) { bridge.startVoice(); } });
    $('btn-reset').addEventListener('click', onReset);
    $('btn-reset-cancel').addEventListener('click', cancelReset);
    $('btn-fullscreen').addEventListener('click', function () { if (bridge) { bridge.toggleFullscreen(); } });
    $('btn-quit').addEventListener('click', function () { if (bridge) { bridge.quitApp(); } });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (resetTimer) { cancelReset(); } else if (bridge) { bridge.exitFullscreen(); }
      } else if (e.key === 'F11') { e.preventDefault(); if (bridge) { bridge.toggleFullscreen(); } }
    });
    window.addEventListener('resize', updateFullscreenFlag);
  }

  // ── Start-up ─────────────────────────────────────────────────
  function connect() {
    if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined' || !qt.webChannelTransport) {
      apply({ type: 'bridge', status: 'unavailable' });
      return;
    }
    /* eslint-disable-next-line no-undef */
    new QWebChannel(qt.webChannelTransport, function (channel) {
      bridge = channel.objects.arceus;
      bridge.eventJson.connect(onEventJson);
      apply({ type: 'bridge', status: 'connected' });
      bridge.requestSnapshot();
    });
  }

  buildBars();
  bind();
  renderAll();
  window.requestAnimationFrame(loop);
  connect();
})();
