const os = require('os'), fs = require('fs'), path = require('path');
const { buildToastScript, showToast, messageFor, psString } = require('./notify-toast.js');

let pass = 0, fail = 0;
function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log('  ok  ', name); }
  else { fail++; console.log('  FAIL', name, '\n     got ', g, '\n     want', w); }
}

// A name is data from TimeWatch, not code. The only escape inside a
// single-quoted PowerShell string is doubling the quote.
eq('an apostrophe cannot end the string', psString("O'Brien"), "'O''Brien'");
eq('a quote and a semicolon stay inside the string',
  psString("x'; Remove-Item C:\\ -Recurse; '"), "'x''; Remove-Item C:\\ -Recurse; '''");
eq('backslashes are literal in PowerShell single quotes',
  psString('C:\\notif_test\\app'), "'C:\\notif_test\\app'");

const script = buildToastScript({ title: 'נוכחות', text: 'זילברברג ברינה נכנס/ה', seconds: 5 });
eq('the tray icon is removed again',
  [/\$icon\.Visible = \$false/.test(script), /\$icon\.Dispose\(\)/.test(script)], [true, true]);
eq('the balloon time and the sleep agree',
  [/ShowBalloonTip\(5000\)/.test(script), /Start-Sleep -Seconds 5/.test(script)], [true, true]);
eq('an absurd duration is clamped',
  /Start-Sleep -Seconds 30/.test(buildToastScript({ title: 't', text: 'x', seconds: 9999 })), true);

eq('an arrival names the time', messageFor({ type: 'in', name: 'ברינה', since: '09:04' }).text,
  'ברינה נכנס/ה — מ־09:04');
eq('a departure does not', messageFor({ type: 'out', name: 'ברינה', since: '09:04' }).text,
  'ברינה יצא/ה');

// PowerShell 5.1 reads a file in the system codepage unless a BOM says
// otherwise, and Hebrew names would arrive as noise.
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'toast-'));
const file = showToast({ title: 'נוכחות', text: 'זילברברג ברינה נכנס/ה' }, { tempDir: dir, dryRun: true });
const bytes = fs.readFileSync(file);
eq('the script is written with a UTF-8 BOM', [...bytes.subarray(0, 3)], [0xef, 0xbb, 0xbf]);
eq('the Hebrew survives', fs.readFileSync(file, 'utf8').includes('זילברברג ברינה'), true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
