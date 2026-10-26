/**
 * Geotechnical News Desk — AI assistant bridge, e-mail sender and planning sheet (Google Apps Script)
 *
 * The website is public, so it cannot hold an API key. This small script runs in your own Google
 * account instead: the website sends each question here, the script adds your Anthropic key (read
 * from your private Google Doc) and passes the question to Claude. The key never reaches the website
 * or the repository. It also e-mails the alerts and weekly summary once the Script property NOTIFY_TOKEN
 * is set (see "E-mail" below), and keeps the editorial team's shared planning sheet in Google Sheets
 * (run setupPlanningSheet once; see "Shared planning sheet" at the end). Setup: the repository README.
 */

// The Google Doc that holds your Anthropic key (paste its link or ID). The key is
// found anywhere in the document as the text starting with "sk-ant-".
// Alternatively set a Script property named ANTHROPIC_API_KEY (Project Settings).
const KEY_DOC = 'PASTE-THE-LINK-TO-YOUR-KEY-DOCUMENT-HERE';

const DEFAULT_MODEL = 'claude-sonnet-5-5';
const MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'];
const MAX_TOKENS = 4000;
const DAILY_LIMIT = 100;            // questions per day (Cairo time): protects your Anthropic bill
const MAX_REQUEST_MB = 25;          // largest question + attachments accepted
const TIME_ZONE = 'Africa/Cairo';

// ---------- E-mail (alerts and the weekly summary) ----------
// After each daily scan, notify.py in the repository posts {action: 'notify', token, subject, html, text}
// here and the script sends it from your Google account. Script properties (Project Settings → Script properties):
//   NOTIFY_TOKEN  required: a long random text (for example 40 letters and digits). Add the same text as the
//                 GitHub secret NOTIFY_TOKEN. Without this property the script sends no e-mail at all.
//   MAIL_TO       optional: the recipients, separated by commas. Empty: your own address (the script owner).
// After pasting this version: choose testEmail in the function menu and press Run once, so that Google asks
// for the permission to send e-mail as you; then Deploy → Manage deployments → Edit → Version: New version.
const MAIL_DAILY_LIMIT = 20;        // e-mails per day (Cairo time); a scan sends at most three
const MAX_SUBJECT = 250;            // characters
const MAX_MAIL_KB = 500;            // largest e-mail accepted (HTML and plain text together)
const MAX_RECIPIENTS = 50;
const SENDER_NAME = 'Geotechnical News Desk';

function doGet() {
  let keyFound = false, problem = '';
  try { keyFound = !!apiKey(); } catch (err) { problem = String(err.message || err); }
  return reply({
    ok: keyFound, service: 'Geotechnical News Desk assistant bridge', problem: problem,
    dailyLimit: DAILY_LIMIT, usedToday: usedToday(), passcode: !!accessCode(), email: !!notifyToken()
  });
}

function doPost(e) {
  try {
    const raw = (e && e.postData && e.postData.contents) || '';
    if (raw.length > MAX_REQUEST_MB * 1024 * 1024) {
      return reply({ error: 'This question and its attachments are larger than ' + MAX_REQUEST_MB + ' MB.' });
    }
    const req = JSON.parse(raw);
    if (req && req.action === 'notify') return reply(notify(req));  // an e-mail from the scan, not a question
    if (accessCode() && req.passcode !== accessCode()) return reply({ error: 'passcode', message: 'Passcode required.' });
    const messages = cleanMessages(req.messages);
    if (!messages.length) return reply({ error: 'Empty question.' });
    if (!takeOne()) {
      return reply({ error: "The assistant has reached today's limit of " + DAILY_LIMIT + ' questions. It resets at midnight Cairo time.' });
    }
    const model = MODELS.indexOf(req.model) >= 0 ? req.model : DEFAULT_MODEL;
    const body = {
      model: model,
      max_tokens: MAX_TOKENS,
      system: [{ type: 'text', text: String(req.system || '').slice(0, 80000), cache_control: { type: 'ephemeral' } }],
      messages: messages
    };
    let res = callClaude(body, model !== 'claude-haiku-5-5');
    if (res.code === 400 && /fallback/i.test(res.text)) res = callClaude(body, false);
    let j = {};
    try { j = JSON.parse(res.text); } catch (err) { /* not JSON */ }
    if (res.code !== 200) return reply({ error: explain(res.code, j) });
    const text = (j.content || []).filter(function (b) { return b.type === 'text'; })
      .map(function (b) { return b.text; }).join('');
    return reply({ text: text, stop_reason: j.stop_reason, model: j.model, left: DAILY_LIMIT - usedToday() });
  } catch (err) {
    const msg = String(err.message || err);
    return reply({ error: /timeout|timed out/i.test(msg)
      ? 'Claude took too long to answer. Try a shorter question, or the faster model.' : msg });
  }
}

function callClaude(body, withFallback) {
  const headers = { 'x-api-key': apiKey(), 'anthropic-version': '2023-06-01' };
  const payload = Object.assign({}, body);
  if (withFallback) {
    headers['anthropic-beta'] = 'server-side-fallback-2026-07-01';
    payload.fallbacks = 'default';
  }
  const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
    method: 'post', contentType: 'application/json', headers: headers,
    payload: JSON.stringify(payload), muteHttpExceptions: true
  });
  return { code: res.getResponseCode(), text: res.getContentText() };
}

// Only plain conversation content is passed on: text, and PDF documents.
function cleanMessages(list) {
  if (!Array.isArray(list)) return [];
  return list.slice(-30).filter(function (m) {
    return m && (m.role === 'user' || m.role === 'assistant');
  }).map(function (m) {
    if (typeof m.content === 'string') return { role: m.role, content: m.content.slice(0, 400000) };
    const blocks = (Array.isArray(m.content) ? m.content : []).filter(function (b) {
      return b && (b.type === 'text' || (b.type === 'document' && b.source && b.source.media_type === 'application/pdf'));
    }).map(function (b) {
      if (b.type === 'text') return { type: 'text', text: String(b.text).slice(0, 400000) };
      return { type: 'document', title: String(b.title || 'document.pdf').slice(0, 200),
        source: { type: 'base64', media_type: 'application/pdf', data: String(b.source.data) } };
    });
    return { role: m.role, content: blocks };
  }).filter(function (m) { return typeof m.content === 'string' ? m.content : m.content.length; });
}

function explain(code, j) {
  const msg = (j && j.error && j.error.message) || ('HTTP ' + code);
  if (code === 401) return 'Anthropic did not accept the API key in your Google Doc. Check that the whole key is there.';
  if (code === 429) return 'Too many requests to Claude right now. Wait a minute and try again.';
  if (code === 529 || code >= 500) return 'Claude is busy at the moment. Please try again shortly.';
  return msg;
}

function apiKey() {
  const cache = CacheService.getScriptCache();
  const cached = cache.get('key');
  if (cached) return cached;
  let key = (PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY') || '').trim();
  if (!key) {
    const id = KEY_DOC.indexOf('PASTE-') === 0 ? '' : ((KEY_DOC.match(/\/d\/([-\w]{25,})/) || KEY_DOC.match(/^\s*([-\w]{25,})\s*$/) || [])[1] || '');
    if (!id) {
      throw new Error('The script does not know where your key is yet: on line 15, replace PASTE-THE-LINK-TO-YOUR-KEY-DOCUMENT-HERE ' +
        'with the link of the Google Doc that holds your key, save, and deploy a new version.');
    }
    let text;
    try {
      text = DocumentApp.openById(id).getBody().getText();
    } catch (err) {
      throw new Error('The script could not open the Google Doc in KEY_DOC (' + String(err.message || err) + '). Check that the link ' +
        'is right, that it is a Google Docs document (an uploaded Word file cannot be read: open it and use File > Save as Google Docs), ' +
        'and that the deployment runs as you ("Execute as: Me"). Alternatively add the key as a Script property named ANTHROPIC_API_KEY.');
    }
    const m = text.match(/sk-ant-[A-Za-z0-9_\-]{20,}/);
    if (!m) throw new Error('The Google Doc opened, but no Anthropic key (text starting with sk-ant-) was found in it.');
    key = m[0];
  }
  cache.put('key', key, 600);
  return key;
}

function accessCode() {
  return (PropertiesService.getScriptProperties().getProperty('ACCESS_CODE') || '').trim();
}

function today() { return Utilities.formatDate(new Date(), TIME_ZONE, 'yyyy-MM-dd'); }

function usedToday() {
  return Number(PropertiesService.getScriptProperties().getProperty('count-' + today()) || 0);
}

function takeOne() {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const props = PropertiesService.getScriptProperties();
    const name = 'count-' + today();
    const n = Number(props.getProperty(name) || 0);
    if (n >= DAILY_LIMIT) return false;
    props.setProperty(name, String(n + 1));
    // forget old counters
    Object.keys(props.getProperties()).forEach(function (k) {
      if (k.indexOf('count-') === 0 && k !== name) props.deleteProperty(k);
    });
    return true;
  } finally {
    lock.releaseLock();
  }
}

// ---------- E-mail ----------
function notify(req) {
  const expected = notifyToken();
  if (!expected) {
    return { ok: false, error: 'E-mail is not switched on in the connector: add the Script property NOTIFY_TOKEN ' +
      '(Project Settings → Script properties) with the same text as the GitHub secret NOTIFY_TOKEN.' };
  }
  if (!sameText(String(req.token || ''), expected)) {
    return { ok: false, error: 'The token does not match: give the GitHub secret NOTIFY_TOKEN exactly the text of the ' +
      'Script property NOTIFY_TOKEN.' };
  }
  const subject = String(req.subject || '').replace(/[\r\n\t]+/g, ' ').trim().slice(0, MAX_SUBJECT);
  const html = String(req.html || '');
  const text = String(req.text || '');
  if (!subject || !html) return { ok: false, error: 'Empty e-mail: a subject and a body are needed.' };
  if (html.length + text.length > MAX_MAIL_KB * 1024) {
    return { ok: false, error: 'The e-mail is larger than ' + MAX_MAIL_KB + ' KB, so it was not sent.' };
  }
  const to = recipients();
  if (!to.length) return { ok: false, error: 'No recipient: add the Script property MAIL_TO (addresses separated by commas).' };
  if (MailApp.getRemainingDailyQuota() < to.length) {
    return { ok: false, error: "Google's daily e-mail quota for this account is used up. It resets within 24 hours." };
  }
  if (!takeMail()) {
    return { ok: false, error: "The connector has sent today's limit of " + MAIL_DAILY_LIMIT + ' e-mails. It resets at midnight Cairo time.' };
  }
  try {
    MailApp.sendEmail({ to: to.join(','), subject: subject, htmlBody: html,
      body: text || 'This e-mail is best read in a mail program that shows HTML.', name: SENDER_NAME });
  } catch (err) {
    return { ok: false, error: 'Google did not send the e-mail: ' + String(err.message || err) +
      (/permission|authori/i.test(String(err.message || err)) ? ' Run testEmail once from the script editor to allow e-mail.' : '') };
  }
  return { ok: true, sent_to: to.length };
}

function notifyToken() {
  return (PropertiesService.getScriptProperties().getProperty('NOTIFY_TOKEN') || '').trim();
}

// Compares the SHA-256 digests of the two texts byte by byte, so the time taken does not reveal the token.
function sameText(a, b) {
  const da = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, a, Utilities.Charset.UTF_8);
  const db = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, b, Utilities.Charset.UTF_8);
  let diff = da.length ^ db.length;
  for (let i = 0; i < da.length; i++) diff |= da[i] ^ db[i];
  return diff === 0;
}

function recipients() {
  const list = (PropertiesService.getScriptProperties().getProperty('MAIL_TO') || '').split(/[,;]/)
    .map(function (a) { return a.trim(); }).filter(function (a) { return /^[^@\s]+@[^@\s]+$/.test(a); });
  if (list.length) return list.slice(0, MAX_RECIPIENTS);
  const me = Session.getEffectiveUser().getEmail();
  return me ? [me] : [];
}

// A daily counter of its own for e-mails (the questions' counter is takeOne).
function takeMail() {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const props = PropertiesService.getScriptProperties();
    const name = 'mails-' + today();
    const n = Number(props.getProperty(name) || 0);
    if (n >= MAIL_DAILY_LIMIT) return false;
    props.setProperty(name, String(n + 1));
    Object.keys(props.getProperties()).forEach(function (k) {
      if (k.indexOf('mails-') === 0 && k !== name) props.deleteProperty(k);
    });
    return true;
  } finally {
    lock.releaseLock();
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// Run this once from the editor (select "testConnection", press Run) to check the setup.
function testConnection() {
  const res = callClaude({ model: 'claude-haiku-5-5', max_tokens: 1000, output_config: { effort: 'low' },
    messages: [{ role: 'user', content: 'Reply with the single word: connected' }] }, false);
  Logger.log('HTTP ' + res.code + ': ' + res.text.slice(0, 300));
}

// Run this once from the editor (select "testEmail", press Run) after pasting this version: Google asks for the
// permission to send e-mail as you, and a test message goes to the recipients (MAIL_TO, or your own address).
function testEmail() {
  const to = recipients();
  if (!to.length) throw new Error('No recipient: add the Script property MAIL_TO.');
  const note = 'The connector can send e-mail. Alerts for new 5/5 stories and the weekly summary will arrive this way ' +
    'once the GitHub secret NOTIFY_TOKEN has the same text as the Script property NOTIFY_TOKEN.';
  MailApp.sendEmail({ to: to.join(','), subject: 'Geotechnical News Desk: test e-mail from the connector', name: SENDER_NAME,
    htmlBody: '<p style="font:14px Arial,sans-serif">' + note + '</p>', body: note });
  Logger.log('Test e-mail sent to ' + to.length + ' recipient(s). E-mails Google still allows today: ' +
    MailApp.getRemainingDailyQuota() + '.' + (notifyToken() ? '' : ' The Script property NOTIFY_TOKEN is not set yet: ' +
    'add it (Project Settings → Script properties), or the scan cannot send e-mail.'));
}

// ---------- Shared planning sheet (Google Sheets) ----------
// A spreadsheet in your Google Drive where the editorial team plans each issue together. It reads only the website's
// public data (the stories' headlines, Claude's angles and whom to check them with; never a publisher's text), so it
// needs neither the API key nor the e-mail settings, and the chat and e-mail above work as before.
//
//   setupPlanningSheet  Run it once: choose setupPlanningSheet in the function menu at the top and press Run, then
//                       allow the permissions Google asks for. It creates the spreadsheet "Geotechnical News Desk —
//                       planning" in your Drive (or reuses the one in the Script property SHEET_ID), installs the daily
//                       update (about 07:00 Cairo time, after the 05:00 scan; running it again never adds a second
//                       one), fills the sheet and logs its address (View → Logs, or the log at the bottom). Open that
//                       address, share the sheet with the team (Share button, top right) and, if you like, paste the
//                       address into config.yaml under planning: sheet_url so the issue pages link to it.
//   syncPlanningSheet   The daily update; run it from the editor at any time as well. For the two newest issue windows
//                       on the website (the current quarter and the one before) it adds the new stories and research
//                       papers to the "Q4 2026 stories" tab (and so on), at the bottom, the best rated first; refreshes
//                       the news desk's columns of the rows already there; and marks a story that is no longer in the
//                       digest instead of deleting it. Status, Assigned to and Editor notes are the team's columns:
//                       they, and any column the team adds, are never changed. Each quarter also gets a "Q4 2026 plan"
//                       tab built once from the suggested issue layout (config.yaml issue_layout, published by the
//                       website as exports/layout.json); later updates only refresh its story dropdowns and add rows
//                       for sections added to the layout, and never change what the team has typed.
//
// Script properties (Project Settings → Script properties), both optional:
//   SITE_URL  the website, if it moves (default: DEFAULT_SITE_URL below)
//   SHEET_ID  the spreadsheet's ID: set by setupPlanningSheet; set it yourself to adopt another spreadsheet
// Permissions Google asks for on the first run: see, edit and create your spreadsheets (the planning sheet); connect
// to an external service (to read the website's data); and allow the script to run when you are not present (the
// daily update). No new deployment is needed: the daily update runs the saved script.

const PLAN_TITLE = 'Geotechnical News Desk — planning';
const DEFAULT_SITE_URL = 'https://monabadr12.github.io/geotech-news/';
const PLAN_HOUR = 7;                 // the daily update runs between 07:00 and 08:00 Cairo time
const PLAN_WINDOWS = 2;              // the current issue window and the one before
const LIST_ROWS = 500;               // shortlisted stories offered in a plan's dropdown, at most
const HELP_TAB = 'How to use';
const LISTS_TAB = 'lists';           // hidden: the dropdown lists of the plan tabs
const GONE = 'no longer in the digest';
// the story statuses, as in the Excel workbooks: [text colour, fill]
const STORY_STATUSES = ['To review', 'Shortlisted', 'Commissioned', 'Published', 'Not used'];
const STORY_STYLE = { 'To review': ['#4A5563', '#ECEFF3'], 'Shortlisted': ['#1D4FB8', '#DCE7FB'],
  'Commissioned': ['#8A5300', '#FBE6C2'], 'Published': ['#17663F', '#D3EDDF'], 'Not used': ['#7A8491', '#F1F2F4'] };
const IN_PLAN = ['Shortlisted', 'Commissioned', 'Published'];   // the stories a plan's dropdowns offer
// the statuses of a row of an issue plan
const PLAN_STATUSES = ['To do', 'Requested', 'Draft received', 'Edited', 'Ready', 'Dropped'];
const PLAN_STYLE = { 'To do': ['#4A5563', '#ECEFF3'], 'Requested': ['#1D4FB8', '#DCE7FB'],
  'Draft received': ['#8A5300', '#FBE6C2'], 'Edited': ['#5137B0', '#E7E1FA'], 'Ready': ['#17663F', '#D3EDDF'],
  'Dropped': ['#7A8491', '#F1F2F4'] };
const SOURCE_NAMES = { scanner: 'Scanner', society: 'Society', editor: 'Editor', mixed: 'Society + scanner' };
const TEAM_COLUMNS = ['Status', 'Assigned to', 'Editor notes'];
// [header, width in pixels]: the team's columns first, then the news desk's, the story id last (hidden)
const STORY_COLUMNS = [['Status', 120], ['Assigned to', 120], ['Editor notes', 220], ['Date', 92], ['Theme', 175],
  ['Rating', 58], ['Suggested use', 150], ['Headline', 380], ['Original headline', 260], ['Magazine angle', 340],
  ['Check with', 230], ['Source', 150], ['Country / place', 170], ['Developing story', 230], ['Kind', 58],
  ['Digest note', 190], ['Story id', 130]];
const STORY_WRAP = ['Editor notes', 'Magazine angle', 'Check with'];
const PROPOSED = 'Proposed story / contribution and contact';
const PLAN_COLUMNS = [['#', 36], ['Section', 230], ['Source', 120], ['Pages', 72], ['What goes here', 300],
  ['Slot', 90], [PROPOSED, 380], ['Assigned to', 130], ['Status', 120], ['Notes', 260]];
const PLAN_TEAM = [PROPOSED, 'Assigned to', 'Status', 'Notes'];
const PLAN_NAVY = '#16324F', PLAN_GOLD = '#F3E3B0';  // header colours: the news desk's columns, the team's

function setupPlanningSheet() {
  const props = PropertiesService.getScriptProperties();
  let ss = null;
  const id = (props.getProperty('SHEET_ID') || '').trim();
  if (id) {
    try {
      ss = SpreadsheetApp.openById(id);
    } catch (err) {
      Logger.log('The spreadsheet in the Script property SHEET_ID could not be opened (' + planMessage_(err) +
        '), so a new one is made.');
    }
  }
  if (!ss) {
    ss = SpreadsheetApp.create(PLAN_TITLE);
    props.setProperty('SHEET_ID', ss.getId());
  }
  ss.setSpreadsheetTimeZone(TIME_ZONE);
  // exactly one daily update, whatever was there before
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncPlanningSheet') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncPlanningSheet').timeBased().everyDays(1).atHour(PLAN_HOUR).inTimezone(TIME_ZONE).create();
  let first;
  try {
    first = syncPlanningSheet().summary;
  } catch (err) {
    first = 'The first update did not finish: ' + planMessage_(err) + ' The daily update tries again every morning, ' +
      'or run syncPlanningSheet once the problem is solved.';
  }
  const url = ss.getUrl();
  Logger.log('Planning sheet: ' + url + '\n' + first + '\nThe daily update runs at about ' + planHour_() + ' Cairo ' +
    'time. Next: open the address above, share the sheet with the editorial team (Share button, top right) and, if ' +
    'you like, paste the address into config.yaml under planning: sheet_url so the issue pages link to it.');
  return url;
}

function planHour_() {
  return ('0' + PLAN_HOUR).slice(-2) + ':00';
}

function syncPlanningSheet() {
  const ss = planSpreadsheet_();
  if (!planBegin_()) {
    Logger.log('Another update of the planning sheet is still running, so this one stops.');
    return { url: ss.getUrl(), summary: 'Skipped: another update was running.' };
  }
  try {
    const site = planSite_();
    const windows = planFetch_(site + 'exports/index.json', 'the list of issue windows');
    if (!Array.isArray(windows) || !windows.length) {
      throw new Error('The website lists no issue windows yet (' + site + 'exports/index.json), so there is nothing to add.');
    }
    const notes = [], problems = [];
    let layout = null, countries = {};
    try {
      layout = (planFetch_(site + 'exports/layout.json', 'the suggested issue layout') || {}).sections;
      if (!Array.isArray(layout) || !layout.length) throw new Error('The website\'s issue layout has no sections.');
    } catch (err) {
      layout = null;
      notes.push(planMessage_(err) + ' The plan tabs are left as they are.');
    }
    try {
      countries = planFetch_(site + 'exports/countries.json', 'the country names') || {};
    } catch (err) {
      countries = {};  // the country codes are shown instead
    }
    const help = planHelpTab_(ss, site);
    const synced = [];
    windows.slice(0, PLAN_WINDOWS).forEach(function (win, i) {
      if (!win || !/^\d{4}-Q[1-4]$/.test(String(win.key))) return;
      const label = String(win.label || win.key);
      try {
        const items = planFetch_(site + 'exports/' + win.key + '.json', 'the stories of ' + label);
        if (!Array.isArray(items)) throw new Error('the website did not give a list of stories.');
        const done = planStoriesTab_(ss, label, items, countries, 1 + 2 * i);
        synced.push({ label: label, index: 1 + 2 * i, done: done });
        notes.push(label + ': ' + done.added + ' new, ' + done.updated + ' refreshed' +
          (done.gone ? ', ' + done.gone + ' ' + GONE : '') + '.');
      } catch (err) {
        problems.push(label + ': ' + planMessage_(err));
      }
    });
    const lists = planLists_(ss, synced);
    if (layout) {
      synced.forEach(function (x) {
        notes.push(planIssueTab_(ss, x.label, layout, lists[x.label], x.index));
      });
    }
    const when = Utilities.formatDate(new Date(), TIME_ZONE, 'd MMM yyyy, HH:mm');
    help.getRange(3, 1).setValue('Last update: ' + when + ' (Cairo time)' +
      (problems.length ? ' — with problems: ' + problems.join(' ') : ''));
    const summary = 'Planning sheet updated: ' + notes.concat(problems).join(' ');
    Logger.log(summary);
    if (problems.length) throw new Error('The planning sheet was updated only in part. ' + problems.join(' '));
    return { url: ss.getUrl(), summary: summary };
  } finally {
    planEnd_();
  }
}

function planMessage_(err) {
  return String((err && err.message) || err);
}

function planSpreadsheet_() {
  const id = (PropertiesService.getScriptProperties().getProperty('SHEET_ID') || '').trim();
  if (!id) throw new Error('There is no planning sheet yet: run setupPlanningSheet once from the script editor.');
  try {
    return SpreadsheetApp.openById(id);
  } catch (err) {
    throw new Error('The planning sheet in the Script property SHEET_ID could not be opened (' + planMessage_(err) +
      '). Run setupPlanningSheet again to make a new one, or correct SHEET_ID.');
  }
}

function planSite_() {
  const url = (PropertiesService.getScriptProperties().getProperty('SITE_URL') || '').trim() || DEFAULT_SITE_URL;
  if (!/^https?:\/\//i.test(url)) {
    throw new Error('The Script property SITE_URL must be the website\'s address, starting with https://.');
  }
  return url.replace(/\/*$/, '/');
}

// The website's JSON at url, or an error that says what could not be read and why.
function planFetch_(url, what) {
  let res;
  try {
    res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  } catch (err) {
    throw new Error('The website could not be reached for ' + what + ' (' + url + '): ' + planMessage_(err) + '.');
  }
  const code = res.getResponseCode();
  if (code !== 200) {
    throw new Error('The website did not give ' + what + ' (' + url + ', HTTP ' + code + '). ' + (code === 404
      ? 'Check the Script property SITE_URL, or wait for the next rebuild of the website.' : 'Try again later.'));
  }
  try {
    return JSON.parse(res.getContentText('UTF-8'));
  } catch (err) {
    throw new Error(what + ' (' + url + ') could not be read: the website did not answer with JSON.');
  }
}

// One update at a time (the morning trigger and a manual run could meet). The script lock is held only for a moment,
// so a question to the assistant is never kept waiting; scripts stop after 6 minutes, so an older mark is stale.
function planBegin_() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return false;
  try {
    const props = PropertiesService.getScriptProperties();
    const since = Number(props.getProperty('PLAN_SYNC_RUNNING') || 0);
    if (since && Date.now() - since < 6 * 60 * 1000) return false;
    props.setProperty('PLAN_SYNC_RUNNING', String(Date.now()));
    return true;
  } finally {
    lock.releaseLock();
  }
}

function planEnd_() {
  PropertiesService.getScriptProperties().deleteProperty('PLAN_SYNC_RUNNING');
}

// Text for a cell: a value starting with = + - or @ would be read as a formula, so it is kept as text.
function planText_(value) {
  const text = String(value === null || value === undefined ? '' : value).replace(/\s+/g, ' ').trim().slice(0, 45000);
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}

function planLink_(url, label) {
  const text = String(label || url).replace(/\s+/g, ' ').trim().slice(0, 1000);
  return '=HYPERLINK("' + url.replace(/"/g, '%22') + '","' + text.replace(/"/g, '""') + '")';
}

function planId_(item) {
  return String(item.id || (item.kind === 'paper' && item.l ? 'paper:' + item.l : '')).trim();
}

function planColumnLetter_(n) {
  let s = '';
  for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s;
  return s;
}

// Enough rows (a new tab has 1000) for rows up to last.
function planRoom_(sh, last) {
  const max = sh.getMaxRows();
  if (last > max) sh.insertRowsAfter(max, last - max);
}

// {header: column number} for the tab's header row; the headers in spec that are missing (a new tab, or a column the
// team renamed or deleted) are added at the end, so the update never writes into a column it did not find by name.
function planColumns_(sh, spec, team, fresh) {
  if (fresh) {
    sh.getRange(1, 1, 1, spec.length).setValues([spec.map(function (s) { return s[0]; })]);
  }
  const width = Math.max(sh.getLastColumn(), 1);
  const head = sh.getRange(1, 1, 1, width).getValues()[0].map(function (v) { return String(v).trim(); });
  const cols = {};
  head.forEach(function (h, i) { if (h && !(h in cols)) cols[h] = i + 1; });
  let next = sh.getLastColumn() + 1;
  spec.forEach(function (s) {
    if (s[0] in cols) return;
    if (next > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), next - sh.getMaxColumns());
    sh.getRange(1, next).setValue(s[0]);
    cols[s[0]] = next++;
  });
  spec.forEach(function (s) {
    const cell = sh.getRange(1, cols[s[0]]);
    if (fresh || cols[s[0]] > width) {
      const ours = team.indexOf(s[0]) < 0;
      cell.setFontWeight('bold').setFontColor(ours ? '#FFFFFF' : PLAN_NAVY).setBackground(ours ? PLAN_NAVY : PLAN_GOLD)
        .setVerticalAlignment('middle');
      if (!ours) cell.setNote('The team\'s column: the daily update never changes it.');
      sh.setColumnWidth(cols[s[0]], s[1]);
    }
  });
  if (fresh) sh.setFrozenRows(1);
  return cols;
}

// What the news desk writes in a story's row: {header: value}. Headlines link to the article; a translated one is
// Claude's English translation, marked as such, with the original beside it. No publisher's text beyond headlines.
function planInfo_(item, countries) {
  const paper = item.kind === 'paper';
  const link = /^https?:\/\//i.test(String(item.l || '')) ? String(item.l) : '';
  const head = item.te ? item.te + ' (translated)' : String(item.t || '');
  const place = String(item.pl || '').trim();
  const country = String(countries[item.cc] || item.cc || '').trim();
  const where = place && country && place.toLowerCase().indexOf(country.toLowerCase()) >= 0 ? place
    : [place, country].filter(Boolean).join(', ');
  const check = paper ? 'the paper itself (DOI link)' + (item.au ? '; authors: ' + item.au : '') : item.ps;
  return {
    'Date': planText_(String(item.p || item.d || '').slice(0, 10)),
    'Theme': planText_(item.th),
    'Rating': Number(item.r) || '',
    'Suggested use': planText_(item.u),
    'Headline': link ? planLink_(link, head) : planText_(head),
    'Original headline': item.te ? planText_(item.t) : '',
    'Magazine angle': planText_(item.a),
    'Check with': planText_(check),
    'Source': planText_(item.s),
    'Country / place': planText_(where),
    'Developing story': item.sl ? planText_((item.st || 'Developing story') + (item.sg ? ' · ' + item.sg : '')) : '',
    'Kind': paper ? 'paper' : 'story',
    'Digest note': '',
    'Story id': planId_(item)
  };
}

// The "<quarter> stories" tab: new stories appended (the best rated first), the news desk's columns of the rows already
// there refreshed, stories gone from the website marked; the team's columns and any row without a story id untouched.
function planStoriesTab_(ss, label, items, countries, index) {
  const name = label + ' stories';
  let sh = ss.getSheetByName(name);
  const fresh = !sh;
  if (fresh) sh = ss.insertSheet(name, Math.min(index, ss.getSheets().length));
  const cols = planColumns_(sh, STORY_COLUMNS, TEAM_COLUMNS, fresh);
  if (fresh) sh.hideColumns(cols['Story id']);
  // one entry per story id (a story kept in two digests appears twice on the website: its best-ranked copy counts)
  const byId = {}, order = [];
  items.forEach(function (it) {
    const id = it && planId_(it);
    if (!id) return;
    if (!(id in byId)) order.push(id);
    if (!(id in byId) || (Number(it.rk) || 0) > (Number(byId[id].rk) || 0)) byId[id] = it;
  });
  const info = STORY_COLUMNS.map(function (s) { return s[0]; }).filter(function (h) { return TEAM_COLUMNS.indexOf(h) < 0; });
  const n = Math.max(sh.getLastRow() - 1, 0), width = sh.getLastColumn();
  const values = n ? sh.getRange(2, 1, n, width).getValues() : [];
  const formulas = n ? sh.getRange(2, 1, n, width).getFormulas() : [];
  const rowOf = {};
  values.forEach(function (row, r) {
    const id = String(row[cols['Story id'] - 1] || '').trim();
    if (id && !(id in rowOf)) rowOf[id] = r;
  });
  // the news desk's columns as they stand (formulas kept), then the new content for the rows of known stories
  const data = {};
  info.forEach(function (h) {
    const c = cols[h] - 1;
    data[h] = values.map(function (row, r) { return [formulas[r][c] || row[c]]; });
  });
  let updated = 0, gone = 0;
  const since = today();
  Object.keys(rowOf).forEach(function (id) {
    const r = rowOf[id];
    if (byId[id]) {
      const v = planInfo_(byId[id], countries);
      info.forEach(function (h) { data[h][r][0] = v[h]; });
      updated++;
    } else if (order.length) {  // an empty list from the website marks nothing
      if (String(data['Digest note'][r][0] || '').indexOf(GONE) < 0) data['Digest note'][r][0] = GONE + ' (since ' + since + ')';
      gone++;
    }
  });
  if (n) info.forEach(function (h) { sh.getRange(2, cols[h], n, 1).setValues(data[h]); });
  // new stories at the bottom: the best rated first, then the news desk's rank, then the newest
  const added = order.filter(function (id) { return !(id in rowOf); }).map(function (id) { return byId[id]; });
  added.sort(function (a, b) {
    return (Number(b.r) || 0) - (Number(a.r) || 0) || (Number(b.rk) || 0) - (Number(a.rk) || 0) ||
      String(b.p || b.d || '').localeCompare(String(a.p || a.d || ''));
  });
  const start = Math.max(sh.getLastRow(), 1) + 1;
  if (added.length) {
    planRoom_(sh, start + added.length - 1);
    sh.getRange(2, cols['Story id'], start + added.length - 2, 1).setNumberFormat('@');  // ids stay text
    const total = sh.getLastColumn();
    sh.getRange(start, 1, added.length, total).setValues(added.map(function (it) {
      const v = planInfo_(it, countries), row = [];
      for (let c = 0; c < total; c++) row.push('');
      Object.keys(cols).forEach(function (h) { if (h in v) row[cols[h] - 1] = v[h]; });
      row[cols['Status'] - 1] = STORY_STATUSES[0];
      return row;
    }));
  }
  planStoryFormats_(sh, cols);
  return { added: added.length, updated: updated, gone: gone, sheet: sh, cols: cols, byId: byId };
}

// Dropdowns, colours, wrapping and the filter over all the tab's rows (rebuilt each time, as rows are added).
function planStoryFormats_(sh, cols) {
  const last = Math.max(sh.getLastRow(), 2), rows = last - 1, width = sh.getLastColumn();
  sh.getRange(2, cols['Status'], rows, 1).setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInList(STORY_STATUSES, true).setAllowInvalid(false)
    .setHelpText('To review, Shortlisted, Commissioned, Published or Not used. Shortlisted stories (and those '
      + 'commissioned or published) are offered in the plan tab\'s dropdowns.').build());
  STORY_COLUMNS.forEach(function (s) {  // the update's columns only: a column the team adds keeps its own look
    sh.getRange(2, cols[s[0]], rows, 1).setVerticalAlignment('top').setWrapStrategy(STORY_WRAP.indexOf(s[0]) >= 0
      ? SpreadsheetApp.WrapStrategy.WRAP : SpreadsheetApp.WrapStrategy.CLIP);
  });
  sh.getRange(2, cols['Date'], rows, 1).setNumberFormat('d mmm yyyy');
  const status = sh.getRange(2, cols['Status'], rows, 1);
  const rules = STORY_STATUSES.map(function (s) {
    return SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(s).setFontColor(STORY_STYLE[s][0])
      .setBackground(STORY_STYLE[s][1]).setRanges([status]).build();
  });
  const note = planColumnLetter_(cols['Digest note']);
  rules.push(SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied('=REGEXMATCH($' + note + '2,"' + GONE + '")')
    .setFontColor('#98A2B0').setRanges([sh.getRange(2, 1, rows, width)]).build());
  planRules_(sh, rules);
  planFilter_(sh, last, width);
}

// Replaces the update's own conditional-format rules (a status colour, a story gone) and keeps the team's.
function planRules_(sh, rules) {
  const keep = sh.getConditionalFormatRules().filter(function (rule) {
    let values = [];
    try {
      const c = rule.getBooleanCondition();
      values = c ? c.getCriteriaValues().map(String) : [];
    } catch (err) { values = []; }
    return !values.some(function (v) {
      return STORY_STATUSES.indexOf(v) >= 0 || PLAN_STATUSES.indexOf(v) >= 0 || v.indexOf(GONE) >= 0;
    });
  });
  sh.setConditionalFormatRules(keep.concat(rules));
}

// A filter over the whole table; grown with the table, keeping the filters the team has set.
function planFilter_(sh, last, width) {
  const f = sh.getFilter();
  if (f) {
    const r = f.getRange();
    if (r.getRow() === 1 && r.getColumn() === 1 && r.getNumRows() >= last && r.getNumColumns() >= width) return;
    const criteria = {};
    for (let c = r.getColumn(); c < r.getColumn() + r.getNumColumns(); c++) {
      const k = f.getColumnFilterCriteria(c);
      if (k) criteria[c] = k;
    }
    f.remove();
    const nf = sh.getRange(1, 1, last, width).createFilter();
    Object.keys(criteria).forEach(function (c) { nf.setColumnFilterCriteria(Number(c), criteria[c]); });
  } else {
    sh.getRange(1, 1, last, width).createFilter();
  }
}

// The hidden "lists" tab: one column per quarter with the headlines of its stories whose Status is Shortlisted,
// Commissioned or Published (in that order), refreshed at each update. Returns {quarter: the range a plan's dropdown uses}.
function planLists_(ss, synced) {
  let sh = ss.getSheetByName(LISTS_TAB);
  if (!sh) {
    sh = ss.insertSheet(LISTS_TAB, ss.getSheets().length);
    sh.hideSheet();
  }
  planRoom_(sh, LIST_ROWS + 1);
  const width = Math.max(sh.getLastColumn(), 1);
  const head = sh.getRange(1, 1, 1, width).getValues()[0].map(function (v) { return String(v).trim(); });
  const out = {};
  synced.forEach(function (x) {
    const title = x.label + ' shortlisted';
    let c = head.indexOf(title) + 1;
    if (!c) {
      c = head.length === 1 && !head[0] ? 1 : head.length + 1;
      if (c > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), c - sh.getMaxColumns());
      sh.getRange(1, c).setValue(title).setFontWeight('bold');
      head[c - 1] = title;
    }
    const d = x.done, n = Math.max(d.sheet.getLastRow() - 1, 0);
    const picked = [];
    if (n) {
      const status = d.sheet.getRange(2, d.cols['Status'], n, 1).getValues();
      const ids = d.sheet.getRange(2, d.cols['Story id'], n, 1).getValues();
      const heads = d.sheet.getRange(2, d.cols['Headline'], n, 1).getValues();
      IN_PLAN.forEach(function (s) {
        status.forEach(function (v, r) {
          if (String(v[0]).trim() !== s) return;
          const it = d.byId[String(ids[r][0]).trim()];
          const text = planText_(it ? (it.te || it.t) : heads[r][0]);
          if (text && picked.indexOf(text) < 0) picked.push(text);
        });
      });
    }
    sh.getRange(2, c, LIST_ROWS, 1).clearContent();
    if (picked.length) {
      const list = picked.slice(0, LIST_ROWS);
      sh.getRange(2, c, list.length, 1).setValues(list.map(function (t) { return [t]; }));
    }
    out[x.label] = sh.getRange(2, c, LIST_ROWS, 1);
  });
  return out;
}

// The "<quarter> plan" tab: made once from the layout (one row per slot of a section the scanner fills, one
// "Contribution" row per society, editor or mixed section); later only its dropdowns are refreshed and rows added for
// sections (or slots) new to the layout. Nothing the team has typed is changed, and a row the team deletes stays
// deleted: the rows a plan has had are recorded in the hidden lists tab.
function planIssueTab_(ss, label, layout, listRange, index) {
  const name = label + ' plan';
  let sh = ss.getSheetByName(name);
  const fresh = !sh;
  if (fresh) sh = ss.insertSheet(name, Math.min(index, ss.getSheets().length));
  const cols = planColumns_(sh, PLAN_COLUMNS, PLAN_TEAM, fresh);
  const key = function (sectionName, slot) { return String(sectionName).replace(/\s+/g, ' ').trim() + '|' + slot; };
  const wanted = [];
  layout.forEach(function (sec, i) {
    if (!sec || !String(sec.name || '').trim()) return;
    const slots = Math.max(0, Math.min(Number(sec.slots) || 0, 50));
    for (let k = 1; k <= slots; k++) wanted.push({ sec: sec, n: i + 1, slot: 'Slot ' + k });
    if (sec.source !== 'scanner' || !slots) wanted.push({ sec: sec, n: i + 1, slot: 'Contribution' });
  });
  const n = Math.max(sh.getLastRow() - 1, 0);
  const have = {};
  if (n) {
    const secs = sh.getRange(2, cols['Section'], n, 1).getValues();
    const slots = sh.getRange(2, cols['Slot'], n, 1).getValues();
    secs.forEach(function (v, r) { have[key(v[0], String(slots[r][0]).trim())] = true; });
  }
  const known = planKnownRows_(ss, label);
  const seen = {};
  (known.keys.length ? known.keys : Object.keys(have)).forEach(function (k) { seen[k] = true; });
  const add = wanted.filter(function (w) {
    const k = key(w.sec.name, w.slot);
    return !seen[k] && !have[k];
  });
  const record = (known.keys.length ? [] : Object.keys(have)).concat(add.map(function (w) { return key(w.sec.name, w.slot); }));
  if (record.length) {
    const first = known.keys.length + 2;
    planRoom_(known.sheet, first + record.length - 1);
    known.sheet.getRange(first, known.col, record.length, 1).setValues(record.map(function (k) { return [planText_(k)]; }));
  }
  if (add.length) {
    const start = Math.max(sh.getLastRow(), 1) + 1;
    planRoom_(sh, start + add.length - 1);
    const total = sh.getLastColumn();
    sh.getRange(start, 1, add.length, total).setValues(add.map(function (w) {
      const row = [];
      for (let c = 0; c < total; c++) row.push('');
      const put = function (h, v) { if (cols[h]) row[cols[h] - 1] = v; };
      put('#', w.n);
      put('Section', planText_(w.sec.name));
      put('Source', SOURCE_NAMES[w.sec.source] || planText_(w.sec.source));
      put('Pages', planText_(w.sec.pages));
      put('What goes here', planText_(w.sec.use));
      put('Slot', w.slot);
      put('Status', PLAN_STATUSES[0]);
      return row;
    }));
  }
  const last = sh.getLastRow();
  if (last >= 2) {
    const rows = last - 1;
    if (listRange) {  // the proposed story of each slot: the quarter's shortlisted stories, or a text of the team's own
      const rule = SpreadsheetApp.newDataValidation().requireValueInRange(listRange, true).setAllowInvalid(true)
        .setHelpText('Choose one of the quarter\'s shortlisted stories (Status Shortlisted, Commissioned or Published ' +
          'in the stories tab), or type your own.').build();
      const slots = sh.getRange(2, cols['Slot'], rows, 1).getValues();
      let from = -1;
      for (let r = 0; r <= rows; r++) {  // one call per run of slot rows
        const isSlot = r < rows && /^Slot \d+$/.test(String(slots[r][0]).trim());
        if (isSlot && from < 0) from = r;
        if (!isSlot && from >= 0) {
          sh.getRange(2 + from, cols[PROPOSED], r - from, 1).setDataValidation(rule);
          from = -1;
        }
      }
    }
    const status = sh.getRange(2, cols['Status'], rows, 1);
    status.setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(PLAN_STATUSES, true)
      .setAllowInvalid(false).build());
    if (fresh || add.length) {
      PLAN_COLUMNS.forEach(function (s) {
        sh.getRange(2, cols[s[0]], rows, 1).setVerticalAlignment('top').setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
      });
      planRules_(sh, PLAN_STATUSES.map(function (s) {
        return SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(s).setFontColor(PLAN_STYLE[s][0])
          .setBackground(PLAN_STYLE[s][1]).setRanges([status]).build();
      }));
    }
  }
  return name + ': ' + (fresh ? 'made from the layout (' + add.length + ' rows).' :
    (add.length ? add.length + ' rows added for new sections of the layout.' : 'unchanged.'));
}

// The rows ("section|slot") a quarter's plan has had, from its column in the hidden lists tab.
function planKnownRows_(ss, label) {
  const sh = ss.getSheetByName(LISTS_TAB);
  const title = label + ' plan rows';
  const width = Math.max(sh.getLastColumn(), 1);
  const head = sh.getRange(1, 1, 1, width).getValues()[0].map(function (v) { return String(v).trim(); });
  let col = head.indexOf(title) + 1;
  if (!col) {
    col = head.length === 1 && !head[0] ? 1 : head.length + 1;
    if (col > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), col - sh.getMaxColumns());
    sh.getRange(1, col).setValue(title).setFontWeight('bold');
  }
  const n = Math.max(sh.getLastRow() - 1, 0);
  const keys = n ? sh.getRange(2, col, n, 1).getValues().map(function (v) { return String(v[0]).trim(); })
    .filter(function (k) { return k; }) : [];
  return { sheet: sh, col: col, keys: keys };
}

// The first tab: what the sheet is for and how the update treats the team's work (written once), and the time of
// the last update (row 3, each time).
function planHelpTab_(ss, site) {
  let sh = ss.getSheetByName(HELP_TAB);
  if (sh) return sh;
  const sheets = ss.getSheets();
  if (sheets.length === 1 && sheets[0].getLastRow() === 0 && sheets[0].getLastColumn() === 0) {
    sh = sheets[0];  // a new spreadsheet's empty first tab
    sh.setName(HELP_TAB);
  } else {
    sh = ss.insertSheet(HELP_TAB, 0);
  }
  const lines = [
    PLAN_TITLE,
    'The editorial team\'s shared sheet for planning each issue of the ISSMGE Magazine, kept up to date from ' + site,
    'Last update: not yet',
    '',
    'Stories tabs ("Q4 2026 stories" and so on)',
    '• Every story and research paper the news desk collected in the quarter, updated every morning at about ' +
      planHour_() + ' Cairo time. New stories are added at the bottom, the best rated first; sort and filter ' +
      'with the buttons in the header row.',
    '• Status, Assigned to and Editor notes (gold headers) are yours: the update never changes them, nor any column ' +
      'you add. Choose a Status from its dropdown: To review, Shortlisted, Commissioned, Published or Not used.',
    '• The other columns are the news desk\'s and are refreshed every morning. A story no longer in the digest stays, ' +
      'marked in Digest note. Do not delete rows: set the Status to Not used (a deleted row comes back the next morning).',
    '• Headline links to the article. A headline marked (translated) is Claude\'s English translation; the original ' +
      'is beside it. Check with names the primary source to check the facts with.',
    '',
    'Plan tabs ("Q4 2026 plan" and so on)',
    '• One row for each section of the suggested issue layout (config.yaml, issue_layout), with a row per item for ' +
      'the sections the news desk fills. Pick the proposed story from the dropdown, which lists the quarter\'s stories ' +
      'marked Shortlisted (or Commissioned or Published), or type your own; give society and editor sections a ' +
      'contribution and a contact.',
    '• The plan is made once. Later updates only refresh the dropdowns and add rows for sections added to the layout.',
    '',
    'Before you use a story',
    '1. Treat the news item as a lead, not as your source.  2. Check the facts with the primary source (Check with).  ' +
      '3. Write the piece in your own words.  4. Quote a sentence or two at most, naming and linking the publication.  ' +
      '5. For images, use your own, the project\'s press-kit photos released for media use, or ask permission.'
  ];
  sh.getRange(1, 1, lines.length, 1).setValues(lines.map(function (t) { return [t]; }));
  sh.getRange(1, 1).setFontWeight('bold').setFontSize(14).setFontColor(PLAN_NAVY);
  [5, 11, 15].forEach(function (r) { sh.getRange(r, 1).setFontWeight('bold').setFontColor(PLAN_NAVY); });
  sh.getRange(3, 1).setFontColor('#5B6573');
  sh.setColumnWidth(1, 900);
  sh.getRange(1, 1, lines.length, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  return sh;
}
