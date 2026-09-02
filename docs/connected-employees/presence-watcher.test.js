const os = require('os'), fs = require('fs'), path = require('path');
const { diffPresence, createWatcher } = require('./presence-watcher.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}
const now = new Date(2026, 8, 2, 12, 0);
const strip = (evts) => evts.map((e) => ({ type: e.type, name: e.name, since: e.since }));

const brina = { name: 'ברינה', since: '09:04' };
const shalev = { name: 'שלו', since: '08:13' };

eq('first run reports initial, not arrivals',
  strip(diffPresence(null, [brina, shalev], now)),
  [{ type: 'initial', name: 'ברינה', since: '09:04' }, { type: 'initial', name: 'שלו', since: '08:13' }]);

eq('no change -> no events', diffPresence([brina], [brina], now), []);

eq('arrival', strip(diffPresence([shalev], [shalev, brina], now)),
  [{ type: 'in', name: 'ברינה', since: '09:04' }]);

eq('departure', strip(diffPresence([shalev, brina], [shalev], now)),
  [{ type: 'out', name: 'ברינה', since: '09:04' }]);

// Out for lunch and back the same poll: the entry time changes, so it is a
// fresh arrival rather than silence.
eq('clocked out and back in between polls',
  strip(diffPresence([brina], [{ name: 'ברינה', since: '13:15' }], now)),
  [{ type: 'in', name: 'ברינה', since: '13:15' }]);

eq('everyone leaves', strip(diffPresence([brina, shalev], [], now)),
  [{ type: 'out', name: 'ברינה', since: '09:04' }, { type: 'out', name: 'שלו', since: '08:13' }]);

// --- watcher: alerts, filtering, logging ---
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'presence-'));
const alerts = [];
const w = createWatcher({ logDir: dir, watchNames: ['ברינה'], notify: (e) => alerts.push(e) });

w.update([shalev], now);                     // initial - never alerts
eq('initial never alerts', alerts.length, 0);

w.update([shalev, brina], now);              // Brina arrives
eq('watched arrival alerts', strip(alerts), [{ type: 'in', name: 'ברינה', since: '09:04' }]);

w.update([shalev, brina, { name: 'מאיה', since: '11:00' }], now);
eq('unwatched arrival does not alert', alerts.length, 1);

w.update([brina], now);                      // Shalev and Maya leave
eq('unwatched departures do not alert', alerts.length, 1);

w.update([], now);                           // Brina leaves
eq('watched departure alerts', strip(alerts).slice(1), [{ type: 'out', name: 'ברינה', since: '09:04' }]);

// initial:shalev, in:brina, in:maya, out:shalev, out:maya, out:brina
const logged = w.today(now);
eq('log holds every event, watched or not', logged.length, 6);
eq('log records unwatched people too',
  logged.filter((e) => e.name === 'מאיה').map((e) => e.type), ['in', 'out']);

// A failing notifier must not break the update. The error it logs below is
// the point of the test, not a failure.
const w2 = createWatcher({ logDir: dir, notify: () => { throw new Error('notifier down'); } });
w2.update([], now);
let survived = true;
try { w2.update([brina], now); } catch { survived = false; }
eq('a failing notifier does not break the poll', survived, true);

fs.rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
