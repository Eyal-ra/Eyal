'use strict';
/**
 * Find out how the attendance page wants to be asked.
 *
 * The filter form is discovered and the report requested four ways - GET and
 * POST, with and without the form's own submit button - and each answer is
 * measured the only way that matters: does it contain rows carrying a date.
 *
 * This exists because a request that returns the filter form and no report
 * looks exactly like a request that returns an empty report. Guessing between
 * GET and POST one round-trip at a time costs a person a screenshot each time;
 * asking all four at once costs one.
 *
 *   node probe.js [name or number] [dd/mm/yyyy]
 *
 * Prints times, names and URLs. No credentials.
 */

const { loadConfig, rowsWithCells, REQUEST_PLANS } = require('./timewatch-client');
const { discoverLoginForm, buildLoginBody } = require('./login-form');
const {
  discoverAttendanceForm, buildAttendanceQuery, buildAttendanceQueryWithSubmit,
  discoverEmployees,
} = require('./attendance-form');

const TIMEOUT = 20000;

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
  const page = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT) });
  collectCookies(page, jar);
  const form = discoverLoginForm(await readBody(page));
  if (!form) throw new Error('no login form');
  const action = form.action ? new URL(form.action, url).toString() : url;
  const res = await fetch(action, {
    method: 'POST', body: buildLoginBody(form, cfg), redirect: 'manual',
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
      cookie: cookieHeader(jar), referer: url,
    },
    signal: AbortSignal.timeout(TIMEOUT),
  });
  collectCookies(res, jar);
  await readBody(res);
  return jar;
}

const attr = (tag, name) => {
  const m = new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i').exec(tag);
  return m ? (m[2] ?? m[3] ?? m[4] ?? null) : null;
};

/** Links that could be the report itself, in case it lives elsewhere. */
function phpLinks(html) {
  const seen = new Set();
  for (const tag of html.match(/<a\b[^>]*href\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi) || []) {
    const href = attr(tag, 'href');
    if (href && /\.php\?/i.test(href) && !/logout|login/i.test(href)) seen.add(href);
  }
  return [...seen];
}

const datedRows = (html) => rowsWithCells(html)
  .filter((cells) => cells.some((c) => /\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b/.test(c)));

async function attempt(label, url, method, params, jar) {
  const opts = { headers: { cookie: cookieHeader(jar) }, signal: AbortSignal.timeout(TIMEOUT) };
  let target = url;
  if (method === 'post') {
    opts.method = 'POST';
    opts.body = params.toString();
    opts.headers['content-type'] = 'application/x-www-form-urlencoded';
  } else {
    target = `${url}?${params}`;
  }
  try {
    const res = await fetch(target, opts);
    const html = await readBody(res);
    const rows = rowsWithCells(html);
    const dated = datedRows(html);
    return { label, ok: res.ok, status: res.status, chars: html.length,
             rows: rows.length, dated: dated.length, html, sample: dated[0] || null };
  } catch (err) {
    return { label, error: err.message, rows: 0, dated: 0 };
  }
}

async function main() {
  const cfg = loadConfig();
  const arg = process.argv[3];
  const date = arg ? new Date(arg.split('/').reverse().join('-')) : new Date();
  const year = date.getFullYear(), month = date.getMonth() + 1, day = date.getDate();

  const jar = await login(cfg);
  const pageUrl = cfg.baseUrl + cfg.attendancePath;
  const page = await fetch(pageUrl, { headers: { cookie: cookieHeader(jar) }, signal: AbortSignal.timeout(TIMEOUT) });
  const html = await readBody(page);

  const form = discoverAttendanceForm(html);
  if (!form) { console.log('no filter form on ' + pageUrl); return 1; }
  const url = form.action ? new URL(form.action, pageUrl).toString() : pageUrl;

  const roster = discoverEmployees(html);
  const wanted = process.argv[2];
  const match = wanted
    ? roster.find((e) => e.id === wanted || e.number === wanted || e.name.includes(wanted))
    : roster[0];
  const employeeId = match ? match.id : wanted;
  if (!employeeId) { console.log('no employee to ask about'); return 1; }

  const submits = form.submits || {};

  console.log('=== the form ===');
  console.log('  action   :', url);
  console.log('  method   :', form.method, '(as the page declares it)');
  console.log('  employee :', (form.employeeFields || []).join(', '));
  console.log('  year/mon :', form.year, '/', form.month);
  console.log('  submits  :', Object.keys(submits).length ? JSON.stringify(submits) : '(none)');
  console.log('  asking   :', match ? `${match.name} id=${employeeId}` : employeeId,
              `for ${day}/${month}/${year}`);

  // Straight from the client's own list, so this can never report on a
  // request shape the client would not actually try.
  const options = { employeeId, year, month };
  const results = [];
  for (const plan of REQUEST_PLANS) {
    if (plan.submit && !Object.keys(submits).length) continue;
    const label = `${plan.method.toUpperCase()}${plan.submit ? ' + submit' : ''}`;
    const params = plan.submit
      ? buildAttendanceQueryWithSubmit(form, options)
      : buildAttendanceQuery(form, options);
    results.push(await attempt(label, url, plan.method, params, jar));
  }

  console.log('\n=== results ===');
  for (const r of results) {
    if (r.error) { console.log(`  ${r.label.padEnd(14)} error: ${r.error}`); continue; }
    console.log(`  ${r.label.padEnd(14)} HTTP ${r.status}  ${r.chars} chars  ` +
                `${r.rows} rows  ${r.dated} with a date`);
  }

  const winner = results.filter((r) => r.dated > 0).sort((a, b) => b.dated - a.dated)[0];

  if (winner) {
    console.log(`\n=== ${winner.label} returned a report ===`);
    const dated = datedRows(winner.html);
    const re = new RegExp(`(^|\\D)0?${day}[./-]0?${month}[./-]\\d{4}`);
    const today = dated.find((cells) => cells.some((c) => re.test(c)));
    const row = today || dated[dated.length - 1];
    console.log(today ? `  (today, ${day}/${month}/${year})` : '  (today is absent - showing the last dated row)');
    row.forEach((c, i) => console.log(`  [${i}] ${c || '(empty)'}`));
  } else {
    console.log('\n=== no variant returned a report ===');
    const links = phpLinks(html);
    if (links.length) {
      console.log('  Links on the page - the report may live at one of these:');
      links.slice(0, 15).forEach((l) => console.log('   ', l));
    } else {
      console.log('  No candidate links either.');
    }
  }

  console.log('\n=== the one line that matters ===');
  console.log(winner
    ? `  ${winner.label} works. Send the [n] indices above.`
    : '  None of GET/POST returned rows. Send this whole output.');
  console.log();
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => { console.error('\nerror:', e.message); process.exit(1); });
