'use strict';
/**
 * Discovering the attendance filter form on update.php.
 *
 * The query parameters were carried over from the employee portal and are
 * the likeliest thing to be wrong. Rather than guess again, the page is
 * fetched and its filter form read: which control picks the employee, which
 * the month, which the year - and every other filter (branch, department,
 * role, view) is resubmitted at whatever value the page already had, so the
 * defaults are preserved instead of being dropped.
 */

const CONTROL_RE = /<(input|select)\b[^>]*>/gi;
const SELECT_RE = /<select\b[^>]*>[\s\S]*?<\/select>/gi;
const OPTION_RE = /<option\b[^>]*>([\s\S]*?)<\/option>/gi;

function attr(tag, name) {
  const m = new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i').exec(tag);
  return m ? (m[2] ?? m[3] ?? m[4] ?? null) : null;
}

function textOf(html) {
  return html.replace(/<[^>]*>/g, ' ').replace(/&nbsp;/gi, ' ').replace(/\s+/g, ' ').trim();
}

/** The value a control would submit if the form were posted untouched. */
function currentValue(tag, selectHtml) {
  if (!selectHtml) return attr(tag, 'value') || '';
  const options = selectHtml.match(/<option\b[^>]*>/gi) || [];
  const selected = options.find((o) => /\bselected\b/i.test(o));
  const chosen = selected || options[0];
  return chosen ? (attr(chosen, 'value') ?? '') : '';
}

function optionValues(selectHtml) {
  const out = [];
  let m;
  OPTION_RE.lastIndex = 0;
  while ((m = OPTION_RE.exec(selectHtml))) {
    const tag = /<option\b[^>]*>/i.exec(m[0])[0];
    out.push({ value: attr(tag, 'value') ?? textOf(m[1]), label: textOf(m[1]) });
  }
  return out;
}

const YEAR_NOW = new Date().getFullYear();
const looksLikeYears = (opts) =>
  opts.length >= 2 && opts.length <= 30 &&
  opts.every((o) => /^\d{4}$/.test(o.value) && +o.value > YEAR_NOW - 25 && +o.value < YEAR_NOW + 5);

const looksLikeMonths = (opts) =>
  opts.length >= 12 && opts.length <= 13 &&
  opts.filter((o) => /^\d{1,2}$/.test(o.value) && +o.value >= 1 && +o.value <= 12).length >= 12;

/**
 * @returns {{action:string|null, method:string, fields:Object,
 *            employee:string|null, year:string|null, month:string|null}|null}
 */
function discoverAttendanceForm(html, options = {}) {
  const forms = html.match(/<form\b[\s\S]*?<\/form>/gi) || [];
  // The attendance filter form is the one carrying a year picker.
  let form = null;
  for (const f of forms) {
    const selects = f.match(SELECT_RE) || [];
    if (selects.some((s) => looksLikeYears(optionValues(s)))) { form = f; break; }
  }
  if (!form) form = forms[0];
  if (!form) return null;

  const selectsByName = {};
  for (const s of form.match(SELECT_RE) || []) {
    const name = attr(/<select\b[^>]*>/i.exec(s)[0], 'name');
    if (name) selectsByName[name] = s;
  }

  const fields = {};
  let year = null, month = null, employee = null;

  for (const tag of form.match(CONTROL_RE) || []) {
    const name = attr(tag, 'name');
    if (!name) continue;
    const type = (attr(tag, 'type') || 'text').toLowerCase();
    if (['submit', 'button', 'reset', 'image'].includes(type)) continue;
    if (['checkbox', 'radio'].includes(type) && !/\bchecked\b/i.test(tag)) continue;
    fields[name] = currentValue(tag, selectsByName[name]);
  }
  for (const [name, s] of Object.entries(selectsByName)) {
    fields[name] = currentValue(null, s);
    const opts = optionValues(s);
    if (!year && looksLikeYears(opts)) year = name;
    else if (!month && looksLikeMonths(opts)) month = name;
  }

  // The employee picker: the control whose current value is the employee
  // number the page is showing, or a select listing the staff by name.
  const known = String(options.knownEmployeeId || '');
  for (const [name, value] of Object.entries(fields)) {
    if (name === year || name === month) continue;
    if (known && String(value) === known) { employee = name; break; }
  }
  if (!employee) {
    employee = Object.keys(fields).find((n) => /^(ee|emp|employee|oved)/i.test(n)) || null;
  }

  return {
    action: attr(form, 'action'),
    method: (attr(form, 'method') || 'get').toLowerCase(),
    fields, employee, year, month,
  };
}

/** Resubmit the discovered form with employee, year and month replaced. */
function buildAttendanceQuery(form, { employeeId, year, month }) {
  const params = new URLSearchParams(form.fields);
  if (form.employee) params.set(form.employee, String(employeeId));
  if (form.year) params.set(form.year, String(year));
  if (form.month) params.set(form.month, String(month));
  return params;
}

module.exports = { discoverAttendanceForm, buildAttendanceQuery };
