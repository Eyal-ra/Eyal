'use strict';
/**
 * One-shot setup check. Run this on EYAL before touching the dashboard:
 *
 *   node verify-setup.js
 *
 * It walks the chain in order - config, login, fetch, parse - and stops at the
 * first broken link with a specific instruction, rather than a stack trace.
 *
 * Safe to paste the output anywhere: secrets are never printed, only whether
 * they are present and how long they are.
 */

const { loadConfig, getConnectedEmployees } = require('./timewatch-client');

const SECRETS_PATH = process.env.TIMEWATCH_CONFIG || 'C:\\OfficeSecrets\\timewatch.json';

const ok = (m) => console.log(`  \x1b[32mOK\x1b[0m    ${m}`);
const bad = (m, fix) => { console.log(`  \x1b[31mFAIL\x1b[0m  ${m}`); if (fix) console.log(`        \u2192 ${fix}`); };
const info = (m) => console.log(`        ${m}`);

/** Never print a secret - only that it is there and roughly how big. */
const shape = (v) => (v ? `set (${String(v).length} chars)` : 'MISSING');

async function main() {
  console.log('\n=== 1. \u05e7\u05d5\u05d1\u05e5 \u05d4\u05e7\u05d5\u05e0\u05e4\u05d9\u05d2 ===');
  let cfg;
  try {
    cfg = loadConfig();
    ok(`\u05e0\u05e7\u05e8\u05d0 \u05de\u05be${SECRETS_PATH}`);
  } catch (err) {
    if (err.code === 'ENOENT') {
      bad(`\u05d4\u05e7\u05d5\u05d1\u05e5 \u05dc\u05d0 \u05e7\u05d9\u05d9\u05dd: ${SECRETS_PATH}`,
        '\u05d4\u05e2\u05ea\u05e7 \u05d0\u05ea config.example.json \u05dc\u05e9\u05dd \u05d5\u05de\u05dc\u05d0 \u05d0\u05ea \u05d4\u05e4\u05e8\u05d8\u05d9\u05dd');
    } else {
      bad(`\u05d4\u05e7\u05d5\u05d1\u05e5 \u05dc\u05d0 \u05e0\u05e7\u05e8\u05d0: ${err.message}`, '\u05d1\u05d3\u05d5\u05e7 \u05e9\u05d4\u05beJSON \u05ea\u05e7\u05d9\u05df');
    }
    return 1;
  }

  info(`company:   ${shape(cfg.company)}`);
  info(`adminUser: ${shape(cfg.adminUser)}`);
  info(`password:  ${shape(cfg.password)}`);
  info(`baseUrl:   ${cfg.baseUrl}`);

  const placeholders = ['COMPANY_NUMBER', 'ADMIN_EMPLOYEE_NUMBER', 'ADMIN_PASSWORD'];
  const stillTemplate = [cfg.company, cfg.adminUser, cfg.password]
    .filter((v) => placeholders.includes(String(v)));
  if (stillTemplate.length) {
    bad(`${stillTemplate.length} \u05e9\u05d3\u05d5\u05ea \u05e2\u05d3\u05d9\u05d9\u05df \u05de\u05db\u05d9\u05dc\u05d9\u05dd \u05d0\u05ea \u05e2\u05e8\u05db\u05d9 \u05d4\u05ea\u05d1\u05e0\u05d9\u05ea`,
      '\u05de\u05dc\u05d0 \u05d0\u05ea \u05d4\u05e2\u05e8\u05db\u05d9\u05dd \u05d4\u05d0\u05de\u05d9\u05ea\u05d9\u05d9\u05dd \u05d1\u05de\u05e7\u05d5\u05dd COMPANY_NUMBER / ADMIN_EMPLOYEE_NUMBER / ADMIN_PASSWORD');
    return 1;
  }
  ok('\u05db\u05dc \u05e9\u05d3\u05d5\u05ea \u05d4\u05d7\u05d5\u05d1\u05d4 \u05de\u05dc\u05d0\u05d9\u05dd');

  const unset = cfg.employees.filter((e) => String(e.id) === '0');
  if (unset.length) {
    bad(`${unset.length} \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05e2\u05dd id=0: ${unset.map((e) => e.name).join(', ')}`,
      "\u05de\u05dc\u05d0 \u05d0\u05ea \u05de\u05e1\u05e4\u05e8\u05d9 \u05d4\u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05de\u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5\u05f3 (\u05de\u05e1' \u05e2\u05d5\u05d1\u05d3, \u05db\u05de\u05d5 43)");
  } else {
    ok(`${cfg.employees.length} \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05e2\u05dd \u05de\u05e1\u05e4\u05e8\u05d9\u05dd`);
  }

  console.log('\n=== 2. \u05e8\u05e9\u05ea ===');
  try {
    const res = await fetch(cfg.baseUrl, { signal: AbortSignal.timeout(15000) });
    // A reply is not the same as reaching TimeWatch: a blocking proxy answers
    // too, usually 403/407. Treating that as "reachable" would send you
    // hunting for a credentials bug that isn't there.
    if (res.status === 403 || res.status === 407) {
      bad(`${cfg.baseUrl} \u05d4\u05d7\u05d6\u05d9\u05e8 HTTP ${res.status} \u2014 \u05db\u05e0\u05e8\u05d0\u05d4 \u05d7\u05e1\u05d9\u05de\u05ea \u05e8\u05e9\u05ea, \u05dc\u05d0 \u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5\u05f3`,
        '\u05d4\u05e8\u05e5 \u05d0\u05ea \u05d6\u05d4 \u05e2\u05dc EYAL. \u05d1\u05e1\u05d1\u05d9\u05d1\u05d4 \u05de\u05e8\u05d5\u05d7\u05e7\u05ea \u05d4\u05d3\u05d5\u05de\u05d9\u05d9\u05df \u05d7\u05e1\u05d5\u05dd \u05d5\u05e9\u05d5\u05dd \u05e1\u05d9\u05e1\u05de\u05d4 \u05dc\u05d0 \u05ea\u05e2\u05d6\u05d5\u05e8');
      return 1;
    }
    if (!res.ok && res.status >= 500) {
      bad(`${cfg.baseUrl} \u05d4\u05d7\u05d6\u05d9\u05e8 HTTP ${res.status}`, '\u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5\u05f3 \u05db\u05e0\u05e8\u05d0\u05d4 \u05dc\u05de\u05d8\u05d4. \u05e0\u05e1\u05d4 \u05e9\u05d5\u05d1 \u05de\u05d0\u05d5\u05d7\u05e8 \u05d9\u05d5\u05ea\u05e8');
      return 1;
    }
    ok(`${cfg.baseUrl} \u05e0\u05d2\u05d9\u05e9 (HTTP ${res.status})`);
  } catch (err) {
    bad(`${cfg.baseUrl} \u05dc\u05d0 \u05e0\u05d2\u05d9\u05e9: ${err.message}`,
      '\u05d4\u05e8\u05e5 \u05d0\u05ea \u05d6\u05d4 \u05e2\u05dc EYAL, \u05dc\u05d0 \u05de\u05e1\u05d1\u05d9\u05d1\u05d4 \u05de\u05e8\u05d5\u05d7\u05e7\u05ea');
    return 1;
  }

  console.log('\n=== 3. \u05dc\u05d5\u05d2\u05d9\u05df ===');
  let result;
  try {
    result = await getConnectedEmployees({ config: cfg });
    ok(`\u05d4\u05dc\u05d5\u05d2\u05d9\u05df \u05e2\u05d1\u05e8 (${cfg.baseUrl}${cfg.loginPath})`);
  } catch (err) {
    bad(`\u05d4\u05dc\u05d5\u05d2\u05d9\u05df \u05e0\u05db\u05e9\u05dc: ${err.message}`,
      '\u05e4\u05ea\u05d7 \u05d0\u05ea \u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5\u05f3 \u05d1\u05db\u05e8\u05d5\u05dd, F12 \u2192 Network, \u05d4\u05ea\u05d7\u05d1\u05e8, \u05d5\u05d4\u05e9\u05d5\u05d5\u05d4 \u05d0\u05ea \u05d4\u05beURL \u05d5\u05e9\u05de\u05d5\u05ea \u05d4\u05e9\u05d3\u05d5\u05ea \u05e9\u05dc \u05d4\u05d1\u05e7\u05e9\u05d4 \u05de\u05d5\u05dc loginPath \u05d1\u05e7\u05d5\u05e0\u05e4\u05d9\u05d2');
    return 1;
  }

  console.log('\n=== 4. \u05e7\u05e8\u05d9\u05d0\u05ea \u05e0\u05d5\u05db\u05d7\u05d5\u05ea ===');
  if (result.errors.length) {
    bad(`${result.errors.length} \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05dc\u05d0 \u05e0\u05e7\u05e8\u05d0\u05d5`);
    result.errors.slice(0, 3).forEach((e) => info(`${e.name}: ${e.error}`));
    info('\u05d0\u05dd \u05db\u05d5\u05dc\u05dd \u05e0\u05db\u05e9\u05dc\u05d5 \u2014 attendancePath \u05d0\u05d5 \u05d4\u05e4\u05e8\u05de\u05d8\u05e8\u05d9\u05dd \u05e9\u05d2\u05d5\u05d9\u05d9\u05dd (F12 \u2192 Network \u05e2\u05dc update.php)');
  }
  const read = result.connected.length + result.away.length;
  if (read === 0) {
    bad('\u05d0\u05e3 \u05e2\u05d5\u05d1\u05d3 \u05dc\u05d0 \u05e0\u05e7\u05e8\u05d0', '\u05e8\u05d0\u05d4 \u05d4\u05e9\u05d2\u05d9\u05d0\u05d5\u05ea \u05dc\u05de\u05e2\u05dc\u05d4');
    return 1;
  }
  ok(`${read} \u05e2\u05d5\u05d1\u05d3\u05d9\u05dd \u05e0\u05e7\u05e8\u05d0\u05d5`);

  console.log('\n=== 5. \u05d4\u05ea\u05d5\u05e6\u05d0\u05d4 ===');
  if (result.connected.length === 0) {
    info('\u05d0\u05e3 \u05d0\u05d7\u05d3 \u05dc\u05d0 \u05de\u05e1\u05d5\u05de\u05df \u05db\u05e0\u05d5\u05db\u05d7 \u05db\u05e8\u05d2\u05e2.');
    info('\u05d0\u05dd \u05d6\u05d4 \u05dc\u05d0 \u05e0\u05db\u05d5\u05df \u2014 \u05db\u05e0\u05e8\u05d0\u05d4 punchOffsets \u05e9\u05d2\u05d5\u05d9. \u05e4\u05ea\u05d7 \u05d0\u05ea update.php,');
    info('\u05e1\u05e4\u05d5\u05e8 \u05d1\u05d0\u05d9\u05d6\u05d4 \u05ea\u05d0 \u05d9\u05d5\u05e9\u05d1\u05d5\u05ea \u05d4\u05db\u05e0\u05d9\u05e1\u05d4 \u05d5\u05d4\u05d9\u05e6\u05d9\u05d0\u05d4, \u05d5\u05e2\u05d3\u05db\u05df \u05d1\u05e7\u05d5\u05e0\u05e4\u05d9\u05d2.');
  } else {
    result.connected.forEach((e) => info(`\u05e0\u05d5\u05db\u05d7: ${e.name} \u2014 \u05de\u05be${e.since} (${e.minutes} \u05d3\u05e7')`));
  }
  if (result.away.length) {
    info(`\u05dc\u05d0 \u05e0\u05d5\u05db\u05d7\u05d9\u05dd: ${result.away.map((e) => e.name).join(', ')}`);
  }

  console.log('\n\u05d4\u05e9\u05d5\u05d5\u05d4 \u05de\u05d5\u05dc \u05d8\u05d9\u05d9\u05dd \u05d5\u05d5\u05d8\u05e5\u05f3 \u05d1\u05d3\u05e4\u05d3\u05e4\u05df. \u05ea\u05d5\u05d0\u05dd \u2192 \u05de\u05d5\u05db\u05df \u05dc\u05d4\u05d8\u05de\u05e2\u05d4.\n');
  return 0;
}

main().then((code) => process.exit(code)).catch((err) => {
  console.error('\n\u05e9\u05d2\u05d9\u05d0\u05d4 \u05dc\u05d0 \u05e6\u05e4\u05d5\u05d9\u05d4:', err.message);
  process.exit(1);
});
