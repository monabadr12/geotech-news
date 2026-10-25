/**
 * Geotechnical News Desk — AI assistant bridge and e-mail sender (Google Apps Script)
 *
 * The website is public, so it cannot hold an API key. This small script runs in your own Google
 * account instead: the website sends each question here, the script adds your Anthropic key (read
 * from your private Google Doc) and passes the question to Claude. The key never reaches the website
 * or the repository. It also e-mails the news desk's alerts and weekly summary from your account once
 * the Script property NOTIFY_TOKEN is set (the same text as the GitHub secret NOTIFY_TOKEN); MAIL_TO
 * (optional) lists the recipients. See "E-mail" below. Setup: "AI assistant" in the repository README.
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
