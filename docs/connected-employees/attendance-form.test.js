const { discoverAttendanceForm, buildAttendanceQuery } = require('./attendance-form.js');

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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
