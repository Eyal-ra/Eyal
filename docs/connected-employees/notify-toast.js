'use strict';
/**
 * A presence alert that needs nothing installed.
 *
 * The office notifier is a Python app with no file queue to drop a request
 * into, and its interface is not known yet. Rather than block the alert on
 * learning it, this puts the notification on screen through Windows itself:
 * a tray balloon via NotifyIcon, which is present on every Windows box and
 * needs no module, no service and no admin rights.
 *
 * The PowerShell it generates disposes of the icon and exits, so nothing is
 * left running and no window stays open.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile, execFileSync } = require('child_process');

/** Single-quoted PowerShell string: the only escape inside one is ''. */
const psString = (value) => `'${String(value).replace(/'/g, "''")}'`;

/**
 * @param {{title:string, text:string, seconds?:number}} message
 * @returns {string} a self-contained PowerShell script
 */
function buildToastScript(message) {
  const seconds = Math.max(1, Math.min(30, message.seconds || 8));
  return [
    'Add-Type -AssemblyName System.Windows.Forms',
    'Add-Type -AssemblyName System.Drawing',
    '$icon = New-Object System.Windows.Forms.NotifyIcon',
    '$icon.Icon = [System.Drawing.SystemIcons]::Information',
    `$icon.BalloonTipTitle = ${psString(message.title)}`,
    `$icon.BalloonTipText = ${psString(message.text)}`,
    '$icon.Visible = $true',
    `$icon.ShowBalloonTip(${seconds * 1000})`,
    // Kept alive only as long as the balloon, then removed from the tray -
    // an alert that leaves an icon behind becomes clutter within a day.
    `Start-Sleep -Seconds ${seconds}`,
    '$icon.Visible = $false',
    '$icon.Dispose()',
  ].join('\n');
}

/**
 * Show one balloon.
 *
 * The script is written as UTF-8 with a BOM: without it PowerShell 5.1 reads
 * the file in the system codepage and the Hebrew names arrive as noise.
 */
function showToast(message, options = {}) {
  const dir = options.tempDir || os.tmpdir();
  const file = path.join(dir, `presence-toast-${Date.now()}-${process.pid}.ps1`);
  fs.writeFileSync(file, `﻿${buildToastScript(message)}`, 'utf8');

  if (options.dryRun) return file;

  execFile('powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', file],
    { windowsHide: true },
    () => { try { fs.unlinkSync(file); } catch { /* already gone */ } });
  return file;
}

/** @param {{type:'in'|'out', name:string, since:string}} event */
function messageFor(event) {
  return {
    title: event.type === 'in' ? 'נוכחות — כניסה' : 'נוכחות — יציאה',
    text: event.type === 'in'
      ? `${event.name} נכנס/ה — מ־${event.since}`
      : `${event.name} יצא/ה`,
  };
}

/**
 * A notifier that works on this machine.
 *
 * Off Windows there is no tray to put a balloon in, so it says so on stdout
 * rather than failing - the tests and any future Linux host still see the
 * events.
 */
function createToastNotifier(options = {}) {
  const platform = options.platform || process.platform;
  return (event) => {
    const message = messageFor(event);
    if (platform !== 'win32') {
      console.log(`[presence] ${message.title}: ${message.text}`);
      return null;
    }
    return showToast(message, options);
  };
}

/**
 * Show one balloon and wait, reporting what happened.
 *
 * The fire-and-forget path returns before Windows has drawn anything, so
 * "no error" says nothing about whether an alert would actually arrive -
 * which is the only question worth asking of an alert channel.
 */
function testToast(options = {}) {
  const message = messageFor({ type: 'in', name: options.name || 'בדיקה', since: '09:04' });
  if ((options.platform || process.platform) !== 'win32') {
    console.log(`not Windows - would have shown: ${message.title} / ${message.text}`);
    return 0;
  }
  const file = showToast({ ...message, seconds: options.seconds || 6 },
    { ...options, dryRun: true });
  console.log(`script: ${file}`);
  try {
    execFileSync('powershell.exe',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', file],
      { stdio: 'inherit', windowsHide: true });
    console.log('powershell finished without error - a balloon should have appeared');
    return 0;
  } catch (err) {
    console.error(`powershell failed (exit ${err.status}): ${err.message}`);
    return 1;
  } finally {
    try { fs.unlinkSync(file); } catch { /* already gone */ }
  }
}

if (require.main === module) {
  process.exit(testToast({ name: process.argv[2] }));
}

module.exports = {
  createToastNotifier, buildToastScript, showToast, messageFor, psString, testToast,
};
