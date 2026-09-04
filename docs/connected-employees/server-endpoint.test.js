const os = require('os'), fs = require('fs'), path = require('path');
const { registerConnectedEmployees } = require('./server-endpoint.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

/** The smallest thing that looks like express to this module. */
function fakeApp() {
  const routes = {};
  return {
    get: (p, handler) => { routes[p] = handler; },
    call: (p) => new Promise((resolve) => {
      routes[p]({}, { set: () => {}, status() { return this; }, json: resolve });
    }),
  };
}

const brina = { name: 'זילברברג ברינה', since: '09:04', minutes: 60 };
const logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'presence-endpoint-'));

(async () => {
  const alerts = [];
  let payload = { fetchedAt: new Date().toISOString(), connected: [brina], away: [], errors: [], warning: null };

  const app = fakeApp();
  registerConnectedEmployees(app, {
    config: { watchNames: [], employees: [] },
    logDir,
    cacheSeconds: 0,
    notify: (e) => alerts.push(e.type + ':' + e.name),
    fetchPresence: async () => payload,
  });

  await app.call('/api/connected-employees');          // initial - never alerts
  eq('the first read is a baseline, not an arrival', alerts, []);

  payload = { ...payload, connected: [] };
  await app.call('/api/connected-employees');
  eq('a real departure does alert', alerts, ['out:זילברברג ברינה']);

  // The failure that matters: the read broke, so the office looks empty.
  payload = { ...payload, connected: [brina], warning: null };
  await app.call('/api/connected-employees');
  alerts.length = 0;
  payload = { fetchedAt: new Date().toISOString(), connected: [], away: [], errors: [], warning: 'no data rows' };
  const answer = await app.call('/api/connected-employees');
  eq('an unreadable report fires no departure alerts', alerts, []);
  eq('and the card is told why', answer.warning, 'no data rows');

  // State did not move, so the next good read is not an arrival either.
  payload = { fetchedAt: new Date().toISOString(), connected: [brina], away: [], errors: [], warning: null };
  await app.call('/api/connected-employees');
  eq('recovery is not an arrival', alerts, []);

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
