'use strict';
/**
 * TimeWatch client - "who is still clocked in".
 *
 * Pure HTTP (no puppeteer / no browser window), so nothing has to be closed
 * afterwards. Node 24 global fetch only, zero npm dependencies.
 *
 * Verified endpoints (from public TimeWatch automation projects):
 *   POST /punch/punch2.php   fields: comp, name, pw   -> session cookie
 *   GET  /punch/editwh.php?ee=<employeeId>&e=<company>&y=<yyyy>&m=<m>
 *
 * The day-row column layout of editwh.php is the ONE part that must be
 * confirmed against the live account - see extractDayTimes() below.
 */

const fs = require('fs');

const SECRETS_PATH = process.env.TIMEWATCH_CONFIG || 'C:\\OfficeSecrets\\timewatch.json';

function loadConfig() {
  const raw = fs.readFileSync(SECRETS_PATH, 'utf8');
  const cfg = JSON.parse(raw);
  for (const key of ['company', 'adminUser', 'password']) {
    if (!cfg[key]) throw new Error(`timewatch config: missing "${key}" in ${SECRETS_PATH}`);
  }
  cfg.baseUrl = (cfg.baseUrl || 'https://checkin.timewatch.co.il').replace(/\/+$/, '');
  cfg.cacheSeconds = cfg.cacheSeconds ?? 60;
  cfg.requestTimeoutMs = cfg.requestTimeoutMs ?? 15000;
  cfg.employees = cfg.employees || [];
  return cfg;
}

/** TimeWatch still serves legacy Hebrew pages; honour the declared charset. */
async function readBody(res) {
  const contentType = res.headers.get('content-type') || '';
  const match = /charset=([\w-]+)/i.exec(contentType);
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
  const body = new URLSearchParams({
    comp: String(cfg.company),
    name: String(cfg.adminUser),
    pw: String(cfg.password),
  });
  const res = await fetch(`${cfg.baseUrl}/punch/punch2.php`, {
    method: 'POST',
    body,
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    redirect: 'manual',
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
  });
  collectCookies(res, jar);
  const html = await readBody(res);
  // TimeWatch renders the login form again (and the Hebrew word "אינך") on failure.
  if (/ixemplee/.test(html) === false && /אינך/.test(html)) {
    throw new Error('timewatch login rejected - check company/user/password');
  }
  if (Object.keys(jar).length === 0) {
    throw new Error('timewatch login returned no session cookie');
  }
  return jar;
}

/** Strip tags and decode the few entities TimeWatch emits. */
function textOf(html) {
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

const CELL_RE = /<t[dh]\b[^>]*>[\s\S]*?<\/t[dh]>/gi;
const EXACT_TIME_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

/** Cell indices in this row that hold a clock value and nothing else. */
function timeCellIndices(cells) {
  const out = [];
  cells.forEach((c, i) => { if (EXACT_TIME_RE.test(c)) out.push(i); });
  return out;
}

/**
 * Infer which columns are entry and exit.
 *
 * The month table also carries a total-hours column that reads exactly like a
 * clock value ("8:31"), so position - not order of appearance - decides. Fully
 * closed days (entry + exit + total) reveal the layout, so we take the two
 * lowest time-column indices from those rows and use the most common pair.
 * Returns null when the month has no closed day to learn from.
 */
function calibrateColumns(rowCells) {
  const votes = new Map();
  for (const cells of rowCells) {
    const idx = timeCellIndices(cells);
    if (idx.length < 3) continue; // need entry + exit + total to be sure
    const key = `${idx[0]},${idx[1]}`;
    votes.set(key, (votes.get(key) || 0) + 1);
  }
  let best = null;
  let bestCount = 0;
  for (const [key, count] of votes) {
    if (count > bestCount) { best = key; bestCount = count; }
  }
  return best ? best.split(',').map(Number) : null;
}

function rowsWithCells(html) {
  const rows = html.match(/<tr\b[^>]*>[\s\S]*?<\/tr>/gi) || [];
  return rows.map((row) => ({
    text: textOf(row),
    cells: (row.match(CELL_RE) || []).map(textOf),
  }));
}

/**
 * Pull the given day's row out of a monthly editwh.php page.
 *
 * An entry with an empty exit cell means the employee is still clocked in.
 * `timeCells` ([entryColumn, exitColumn]) from the config overrides the
 * calibration when a live page turns out to be laid out differently.
 */
function extractDayTimes(html, date, timeCells) {
  const day = date.getDate();
  const month = date.getMonth() + 1;
  const datePattern = new RegExp(`(^|\\D)0?${day}[./-]0?${month}[./-]`);
  const rows = rowsWithCells(html);

  const columns = Array.isArray(timeCells) && timeCells.length === 2
    ? timeCells
    : calibrateColumns(rows.map((r) => r.cells));

  for (const { text, cells } of rows) {
    if (!datePattern.test(text)) continue;
    if (columns) {
      const entry = EXACT_TIME_RE.test(cells[columns[0]] || '') ? cells[columns[0]] : null;
      const exit = EXACT_TIME_RE.test(cells[columns[1]] || '') ? cells[columns[1]] : null;
      return { entry, exit, found: true };
    }
    // No closed day to calibrate against: fall back to order of appearance.
    const idx = timeCellIndices(cells);
    return {
      entry: idx.length > 0 ? cells[idx[0]] : null,
      exit: idx.length > 1 ? cells[idx[1]] : null,
      found: true,
    };
  }
  return { entry: null, exit: null, found: false };
}

async function fetchEmployeeDay(cfg, jar, employeeId, date) {
  const url = `${cfg.baseUrl}/punch/editwh.php`
    + `?ee=${encodeURIComponent(employeeId)}`
    + `&e=${encodeURIComponent(cfg.company)}`
    + `&y=${date.getFullYear()}`
    + `&m=${date.getMonth() + 1}`;
  const res = await fetch(url, {
    headers: { cookie: cookieHeader(jar) },
    signal: AbortSignal.timeout(cfg.requestTimeoutMs),
  });
  if (!res.ok) throw new Error(`editwh.php ${res.status} for employee ${employeeId}`);
  return extractDayTimes(await readBody(res), date, cfg.timeCells);
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
    cfg.employees.map((emp) => fetchEmployeeDay(cfg, jar, emp.id, now))
  );

  results.forEach((result, i) => {
    const emp = cfg.employees[i];
    if (result.status === 'rejected') {
      errors.push({ name: emp.name, error: String(result.reason && result.reason.message || result.reason) });
      return;
    }
    const { entry, exit } = result.value;
    if (entry && !exit) {
      connected.push({ name: emp.name, since: entry, minutes: minutesSince(entry, now) });
    } else {
      away.push({ name: emp.name, entry: entry || null, exit: exit || null });
    }
  });

  connected.sort((a, b) => b.minutes - a.minutes);
  return { fetchedAt: now.toISOString(), connected, away, errors };
}

module.exports = { getConnectedEmployees, loadConfig, extractDayTimes, minutesSince };
