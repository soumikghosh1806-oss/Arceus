'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./dom-stub');

const snapshot = (over) => Object.assign({
  type: 'snapshot', seq: 5, ts: 1, version: '0.1.0', app: { fullscreen: false }, state: 'STANDBY', detail: '', busy: false,
  messages: [], activity: [],
  backend: { kind: 'ollama', label: 'LOCAL AI', model: 'qwen2.5:3b', connection: 'CONNECTED', model_installed: true,
             residency: { state: 'GPU', gpu_percent: 100 } },
  devices: { mic: 'AVAILABLE', mic_detail: '', last_capture: null }, voice: { loaded: false },
  metrics: { cpu_percent: null, ram_used_gb: null, ram_total_gb: null, ram_percent: null, uptime_s: 0 },
}, over);

function online(over) {
  const page = boot();
  assert.deepStrictEqual(page.calls[0], ['requestSnapshot']);       // asks for state as soon as linked
  page.bridge.emit(snapshot(over));
  return page;
}

test('boots, connects and shows real snapshot data', () => {
  const p = online();
  assert.strictEqual(p.els['link-status'].textContent, 'LINK ONLINE');
  assert.strictEqual(p.els['core'].getAttribute('data-state'), 'STANDBY');
  assert.strictEqual(p.els['core-id'].textContent, 'ARCEUS CORE / LOCAL AI');
  assert.strictEqual(p.els['sys-model'].textContent, 'qwen2.5:3b');
  assert.strictEqual(p.els['sys-memory'].textContent, 'GPU 100%');
  assert.strictEqual(p.els['sys-cpu'].textContent, 'N/A');           // unmeasured -> N/A, not a made-up number
  assert.strictEqual(p.els['mic-state'].textContent, 'VOICE READY');
  assert.strictEqual(p.els['cmd-input'].disabled, false);
  assert.strictEqual(p.els['version'].textContent, 'v0.1.0');
});

test('visualiser bars are built and animate with state', () => {
  const p = online();
  const bars = p.els['bars'].children;
  assert.strictEqual(bars.length, 72);
  p.frame(100); p.frame(200);
  const y = bars.map((b) => Number(b.getAttribute('y2')));
  assert.ok(y.every((v) => v < 150 && v > 100));
});

test('typing and pressing Enter sends the text to the backend', () => {
  const p = online();
  p.els['cmd-input'].value = 'status report';
  p.els['cmd-input'].fire('input');
  assert.strictEqual(p.els['btn-send'].disabled, false);
  p.els['cmd-input'].fire('keydown', { key: 'Enter' });
  assert.deepStrictEqual(p.calls.at(-1), ['submitText', 'status report']);
  assert.strictEqual(p.els['cmd-input'].value, '');
});

test('send and mic are disabled while a request is running', () => {
  const p = online();
  p.bridge.emit({ type: 'state', seq: 6, state: 'PROCESSING', detail: 'GENERATING RESPONSE', busy: true });
  assert.strictEqual(p.els['core'].getAttribute('data-state'), 'PROCESSING');
  assert.strictEqual(p.els['core-detail'].textContent, 'GENERATING RESPONSE');
  assert.strictEqual(p.els['btn-mic'].disabled, true);
  assert.strictEqual(p.els['btn-reset'].disabled, true);
  p.els['cmd-input'].value = 'second';
  p.els['btn-send'].fire('click');
  assert.ok(!p.calls.some((c) => c[0] === 'submitText'));
  assert.strictEqual(p.els['resp-status'].textContent, 'GENERATING');
});

test('core states: listening, speaking and error', () => {
  const p = online();
  p.bridge.emit({ type: 'state', seq: 6, state: 'LISTENING', detail: 'RECORDING 5S', busy: true });
  assert.strictEqual(p.els['core'].getAttribute('data-state'), 'LISTENING');
  assert.strictEqual(p.els['core-state'].textContent, 'LISTENING');
  assert.ok(p.els['btn-mic'].classList.contains('is-active'));
  assert.strictEqual(p.els['mic-state'].textContent, 'LISTENING');
  p.bridge.emit({ type: 'state', seq: 7, state: 'SPEAKING', detail: 'SPEAKING RESPONSE', busy: true });
  assert.strictEqual(p.els['core-state'].textContent, 'SPEAKING');
  assert.ok(!p.els['btn-mic'].classList.contains('is-active'));
  p.bridge.emit({ type: 'state', seq: 8, state: 'ERROR', detail: 'Cannot reach Ollama at http://localhost:11434.', busy: false });
  assert.strictEqual(p.els['core'].getAttribute('data-state'), 'ERROR');
  assert.strictEqual(p.els['core-detail'].hidden, false);
  assert.match(p.els['core-detail'].textContent, /Cannot reach Ollama/);
  p.bridge.emit({ type: 'state', seq: 9, state: 'STANDBY', detail: '', busy: false });
  assert.strictEqual(p.els['core-detail'].hidden, true);
});

test('messages render as plain text and never as markup', () => {
  const p = online();
  const evil = '<img src=x onerror=alert(1)> **bold**';
  p.bridge.emit({ type: 'message', seq: 6, role: 'assistant', text: evil, source: 'text', ts: 1700000000 });
  const box = p.els['transcript'];
  const msg = box.children.at(-1);
  assert.strictEqual(msg.children[1].textContent, evil);              // body is a text node, not parsed HTML
  assert.strictEqual(msg.children[1].children.length, 0);
  assert.strictEqual(p.els['transcript-empty'].hidden, true);
});

test('transcript from a reconnect snapshot is not duplicated by late events', () => {
  const p = online({ seq: 20, messages: [{ role: 'user', text: 'hi', source: 'text', ts: 1 }] });
  p.bridge.emit({ type: 'message', seq: 19, role: 'user', text: 'hi', source: 'text', ts: 1 });
  const bubbles = p.els['transcript'].children.filter((c) => c.id !== 'transcript-empty');
  assert.strictEqual(bubbles.length, 1);
});

test('backend loss is shown and logged; recovery clears it', () => {
  const p = online();
  p.bridge.emit({ type: 'backend', seq: 6, connection: 'DISCONNECTED', residency: { state: 'N/A' } });
  assert.strictEqual(p.els['sys-backend'].textContent, 'DISCONNECTED');
  assert.strictEqual(p.els['sys-backend'].getAttribute('data-tone'), 'warn');
  assert.strictEqual(p.els['deck-conn'].textContent, 'LOCAL AI DISCONNECTED');
  p.bridge.emit({ type: 'activity', seq: 7, level: 'warn', text: 'Cannot reach Ollama', ts: 5 });
  const li = p.els['activity'].children[0];
  assert.strictEqual(li.getAttribute('data-level'), 'warn');
  assert.strictEqual(li.children[1].textContent, 'Cannot reach Ollama');
  p.bridge.emit({ type: 'backend', seq: 8, connection: 'CONNECTED' });
  assert.strictEqual(p.els['sys-backend'].textContent, 'CONNECTED');
});

test('metrics: real numbers are shown, nulls stay N/A', () => {
  const p = online();
  p.bridge.emit({ type: 'metrics', seq: 6, cpu_percent: 37.4, ram_used_gb: 8.2, ram_total_gb: 24, ram_percent: 34.2, uptime_s: 65 });
  assert.strictEqual(p.els['sys-cpu'].textContent, '37%');
  assert.strictEqual(p.els['sys-ram'].textContent, '8.2 / 24.0 GB');
  assert.strictEqual(p.els['sys-runtime'].textContent, '00:01:05');
  assert.strictEqual(p.els['sys-cpu-bar'].style.width, '37.4%');
  p.bridge.emit({ type: 'metrics', seq: 7, cpu_percent: null, ram_used_gb: null, ram_total_gb: null, ram_percent: null, uptime_s: 66 });
  assert.strictEqual(p.els['sys-cpu'].textContent, 'N/A');
  assert.strictEqual(p.els['sys-cpu-bar'].style.width, '0%');
});

test('reset needs confirmation and Escape cancels it', () => {
  const p = online();
  p.els['btn-reset'].fire('click');
  assert.strictEqual(p.els['btn-reset'].textContent, 'CONFIRM RESET');
  assert.strictEqual(p.els['btn-reset-cancel'].hidden, false);
  assert.ok(!p.calls.some((c) => c[0] === 'resetConversation'));
  p.key('Escape');                                                    // cancels, does not leave full-screen
  assert.strictEqual(p.els['btn-reset'].textContent, 'RESET');
  assert.ok(!p.calls.some((c) => c[0] === 'exitFullscreen'));
  p.els['btn-reset'].fire('click'); p.els['btn-reset'].fire('click'); // second press confirms
  assert.deepStrictEqual(p.calls.at(-1), ['resetConversation']);
  assert.strictEqual(p.els['btn-reset-cancel'].hidden, true);
});

test('Escape leaves full-screen, F11 toggles, quit button closes', () => {
  const p = online();
  p.key('Escape'); assert.deepStrictEqual(p.calls.at(-1), ['exitFullscreen']);
  p.key('F11'); assert.deepStrictEqual(p.calls.at(-1), ['toggleFullscreen']);
  p.els['btn-fullscreen'].fire('click'); assert.deepStrictEqual(p.calls.at(-1), ['toggleFullscreen']);
  p.els['btn-quit'].fire('click'); assert.deepStrictEqual(p.calls.at(-1), ['quitApp']);
});

test('microphone button starts one voice turn', () => {
  const p = online();
  p.els['btn-mic'].fire('click');
  assert.deepStrictEqual(p.calls.at(-1), ['startVoice']);
});

test('without the Qt bridge the page says so instead of pretending', () => {
  const p = boot({ bridgeUp: false });
  assert.strictEqual(p.els['link-status'].textContent, 'LINK DOWN');
  assert.strictEqual(p.els['core'].getAttribute('data-state'), 'ERROR');
  assert.match(p.els['core-detail'].textContent, /python main\.py --hud/);
  assert.strictEqual(p.els['cmd-input'].disabled, true);
  assert.strictEqual(p.els['btn-send'].disabled, true);
  assert.strictEqual(p.els['btn-mic'].disabled, true);
});

test('garbage from the backend is ignored, not fatal', () => {
  const p = online();
  p.bridge.emitRaw('{not json');
  p.bridge.emit({ type: 'unknown-future-event', seq: 99 });
  assert.strictEqual(p.els['core'].getAttribute('data-state'), 'STANDBY');
});
