const {
  discoverAttendanceForm, buildAttendanceQuery, buildAttendanceQueryWithSubmit, discoverEmployees,
} = require('./attendance-form.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

const years = (sel) => `<select name="${sel}">
  <option value="2024">2024</option><option value="2025">2025</option>
  <option value="2026" selected>2026</option></select>`;
const months = (sel) => `<select name="${sel}">` +
  Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}"${i === 8 ? ' selected' : ''}>${i + 1}</option>`).join('') +
  '</select>';

// Shaped like the filter bar on update.php: year, month, branch, department,
// role, view, and the employee number.
const page = `<html><body>
<form action="/update.php" method="GET">
  <input type="hidden" name="token" value="xyz">
  ${years('y')}
  ${months('m')}
  <select name="branch"><option value="0" selected>כללי</option><option value="1">סניף א</option></select>
  <select name="dept"><option value="all" selected>כולם</option></select>
  <input type="text" name="ovedno" value="43">
  <select name="tafkid"><option value="all" selected>כולם</option></select>
  <select name="tzuga"><option value="all" selected>כל הימים</option></select>
  <input type="submit" value="הצג">
</form></body></html>`;

const form = discoverAttendanceForm(page, { knownEmployeeId: '43' });
eq('finds the year picker', form.year, 'y');
eq('finds the month picker', form.month, 'm');
eq('finds the employee field by its current value', form.employee, 'ovedno');
eq('reads the action', form.action, '/update.php');

eq('keeps every other filter at its default',
  { branch: form.fields.branch, dept: form.fields.dept, tafkid: form.fields.tafkid, tzuga: form.fields.tzuga },
  { branch: '0', dept: 'all', tafkid: 'all', tzuga: 'all' });
eq('carries the hidden token', form.fields.token, 'xyz');
eq('the submit button is not a field', form.fields.hasOwnProperty('undefined') || 'הצג' in form.fields, false);

const q = buildAttendanceQuery(form, { employeeId: '7', year: 2026, month: 9 });
eq('employee is replaced', q.get('ovedno'), '7');
eq('year is replaced', q.get('y'), '2026');
eq('month is replaced', q.get('m'), '9');
eq('branch default still submitted', q.get('branch'), '0');
eq('token still submitted', q.get('token'), 'xyz');

// A selected option marks the default even when it is not the first.
eq('selected option wins over the first', form.fields.y, '2026');
eq('selected month wins', form.fields.m, '9');

// Unfamiliar names must still resolve - the whole point of discovering.
const renamed = discoverAttendanceForm(
  `<form action="a.php">${years('shana')}${months('chodesh')}<input name="misparOved" value="43"></form>`,
  { knownEmployeeId: '43' });
eq('unfamiliar names resolve',
  { y: renamed.year, m: renamed.month, e: renamed.employee },
  { y: 'shana', m: 'chodesh', e: 'misparOved' });

// With no known id, fall back to a name-shaped guess.
const noHint = discoverAttendanceForm(`<form>${years('y')}${months('m')}<input name="ee" value=""></form>`);
eq('falls back to a name-shaped field', noHint.employee, 'ee');

// The right form is picked when the page carries a search box too.
const twoForms = discoverAttendanceForm(
  `<form action="/search.php"><input name="q"></form>
   <form action="/update.php">${years('y')}${months('m')}<input name="ee" value="43"></form>`,
  { knownEmployeeId: '43' });
eq('picks the form with the year picker', twoForms.action, '/update.php');

eq('a page with no form returns null', discoverAttendanceForm('<p>hi</p>'), null);

// The real update.php filter bar: the roster appears twice, once by name and
// once by payroll number, on the same option values. Attributes are unquoted,
// as they are on the live page.
const twinPage = `<form action="update.php" method="get">
  <select name="year"><option value=2026 selected>2026<option value=2025>2025<option value=2024>2024</select>
  <select name="month"><option value=1>01<option value=9 selected>09<option value=2>02<option value=3>03
    <option value=4>04<option value=5>05<option value=6>06<option value=7>07<option value=8>08
    <option value=10>10<option value=11>11<option value=12>12</select>
  <select name="branch"><option value=0 selected>\u05db\u05dc\u05dc\u05d9</select>
  <select name="department"><option value=0 selected>\u05db\u05d5\u05dc\u05dd<option value=26039>2
    <option value=26038>\u05e2\u05d5\u05d1\u05d3\u05d9\u05dd<option value=27494>\u05e9\u05d5\u05ea\u05e4\u05d5\u05ea</select>
  <select name="emplee_name"><option value=0 selected>---<option value=880427>\u05d0\u05d5\u05d7\u05d9\u05d5\u05df \u05de\u05e8\u05d9\u05dd
    <option value=874747>\u05d3\u05d1\u05d7 \u05e9\u05dc\u05d5<option value=642214>\u05d6\u05d9\u05dc\u05d1\u05e8\u05d1\u05e8\u05d2 \u05d1\u05e8\u05d9\u05e0\u05d4
    <option value=455198>\u05db\u05d4\u05df \u05de\u05d0\u05d9\u05d4</select>
  <select name="emplee_id"><option value=0 selected>---<option value=455198>28<option value=642214>34
    <option value=874747>43<option value=880427>45</select>
  <select name="display"><option value=0 selected>\u05db\u05dc \u05d4\u05d9\u05de\u05d9\u05dd<option value=1>\u05ea\u05e0\u05d5\u05e2\u05d5\u05ea \u05d7\u05e1\u05e8\u05d5\u05ea</select>
</form>`;

const twin = discoverAttendanceForm(twinPage);
eq('both halves of the employee picker are found',
  twin.employeeFields.slice().sort(), ['emplee_id', 'emplee_name']);
eq('the roster is not mistaken for the month picker', [twin.year, twin.month], ['year', 'month']);
eq('a four-option department is not the roster',
  twin.employeeFields.includes('department'), false);

const twinQuery = buildAttendanceQuery(twin, { employeeId: '642214', year: 2026, month: 9 });
eq('both employee fields carry the id',
  [twinQuery.get('emplee_name'), twinQuery.get('emplee_id')], ['642214', '642214']);
eq('other filters keep their page defaults',
  [twinQuery.get('branch'), twinQuery.get('department'), twinQuery.get('display')], ['0', '0', '0']);

const roster = discoverEmployees(twinPage);
eq('roster pairs each name with its payroll number', roster, [
  { id: '880427', number: '45', name: '\u05d0\u05d5\u05d7\u05d9\u05d5\u05df \u05de\u05e8\u05d9\u05dd' },
  { id: '874747', number: '43', name: '\u05d3\u05d1\u05d7 \u05e9\u05dc\u05d5' },
  { id: '642214', number: '34', name: '\u05d6\u05d9\u05dc\u05d1\u05e8\u05d1\u05e8\u05d2 \u05d1\u05e8\u05d9\u05e0\u05d4' },
  { id: '455198', number: '28', name: '\u05db\u05d4\u05df \u05de\u05d0\u05d9\u05d4' },
]);

// A page that lists the roster only once still yields names.
const singlePage = twinPage.replace(/<select name="emplee_id">[\s\S]*?<\/select>/, '');
eq('a single roster select still works',
  discoverEmployees(singlePage).map((e) => [e.number, e.name.slice(0, 4)]),
  [[null, '\u05d0\u05d5\u05d7\u05d9'], [null, '\u05d3\u05d1\u05d7 '], [null, '\u05d6\u05d9\u05dc\u05d1'], [null, '\u05db\u05d4\u05df ']]);

// The submit button is kept apart from the fields - resubmitting every button
// as a plain field would be wrong - but an old page may gate the report on it.
const gated = discoverAttendanceForm(`<form action="update.php">
  <select name="year"><option value=2026 selected>2026<option value=2025>2025</select>
  <select name="month"><option value=9 selected>09<option value=1>01<option value=2>02<option value=3>03
    <option value=4>04<option value=5>05<option value=6>06<option value=7>07<option value=8>08
    <option value=10>10<option value=11>11<option value=12>12</select>
  <select name="ee"><option value=0>---<option value=11>\u05d0<option value=22>\u05d1</select>
  <select name="ee2"><option value=0>---<option value=11>1<option value=22>2</select>
  <input type=hidden name=csrf value=abc>
  <input type=submit name=go value="\u05d4\u05e6\u05d2">
  <input type=reset name=clear value="\u05e0\u05e7\u05d4">
</form>`);
eq('submit buttons are held separately', gated.submits, { go: '\u05d4\u05e6\u05d2' });
eq('a submit button is not a field', 'go' in gated.fields, false);
eq('a reset button is neither', ['clear' in gated.fields, 'clear' in gated.submits], [false, false]);
eq('hidden fields survive', gated.fields.csrf, 'abc');

const plain = buildAttendanceQuery(gated, { employeeId: '22', year: 2026, month: 9 });
eq('the plain query omits the button', plain.get('go'), null);
const clicked = buildAttendanceQueryWithSubmit(gated, { employeeId: '22', year: 2026, month: 9 });
eq('the clicked query carries it', [clicked.get('go'), clicked.get('ee'), clicked.get('ee2')],
  ['\u05d4\u05e6\u05d2', '22', '22']);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
