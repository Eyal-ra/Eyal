'use strict';
/**
 * Show what the attendance page actually returns for one employee, so the
 * punch columns can be mapped against the real DOM instead of a replica.
 *
 * Prints the discovered filter fields and then every cell of the day's row
 * with its index. Times and a name, no credentials.
 *
 *   node dump-row.js [employeeId] [dd/mm/yyyy]
 */

const { loadConfig, discoverAttendance } = require('./timewatch-client');
const { discoverLoginForm, buildLoginBody } = require('./login-form');
const { buildAttendanceQuery } = require('./attendance-form');

async function readBody(res) {
  const m = /charset=([\w-]+)/i.exec(res.headers.get('content-type') || '');
  const charset = (m ? m[1] : 'windows-1255').toLowerCase();
  const buf = Buffer.from(await res.arrayBuffer());
  try { return new TextDecoder(charset).decode(buf); }
  catch { return new TextDecoder('windows-1255').decode(buf); }
}
const cookieHeader = (jar) => Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; ');
function collectCookies(res, jar) {
  const list = typeof res.headers.getSetCookie === 'function'
    ? res.headers.getSetCookie() : [res.headers.get('set-cookie')].filter(Boolean);
  for (const line of list) {
    const [pair] = line.split(';');
    const i = pair.indexOf('=');
    if (i > 0) jar[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
  }
}

async function login(cfg) {
  const jar = {};
  const url = cfg.baseUrl + cfg.loginPath;
  const page = await fetch(url, { signal: AbortSignal.timeout(cfg.requestTimeoutMs) });
  collectCookies(page, jar);
  const form = discoverLoginForm(await readBody(page));
  if (!form) throw new Error('no login form');
  const action = form.action ? new URL(form.action, url).toString() : url;
  const res = await fetch(action, {
    method: 'POST', body: buildLoginBody(form, cfg), redirect: 'manual',
    headers: { 'content-type': 'application/x-www-form-urlencoded', cookie: cookieHeader(jar), referer: url },
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
  });
  collectCookies(res, jar);
  await readBody(res);
  return jar;
}

const textOf = (h) => h.replace(/<[^>]*>/g, ' ').replace(/&nbsp;/gi, ' ').replace(/\s+/g, ' ').trim();
const CELL_RE = /<t[dh]\b[^>]*>[\s\S]*?<\/t[dh]>/gi;

async function main() {
  const cfg = loadConfig();
  const employeeId = process.argv[2] || (cfg.employees.find((e) => String(e.id).trim()) || {}).id;
  if (!employeeId) { console.log('usage: node dump-row.js <employeeId>'); return 1; }

  const arg = process.argv[3];
  const date = arg ? new Date(arg.split('/').reverse().join('-')) : new Date();

  const jar = await login(cfg);
  const attendance = await discoverAttendance(cfg, jar);

  console.log('\n=== discovered filter form ===');
  if (!attendance) {
    console.log('  none - falling back to ee/e/y/m');
  } else {
    console.log('  url      :', attendance.url);
    console.log('  employee :', attendance.form.employee);
    console.log('  year     :', attendance.form.year);
    console.log('  month    :', attendance.form.month);
    console.log('  fields   :', JSON.stringify(attendance.form.fields));
  }

  const y = date.getFullYear(), mo = date.getMonth() + 1, d = date.getDate();
  let url;
  if (attendance) {
    url = `${attendance.url}?${buildAttendanceQuery(attendance.form, { employeeId, year: y, month: mo })}`;
  } else {
    url = `${cfg.baseUrl}${cfg.attendancePath}?ee=${employeeId}&e=${cfg.company}&y=${y}&m=${mo}`;
  }
  console.log('\n=== request ===\n ', url);

  const res = await fetch(url, { headers: { cookie: cookieHeader(jar) }, signal: AbortSignal.timeout(cfg.requestTimeoutMs) });
  const html = await readBody(res);
  console.log('  HTTP', res.status, '|', html.length, 'chars');

  const rows = (html.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/gi) || [])
    .map((r) => (r.match(CELL_RE) || []).map(textOf));
  console.log('\n=== rows found ===\n ', rows.length);

  const dateRe = new RegExp(`(^|\\D)0?${d}[./-]0?${mo}[./-]\\d{4}`);
  const idx = rows.findIndex((cells) => cells.some((c) => dateRe.test(c)));

  if (idx === -1) {
    console.log(`\n  no row matched ${d}/${mo}/${y}. First 3 rows with any cells:`);
    rows.filter((r) => r.length).slice(0, 3).forEach((cells, i) =>
      console.log(`   row ${i}: ` + cells.map((c, j) => `[${j}] ${c || '-'}`).join(' | ')));
    return 1;
  }

  console.log(`\n=== today's row (${d}/${mo}/${y}) ===`);
  rows[idx].forEach((c, i) => console.log(`  [${i}] ${c || '(empty)'}`));

  console.log('\n=== a closed day above it, for comparison ===');
  for (let i = idx - 1; i >= 0 && i > idx - 6; i--) {
    if (rows[i].filter((c) => /^\d{1,2}:\d{2}$/.test(c)).length >= 2) {
      rows[i].forEach((c, j) => console.log(`  [${j}] ${c || '(empty)'}`));
      break;
    }
  }
  console.log('\nSend this output back - the [n] indices set punchOffsets.\n');
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => { console.error('\nerror:', e.message); process.exit(1); });
