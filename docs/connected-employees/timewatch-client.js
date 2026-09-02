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
 * TimeWatch publishes no API, so the request shape lives in the config and
 * is captured once from the browser - see README, "לכידת הבקשה". The table
 * parsing below is the part that is pinned down and covered by tests.
 */

const fs = require('fs');

const SECRETS_PATH = process.env.TIMEWATCH_CONFIG || 'C:\\OfficeSecrets\\timewatch.json';

function loadConfig(path) {
  const cfg = JSON.parse(fs.readFileSync(path || SECRETS_PATH, 'utf8'));
  for (const key of ['company', 'adminUser', 'password']) {
    if (!cfg[key]) throw new Error(`timewatch config: missing "${key}"`);
  }
  cfg.baseUrl = (cfg.baseUrl || 'https://a.timewatch.co.il').replace(/\/+$/, '');
  cfg.loginPath = cfg.loginPath || '/punch/punch2.php';
  cfg.attendancePath = cfg.attendancePath || '/update.php';
  cfg.requestTimeoutMs = cfg.requestTimeoutMs ?? 15000;
  cfg.employees = cfg.employees || [];
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
  const res = await fetch(cfg.baseUrl + cfg.loginPath, {
    method: 'POST',
    body: new URLSearchParams({
      comp: String(cfg.company),
      name: String(cfg.adminUser),
      pw: String(cfg.password),
    }),
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    redirect: 'manual',
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
  });
  collectCookies(res, jar);
  if (Object.keys(jar).length === 0) {
    throw new Error('timewatch login returned no session cookie - check credentials and loginPath');
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

function rowsWithCells(html) {
  return (html.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/gi) || [])
    .map((row) => (row.match(CELL_RE) || []).map(textOf));
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
  // The page writes dates as "ד 02-09-2026"; allow ./- and an optional zero.
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

async function fetchEmployeeMonth(cfg, jar, employeeId, date) {
  const params = new URLSearchParams({
    ee: String(employeeId),
    e: String(cfg.company),
    y: String(date.getFullYear()),
    m: String(date.getMonth() + 1),
    ...(cfg.extraParams || {}),
  });
  const res = await fetch(`${cfg.baseUrl}${cfg.attendancePath}?${params}`, {
    headers: { cookie: cookieHeader(jar) },
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
  });
  if (!res.ok) throw new Error(`${cfg.attendancePath} ${res.status} for employee ${employeeId}`);
  return readBody(res);
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

  const connected = [];
  const away = [];
  const errors = [];

  const results = await Promise.allSettled(
    cfg.employees.map(async (emp) => {
      const html = await fetchEmployeeMonth(cfg, jar, emp.id, now);
      return extractDayPunches(html, now, cfg.punchOffsets);
    })
  );

  results.forEach((result, i) => {
    const emp = cfg.employees[i];
    if (result.status === 'rejected') {
      errors.push({ name: emp.name, error: String(result.reason?.message || result.reason) });
      return;
    }
    const day = result.value;
    if (day.connected) {
      connected.push({ name: emp.name, since: day.since, minutes: minutesSince(day.since, now) });
    } else {
      away.push({ name: emp.name, lastExit: day.lastExit, punches: day.pairs.length });
    }
  });

  connected.sort((a, b) => b.minutes - a.minutes);
  return { fetchedAt: now.toISOString(), connected, away, errors };
}

module.exports = {
  getConnectedEmployees, loadConfig, extractDayPunches, minutesSince, PUNCH_OFFSETS,
};
