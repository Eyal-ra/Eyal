const os = require('os'), fs = require('fs'), path = require('path');
const {
  buildNotification, createNotifier, resolveQueueDir, COLORS,
} = require('./notify-presence.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

const arrival = { type: 'in', name: 'ברינה', since: '09:04', at: '2026-09-02T09:05:00.000Z' };
const departure = { type: 'out', name: 'ברינה', since: '09:04', at: '2026-09-02T17:20:00.000Z' };

const a = buildNotification(arrival);
eq('arrival text names the person and the time', a.text, 'ברינה נכנס/ה — מ־09:04');
eq('departure text', buildNotification(departure).text, 'ברינה יצא/ה');
eq('arrival colour', a.color, COLORS.in);
eq('departure colour differs from arrival',
  buildNotification(departure).color !== a.color, true);
eq('tagged as presence so the notifier can route it', a.kind, 'presence');

// The whole point of the colour: it must not collide with the notifier's
// existing red / green / blue traffic.
const clashes = ['#ff0000', '#f00', 'red', '#00ff00', 'green', '#0000ff', 'blue'];
const used = [COLORS.in, COLORS.out].map((c) => c.toLowerCase());
eq('presence colours do not reuse error/ok/info colours',
  used.some((c) => clashes.includes(c)), false);

eq('colours are overridable',
  buildNotification(arrival, { colors: { in: '#123456' } }).color, '#123456');
eq('title is overridable', buildNotification(arrival, { title: 'משרד' }).title, 'משרד');

// --- queue file ---
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'notif-'));
const notify = createNotifier({ queueDir: dir });
notify(arrival);
notify(departure);

const files = fs.readdirSync(dir);
eq('one file per event', files.length, 2);
eq('no leftover temp files - a rename put them in place',
  files.some((f) => f.endsWith('.tmp')), false);

const written = JSON.parse(fs.readFileSync(path.join(dir, files.sort()[0]), 'utf8'));
eq('Hebrew survives the round trip', written.name, 'ברינה');
eq('colour reaches the queue', typeof written.color === 'string' && written.color.startsWith('#'), true);

// Two events in the same millisecond must not overwrite each other.
const before = fs.readdirSync(dir).length;
for (let i = 0; i < 20; i++) notify(arrival);
eq('rapid events do not collide', fs.readdirSync(dir).length, before + 20);

fs.rmSync(dir, { recursive: true, force: true });
// A wrong queue path used to create itself: alerts written forever, nothing
// reading them. A presence alert that never arrives is the failure nobody
// notices, so this has to be loud.
{
  const real = fs.mkdtempSync(path.join(os.tmpdir(), 'notif-real-'));
  const missing = path.join(real, 'does-not-exist');

  eq('an existing directory is chosen', resolveQueueDir([missing, real]), real);
  eq('the first existing one wins', resolveQueueDir([real, missing]), real);

  let message = null;
  try { resolveQueueDir([missing, path.join(real, 'nor-this')]); }
  catch (err) { message = err.message; }
  eq('a missing directory names every path tried',
    [/no notifier queue directory/.test(message || ''), (message || '').includes(missing)],
    [true, true]);
  eq('and creates nothing', fs.existsSync(missing), false);

  const notifier = createNotifier({ queueDir: [missing, real] });
  notifier({ type: 'in', name: 'ברינה', since: '09:04', at: '2026-09-04T09:04:00Z' });
  eq('the alert lands in the directory that exists',
    fs.readdirSync(real).filter((f) => f.endsWith('.json')).length, 1);

  let failed = null;
  const broken = createNotifier({ queueDir: [missing] });
  try { broken({ type: 'in', name: 'ברינה', since: '09:04', at: '2026-09-04T09:04:00Z' }); }
  catch (err) { failed = err.message; }
  eq('a notifier with nowhere to write throws', /no notifier queue directory/.test(failed || ''), true);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
