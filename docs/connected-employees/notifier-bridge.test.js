const os = require('os'), fs = require('fs'), path = require('path');
const {
  readNotifierConfig, findTemplate, buildPanelMessage, sendToPanel, messagesUnder,
} = require('./notifier-bridge.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

// A replica of the notifier's layout: config beside the app, messages under
// <data_folder>/outbox/<employee>/<id>.json.
function makeOffice(options = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'notif-office-'));
  const appDir = path.join(root, 'app');
  const dataFolder = path.join(root, 'data');
  fs.mkdirSync(appDir, { recursive: true });
  fs.mkdirSync(path.join(dataFolder, 'outbox', 'eyal'), { recursive: true });
  fs.mkdirSync(path.join(dataFolder, 'archive', '2026-09-01'), { recursive: true });
  fs.writeFileSync(path.join(appDir, 'config.json'),
    '﻿' + JSON.stringify({ data_folder: dataFolder, employee_name: 'eyal', poll_interval_seconds: 10 }),
    'utf8');
  if (options.template !== null) {
    fs.writeFileSync(
      path.join(dataFolder, 'outbox', 'eyal', 'm-1.json'),
      JSON.stringify(options.template || {
        id: 'm-1', to: 'eyal', type: 'task', title: 'לקוח כהן — מע״מ',
        body: 'להעביר דוח לכהן ושות׳ עד 15/9', created_at: '2026-09-01T08:00:00.000Z',
        status: 'pending', read: false, attachments: [], meta: { source: 'crm' },
      }, null, 2), 'utf8');
  }
  return { root, appDir, dataFolder };
}

const now = new Date(2026, 8, 6, 9, 5);
const arrival = { type: 'in', name: 'זילברברג ברינה', since: '09:04' };

// The config carries a BOM, as PowerShell-written files here do.
{
  const office = makeOffice();
  eq('the config is read through its BOM',
    readNotifierConfig(office.appDir),
    { dataFolder: office.dataFolder, employee: 'eyal' });
}

// The shape is copied from a message the notifier itself wrote. Guessing it
// would be the same mistake as guessing TimeWatch's query parameters.
{
  const office = makeOffice();
  const found = findTemplate(office.dataFolder, 'eyal');
  eq('a pending message is found as the template', path.basename(found.file), 'm-1.json');

  const message = buildPanelMessage(found.message, arrival, { employee: 'eyal', now, id: 'p-1' });
  eq('every field of the template is present',
    Object.keys(message).sort(), Object.keys(found.message).sort());
  eq('structural fields keep their values',
    [message.type, message.status, message.read], ['task', 'pending', false]);
  eq('the id and the recipient are ours', [message.id, message.to], ['p-1', 'eyal']);
  eq('the time is now', message.created_at, now.toISOString());
}

// A template carries someone's client. Copying its text into a new message
// would put that client in front of the wrong eyes.
{
  const office = makeOffice();
  const found = findTemplate(office.dataFolder, 'eyal');
  const message = buildPanelMessage(found.message, arrival, { employee: 'eyal', now });
  const serialised = JSON.stringify(message);
  eq('no text from the template survives',
    [/כהן/.test(serialised), /מע/.test(serialised)], [false, false]);
  eq('the alert says who arrived and from when',
    [message.title, message.body], ['נוכחות — כניסה', 'זילברברג ברינה נכנס/ה — מ־09:04']);
  eq('a departure drops the time',
    buildPanelMessage(found.message, { type: 'out', name: 'ברינה' }, { now }).body, 'ברינה יצא/ה');
  eq('nested values are emptied rather than copied',
    [message.attachments, message.meta], [[], {}]);
}

// With no template at all it still produces something the panel can read.
{
  const office = makeOffice({ template: null });
  const result = sendToPanel(arrival, { appDir: office.appDir, now, dryRun: true });
  eq('no template still yields a message', result.template, null);
  eq('and it carries the essentials',
    [typeof result.message.id, result.message.to, result.message.title],
    ['string', 'eyal', 'נוכחות — כניסה']);
}

// Writing into a folder ten people's notifiers read is not something to do
// by accident.
{
  const office = makeOffice();
  const dry = sendToPanel(arrival, { appDir: office.appDir, now, dryRun: true });
  eq('a dry run writes nothing',
    [dry.file, fs.readdirSync(path.join(office.dataFolder, 'outbox', 'eyal'))],
    [null, ['m-1.json']]);

  const sent = sendToPanel(arrival, { appDir: office.appDir, now, id: 'p-9' });
  eq('sending lands in the recipient outbox',
    path.relative(office.dataFolder, sent.file).split(path.sep), ['outbox', 'eyal', 'p-9.json']);
  eq('the panel can parse it',
    JSON.parse(fs.readFileSync(sent.file, 'utf8')).body, 'זילברברג ברינה נכנס/ה — מ־09:04');
  eq('no temp file is left behind',
    fs.readdirSync(path.join(office.dataFolder, 'outbox', 'eyal')).filter((f) => f.endsWith('.tmp')), []);
}

// Dropbox leaves these behind when the same identity writes from two
// machines; they are stale by definition.
{
  const office = makeOffice();
  const dir = path.join(office.dataFolder, 'outbox', 'eyal');
  fs.writeFileSync(path.join(dir, "m-1 (EYAL's conflicted copy 2026-09-01).json"),
    JSON.stringify({ id: 'x', title: 'stale', body: 'stale' }), 'utf8');
  eq('a conflicted copy is not a template',
    messagesUnder(dir).some((m) => /conflicted/i.test(m.file)), false);
}

// The first real alert came back as a message waiting for a reply, carrying a
// link to an unrelated service - both copied from the template. A presence
// alert is an announcement: it wants no answer and there is nothing to click.
{
  const office = makeOffice({ template: {
    id: 'msg-1', type: 'reminder', title: 'תזכורת', body: 'טקסט של מישהו',
    to: 'Eyal', from: 'שעון שעות', from_employee: null,
    created_at: '2026-09-03T21:02:37.000Z', auto_close_seconds: 45,
    expects_reply: true, reply_options: ['כן', 'לא'], link: 'http://EYAL:3020/',
  } });
  const found = findTemplate(office.dataFolder, 'eyal');
  const message = buildPanelMessage(found.message, arrival, { employee: 'Eyal', now, id: 'p-2' });

  eq('it does not ask for a reply',
    [message.expects_reply, message.reply_options], [false, []]);
  eq('it carries no link to somewhere else', message.link, '');
  eq('it says who it is from', message.from, 'נוכחות');
  eq('a null stays null rather than becoming a label', message.from_employee, null);
  eq('the type the panel knows is kept', message.type, 'reminder');
  eq('and the text is the alert', [message.title, message.body],
    ['נוכחות — כניסה', 'זילברברג ברינה נכנס/ה — מ־09:04']);
  eq('a key the template lacks is not invented', 'link' in buildPanelMessage(
    { id: 'x', title: 't', body: 'b' }, arrival, { now }), false);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
