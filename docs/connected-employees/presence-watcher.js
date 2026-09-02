'use strict';
/**
 * Turns successive presence snapshots into arrival/departure events.
 *
 * The dashboard card answers "who is in right now". This answers "who came
 * in and who left", which is what an alert needs: only a change is worth
 * telling anyone about, and only once.
 *
 * Events are appended to a per-day JSONL log so the history survives a
 * restart of the dashboard server.
 */

const fs = require('fs');
const path = require('path');

/**
 * Compare two snapshots and return what changed.
 *
 * A first run has no previous snapshot: whoever is already in is reported as
 * `initial`, not as an arrival, so restarting the server mid-morning does not
 * fire an alert for everyone who has been at their desk for hours.
 *
 * @param {{name:string, since:string}[]|null} previous
 * @param {{name:string, since:string}[]} current
 */
function diffPresence(previous, current, now) {
  const at = (now || new Date()).toISOString();
  const currentByName = new Map(current.map((e) => [e.name, e]));

  if (previous === null || previous === undefined) {
    return current.map((e) => ({ type: 'initial', name: e.name, since: e.since, at }));
  }

  const previousByName = new Map(previous.map((e) => [e.name, e]));
  const events = [];

  for (const [name, entry] of currentByName) {
    const before = previousByName.get(name);
    // A new `since` means they clocked out and back in - a fresh arrival.
    if (!before) events.push({ type: 'in', name, since: entry.since, at });
    else if (before.since !== entry.since) events.push({ type: 'in', name, since: entry.since, at });
  }
  for (const [name, entry] of previousByName) {
    if (!currentByName.has(name)) events.push({ type: 'out', name, since: entry.since, at });
  }

  events.sort((a, b) => a.name.localeCompare(b.name, 'he'));
  return events;
}

function logPathFor(dir, date) {
  const d = date || new Date();
  const stamp = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return path.join(dir, `presence-${stamp}.jsonl`);
}

function appendEvents(dir, events, date) {
  if (!events.length) return;
  fs.mkdirSync(dir, { recursive: true });
  const lines = events.map((e) => JSON.stringify(e)).join('\n') + '\n';
  fs.appendFileSync(logPathFor(dir, date), lines, 'utf8');
}

function readDayLog(dir, date) {
  try {
    return fs.readFileSync(logPathFor(dir, date), 'utf8')
      .split('\n')
      .filter(Boolean)
      .map((line) => { try { return JSON.parse(line); } catch { return null; } })
      .filter(Boolean);
  } catch (err) {
    if (err.code === 'ENOENT') return [];
    throw err;
  }
}

/**
 * Stateful watcher. Feed it each snapshot; it logs the changes and hands the
 * alert-worthy ones to `notify`.
 *
 * `watchNames` limits alerts to the people worth interrupting for (everything
 * still reaches the log). `initial` events are never alerted on.
 */
function createWatcher(options = {}) {
  const dir = options.logDir || 'presence-log';
  const watchNames = options.watchNames && options.watchNames.length
    ? new Set(options.watchNames)
    : null;
  const notify = options.notify || (() => {});
  let previous = options.initialSnapshot ?? null;

  return {
    /** @param {{name:string, since:string}[]} connected */
    update(connected, now) {
      const events = diffPresence(previous, connected, now);
      previous = connected;
      appendEvents(dir, events, now);
      for (const event of events) {
        if (event.type === 'initial') continue;
        if (watchNames && !watchNames.has(event.name)) continue;
        try {
          notify(event);
        } catch (err) {
          // An alert that fails must never take the dashboard down with it.
          console.error('[presence-watcher] notify failed', err);
        }
      }
      return events;
    },
    today(now) { return readDayLog(dir, now); },
  };
}

module.exports = { createWatcher, diffPresence, readDayLog, logPathFor };
