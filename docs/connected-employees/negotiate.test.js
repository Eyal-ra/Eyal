const http = require('http');
const { negotiateRequest, getConnectedEmployees, REQUEST_PLANS } = require('./timewatch-client.js');
const { discoverAttendanceForm } = require('./attendance-form.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

const FILTER_BAR = `<form action="/update.php" method="post">
  <select name="year"><option value=2026 selected>2026<option value=2025>2025</select>
  <select name="month"><option value=9 selected>09<option value=1>01<option value=2>02<option value=3>03
    <option value=4>04<option value=5>05<option value=6>06<option value=7>07<option value=8>08
    <option value=10>10<option value=11>11<option value=12>12</select>
  <select name="emplee_name"><option value=0 selected>---<option value=642214>זילברברג ברינה<option value=874747>דבח שלו</select>
  <select name="emplee_id"><option value=0 selected>---<option value=642214>34<option value=874747>43</select>
  <input type=submit name=go value="הצג">
</form>`;

const REPORT = `<table>
<tr><th>תאריך<th>יום<th>שעות תקן<th>כניסה<th>יציאה<th>כניסה<th>יציאה<th>סה"כ
<tr><td>ד 02-09-2026<td>רביעי<td>9:06<td>08:13<td>12:30<td>13:15<td><td>4:17
</table>`;

/** A server that answers anything but POST-with-the-button with the bare form. */
function startServer(accepts) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let body = '';
      req.on('data', (c) => { body += c; });
      req.on('end', () => {
        const query = req.url.includes('?') ? req.url.slice(req.url.indexOf('?') + 1) : '';
        const params = new URLSearchParams(req.method === 'POST' ? body : query);
        server.seen.push({ method: req.method, params: Object.fromEntries(params) });
        res.setHeader('content-type', 'text/html; charset=utf-8');
        res.end(FILTER_BAR + (accepts(req.method, params) ? REPORT : ''));
      });
    });
    server.seen = [];
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

const cfg = { requestTimeoutMs: 5000 };

async function attendanceFor(server) {
  const url = `http://127.0.0.1:${server.address().port}/update.php`;
  const form = discoverAttendanceForm(FILTER_BAR);
  return { form, url, employees: [{ id: '642214', name: 'זילברברג ברינה', number: '34' }] };
}

(async () => {
  // 1. Only POST carrying the submit button returns a report.
  {
    const server = await startServer((method, p) => method === 'POST' && p.get('go') === 'הצג');
    const attendance = await attendanceFor(server);
    const result = await negotiateRequest(cfg, {}, attendance, ['642214'], new Date(2026, 8, 2));
    eq('finds the plan the server actually accepts',
      [result.plan.method, result.plan.submit], ['post', true]);
    eq('and stops there', result.employeeId, '642214');
    eq('having tried the cheaper ones first',
      server.seen.map((s) => s.method), ['GET', 'POST', 'GET', 'POST']);
    server.close();
  }

  // 2. The common case costs one request, not four.
  {
    const server = await startServer((method) => method === 'GET');
    const attendance = await attendanceFor(server);
    const result = await negotiateRequest(cfg, {}, attendance, ['642214'], new Date(2026, 8, 2));
    eq('a plain GET is settled on the first try', result.plan.method, 'get');
    eq('one request, not four', server.seen.length, 1);
    server.close();
  }

  // 3. A person with no punches this month must not look like a broken request.
  {
    const server = await startServer((method, p) => p.get('emplee_name') === '874747');
    const attendance = await attendanceFor(server);
    const result = await negotiateRequest(
      cfg, {}, attendance, ['642214', '874747'], new Date(2026, 8, 2));
    eq('moves on to the next employee', result.employeeId, '874747');
    server.close();
  }

  // 4. When nothing works, say so - loudly and with what was tried.
  {
    const server = await startServer(() => false);
    const attendance = await attendanceFor(server);
    let message = null;
    try {
      await negotiateRequest(cfg, {}, attendance, ['642214'], new Date(2026, 8, 2));
    } catch (err) { message = err.message; }
    eq('reports failure rather than an empty office',
      /no data rows \(tried GET: no data rows; POST: no data rows/.test(message || ''), true);
    server.close();
  }

  // 5. End to end: the whole run reports a warning instead of "nobody is in".
  {
    const server = await startServer(() => false);
    const attendance = await attendanceFor(server);
    const result = await getConnectedEmployees({
      config: { ...cfg, employees: [], watchNames: [] },
      now: new Date(2026, 8, 2, 12, 0),
      login: async () => ({}),
      discover: async () => attendance,
    });
    eq('an unreadable report is a warning, not an empty office',
      [result.connected.length, result.away.length, /no data rows/.test(result.warning || '')],
      [0, 0, true]);
    server.close();
  }

  // 6. The whole chain on a server that behaves like the real one.
  {
    const server = await startServer((method, p) => method === 'POST' && p.get('go') === 'הצג');
    const attendance = await attendanceFor(server);
    attendance.employees = [
      { id: '642214', number: '34', name: 'זילברברג ברינה' },
      { id: '874747', number: '43', name: 'דבח שלו' },
    ];
    const result = await getConnectedEmployees({
      config: { ...cfg, employees: [], watchNames: [] },
      now: new Date(2026, 8, 2, 15, 30),
      login: async () => ({}),
      discover: async () => attendance,
    });
    eq('reports who is in, from when, for how long',
      result.connected.map((e) => [e.name, e.since, e.minutes]),
      [['זילברברג ברינה', '13:15', 135], ['דבח שלו', '13:15', 135]]);
    eq('no warning on a good run', result.warning, null);
    // 4 negotiation attempts + 1 for the second employee; the employee the
    // negotiation succeeded on is not asked about twice.
    eq('the negotiated page is reused', server.seen.length, 5);
    server.close();
  }

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
