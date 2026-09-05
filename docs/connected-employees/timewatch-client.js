'use strict';
/**
 * TimeWatch client - who is clocked in right now.
 *
 * Targets the employer portal at a.timewatch.co.il (the one the office
 * actually uses), not the employee-facing checkin.timewatch.co.il.
 *
 * Pure HTTP (no puppeteer / no browser window), so nothing has to be closed
 * afterwards. Global fetch only, zero npm dependencies.
 *
 * TimeWatch publishes no API, so both forms it needs - the login and the
 * attendance filter - are read off the page at run time rather than guessed.
 * See login-form.js and attendance-form.js.
 */

const fs = require('fs');
const path = require('path');
const { discoverLoginForm, buildLoginBody } = require('./login-form');
const {
  discoverAttendanceForm, buildAttendanceQuery, buildAttendanceQueryWithSubmit,
  discoverEmployees,
} = require('./attendance-form');

// Secrets live in a .env under C:\OfficeSecrets; everything else (employee
// numbers, who to alert on) is not secret and sits next to the code.
const ENV_PATH = process.env.TIMEWATCH_ENV || 'C:\\OfficeSecrets\\timewatch.env';
const SETTINGS_PATH = process.env.TIMEWATCH_SETTINGS || path.join(__dirname, 'employees.json');

/** Minimal .env reader - no dependency, and it must not choke on a password. */
function parseEnv(text) {
  const out = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq < 1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    // Quotes are stripped, so a password with a # or spaces survives intact.
    if (/^".*"$/.test(value) || /^'.*'$/.test(value)) value = value.slice(1, -1);
    out[key] = value;
  }
  return out;
}

function loadConfig(options = {}) {
  const envPath = options.envPath || ENV_PATH;
  const env = parseEnv(fs.readFileSync(envPath, 'utf8'));

  const cfg = {
    company: env.TIMEWATCH_COMPANY,
    username: env.TIMEWATCH_USER,
    password: env.TIMEWATCH_PASSWORD,
    baseUrl: (env.TIMEWATCH_BASE_URL || 'https://a.timewatch.co.il').replace(/\/+$/, ''),
    loginPath: env.TIMEWATCH_LOGIN_PATH || '/user/login.php',
    attendancePath: env.TIMEWATCH_ATTENDANCE_PATH || '/update.php',
    requestTimeoutMs: Number(env.TIMEWATCH_TIMEOUT_MS || 15000),
    employees: [],
    watchNames: [],
  };

  for (const key of ['company', 'username', 'password']) {
    if (!cfg[key]) throw new Error(`timewatch env: missing TIMEWATCH_${key.toUpperCase()} in ${envPath}`);
  }

  const settingsPath = options.settingsPath || SETTINGS_PATH;
  try {
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    cfg.employees = settings.employees || [];
    cfg.watchNames = settings.watchNames || [];
    if (settings.punchOffsets) cfg.punchOffsets = settings.punchOffsets;
  } catch (err) {
    if (err.code !== 'ENOENT') throw err;
  }
  return cfg;
}

/**
 * What actually went wrong.
 *
 * Node's fetch reports every network failure as the same three words -
 * "fetch failed" - and puts the reason in err.cause. Without it a DNS
 * failure, a refused connection and an expired certificate are one
 * indistinguishable message, which is a wasted round trip through a person
 * every time one happens.
 */
function describeError(err) {
  const cause = err && err.cause;
  if (!cause) return err ? err.message : String(err);
  const detail = cause.code || cause.message || String(cause);
  return detail && !err.message.includes(detail) ? `${err.message} (${detail})` : err.message;
}

// A network error is worth one more try; an HTTP answer is not - the server
// spoke, and asking again will not change its mind.
const TRANSIENT = new Set([
  'ETIMEDOUT', 'ECONNRESET', 'ECONNREFUSED', 'EAI_AGAIN', 'ENOTFOUND',
  'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_SOCKET', 'UND_ERR_HEADERS_TIMEOUT',
]);
const isTransient = (err) => Boolean(
  err && (err.name === 'TimeoutError' || TRANSIENT.has(err.code)
    || (err.cause && TRANSIENT.has(err.cause.code))));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * fetch with a short retry, because a single blip should not cost a poll.
 *
 * The poll runs every few minutes, so waiting a second and trying again is
 * cheaper than skipping a cycle - and skipping is not free: it delays the
 * alert this whole system exists to send.
 */
async function httpFetch(cfg, url, options = {}, attempts = 3) {
  const { retryDelayMs, ...init } = options;
  let last = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      // A fresh timeout each attempt: one made by the caller would already
      // have fired by the time the retry runs.
      return await fetch(url, { ...init, signal: AbortSignal.timeout(cfg.requestTimeoutMs) });
    } catch (err) {
      last = err;
      if (!isTransient(err) || attempt === attempts) break;
      await sleep(retryDelayMs ?? 200 * attempt);
    }
  }
  const error = new Error(`${url}: ${describeError(last)}`);
  error.cause = last;
  throw error;
}

/** TimeWatch serves legacy Hebrew pages; honour the declared charset. */
async function readBody(res) {
  const match = /charset=([\w-]+)/i.exec(res.headers.get('content-type') || '');
  const charset = (match ? match[1] : 'windows-1255').toLowerCase();
  const buf = Buffer.from(await res.arrayBuffer());
  try {
    return new TextDecoder(charset).decode(buf);
  } catch {
    return new TextDecoder('windows-1255').decode(buf);
  }
}

function cookieHeader(jar) {
  return Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; ');
}

function collectCookies(res, jar) {
  const list = typeof res.headers.getSetCookie === 'function'
    ? res.headers.getSetCookie()
    : [res.headers.get('set-cookie')].filter(Boolean);
  for (const line of list) {
    const [pair] = line.split(';');
    const idx = pair.indexOf('=');
    if (idx > 0) jar[pair.slice(0, idx).trim()] = pair.slice(idx + 1).trim();
  }
}

async function login(cfg) {
  const jar = {};
  const loginUrl = cfg.baseUrl + cfg.loginPath;

  // Read the form first: its field names are not documented, and a wrong
  // guess is indistinguishable from a wrong password.
  const pageRes = await httpFetch(cfg, loginUrl);
  if (!pageRes.ok) throw new Error(`login page ${pageRes.status} at ${loginUrl}`);
  collectCookies(pageRes, jar);
  const form = discoverLoginForm(await readBody(pageRes));
  if (!form) throw new Error(`no login form found at ${loginUrl} - check TIMEWATCH_LOGIN_PATH`);

  const action = form.action
    ? new URL(form.action, loginUrl).toString()
    : loginUrl;

  const res = await httpFetch(cfg, action, {
    method: 'POST',
    body: buildLoginBody(form, cfg),
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
      cookie: cookieHeader(jar),
      referer: loginUrl,
    },
    redirect: 'manual',
  });
  collectCookies(res, jar);

  // Being handed the login form again means the credentials bounced.
  const body = await readBody(res);
  if (discoverLoginForm(body) && res.status === 200) {
    throw new Error('login rejected - check company number, username and password');
  }
  if (Object.keys(jar).length === 0) {
    throw new Error('login returned no session cookie');
  }
  return jar;
}

/* ------------------------------------------------------------------ *
 * Parsing the attendance table (a.timewatch.co.il/update.php)
 * ------------------------------------------------------------------ */

/**
 * Column layout of one body row, left to right in the DOM (the page renders
 * it RTL):
 *
 *   date | work-day type | day name | standard hours
 *   | entry1 | exit1 | entry2 | exit2 | entry3 | exit3
 *   | absence reason | notes | total hours
 *
 * Offsets are relative to the date cell, so an extra leading column does not
 * shift the mapping. Both "standard hours" (9:06) and "total hours" (8:19)
 * read exactly like clock values, which is why punches are addressed by
 * position and never by "the times in this row".
 */
const PUNCH_OFFSETS = [[4, 5], [6, 7], [8, 9]];

const CELL_RE = /<t[dh]\b[^>]*>[\s\S]*?<\/t[dh]>/gi;
const EXACT_TIME_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

function textOf(html) {
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Split a table into rows and cells without requiring closing tags.
 *
 * The attendance page is old hand-written HTML that leaves <tr> and <td>
 * unclosed. Matching <tr>...</tr> found two rows in a 150KB page - the
 * filter bar, which happens to be well formed - and missed the attendance
 * table entirely. Splitting on the opening tags reads both.
 */
function rowsWithCells(html) {
  return html
    .split(/<tr\b[^>]*>/i)
    .slice(1)
    .map((row) => row
      .split(/<t[dh]\b[^>]*>/i)
      .slice(1)
      // A cell ends at its own closing tag if it has one, or at the next
      // cell or row, which the split already handled.
      .map((cell) => textOf(cell.replace(/<\/t[dh]>[\s\S]*$/i, ''))));
}

/**
 * The punch columns as the page's own header names them.
 *
 * Offsets from the date cell are a guess about layout; a header that says
 * "כניסה" and "יציאה" is the page stating it. When the header is
 * there it wins, because it also rules out the two columns that read like
 * clock times but are not punches - standard hours and the daily total.
 *
 * @returns {Array<[number, number]>|null} absolute [entry, exit] cell indices
 */
function punchColumnsFromHeader(html) {
  for (const cells of rowsWithCells(html)) {
    if (cells.length < 4) continue;
    const entries = [];
    const exits = [];
    cells.forEach((cell, i) => {
      // Anchored on the stem, so "שעת כניסה" and "כניסה 2" both count.
      if (/\u05db\u05e0\u05d9\u05e1/.test(cell) || /\bentry\b/i.test(cell)) entries.push(i);
      else if (/\u05d9\u05e6\u05d9\u05d0/.test(cell) || /\bexit\b/i.test(cell)) exits.push(i);
    });
    if (!entries.length || entries.length !== exits.length) continue;
    const pairs = entries.map((e, i) => [e, exits[i]]);
    // An exit column always sits to the right of the entry it closes; if it
    // does not, this row is prose about attendance, not a header.
    if (pairs.every(([e, x]) => x > e)) return pairs;
  }
  return null;
}

function timeAt(cells, index) {
  const value = (cells[index] || '').trim();
  return EXACT_TIME_RE.test(value) ? value : null;
}

/**
 * Read one day's punches.
 *
 * TimeWatch allows up to three entry/exit pairs a day, so someone who stepped
 * out and came back has two. Still clocked in means a pair has an entry and
 * no exit yet.
 */
function extractDayPunches(html, date, offsets) {
  const day = date.getDate();
  const month = date.getMonth() + 1;
  // The page writes dates as "\u05d3 02-09-2026"; allow ./- and an optional zero.
  const dateRe = new RegExp(`(^|\\D)0?${day}[./-]0?${month}[./-]\\d{4}`);

  // A configured override beats everything; then the page's own header; then
  // the layout seen on this account.
  const header = offsets ? null : punchColumnsFromHeader(html);
  const punchOffsets = offsets || PUNCH_OFFSETS;

  for (const cells of rowsWithCells(html)) {
    const dateIdx = cells.findIndex((c) => dateRe.test(c));
    if (dateIdx === -1) continue;

    const columns = header || punchOffsets.map(([e, x]) => [dateIdx + e, dateIdx + x]);
    const pairs = [];
    for (const [e, x] of columns) {
      const entry = timeAt(cells, e);
      const exit = timeAt(cells, x);
      if (entry || exit) pairs.push({ entry, exit });
    }
    const open = pairs.filter((p) => p.entry && !p.exit);
    return {
      found: true,
      pairs,
      connected: open.length > 0,
      since: open.length ? open[open.length - 1].entry : null,
      lastExit: pairs.length ? pairs[pairs.length - 1].exit : null,
    };
  }
  return { found: false, pairs: [], connected: false, since: null, lastExit: null };
}

/* ------------------------------------------------------------------ *
 * Fetching
 * ------------------------------------------------------------------ */

async function getPage(cfg, jar, url) {
  const res = await httpFetch(cfg, url, { headers: { cookie: cookieHeader(jar) } });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return readBody(res);
}

/**
 * Read the attendance page once and learn how to ask it for a given
 * employee and month.
 *
 * The alternative is hard-coding query parameters, and the ones inherited
 * from the employee portal are probably wrong here. Discovery also keeps
 * whatever the page's other filters (branch, department, role, view) are
 * already set to, instead of silently dropping them.
 */
async function discoverAttendance(cfg, jar) {
  const url = cfg.baseUrl + cfg.attendancePath;
  const html = await getPage(cfg, jar, url);
  const form = discoverAttendanceForm(html, {
    knownEmployeeId: cfg.employees.find((e) => String(e.id).trim())?.id,
  });
  if (!form || !form.year || !form.month) return null;
  return {
    form,
    url: form.action ? new URL(form.action, url).toString() : url,
    // The roster the portal itself lists, so nobody has to maintain one.
    employees: discoverEmployees(html),
  };
}

/**
 * The four ways this form could want to be submitted.
 *
 * A page that answers a wrong request with its own filter bar and no data
 * looks exactly like a page reporting an empty month, so the difference
 * cannot be reasoned out - only measured. Ordered by what a browser does
 * most often, so the common case is settled on the first try.
 */
const REQUEST_PLANS = [
  { method: 'get', submit: false },
  { method: 'post', submit: false },
  { method: 'get', submit: true },
  { method: 'post', submit: true },
];

const DATE_IN_CELL = /\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b/;
/** Did this answer carry a report, or just the filter bar again? */
const hasReport = (html) =>
  rowsWithCells(html).some((cells) => cells.some((c) => DATE_IN_CELL.test(c)));

async function requestReport(cfg, jar, attendance, plan, employeeId, date) {
  const options = { employeeId, year: date.getFullYear(), month: date.getMonth() + 1 };
  const params = plan.submit
    ? buildAttendanceQueryWithSubmit(attendance.form, options)
    : buildAttendanceQuery(attendance.form, options);

  if (plan.method === 'post') {
    const res = await httpFetch(cfg, attendance.url, {
      method: 'POST',
      body: params.toString(),
      headers: {
        'content-type': 'application/x-www-form-urlencoded',
        cookie: cookieHeader(jar),
        referer: attendance.url,
      },
    });
    if (!res.ok) throw new Error(`${attendance.url} returned ${res.status}`);
    return readBody(res);
  }
  return getPage(cfg, jar, `${attendance.url}?${params}`);
}

/**
 * Settle how the report wants to be asked for, once per run.
 *
 * The alternative is a person running a diagnostic and reporting back which
 * of four requests worked, which costs a round trip through a human for
 * something the code can measure in four requests of its own. The answer is
 * remembered on the discovery object, so the rest of the roster is fetched
 * with one request each.
 *
 * More than one employee is offered, because a single person with no punches
 * this month would otherwise look like a broken request.
 *
 * @returns {Promise<{plan:Object, employeeId:string, html:string}>} the
 *   winning plan and the page it produced, so that employee is not fetched
 *   twice.
 */
async function negotiateRequest(cfg, jar, attendance, employeeIds, date) {
  const tried = [];
  let last = null;
  const plans = REQUEST_PLANS.filter((plan) =>
    // A plan that would send no submit button is the same request as the one
    // before it, so skip it rather than spend a round trip proving that.
    !plan.submit || Object.keys(attendance.form.submits || {}).length);

  for (const employeeId of employeeIds) {
    for (const plan of plans) {
      const label = `${plan.method.toUpperCase()}${plan.submit ? ' + submit' : ''}`;
      try {
        const html = await requestReport(cfg, jar, attendance, plan, employeeId, date);
        last = html;
        if (hasReport(html)) return { plan, employeeId, html };
        const note = `${label}: no data rows`;
        if (!tried.includes(note)) tried.push(note);
      } catch (err) {
        tried.push(`${label}: ${err.message}`);
      }
    }
  }
  const error = new Error(`the report returned no data rows (tried ${tried.join('; ')})`);
  error.lastHtml = last;
  throw error;
}

async function fetchEmployeeMonth(cfg, jar, employeeId, date, attendance) {
  if (attendance) {
    return requestReport(cfg, jar, attendance, attendance.plan || REQUEST_PLANS[0],
      employeeId, date);
  }
  // Nothing to learn from - fall back to the parameters the employee portal
  // uses, which is all there was before discovery.
  const params = new URLSearchParams({
    ee: String(employeeId), e: String(cfg.company),
    y: String(date.getFullYear()), m: String(date.getMonth() + 1),
    ...(cfg.extraParams || {}),
  });
  return getPage(cfg, jar, `${cfg.baseUrl}${cfg.attendancePath}?${params}`);
}

function minutesSince(hhmm, now) {
  const [h, m] = hhmm.split(':').map(Number);
  const start = new Date(now);
  start.setHours(h, m, 0, 0);
  return Math.max(0, Math.round((now - start) / 60000));
}

/**
 * @returns {Promise<{fetchedAt:string, connected:Array, away:Array,
 *                    errors:Array, warning:string|null}>}
 */
async function getConnectedEmployees(options = {}) {
  const cfg = options.config || loadConfig();
  const now = options.now || new Date();
  // Both steps are injectable so the whole run can be exercised against a
  // local server, which is the only way to test the request negotiation.
  const jar = await (options.login || login)(cfg);
  // One extra request, shared by every employee below.
  const attendance = await (options.discover || discoverAttendance)(cfg, jar).catch(() => null);

  // The portal's own roster is authoritative; employees.json is only a
  // fallback for when discovery fails, and for who to raise alerts about.
  const roster = attendance && attendance.employees.length
    ? attendance.employees : cfg.employees;

  const connected = [];
  const away = [];
  const errors = [];

  // An empty roster reaches the same "nobody is in" as a working read of an
  // empty office, which is the one wrong answer that looks like a right one.
  if (!roster.length) {
    return {
      fetchedAt: now.toISOString(), connected: [], away: [], errors: [],
      warning: 'no employees found - the attendance page listed none and '
        + 'employees.json has none either',
    };
  }

  // Settle how the report wants to be asked for before asking seven times.
  let negotiated = null;
  let warning = null;
  if (attendance) {
    try {
      negotiated = await negotiateRequest(
        cfg, jar, attendance, roster.slice(0, 3).map((e) => e.id), now);
      attendance.plan = negotiated.plan;
    } catch (err) {
      // Reported rather than swallowed: an empty card that says nothing is
      // indistinguishable from an office where nobody has clocked in.
      warning = err.message;
    }
  }
  if (warning) {
    return { fetchedAt: now.toISOString(), connected: [], away: [], errors: [], warning };
  }

  const results = await Promise.allSettled(
    roster.map(async (emp) => {
      const html = negotiated && emp.id === negotiated.employeeId
        ? negotiated.html
        : await fetchEmployeeMonth(cfg, jar, emp.id, now, attendance);
      return extractDayPunches(html, now, cfg.punchOffsets);
    })
  );

  results.forEach((result, i) => {
    const emp = roster[i];
    if (result.status === 'rejected') {
      errors.push({ name: emp.name, error: String(result.reason?.message || result.reason) });
      return;
    }
    const day = result.value;
    if (day.connected) {
      connected.push({
        name: emp.name, since: day.since, minutes: minutesSince(day.since, now),
      });
    } else {
      away.push({ name: emp.name, lastExit: day.lastExit, punches: day.pairs.length });
    }
  });

  connected.sort((a, b) => b.minutes - a.minutes);
  return { fetchedAt: now.toISOString(), connected, away, errors, warning: null };
}

module.exports = {
  getConnectedEmployees, loadConfig, extractDayPunches, minutesSince, parseEnv,
  discoverAttendance, PUNCH_OFFSETS, rowsWithCells, punchColumnsFromHeader,
  describeError, isTransient, httpFetch,
  negotiateRequest, REQUEST_PLANS,
};
