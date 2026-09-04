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
  discoverAttendanceForm, buildAttendanceQuery, discoverEmployees,
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
  const pageRes = await fetch(loginUrl, { signal: AbortSignal.timeout(cfg.requestTimeoutMs) });
  if (!pageRes.ok) throw new Error(`login page ${pageRes.status} at ${loginUrl}`);
  collectCookies(pageRes, jar);
  const form = discoverLoginForm(await readBody(pageRes));
  if (!form) throw new Error(`no login form found at ${loginUrl} - check TIMEWATCH_LOGIN_PATH`);

  const action = form.action
    ? new URL(form.action, loginUrl).toString()
    : loginUrl;

  const res = await fetch(action, {
    method: 'POST',
    body: buildLoginBody(form, cfg),
    headers: {
      'content-type': 'application/x-www-form-urlencoded',
      cookie: cookieHeader(jar),
      referer: loginUrl,
    },
    redirect: 'manual',
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
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
  const punchOffsets = offsets || PUNCH_OFFSETS;
  const day = date.getDate();
  const month = date.getMonth() + 1;
  // The page writes dates as "\u05d3 02-09-2026"; allow ./- and an optional zero.
  const dateRe = new RegExp(`(^|\\D)0?${day}[./-]0?${month}[./-]\\d{4}`);

  for (const cells of rowsWithCells(html)) {
    const dateIdx = cells.findIndex((c) => dateRe.test(c));
    if (dateIdx === -1) continue;

    const pairs = [];
    for (const [e, x] of punchOffsets) {
      const entry = timeAt(cells, dateIdx + e);
      const exit = timeAt(cells, dateIdx + x);
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
  const res = await fetch(url, {
    headers: { cookie: cookieHeader(jar) },
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
  });
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

async function fetchEmployeeMonth(cfg, jar, employeeId, date, attendance) {
  const year = date.getFullYear();
  const month = date.getMonth() + 1;

  let url;
  if (attendance) {
    const params = buildAttendanceQuery(attendance.form, { employeeId, year, month });
    url = `${attendance.url}?${params}`;
  } else {
    // Nothing to learn from - fall back to the parameters the employee
    // portal uses, which is all there was before discovery.
    const params = new URLSearchParams({
      ee: String(employeeId), e: String(cfg.company),
      y: String(year), m: String(month), ...(cfg.extraParams || {}),
    });
    url = `${cfg.baseUrl}${cfg.attendancePath}?${params}`;
  }
  return getPage(cfg, jar, url);
}

function minutesSince(hhmm, now) {
  const [h, m] = hhmm.split(':').map(Number);
  const start = new Date(now);
  start.setHours(h, m, 0, 0);
  return Math.max(0, Math.round((now - start) / 60000));
}

/**
 * @returns {Promise<{fetchedAt:string, connected:Array, away:Array, errors:Array}>}
 */
async function getConnectedEmployees(options = {}) {
  const cfg = options.config || loadConfig();
  const now = options.now || new Date();
  const jar = await login(cfg);
  // One extra request, shared by every employee below.
  const attendance = await discoverAttendance(cfg, jar).catch(() => null);

  // The portal's own roster is authoritative; employees.json is only a
  // fallback for when discovery fails, and for who to raise alerts about.
  const roster = attendance && attendance.employees.length
    ? attendance.employees : cfg.employees;

  const connected = [];
  const away = [];
  const errors = [];

  const results = await Promise.allSettled(
    roster.map(async (emp) => {
      const html = await fetchEmployeeMonth(cfg, jar, emp.id, now, attendance);
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
  return { fetchedAt: now.toISOString(), connected, away, errors };
}

module.exports = {
  getConnectedEmployees, loadConfig, extractDayPunches, minutesSince, parseEnv,
  discoverAttendance, PUNCH_OFFSETS, rowsWithCells,
};
