'use strict';
/**
 * Put presence alerts into the office notifier's own panel.
 *
 * The notifier is a Python app that reads pending messages from
 * <data_folder>/outbox/<employee>/<id>.json and tracks what it has shown.
 * So an alert only has to be a file of the right shape in the right place.
 *
 * The shape is not hard-coded. It is copied from a message the notifier
 * itself wrote: the newest one in the outbox or the archive becomes the
 * template, and its field names are reused. Guessing a schema here would be
 * the same mistake as guessing TimeWatch's query parameters - and this one
 * writes into a folder ten people's notifiers are reading.
 *
 *   node notifier-bridge.js          # dry run: print what would be written
 *   node notifier-bridge.js --send   # actually write one test alert
 */

const fs = require('fs');
const path = require('path');

const APP_DIR = process.env.NOTIFIER_APP || 'C:\\notif_test\\app';

/** Text fields are the notification itself; everything else is plumbing. */
const TEXT_KEYS = ['title', 'body', 'text', 'message', 'subject', 'content', 'description'];
const ID_KEYS = ['id', 'message_id', 'msg_id'];
const TIME_KEYS = ['created_at', 'created', 'timestamp', 'ts', 'at', 'date', 'sent_at'];
const TO_KEYS = ['to', 'to_employee', 'employee', 'recipient'];

const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));

function readNotifierConfig(appDir = APP_DIR) {
  const config = readJson(path.join(appDir, 'config.json'));
  if (!config.data_folder) throw new Error(`${appDir}\\config.json has no data_folder`);
  return { dataFolder: config.data_folder, employee: config.employee_name || null };
}

/** Every message file under a directory, newest first. */
function messagesUnder(dir, depth = 2) {
  const out = [];
  const walk = (current, left) => {
    let entries;
    try { entries = fs.readdirSync(current, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) { if (left > 0) walk(full, left - 1); continue; }
      if (!entry.name.endsWith('.json')) continue;
      // Dropbox leaves these behind when two machines write the same name.
      if (/conflicted copy/i.test(entry.name)) continue;
      try { out.push({ file: full, mtime: fs.statSync(full).mtimeMs }); } catch { /* vanished */ }
    }
  };
  walk(dir, depth);
  return out.sort((a, b) => b.mtime - a.mtime);
}

/**
 * A message the notifier wrote, to copy the shape from.
 *
 * The outbox is preferred over the archive: a pending message is exactly
 * what we are about to create, while an archived one may carry extra fields
 * the archiving added.
 */
function findTemplate(dataFolder, employee) {
  const roots = [
    employee && path.join(dataFolder, 'outbox', employee),
    path.join(dataFolder, 'outbox'),
    path.join(dataFolder, 'archive'),
  ].filter(Boolean);

  for (const root of roots) {
    for (const { file } of messagesUnder(root)) {
      try {
        const value = readJson(file);
        const message = Array.isArray(value) ? value[0] : value;
        if (message && typeof message === 'object'
            && TEXT_KEYS.some((k) => k in message)) {
          return { file, message };
        }
      } catch { /* not a message */ }
    }
  }
  return null;
}

const newId = (now) =>
  `presence-${now.toISOString().replace(/[^0-9]/g, '').slice(0, 14)}-`
  + Math.random().toString(36).slice(2, 8);

/**
 * A presence alert shaped like the notifier's own messages.
 *
 * Keys come from the template; values do not. Anything textual is replaced
 * rather than copied - a template carries someone's client, and copying its
 * text into a new message would put that client in front of the wrong eyes.
 */
function buildPanelMessage(template, event, options = {}) {
  const now = options.now || new Date();
  const employee = options.employee || null;
  const arrived = event.type === 'in';

  const title = arrived ? 'נוכחות — כניסה' : 'נוכחות — יציאה';
  const body = arrived
    ? `${event.name} נכנס/ה — מ־${event.since}`
    : `${event.name} יצא/ה`;

  const message = {};
  for (const [key, value] of Object.entries(template || {})) {
    if (TEXT_KEYS.includes(key)) { message[key] = key === 'title' ? title : body; continue; }
    if (ID_KEYS.includes(key)) { message[key] = options.id || newId(now); continue; }
    if (TIME_KEYS.includes(key)) { message[key] = now.toISOString(); continue; }
    if (TO_KEYS.includes(key)) { message[key] = employee ?? value; continue; }
    // Structural fields - type, status, flags - keep the template's value, so
    // the panel renders this the way it renders a message it wrote itself.
    // An invented type could be one the panel has no branch for.
    message[key] = typeof value === 'string' || typeof value === 'number'
      || typeof value === 'boolean' || value === null ? value : Array.isArray(value) ? [] : {};
  }

  // A template without a title or body still has to carry the text.
  if (!TEXT_KEYS.some((k) => k in message)) { message.title = title; message.body = body; }
  if (!ID_KEYS.some((k) => k in message)) message.id = options.id || newId(now);
  if (!TIME_KEYS.some((k) => k in message)) message.created_at = now.toISOString();
  if (employee && !TO_KEYS.some((k) => k in message)) message.to = employee;
  if (options.type) message.type = options.type;

  return message;
}

/** Temp file then rename, the same way the notifier writes its own. */
function writeMessage(dataFolder, employee, message) {
  const dir = path.join(dataFolder, 'outbox', employee);
  fs.mkdirSync(dir, { recursive: true });
  const id = ID_KEYS.map((k) => message[k]).find(Boolean);
  const file = path.join(dir, `${id}.json`);
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(message, null, 2), 'utf8');
  fs.renameSync(temp, file);
  return file;
}

/**
 * @returns {{file:string|null, message:object, template:string|null}}
 */
function sendToPanel(event, options = {}) {
  const { dataFolder, employee } = options.config || readNotifierConfig(options.appDir);
  const who = options.employee || employee;
  if (!who) throw new Error('the notifier config has no employee_name, so there is no outbox to write to');

  const found = findTemplate(dataFolder, who);
  const message = buildPanelMessage(found ? found.message : null, event, { ...options, employee: who });

  return {
    template: found ? found.file : null,
    message,
    file: options.dryRun ? null : writeMessage(dataFolder, who, message),
  };
}

const createPanelNotifier = (options = {}) => (event) => sendToPanel(event, options);

if (require.main === module) {
  const send = process.argv.includes('--send');
  try {
    const result = sendToPanel(
      { type: 'in', name: 'בדיקה', since: '09:04' },
      { dryRun: !send },
    );
    console.log(`template: ${result.template || '(none found - using a minimal shape)'}`);
    console.log(JSON.stringify(result.message, null, 2));
    console.log(send ? `written: ${result.file}` : '\ndry run - nothing written. add --send to write it.');
    process.exit(0);
  } catch (err) {
    console.error(`bridge failed: ${err.message}`);
    process.exit(1);
  }
}

module.exports = {
  readNotifierConfig, findTemplate, buildPanelMessage, writeMessage,
  sendToPanel, createPanelNotifier, messagesUnder,
};
