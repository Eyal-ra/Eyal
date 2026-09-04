const os = require('os'), fs = require('fs'), path = require('path');
const { main, pathsIn, chooseNotifier } = require('./watch-presence.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

const brina = { name: 'זילברברג ברינה', since: '09:04', minutes: 60 };
const shalev = { name: 'דבח שלו', since: '08:13', minutes: 111 };
const config = { watchNames: [], employees: [] };

const ok = (connected, away = []) => ({
  fetchedAt: '2026-09-04T09:04:00.000Z', connected, away, errors: [], warning: null,
});

function run(dataDir, payload, alerts, when) {
  return main({
    dataDir, config, quiet: true,
    now: when || new Date(2026, 8, 4, 10, 0),
    fetchPresence: async () => payload,
    notify: (e) => alerts.push(`${e.type}:${e.name}`),
  });
}

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'presence-run-'));
  const files = pathsIn(dir);
  const alerts = [];

  // A scheduled task exits between polls, so "since last time" has to be on
  // disk. The first run is a baseline and must never alert.
  eq('first run exits clean', await run(dir, ok([brina]), alerts), 0);
  eq('the first run is a baseline, not an arrival', alerts, []);
  eq('state is written for the next run',
    JSON.parse(fs.readFileSync(files.state, 'utf8')).connected.map((e) => e.name),
    ['זילברברג ברינה']);

  // A separate main() call is a separate process as far as state goes.
  await run(dir, ok([brina, shalev]), alerts);
  eq('an arrival between polls alerts', alerts, ['in:דבח שלו']);

  alerts.length = 0;
  await run(dir, ok([shalev]), alerts);
  eq('a departure between polls alerts', alerts, ['out:זילברברג ברינה']);

  // The failure that matters: an unreadable report must not read as an
  // office that emptied out.
  alerts.length = 0;
  const before = fs.readFileSync(files.state, 'utf8');
  const code = await run(dir, {
    fetchedAt: '2026-09-04T10:00:00.000Z', connected: [], away: [], errors: [],
    warning: 'the report returned no data rows',
  }, alerts);
  eq('an unreadable report exits non-zero', code, 1);
  eq('and alerts nobody', alerts, []);
  eq('and leaves the state untouched', fs.readFileSync(files.state, 'utf8'), before);
  eq('while telling the dashboard why',
    JSON.parse(fs.readFileSync(files.snapshot, 'utf8')).warning,
    'the report returned no data rows');

  // Recovery is not an arrival - the state never moved.
  alerts.length = 0;
  await run(dir, ok([shalev]), alerts);
  eq('recovery alerts nobody', alerts, []);

  // The dashboard reads a complete file or none at all.
  const snapshot = JSON.parse(fs.readFileSync(files.snapshot, 'utf8'));
  eq('the snapshot carries what the card renders',
    [snapshot.connected.length, snapshot.warning, typeof snapshot.fetchedAt],
    [1, null, 'string']);
  eq('no temp files left behind',
    fs.readdirSync(dir).filter((f) => f.endsWith('.tmp')), []);

  // watchNames still narrows who is worth interrupting for.
  {
    const narrow = fs.mkdtempSync(path.join(os.tmpdir(), 'presence-narrow-'));
    const seen = [];
    const only = { watchNames: ['ברינה'], employees: [] };
    const call = (payload) => main({
      dataDir: narrow, config: only, quiet: true, now: new Date(2026, 8, 4, 10, 0),
      fetchPresence: async () => payload, notify: (e) => seen.push(e.name),
    });
    await call(ok([]));
    await call(ok([brina, shalev]));
    eq('only the watched name interrupts', seen, ['זילברברג ברינה']);
  }

  // One identity, three machines: a state file two of them take turns writing
  // would invent arrivals and departures out of nothing.
  {
    const shared = fs.mkdtempSync(path.join(os.tmpdir(), 'presence-shared-'));
    const seen = [];
    const call = (machine, payload) => main({
      dataDir: shared, config, quiet: true, machine,
      now: new Date(2026, 8, 4, 10, 0),
      fetchPresence: async () => payload, notify: (e) => seen.push(e.name),
    });
    await call('EYAL', ok([brina]));
    eq('a second machine refuses rather than alerting', await call('TS01', ok([])), 1);
    eq('and alerts nobody', seen, []);
    eq('the original machine still works', await call('EYAL', ok([brina])), 0);
  }

  // The office notifier is a Python app with no known queue, so the queue is
  // used only when one is configured and really there. An alert that arrives
  // beats the right channel that does not.
  {
    const queue = fs.mkdtempSync(path.join(os.tmpdir(), 'notif-queue-'));
    const toQueue = chooseNotifier({ notifier: { queueDir: [queue] } });
    toQueue({ type: 'in', name: 'ברינה', since: '09:04', at: '2026-09-04T09:04:00Z' });
    eq('a configured queue that exists receives the alert',
      fs.readdirSync(queue).filter((f) => f.endsWith('.json')).length, 1);

    const missing = path.join(queue, 'not-here');
    const fallback = chooseNotifier({ notifier: { queueDir: [missing] } });
    // Off Windows the balloon prints instead of drawing; the point is that
    // it neither throws nor writes to a directory that is not there.
    let threw = null;
    try { fallback({ type: 'in', name: 'ברינה', since: '09:04', at: 'x' }); }
    catch (err) { threw = err.message; }
    eq('a configured queue that is missing falls back rather than throwing', threw, null);
    eq('and nothing was created at the missing path', fs.existsSync(missing), false);

    eq('no queue configured means no queue is invented',
      typeof chooseNotifier({}), 'function');
  }

  // The panel is preferred over the balloon, and a broken panel still gets
  // the alert out rather than losing it.
  {
    const office = fs.mkdtempSync(path.join(os.tmpdir(), 'notif-office-'));
    const appDir = path.join(office, 'app');
    const dataFolder = path.join(office, 'data');
    fs.mkdirSync(appDir, { recursive: true });
    fs.mkdirSync(path.join(dataFolder, 'outbox', 'eyal'), { recursive: true });
    fs.writeFileSync(path.join(appDir, 'config.json'),
      JSON.stringify({ data_folder: dataFolder, employee_name: 'eyal' }), 'utf8');

    const notify = chooseNotifier({ notifier: { appDir } });
    notify({ type: 'in', name: 'זילברברג ברינה', since: '09:04', at: 'x' });
    const written = fs.readdirSync(path.join(dataFolder, 'outbox', 'eyal'));
    eq('the alert goes to the office panel', written.length, 1);
    eq('and reads as a presence alert',
      JSON.parse(fs.readFileSync(path.join(dataFolder, 'outbox', 'eyal', written[0]), 'utf8')).title,
      'נוכחות — כניסה');

    // No notifier config anywhere: fall through rather than throw.
    let threw = null;
    try {
      chooseNotifier({ notifier: { appDir: path.join(office, 'nope') } })(
        { type: 'out', name: 'ברינה', since: '09:04', at: 'x' });
    } catch (err) { threw = err.message; }
    eq('a missing notifier falls through to the balloon', threw, null);
  }

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
