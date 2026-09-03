'use strict';
/**
 * Discovering the login form instead of guessing its field names.
 *
 * TimeWatch publishes no API and the employer portal's form field names are
 * not documented anywhere. Rather than hard-code a guess that silently posts
 * to the wrong names, the login page is fetched and its form read: which
 * input is the password, which are the two text fields before it, and which
 * hidden fields (tokens, redirects) have to be echoed back.
 *
 * A guess that is wrong looks exactly like a wrong password. Reading the form
 * removes that whole class of confusion.
 */

const INPUT_RE = /<input\b[^>]*>/gi;

function attr(tag, name) {
  const m = new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i').exec(tag);
  if (!m) return null;
  return m[2] ?? m[3] ?? m[4] ?? null;
}

/** The form that owns the password box is the login form. */
function loginFormHtml(html) {
  const forms = html.match(/<form\b[\s\S]*?<\/form>/gi) || [];
  const withPassword = forms.find((f) => /<input\b[^>]*type\s*=\s*["']?password/i.test(f));
  if (withPassword) return withPassword;
  // Some pages leave the inputs outside any <form>; fall back to the page.
  return /<input\b[^>]*type\s*=\s*["']?password/i.test(html) ? html : null;
}

/**
 * @returns {{action:string|null, method:string, password:string,
 *            company:string|null, username:string|null,
 *            hidden:Object<string,string>}|null}
 */
function discoverLoginForm(html) {
  const form = loginFormHtml(html);
  if (!form) return null;

  const inputs = (form.match(INPUT_RE) || [])
    .map((tag) => ({
      name: attr(tag, 'name'),
      type: (attr(tag, 'type') || 'text').toLowerCase(),
      value: attr(tag, 'value') || '',
    }))
    .filter((i) => i.name);

  const password = inputs.find((i) => i.type === 'password');
  if (!password) return null;

  const hidden = {};
  for (const i of inputs) {
    if (i.type === 'hidden') hidden[i.name] = i.value;
  }

  // The two entry boxes above the password, in the order the page shows them:
  // company number, then username. Buttons and checkboxes are not entries.
  const entries = inputs.filter((i) => ['text', 'email', 'tel', 'number'].includes(i.type));

  return {
    action: attr(form, 'action'),
    method: (attr(form, 'method') || 'post').toLowerCase(),
    password: password.name,
    company: entries[0] ? entries[0].name : null,
    username: entries[1] ? entries[1].name : null,
    hidden,
  };
}

/** Build the POST body from the discovered names plus the credentials. */
function buildLoginBody(form, creds) {
  const body = new URLSearchParams(form.hidden || {});
  if (form.company) body.set(form.company, String(creds.company));
  if (form.username) body.set(form.username, String(creds.username));
  body.set(form.password, String(creds.password));
  return body;
}

module.exports = { discoverLoginForm, buildLoginBody };
