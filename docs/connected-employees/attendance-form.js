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
 *
 * The employee picker turned out to be two selects, not one: emplee_name and
 * emplee_id carry the same option values (an internal id like 642214) under
 * different labels - the name in one, the payroll number like 34 in the
 * other. So the roster is read straight off the page, and both fields are
 * submitted together the way the page's own script sets them.
 */

const CONTROL_RE = /<(input|select)\b[^>]*>/gi;
const SELECT_RE = /<select\b[^>]*>[\s\S]*?<\/select>/gi;

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

/**
 * The options of a select, whether or not the page closes its <option> tags.
 *
 * update.php closes neither, so requiring </option> read every dropdown as
 * empty - which in turn made the year picker invisible and the whole filter
 * form unrecognisable. Split on the opening tag and stop at the next one.
 */
function optionValues(selectHtml) {
  const inner = selectHtml.replace(/^[\s\S]*?>/, '').replace(/<\/select>[\s\S]*$/i, '');
  return inner.split(/<option\b/i).slice(1).map((chunk) => {
    const end = chunk.indexOf('>');
    const tag = `<option${chunk.slice(0, end + 1)}`;
    const label = textOf(chunk.slice(end + 1).replace(/<[\s\S]*$/, ''));
    return { value: attr(tag, 'value') ?? label, label };
  });
}

const YEAR_NOW = new Date().getFullYear();
const looksLikeYears = (opts) =>
  opts.length >= 2 && opts.length <= 30 &&
  opts.every((o) => /^\d{4}$/.test(o.value) && +o.value > YEAR_NOW - 25 && +o.value < YEAR_NOW + 5);

const looksLikeMonths = (opts) =>
  opts.length >= 12 && opts.length <= 13 &&
  opts.filter((o) => /^\d{1,2}$/.test(o.value) && +o.value >= 1 && +o.value <= 12).length >= 12;


const PLACEHOLDER_VALUES = new Set(['', '0', '-1']);
const isPlaceholder = (o) => PLACEHOLDER_VALUES.has(String(o.value).trim()) || /^-+$/.test(o.label);
const signature = (opts) => opts.map((o) => String(o.value).trim()).sort().join(',');

/**
 * The selects that pick the employee.
 *
 * A payroll system shows the same roster twice - once by name, once by
 * number - and the two selects share their option values. Two selects with
 * an identical value set are therefore the employee picker, and matching
 * them on values rather than on field names means a renamed field still
 * works. Falls back to a single name-shaped select when there is no twin.
 */
function employeeSelects(selectsByName, skip) {
  const groups = new Map();
  for (const [name, html] of Object.entries(selectsByName)) {
    if (skip.includes(name)) continue;
    const opts = optionValues(html);
    if (opts.filter((o) => !isPlaceholder(o)).length < 2) continue;
    const key = signature(opts);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ name, opts });
  }
  let best = null;
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    if (!best || members[0].opts.length > best[0].opts.length) best = members;
  }
  if (best) return best;

  const single = Object.keys(selectsByName)
    .filter((n) => !skip.includes(n))
    .find((n) => /^(ee|emp|employee|oved)/i.test(n));
  return single ? [{ name: single, opts: optionValues(selectsByName[single]) }] : [];
}

const mostlyNumeric = (opts) =>
  opts.filter((o) => /^\d+$/.test(o.label)).length > opts.length / 2;

/**
 * Read the roster off the filter form: internal id, payroll number, name.
 *
 * Reading it here rather than keeping a hand-written list means nobody has
 * to retype employee numbers when someone joins or leaves, and it avoids
 * pairing numbers with names by eye - on screen the Hebrew names and the
 * numbers run in opposite directions, so the visual order lies.
 */
function discoverEmployees(html) {
  const form = discoverAttendanceForm(html);
  if (!form || !form.employeeSelects) return [];

  const withoutPlaceholders = (s) => s.opts.filter((o) => !isPlaceholder(o));
  const numeric = form.employeeSelects.find((s) => mostlyNumeric(withoutPlaceholders(s)));
  const named = form.employeeSelects.find((s) => s !== numeric);

  const source = named || numeric;
  if (!source) return [];

  const numberById = new Map();
  if (numeric && numeric !== source) {
    for (const o of withoutPlaceholders(numeric)) numberById.set(String(o.value), o.label);
  }

  return withoutPlaceholders(source).map((o) => ({
    id: String(o.value),
    number: numberById.get(String(o.value)) || null,
    name: o.label,
  }));
}

/**
 * @returns {{action:string|null, method:string, fields:Object,
 *            employee:string|null, employeeFields:string[],
 *            employeeSelects:Array, submits:Object,
 *            year:string|null, month:string|null}|null}
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
  // Submit controls are kept apart from the fields: a browser sends the one
  // that was clicked, and old PHP pages routinely gate the report on it, but
  // resubmitting every submit button as a plain field would be wrong.
  const submits = {};
  let year = null, month = null, employee = null;

  for (const tag of form.match(CONTROL_RE) || []) {
    const name = attr(tag, 'name');
    if (!name) continue;
    const type = (attr(tag, 'type') || 'text').toLowerCase();
    if (type === 'submit' || type === 'image') { submits[name] = attr(tag, 'value') ?? ''; continue; }
    if (['button', 'reset'].includes(type)) continue;
    if (['checkbox', 'radio'].includes(type) && !/\bchecked\b/i.test(tag)) continue;
    fields[name] = currentValue(tag, selectsByName[name]);
  }
  for (const [name, s] of Object.entries(selectsByName)) {
    fields[name] = currentValue(null, s);
    const opts = optionValues(s);
    if (!year && looksLikeYears(opts)) year = name;
    else if (!month && looksLikeMonths(opts)) month = name;
  }

  // The employee picker: the twin selects listing the roster, or failing
  // that the control already holding the employee the page is showing.
  const selects = employeeSelects(selectsByName, [year, month].filter(Boolean));
  let employeeFields = selects.map((s) => s.name);

  if (!employeeFields.length) {
    const known = String(options.knownEmployeeId || '');
    for (const [name, value] of Object.entries(fields)) {
      if (name === year || name === month) continue;
      if (known && String(value) === known) { employeeFields = [name]; break; }
    }
    if (!employeeFields.length) {
      const guess = Object.keys(fields).find((n) => /^(ee|emp|employee|oved)/i.test(n));
      if (guess) employeeFields = [guess];
    }
  }
  employee = employeeFields[0] || null;

  return {
    action: attr(form, 'action'),
    method: (attr(form, 'method') || 'get').toLowerCase(),
    fields, employee, employeeFields, employeeSelects: selects, submits, year, month,
  };
}

/** Resubmit the discovered form with employee, year and month replaced. */
function buildAttendanceQuery(form, { employeeId, year, month }) {
  const params = new URLSearchParams(form.fields);
  // Both halves of the picker, because the page's own script sets both and
  // the server has no reason to prefer the one we happened to discover.
  const targets = form.employeeFields && form.employeeFields.length
    ? form.employeeFields : [form.employee].filter(Boolean);
  for (const name of targets) params.set(name, String(employeeId));
  if (form.year) params.set(form.year, String(year));
  if (form.month) params.set(form.month, String(month));
  return params;
}

/** The same query plus the form's own submit buttons, as a click would send. */
function buildAttendanceQueryWithSubmit(form, options) {
  const params = buildAttendanceQuery(form, options);
  for (const [name, value] of Object.entries(form.submits || {})) params.set(name, value);
  return params;
}

module.exports = {
  discoverAttendanceForm, buildAttendanceQuery, buildAttendanceQueryWithSubmit, discoverEmployees,
};
