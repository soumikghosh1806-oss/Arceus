'use strict';
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const M = require(path.join(__dirname, '..', '..', 'arceus', 'hud', 'web', 'hud-model.js'));

const snap = (over) => Object.assign({ type: 'snapshot', seq: 10, state: 'STANDBY', detail: '', busy: false,
  messages: [], activity: [], backend: { label: 'LOCAL AI', model: 'qwen2.5:3b', connection: 'CONNECTED' },
  devices: {}, voice: {}, metrics: {}, app: { fullscreen: false }, version: '0.1.0' }, over);

test('fresh state holds no invented data', () => {
  const s = M.initialState();
  assert.deepStrictEqual(s.messages, []);
  assert.strictEqual(s.metrics.cpu_percent, null);
  assert.strictEqual(M.fmtPercent(s.metrics.cpu_percent), 'N/A');
  assert.strictEqual(M.fmtRam(null, null), 'N/A');
  assert.strictEqual(M.fmtUptime(undefined), 'N/A');
});

test('snapshot replaces state and stale events are ignored', () => {
  let s = M.reduce(M.initialState(), snap({ messages: [{ role: 'user', text: 'hi', ts: 1, seq: 9 }] }), 0);
  assert.strictEqual(s.ready, true);
  assert.strictEqual(s.messages.length, 1);
  const stale = M.reduce(s, { type: 'message', seq: 9, role: 'user', text: 'hi', ts: 1 }, 0);
  assert.strictEqual(stale.messages.length, 1);           // duplicate of what the snapshot already holds
  const fresh = M.reduce(s, { type: 'message', seq: 11, role: 'assistant', text: 'hello', ts: 2 }, 0);
  assert.strictEqual(fresh.messages.length, 2);
});

test('response time is measured from generation start to the assistant message', () => {
  let s = M.reduce(M.initialState(), snap(), 0);
  s = M.reduce(s, { type: 'state', seq: 11, state: 'PROCESSING', detail: M.GENERATING, busy: true }, 1000);
  assert.strictEqual(M.fmtResponse(s.lastResponseMs, true), 'GENERATING');
  s = M.reduce(s, { type: 'message', seq: 12, role: 'assistant', text: 'ok', ts: 1 }, 3400);
  assert.strictEqual(s.lastResponseMs, 2400);
  assert.strictEqual(M.fmtResponse(s.lastResponseMs, false), 'LAST RESPONSE 2.4 S');
  s = M.reduce(s, { type: 'reset', seq: 13 }, 0);
  assert.strictEqual(M.fmtResponse(s.lastResponseMs, false), 'AWAITING INPUT');
});

test('an error clears a pending generation timer', () => {
  let s = M.reduce(M.initialState(), snap(), 0);
  s = M.reduce(s, { type: 'state', seq: 11, state: 'PROCESSING', detail: M.GENERATING, busy: true }, 100);
  s = M.reduce(s, { type: 'state', seq: 12, state: 'ERROR', detail: 'boom', busy: false }, 200);
  assert.strictEqual(s.generationStartedAt, null);
  assert.strictEqual(s.lastResponseMs, null);
});

test('core view: honest error when the bridge is down', () => {
  let s = M.reduce(M.initialState(), { type: 'bridge', status: 'unavailable' }, 0);
  const v = M.coreView(s);
  assert.strictEqual(v.state, 'ERROR');
  assert.match(v.detail, /main\.py --hud/);
  assert.strictEqual(M.canSend(s, 'hi'), false);
  assert.strictEqual(M.canUseVoice(s), false);
});

test('core view follows backend state and identifier follows backend label', () => {
  let s = M.reduce(M.initialState(), snap({ state: 'LISTENING', detail: 'RECORDING 5S', busy: true }), 0);
  assert.deepStrictEqual(M.coreView(s), { state: 'LISTENING', detail: 'RECORDING 5S' });
  assert.strictEqual(M.coreIdentifier(s.backend), 'ARCEUS CORE / LOCAL AI');
  assert.strictEqual(M.coreIdentifier({}), 'ARCEUS CORE / N/A');
});

test('input rules', () => {
  let s = M.reduce(M.initialState(), snap(), 0);
  assert.strictEqual(M.canSend(s, '  '), false);
  assert.strictEqual(M.canSend(s, 'hello'), true);
  s = M.reduce(s, { type: 'state', seq: 11, state: 'PROCESSING', detail: M.GENERATING, busy: true }, 0);
  assert.strictEqual(M.canSend(s, 'hello'), false);
  assert.strictEqual(M.canUseVoice(s), false);
});

test('voice indicator reflects real state and microphone facts', () => {
  const mk = (over) => M.reduce(M.initialState(), snap(over), 0);
  assert.strictEqual(M.voiceIndicator(mk({ state: 'LISTENING', busy: true })).text, 'LISTENING');
  assert.strictEqual(M.voiceIndicator(mk({ state: 'SPEAKING', busy: true })).text, 'SPEAKING');
  assert.strictEqual(M.voiceIndicator(mk({ state: 'PROCESSING', detail: 'TRANSCRIBING', busy: true })).text, 'TRANSCRIBING');
  assert.strictEqual(M.voiceIndicator(mk({ devices: { mic: 'AVAILABLE' } })).text, 'VOICE READY');
  assert.strictEqual(M.voiceIndicator(mk({ devices: { mic: 'NOT DETECTED' } })).tone, 'warn');
  assert.strictEqual(M.voiceIndicator(mk({ devices: { mic: 'N/A' } })).text, 'VOICE N/A');
});

test('formatters never invent values', () => {
  assert.strictEqual(M.fmtResidency({ state: 'GPU' }), 'GPU 100%');
  assert.strictEqual(M.fmtResidency({ state: 'SPLIT', gpu_percent: 25 }), 'SPLIT 25% GPU');
  assert.strictEqual(M.fmtResidency({ state: 'IDLE' }), 'NOT LOADED');
  assert.strictEqual(M.fmtResidency({ state: 'N/A' }), 'N/A');
  assert.strictEqual(M.fmtInstalled(null), 'N/A');
  assert.strictEqual(M.fmtDbfs(null), 'NONE YET');
  assert.strictEqual(M.fmtDbfs({ peak_dbfs: -6.04 }), 'PEAK -6.0 dBFS');
  assert.strictEqual(M.fmtUptime(3725), '01:02:05');
  assert.strictEqual(M.fmtPercent(37.4), '37%');
});

test('visualiser levels stay in range and ERROR is nearly flat', () => {
  for (const st of M.STATES) {
    for (let i = 0; i < 72; i += 7) {
      const v = M.barLevel(st, i, 72, 12.34);
      assert.ok(v >= 0 && v <= 1, `${st} ${i} -> ${v}`);
    }
  }
  const mean = (st) => Array.from({ length: 72 }, (_, i) => M.barLevel(st, i, 72, 3)).reduce((a, b) => a + b) / 72;
  assert.ok(mean('ERROR') < mean('STANDBY') && mean('STANDBY') < mean('SPEAKING'));
});
