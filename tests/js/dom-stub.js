'use strict';
// Minimal DOM + fake Qt bridge, just enough to run hud.js without a browser.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.join(__dirname, '..', '..', 'arceus', 'hud', 'web');

class El {
  constructor(tag, id) {
    this.tagName = tag; this.id = id || ''; this.children = []; this.parent = null;
    this.attrs = {}; this.style = {}; this._text = ''; this.value = ''; this.disabled = false;
    this.hidden = false; this.listeners = {}; this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 0;
    this._classes = new Set();
    const self = this;
    this.classList = {
      add(n) { self._classes.add(n); }, remove(n) { self._classes.delete(n); },
      contains(n) { return self._classes.has(n); },
      toggle(n, on) { (on === undefined ? !self._classes.has(n) : on) ? self._classes.add(n) : self._classes.delete(n); },
    };
  }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return Array.from(this._classes).join(' '); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { c.parent = this; this.children.push(c); this.scrollHeight += 20; return c; }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
  insertBefore(n, ref) {
    if (!ref) return this.appendChild(n);
    n.parent = this; this.children.splice(this.children.indexOf(ref), 0, n); return n;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, ev) { (this.listeners[t] || []).forEach((f) => f(Object.assign({ preventDefault() {} }, ev))); }
}

// Build a page: every id in index.html becomes an element; `bridgeUp` toggles Qt availability.
function boot({ bridgeUp = true } = {}) {
  const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  const els = {};
  for (const m of html.matchAll(/<[a-z0-9]+\s[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const el = new El('x', m[1]);
    if (/\shidden[\s>]/.test(m[0])) el.hidden = true;
    if (/\sdisabled[\s>]/.test(m[0])) el.disabled = true;
    els[m[1]] = el;
  }
  const docListeners = {};
  const document = {
    hidden: false,
    getElementById: (id) => { if (!els[id]) throw new Error('missing element #' + id); return els[id]; },
    createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t),
    addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
  };
  const timers = [];
  const calls = [];
  const bridge = {
    eventJson: { connect(fn) { bridge.emit = (ev) => fn(JSON.stringify(ev)); bridge.emitRaw = fn; } },
  };
  for (const name of ['requestSnapshot', 'submitText', 'startVoice', 'resetConversation', 'toggleFullscreen', 'exitFullscreen', 'quitApp']) {
    bridge[name] = (...args) => calls.push([name, ...args]);
  }
  const frames = [];
  const winListeners = {};
  const window = {
    HudModel: require(path.join(WEB, 'hud-model.js')),
    matchMedia: () => ({ matches: false }), performance: { now: () => 0 },
    requestAnimationFrame: (f) => frames.push(f),
    innerWidth: 1280, innerHeight: 800,
    addEventListener: (t, f) => { (winListeners[t] = winListeners[t] || []).push(f); },
  };
  const sandbox = {
    window, document, screen: { width: 1920, height: 1080 }, console, performance: window.performance,
    setTimeout: (f) => { timers.push(f); return timers.length; }, clearTimeout: (id) => { timers[id - 1] = null; },
  };
  if (bridgeUp) {
    sandbox.qt = { webChannelTransport: {} };
    sandbox.QWebChannel = function (transport, cb) { cb({ objects: { arceus: bridge } }); };
  }
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(WEB, 'hud.js'), 'utf8'), sandbox);
  return {
    els, bridge, calls, timers, window,
    key: (key) => (docListeners.keydown || []).forEach((f) => f({ key, preventDefault() {} })),
    frame: (ts) => { const f = frames.shift(); if (f) f(ts); },
  };
}

module.exports = { boot, El };
