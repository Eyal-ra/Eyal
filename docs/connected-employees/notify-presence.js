'use strict';
/**
 * Presence notifications for the office notifier.
 *
 * Presence events get their own colour so they are recognisable at a glance,
 * before reading a word of them. The violet family is used because the
 * notifier's other traffic is red (failures), green (all clear) and blue
 * (info) - a presence alert in any of those would read as one of them.
 *
 * Arrival and departure stay inside that family rather than taking unrelated
 * colours, so "this is a presence alert" is one signal and "in or out" is a
 * second one, not a competing first.
 */

const fs = require('fs');
const path = require('path');

const COLORS = {
  in: '#7c3aed',   // violet - arrived, reachable
  out: '#a78bfa',  // lighter violet - left. Still saturated enough to read
                   // as a colour on a white card, not as a grey edge.
};

/**
 * Build the notification payload for one presence event.
 *
 * @param {{type:'in'|'out', name:string, since:string, at:string}} event
 * @param {{colors?:object, title?:string}} [options]
 */
function buildNotification(event, options = {}) {
  const colors = { ...COLORS, ...(options.colors || {}) };
  const arrived = event.type === 'in';
  return {
    kind: 'presence',
    type: event.type,
    name: event.name,
    title: options.title || 'נוכחות',
    text: arrived
      ? `${event.name} נכנס/ה — מ־${event.since}`
      : `${event.name} יצא/ה`,
    color: colors[event.type],
    // Violet rather than a green/grey dot: a green marker inside a presence
    // alert reads as "all clear" at a glance, which is a different message.
    icon: arrived ? '🟣' : '⚪',
    at: event.at,
  };
}

/**
 * Drop a notification request into the notifier's queue directory.
 *
 * Written to a temp name and renamed into place: the notifier polls the
 * directory, and a rename is atomic, so it can never pick up a half-written
 * file. UTF-8 explicitly, so Hebrew survives the trip.
 */
function writeRequest(dir, notification, now) {
  const stamp = (now || new Date()).getTime();
  const unique = Math.random().toString(36).slice(2, 8);
  const finalPath = path.join(dir, `presence-${stamp}-${unique}.json`);
  const tempPath = `${finalPath}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(notification, null, 2), { encoding: 'utf8' });
  fs.renameSync(tempPath, finalPath);
  return finalPath;
}

/**
 * The queue directory the notifier is actually watching.
 *
 * Deliberately does not create one. Creating a missing directory turns a
 * wrong path into a silent success - alerts are written forever and nothing
 * ever reads them - and a presence alert that never arrives is exactly the
 * failure nobody notices. An error naming every path tried is the cheaper
 * outcome.
 */
function resolveQueueDir(candidates) {
  const list = (Array.isArray(candidates) ? candidates : [candidates]).filter(Boolean);
  for (const dir of list) {
    try {
      if (fs.statSync(dir).isDirectory()) return dir;
    } catch { /* next candidate */ }
  }
  throw new Error(`no notifier queue directory found - tried: ${list.join(', ')}`);
}

/**
 * The `notify` callback for server-endpoint.js.
 *
 *   notify: createNotifier({ queueDir: 'C:\\notif_test\\app\\presence-requests' })
 *
 * `queueDir` may be a list, and the first one that exists wins; the office
 * notifier has lived in more than one place. Resolution happens on each
 * event rather than once at startup, so a queue directory that appears later
 * - or moves - does not need the dashboard restarted.
 *
 * If the notifier expects different field names, map them here - this is the
 * single place that knows its schema.
 */
function createNotifier(options = {}) {
  const candidates = options.queueDir || [
    'C:\\notif_test\\app\\presence-requests',
    'C:\\notif-requests',
  ];
  return (event) => writeRequest(resolveQueueDir(candidates), buildNotification(event, options));
}

module.exports = {
  createNotifier, buildNotification, writeRequest, resolveQueueDir, COLORS,
};
