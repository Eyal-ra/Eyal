'use strict';
/**
 * One poll of TimeWatch: alert on anyone who arrived or left since last time.
 *
 * Written to be run by the Windows scheduler every few minutes rather than to
 * sit resident. A scheduled task that exits is the thing that survives a
 * reboot, a Dropbox restart and a user logging out and back in - a long-lived
 * process is one more thing to notice has died.
 *
 * That means the "since last time" cannot live in memory, so the last snapshot
 * is kept in a state file beside the log.
 *
 *   node watch-presence.js [--once] [--quiet]
 *
 * Exit codes: 0 read and compared, 1 could not read (state left untouched).
 */

const fs = require('fs');
const path = require('path');
const { getConnectedEmployees, loadConfig, describeError } = require('./timewatch-client');
const { createWatcher } = require('./presence-watcher');
const { createNotifier, resolveQueueDir } = require('./notify-presence');
const { createToastNotifier } = require('./notify-toast');

/**
 * Where the alert goes.
 *
 * The office notifier is a Python app with no known file queue, so the queue
 * is used only when one is configured and actually present. Everything else
 * falls back to a Windows tray balloon, which needs nothing installed - an
 * alert that arrives is worth more than the right channel that does not.
 */
function chooseNotifier(cfg) {
  const configured = (cfg.notifier && cfg.notifier.queueDir) || null;
  if (configured) {
    try {
      resolveQueueDir(configured);
      return createNotifier(cfg.notifier);
    } catch (err) {
      console.error(`[presence] ${err.message} - falling back to a tray balloon`);
    }
  }
  return createToastNotifier();
}

const DATA_DIR = process.env.TIMEWATCH_DATA || path.join(__dirname, 'data');

/** state.json is what makes "since last time" survive the process exiting. */
const pathsIn = (dir) => ({
  state: path.join(dir, 'state.json'),
  snapshot: path.join(dir, 'presence.json'),
  logDir: path.join(dir, 'presence-log'),
});

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

/** Temp file then rename, so the dashboard never reads a half-written file. */
function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), 'utf8');
  fs.renameSync(temp, file);
}

async function main(options = {}) {
  const log = options.quiet ? () => {} : console.log;
  const cfg = options.config || loadConfig();
  const now = options.now || new Date();

  const files = pathsIn(options.dataDir || DATA_DIR);
  const result = await (options.fetchPresence || getConnectedEmployees)({ config: cfg, now });

  if (result.warning) {
    // The state file is deliberately left alone. Treating an unreadable
    // report as "nobody is in" would alert that the whole office left.
    console.error('[presence] could not read attendance:', result.warning);
    writeJson(files.snapshot, {
      fetchedAt: result.fetchedAt, connected: [], away: [], warning: result.warning,
    });
    return 1;
  }

  const previous = readJson(files.state, null);
  // The office has one identity running on three machines, and a state file
  // that two of them take turns writing would invent arrivals and departures
  // out of nothing. Local by default, but say so if that ever changes.
  const machine = options.machine || process.env.COMPUTERNAME || 'unknown';
  if (previous && previous.machine && previous.machine !== machine) {
    console.error(`[presence] state was last written by ${previous.machine}, ` +
      `this is ${machine} - run the poll on one machine only`);
    return 1;
  }
  const watcher = createWatcher({
    logDir: files.logDir,
    watchNames: cfg.watchNames,
    initialSnapshot: previous ? previous.connected : null,
    notify: options.notify || chooseNotifier(cfg),
  });

  const events = watcher.update(result.connected, now);
  writeJson(files.state, { at: now.toISOString(), machine, connected: result.connected });
  writeJson(files.snapshot, {
    fetchedAt: result.fetchedAt,
    connected: result.connected,
    away: result.away,
    errors: result.errors,
    warning: null,
  });

  const changes = events.filter((e) => e.type !== 'initial');
  // The employee count is not decoration: "0 in" out of seven is a quiet
  // office, "0 in" out of zero is a broken read, and they used to print the
  // same line.
  const read = result.connected.length + result.away.length;
  log(`[presence] ${read} employees read, ${result.connected.length} in, `
    + `${changes.length} change(s)`);
  for (const event of changes) {
    log(`  ${event.type === 'in' ? 'נכנס/ה' : 'יצא/ה'}: ${event.name}`);
  }
  return 0;
}

if (require.main === module) {
  const quiet = process.argv.includes('--quiet');
  main({ quiet })
    .then((code) => process.exit(code))
    .catch((err) => {
      console.error('[presence] failed:', describeError(err));
      process.exit(1);
    });
}

module.exports = { main, pathsIn, chooseNotifier, DATA_DIR };
