'use strict';
/**
 * One-shot setup check. Run this on EYAL before touching the dashboard:
 *
 *   node verify-setup.js
 *
 * It walks the chain in order - config, network, login, fetch, parse - and
 * stops at the first broken link with the specific fix, rather than a stack
 * trace that could mean any of them.
 *
 * Safe to paste anywhere: secrets are reported as present-or-missing and a
 * length, never a value.
 */

const { loadConfig, getConnectedEmployees } = require('./timewatch-client');

const ENV_PATH = process.env.TIMEWATCH_ENV || 'C:\\OfficeSecrets\\timewatch.env';

// Colour is dropped when output is redirected to a file, so a saved report
// can be pasted somewhere without escape codes littering it.
const COLOR = process.stdout.isTTY && !process.env.NO_COLOR;
const green = (t) => (COLOR ? `\x1b[32m${t}\x1b[0m` : t);
const red = (t) => (COLOR ? `\x1b[31m${t}\x1b[0m` : t);

const ok = (m) => console.log(`  ${green('OK')}    ${m}`);
const bad = (m, fix) => { console.log(`  ${red('FAIL')}  ${m}`); if (fix) console.log(`        -> ${fix}`); };
const info = (m) => console.log(`        ${m}`);

/** Never print a secret - only that it is there and roughly how big. */
const shape = (v) => (v ? `\u05de\u05dc\u05d0 (${String(v).length} \u05ea\u05d5\u05d5\u05d9\u05dd)` : '\u05d7\u05e1\u05e8');

async function main() {
  console.log('\n=== 1. \u05d4\u05d2\u05d3\u05e8\u05d5\u05ea ===');
  let cfg;
  try {
    cfg = loadConfig();
    ok(`\u05e0\u05e7\u05e8\u05d0 \u05de\u05be${ENV_PATH}`);
  } catch (err) {
    if (err.code === 'ENOENT') {
      bad(`\u05d4\u05e7\u05d5\u05d1\u05e5 \u05dc\u05d0 \u05e7\u05d9\u05d9\u05dd: ${ENV_PATH}`, '\u05d4\u05e2\u05ea\u05e7 \u05dc\u05e9\u05dd \u05d0\u05ea timewatch.env.example \u05d5\u05de\u05dc\u05d0 \u05d0\u05ea \u05d4\u05e1\u05d9\u05e1\u05de\u05d4');
    } else if (/missing TIMEWATCH_/.test(err.message)) {
      const key = (/missing (TIMEWATCH_\w+)/.exec(err.message) || [])[1];
      bad(`${key} \u05e8\u05d9\u05e7 \u05d0\u05d5 \u05d7\u05e1\u05e8`, `\u05de\u05dc\u05d0 \u05d0\u05ea ${key} \u05d1\u05be${ENV_PATH}`);
    } else {
      bad(`\u05d4\u05e7\u05d5\u05d1\u05e5 \u05dc\u05d0 \u05e0\u05e7\u05e8\u05d0: ${err.message}`, '\u05d1\u05d3\u05d5\u05e7 \u05d0\u05ea \u05de\u05d1\u05e0\u05d4 \u05d4\u05e7\u05d5\u05d1\u05e5');
    }
    return 1;
  }

  info(`\u05de\u05e1\u05e4\u05e8 \u05d7\u05d1\u05e8\u05d4: ${shape(cfg.company)}`);
  info(`\u05e9\u05dd \u05de\u05e9\u05ea\u05de\u05e9:  ${cfg.username}`);
  info(`\u05e1\u05d9\u05e1\u05de\u05d4:     ${shape(cfg.password)}`);
  info(`\u05db\u05ea\u05d5\u05d1\u05ea:     ${cfg.baseUrl}${cfg.loginPath}`);
  ok('\u05db\u05dc \u05e9\u05d3\u05d5\u05ea \u05d4\u05d7\u05d5\u05d1\u05d4 \u05de\u05dc\u05d0\u05d9\u05dd');

  // The roster now comes from the portal's own employee picker, so there is
  // nothing to fill in by hand and nothing to go stale when someone joins.
  info('\u05e8\u05e9\u05d9\u05de\u05ea \u05d4\u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05e0\u05e7\u05e8\u05d0\u05ea \u05de\u05d4\u05e4\u05d5\u05e8\u05d8\u05dc \u05e2\u05e6\u05de\u05d5 \u2014 \u05d0\u05d9\u05df \u05de\u05d4 \u05dc\u05de\u05dc\u05d0 \u05d9\u05d3\u05e0\u05d9\u05ea');
  if (cfg.watchNames.length) {
    info(`\u05d4\u05ea\u05e8\u05d0\u05d5\u05ea \u05e2\u05dc: ${cfg.watchNames.join(', ')}`);
  } else {
    info('\u05d0\u05d9\u05df \u05e9\u05de\u05d5\u05ea \u05d1-watchNames \u2014 \u05dc\u05d0 \u05d9\u05d9\u05e9\u05dc\u05d7\u05d5 \u05d4\u05ea\u05e8\u05d0\u05d5\u05ea');
  }

  console.log('\n=== 2. \u05e8\u05e9\u05ea ===');
  try {
    const res = await fetch(cfg.baseUrl, { signal: AbortSignal.timeout(15000) });
    // A reply is not the same as reaching TimeWatch: a blocking proxy answers
    // too, usually 403/407. Calling that "reachable" would send you hunting
    // for a credentials bug that isn't there.
    if (res.status === 403 || res.status === 407) {
      bad(`${cfg.baseUrl} \u05d4\u05d7\u05d6\u05d9\u05e8 HTTP ${res.status} \u2014 \u05d7\u05e1\u05d9\u05de\u05ea \u05e8\u05e9\u05ea, \u05dc\u05d0 \u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5'`,
        '\u05d4\u05e8\u05e5 \u05d0\u05ea \u05d6\u05d4 \u05e2\u05dc EYAL. \u05d1\u05e1\u05d1\u05d9\u05d1\u05d4 \u05de\u05e8\u05d5\u05d7\u05e7\u05ea \u05d4\u05d3\u05d5\u05de\u05d9\u05d9\u05df \u05d7\u05e1\u05d5\u05dd \u05d5\u05e9\u05d5\u05dd \u05e1\u05d9\u05e1\u05de\u05d4 \u05dc\u05d0 \u05ea\u05e2\u05d6\u05d5\u05e8');
      return 1;
    }
    if (res.status >= 500) {
      bad(`${cfg.baseUrl} \u05d4\u05d7\u05d6\u05d9\u05e8 HTTP ${res.status}`, "\u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5' \u05db\u05e0\u05e8\u05d0\u05d4 \u05dc\u05de\u05d8\u05d4. \u05e0\u05e1\u05d4 \u05e9\u05d5\u05d1 \u05de\u05d0\u05d5\u05d7\u05e8 \u05d9\u05d5\u05ea\u05e8");
      return 1;
    }
    ok(`${cfg.baseUrl} \u05e0\u05d2\u05d9\u05e9 (HTTP ${res.status})`);
  } catch (err) {
    bad(`${cfg.baseUrl} \u05dc\u05d0 \u05e0\u05d2\u05d9\u05e9: ${err.message}`, '\u05d4\u05e8\u05e5 \u05d0\u05ea \u05d6\u05d4 \u05e2\u05dc EYAL, \u05dc\u05d0 \u05de\u05e1\u05d1\u05d9\u05d1\u05d4 \u05de\u05e8\u05d5\u05d7\u05e7\u05ea');
    return 1;
  }

  console.log('\n=== 3. \u05dc\u05d5\u05d2\u05d9\u05df ===');
  let result;
  try {
    result = await getConnectedEmployees({ config: cfg });
    ok('\u05d4\u05dc\u05d5\u05d2\u05d9\u05df \u05e2\u05d1\u05e8');
  } catch (err) {
    bad(`\u05d4\u05dc\u05d5\u05d2\u05d9\u05df \u05e0\u05db\u05e9\u05dc: ${err.message}`);
    if (/no login form/.test(err.message)) {
      info(`\u05d4\u05d3\u05e3 \u05d1\u05be${cfg.loginPath} \u05dc\u05d0 \u05de\u05db\u05d9\u05dc \u05d8\u05d5\u05e4\u05e1 \u05e2\u05dd \u05e9\u05d3\u05d4 \u05e1\u05d9\u05e1\u05de\u05d4.`);
      info('\u05d1\u05d3\u05d5\u05e7 \u05d0\u05ea TIMEWATCH_LOGIN_PATH \u05d1\u05e7\u05d5\u05d1\u05e5 \u05d4-env.');
    } else if (/rejected/.test(err.message)) {
      info("\u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5' \u05d4\u05d7\u05d6\u05d9\u05e8 \u05d0\u05ea \u05d8\u05d5\u05e4\u05e1 \u05d4\u05dc\u05d5\u05d2\u05d9\u05df \u2014 \u05de\u05e1\u05e4\u05e8 \u05d7\u05d1\u05e8\u05d4, \u05e9\u05dd \u05de\u05e9\u05ea\u05de\u05e9 \u05d0\u05d5 \u05e1\u05d9\u05e1\u05de\u05d4 \u05e9\u05d2\u05d5\u05d9\u05d9\u05dd.");
    } else {
      info('\u05d0\u05dd \u05d6\u05d4 \u05d7\u05d5\u05d6\u05e8 \u2014 \u05e6\u05dc\u05dd \u05d0\u05ea \u05d4\u05e9\u05d2\u05d9\u05d0\u05d4 \u05d5\u05e9\u05dc\u05d7.');
    }
    return 1;
  }

  console.log('\n=== 4. \u05e7\u05e8\u05d9\u05d0\u05ea \u05e0\u05d5\u05db\u05d7\u05d5\u05ea ===');
  if (result.errors.length) {
    bad(`${result.errors.length} \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05dc\u05d0 \u05e0\u05e7\u05e8\u05d0\u05d5`);
    result.errors.slice(0, 3).forEach((e) => info(`${e.name}: ${e.error}`));
    info("\u05d0\u05dd \u05db\u05d5\u05dc\u05dd \u05e0\u05db\u05e9\u05dc\u05d5 \u2014 TIMEWATCH_ATTENDANCE_PATH \u05d0\u05d5 \u05d4\u05e4\u05e8\u05de\u05d8\u05e8\u05d9\u05dd \u05e9\u05d2\u05d5\u05d9\u05d9\u05dd");
  }
  if (result.warning) {
    bad('\u05d4\u05d3\u05d5\u05d7 \u05d7\u05d6\u05e8 \u05d1\u05dc\u05d9 \u05e9\u05d5\u05e8\u05d5\u05ea \u05e0\u05ea\u05d5\u05e0\u05d9\u05dd', '\u05e9\u05dc\u05d7 \u05d0\u05ea \u05d4\u05e9\u05d5\u05e8\u05d4 \u05d4\u05d1\u05d0\u05d4');
    info(result.warning);
    return 1;
  }
  const read = result.connected.length + result.away.length;
  if (read === 0) {
    bad('\u05d0\u05e3 \u05e2\u05d5\u05d1\u05d3 \u05dc\u05d0 \u05e0\u05e7\u05e8\u05d0', '\u05e8\u05d0\u05d4 \u05d4\u05e9\u05d2\u05d9\u05d0\u05d5\u05ea \u05dc\u05de\u05e2\u05dc\u05d4');
    return 1;
  }
  ok(`${read} \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05e0\u05e7\u05e8\u05d0\u05d5 \u05de\u05d4\u05e4\u05d5\u05e8\u05d8\u05dc`);

  console.log('\n=== 5. \u05d4\u05ea\u05d5\u05e6\u05d0\u05d4 ===');
  if (result.connected.length === 0) {
    info('\u05d0\u05e3 \u05d0\u05d7\u05d3 \u05dc\u05d0 \u05de\u05e1\u05d5\u05de\u05df \u05db\u05e0\u05d5\u05db\u05d7 \u05db\u05e8\u05d2\u05e2.');
    info('\u05d0\u05dd \u05d6\u05d4 \u05dc\u05d0 \u05e0\u05db\u05d5\u05df \u2014 \u05e4\u05ea\u05d7 \u05d0\u05ea \u05d3\u05e3 \u05d4\u05e0\u05d5\u05db\u05d7\u05d5\u05ea,');
    info('\u05e1\u05e4\u05d5\u05e8 \u05d1\u05d0\u05d9\u05d6\u05d4 \u05ea\u05d0 \u05d9\u05d5\u05e9\u05d1\u05d5\u05ea \u05d4\u05db\u05e0\u05d9\u05e1\u05d4 \u05d5\u05d4\u05d9\u05e6\u05d9\u05d0\u05d4, \u05d5\u05d4\u05d5\u05e1\u05e3 punchOffsets \u05dc-employees.json.');
  } else {
    result.connected.forEach((e) => info(`\u05e0\u05d5\u05db\u05d7: ${e.name} \u2014 \u05de\u05be${e.since} (${e.minutes} \u05d3\u05e7')`));
  }
  if (result.away.length) info(`\u05dc\u05d0 \u05e0\u05d5\u05db\u05d7\u05d9\u05dd: ${result.away.map((e) => e.name).join(', ')}`);

  console.log("\n\u05d4\u05e9\u05d5\u05d5\u05d4 \u05de\u05d5\u05dc \u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5' \u05d1\u05d3\u05e4\u05d3\u05e4\u05df. \u05ea\u05d5\u05d0\u05dd \u2192 \u05de\u05d5\u05db\u05df \u05dc\u05d4\u05d8\u05de\u05e2\u05d4.\n");
  return 0;
}

main().then((code) => process.exit(code)).catch((err) => {
  console.error('\n\u05e9\u05d2\u05d9\u05d0\u05d4 \u05dc\u05d0 \u05e6\u05e4\u05d5\u05d9\u05d4:', err.message);
  process.exit(1);
});
