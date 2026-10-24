'use strict';
// Feed a JSON array of real backend events through the real model; print the resulting state.
const fs = require('fs');
const path = require('path');
const M = require(path.join(__dirname, '..', '..', 'arceus', 'hud', 'web', 'hud-model.js'));
let s = M.initialState();
let t = 0;
for (const ev of JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))) { s = M.reduce(s, ev, (t += 100)); }
process.stdout.write(JSON.stringify({ state: s, view: M.coreView(s), id: M.coreIdentifier(s.backend), voice: M.voiceIndicator(s) }));
