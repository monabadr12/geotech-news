/**
 * Geotechnical News Desk — AI assistant bridge (Google Apps Script)
 *
 * The website is public, so it cannot hold an API key. This small script runs in
 * your own Google account instead: the website sends each question here, the
 * script adds your Anthropic key (read from your private Google Doc) and passes
 * the question to Claude. The key never reaches the website or the repository.
 *
 * Set up once (about 5 minutes) — see "AI assistant" in the repository README.
 */

// The Google Doc that holds your Anthropic key (paste its link or ID). The key is
// found anywhere in the document as the text starting with "sk-ant-".
// Alternatively set a Script property named ANTHROPIC_API_KEY (Project Settings).
const KEY_DOC = 'PASTE-THE-LINK-TO-YOUR-KEY-DOCUMENT-HERE';

const DEFAULT_MODEL = 'claude-opus-5-5';
const MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'];
const MAX_TOKENS = 4000;
const DAILY_LIMIT = 100;            // questions per day (Cairo time): protects your Anthropic bill
const MAX_REQUEST_MB = 25;          // largest question + attachments accepted
const TIME_ZONE = 'Africa/Cairo';

function doGet() {
  let keyFound = false, problem = '';
  try { keyFound = !!apiKey(); } catch (err) { problem = String(err.message || err); }
  return reply({
    ok: keyFound, service: 'Geotechnical News Desk assistant bridge', problem: problem,
    dailyLimit: DAILY_LIMIT, usedToday: usedToday(), passcode: !!accessCode()
  });
}

function doPost(e) {
  try {
    const raw = (e && e.postData && e.postData.contents) || '';
    if (raw.length > MAX_REQUEST_MB * 1024 * 1024) {
      return reply({ error: 'This question and its attachments are larger than ' + MAX_REQUEST_MB + ' MB.' });
    }
    const req = JSON.parse(raw);
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
    const id = (KEY_DOC.match(/[-\w]{25,}/) || [])[0];
    if (!id) throw new Error('KEY_DOC is not set: paste the link of the Google Doc that holds your key at the top of the script.');
    const text = DocumentApp.openById(id).getBody().getText();
    const m = text.match(/sk-ant-[A-Za-z0-9_\-]{20,}/);
    if (!m) throw new Error('No Anthropic key (text starting with sk-ant-) was found in the Google Doc.');
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

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// Run this once from the editor (select "testConnection", press Run) to check the setup.
function testConnection() {
  const res = callClaude({ model: 'claude-haiku-5-5', max_tokens: 1000, output_config: { effort: 'low' },
    messages: [{ role: 'user', content: 'Reply with the single word: connected' }] }, false);
  Logger.log('HTTP ' + res.code + ': ' + res.text.slice(0, 300));
}
