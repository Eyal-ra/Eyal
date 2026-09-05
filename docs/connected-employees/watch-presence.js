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
const { readNotifierConfig, createPanelNotifier } = require('./notifier-bridge');

/**
 * Where the alert goes, best channel first.
 *
 * 1. The office notifier's own panel, if its config is there. The alert then
 *    appears where every other office notification already appears.
 * 2. A configured file queue, if one is set and present.
 * 3. A Windows tray balloon, which needs nothing installed.
 *
 * Each falls through to the next on failure rather than losing the event: an
 * alert in the wrong place beats an alert nowhere.
 */
function chooseNotifier(cfg) {
  const configured = (cfg.notifier && cfg.notifier.queueDir) || null;
  const toast = createToastNotifier();

  if (configured) {
    try {
      resolveQueueDir(configured);
      return createNotifier(cfg.notifier);
    } catch (err) {
      console.error(`[presence] ${err.message} - trying the office panel`);
    }
  }

  try {
    readNotifierConfig((cfg.notifier && cfg.notifier.appDir) || undefined);
    const panel = createPanelNotifier({ appDir: cfg.notifier && cfg.notifier.appDir });
    return (event) => {
      try {
        return panel(event);
      } catch (err) {
        console.error(`[presence] office panel: ${err.message} - showing a balloon instead`);
        return toast(event);
      }
    };
  } catch {
    return toast;
  }
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


/**
 * Put the snapshot where the dashboard can read it.
 *
 * Beside dashboard.html rather than behind an endpoint, so the card works
 * whether the page is served or opened directly, with no server to keep
 * alive. The .js twin is for file://, where fetch is blocked but a script
 * tag still loads.
 */
function publish(snapshot, targets) {
  const written = [];
  for (const dir of targets) {
    try {
      writeJson(path.join(dir, 'presence.json'), snapshot);
      const js = `window.__presence = ${JSON.stringify(snapshot, null, 2)};\n`;
      const file = path.join(dir, 'presence-data.js');
      fs.writeFileSync(`${file}.tmp`, js, 'utf8');
      fs.renameSync(`${file}.tmp`, file);
      written.push(dir);
    } catch (err) {
      console.error(`[presence] could not publish to ${dir}: ${err.message}`);
    }
  }
  return written;
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
    const failed = {
      fetchedAt: result.fetchedAt, connected: [], away: [], warning: result.warning,
    };
    writeJson(files.snapshot, failed);
    publish(failed, options.publishTo || (cfg.dashboard && cfg.dashboard.publishTo) || []);
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
  const snapshot = {
    fetchedAt: result.fetchedAt,
    connected: result.connected,
    away: result.away,
    errors: result.errors,
    warning: null,
  };
  writeJson(files.snapshot, snapshot);
  const published = publish(snapshot,
    options.publishTo || (cfg.dashboard && cfg.dashboard.publishTo) || []);

  const changes = events.filter((e) => e.type !== 'initial');
  // The employee count is not decoration: "0 in" out of seven is a quiet
  // office, "0 in" out of zero is a broken read, and they used to print the
  // same line.
  const read = result.connected.length + result.away.length;
  log(`[presence] ${read} employees read, ${result.connected.length} in, `
    + `${changes.length} change(s)`
    + (published.length ? `, published to ${published.length} dashboard folder(s)` : ''));
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

module.exports = { main, pathsIn, chooseNotifier, publish, DATA_DIR };
