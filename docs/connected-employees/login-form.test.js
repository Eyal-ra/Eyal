const { discoverLoginForm, buildLoginBody } = require('./login-form.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

// Shaped like a.timewatch.co.il/user/login.php: company, username, password.
const page = `<html><body>
<form action="/user/validate_user.php" method="POST">
  <input type="hidden" name="csrf" value="abc123">
  <input type="text" name="comp" placeholder="מספר חברה">
  <input type="text" name="user" placeholder="שם משתמש">
  <input type="password" name="pw">
  <input type="submit" value="כניסה">
</form></body></html>`;

const form = discoverLoginForm(page);
eq('finds the password field', form.password, 'pw');
eq('company is the first entry box', form.company, 'comp');
eq('username is the second', form.username, 'user');
eq('carries hidden fields', form.hidden, { csrf: 'abc123' });
eq('reads the action', form.action, '/user/validate_user.php');
eq('submit button is not mistaken for an entry box', form.company !== 'submit', true);

const body = buildLoginBody(form, { company: '6979', username: 'eyal@cpateam.co.il', password: 's3cret' });
eq('body carries every field', [...body.keys()].sort(), ['comp', 'csrf', 'pw', 'user']);
eq('company value', body.get('comp'), '6979');
eq('username value', body.get('user'), 'eyal@cpateam.co.il');
eq('hidden token echoed back', body.get('csrf'), 'abc123');

// Different names must be picked up just as well - that is the whole point.
const renamed = discoverLoginForm(`<form method="get" action="x.php">
  <input name="companyId"><input type="email" name="loginEmail"><input type="password" name="secret">
</form>`);
eq('unfamiliar names still resolve',
  { c: renamed.company, u: renamed.username, p: renamed.password, m: renamed.method },
  { c: 'companyId', u: 'loginEmail', p: 'secret', m: 'get' });

// Single quotes and unquoted attributes appear in old markup.
const quoting = discoverLoginForm(`<form action='/a.php'>
  <input name='c' type='text'><input name=u type=text><input name="p" type="password"></form>`);
eq('handles single-quoted and bare attributes',
  { c: quoting.company, u: quoting.username, p: quoting.password, a: quoting.action },
  { c: 'c', u: 'u', p: 'p', a: '/a.php' });

// A checkbox alongside the entries must not shift the mapping.
const withBox = discoverLoginForm(`<form>
  <input type="checkbox" name="remember"><input type="text" name="comp">
  <input type="text" name="user"><input type="password" name="pw"></form>`);
eq('checkbox is not an entry box',
  { c: withBox.company, u: withBox.username }, { c: 'comp', u: 'user' });

// Two forms on the page: the one with the password wins.
const twoForms = discoverLoginForm(`
  <form action="/search.php"><input type="text" name="q"></form>
  <form action="/login.php"><input type="text" name="comp"><input type="text" name="user">
  <input type="password" name="pw"></form>`);
eq('picks the form holding the password', twoForms.action, '/login.php');

eq('a page with no password form returns null', discoverLoginForm('<p>hello</p>'), null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
