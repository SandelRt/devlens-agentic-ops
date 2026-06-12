/**
 * DevLens — Chat UI JavaScript
 * Agentic Observability for Developers
 *
 * Handles:
 * - Chat message rendering
 * - Calls to the DevLens REST API (/services/devlens/investigate)
 * - Animated "thinking" state while the agent works
 * - SPL copy-to-clipboard
 * - Auto-expanding textarea
 * - Keyboard shortcuts (Enter to send, Shift+Enter for newline)
 */

'use strict';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const CONFIG = {
  // In Splunk, this points to the custom REST handler
  // For standalone demo, we mock the response
  API_ENDPOINT: '/en-US/splunkd/__raw/services/devlens/investigate',
  DEMO_MODE: false,  // true = canned responses (standalone preview) | false = live Splunk REST API
  DEFAULT_TIMERANGE: '-1h',
  DEFAULT_INDEX: '*',
  TYPING_DELAY: 80,  // ms between chars in simulated typing
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  isInvestigating: false,
  currentTimerange: CONFIG.DEFAULT_TIMERANGE,
  currentIndex: CONFIG.DEFAULT_INDEX,
  conversationHistory: [],
};

// ---------------------------------------------------------------------------
// DOM refs (cached on first access)
// ---------------------------------------------------------------------------
const dom = {
  get chatFeed()      { return document.getElementById('chatFeed'); },
  get emptyState()    { return document.getElementById('emptyState'); },
  get questionInput() { return document.getElementById('questionInput'); },
  get sendBtn()       { return document.getElementById('sendBtn'); },
  get currentIndex()  { return document.getElementById('currentIndex'); },
  get statusPill()    { return document.getElementById('statusPill'); },
};

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  setupTextarea();
  setupTimeButtons();
  setupKeyboardShortcuts();

  // Update index display
  dom.currentIndex.textContent = state.currentIndex;

  // Check connection in non-demo mode
  if (!CONFIG.DEMO_MODE) {
    checkSplunkConnection();
  }
});

// ---------------------------------------------------------------------------
// Main investigation flow
// ---------------------------------------------------------------------------
async function investigate() {
  const question = dom.questionInput.value.trim();
  if (!question || state.isInvestigating) return;

  state.isInvestigating = true;
  setButtonState('loading');

  // Hide empty state, show chat feed
  dom.emptyState.style.display = 'none';
  dom.chatFeed.style.display = 'flex';

  // Render user message
  appendUserMessage(question);
  dom.questionInput.value = '';
  resizeTextarea(dom.questionInput);

  // Render "thinking" state
  const thinkingEl = appendThinkingMessage();

  try {
    let result;

    if (CONFIG.DEMO_MODE) {
      // Simulate the agentic investigation with realistic delays
      result = await simulateDemoInvestigation(question, thinkingEl);
    } else {
      // Real call to DevLens REST API in Splunk
      result = await callDevLensAPI(question, thinkingEl);
    }

    // Remove thinking indicator
    thinkingEl.remove();

    // Render the agent's answer
    appendAgentMessage(result);

    // Store in history
    state.conversationHistory.push({ role: 'user', content: question });
    state.conversationHistory.push({ role: 'agent', content: result.answer });

  } catch (err) {
    thinkingEl.remove();
    appendErrorMessage(`Investigation failed: ${err.message}. Check that DevLens is properly installed and Splunk is running.`);
  } finally {
    state.isInvestigating = false;
    setButtonState('ready');
    dom.questionInput.focus();
  }
}

// ---------------------------------------------------------------------------
// API call (production mode)
// ---------------------------------------------------------------------------
async function callDevLensAPI(question, thinkingEl) {
  updateThinkingStep(thinkingEl, 'plan', 'done');
  updateThinkingStep(thinkingEl, 'query', 'active');

  const formData = new URLSearchParams({
    question,
    timerange: state.currentTimerange,
    index: state.currentIndex,
    output_mode: 'json',
  });

  const response = await fetch(CONFIG.API_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData,
    credentials: 'same-origin',
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  const raw = await response.json();
  const data = JSON.parse(raw.entry?.[0]?.content?.data || raw.data || '{}');

  updateThinkingStep(thinkingEl, 'query', 'done');
  updateThinkingStep(thinkingEl, 'analyze', 'done');
  updateThinkingStep(thinkingEl, 'synthesize', 'done');

  return data;
}

// ---------------------------------------------------------------------------
// Demo simulation (shows the agentic loop in action)
// ---------------------------------------------------------------------------
async function simulateDemoInvestigation(question, thinkingEl) {
  const DEMO_RESPONSES = getDemoResponses(question);

  await sleep(600);
  updateThinkingStep(thinkingEl, 'plan', 'done');
  addThinkingStep(thinkingEl, 'query-1', `🔍 Running: ${DEMO_RESPONSES.queries[0].slice(0, 60)}...`);

  await sleep(900);
  updateThinkingStep(thinkingEl, 'query-1', 'done');
  addThinkingStep(thinkingEl, 'obs-1', '📊 Analyzing search results...');

  await sleep(700);
  updateThinkingStep(thinkingEl, 'obs-1', 'done');

  if (DEMO_RESPONSES.queries.length > 1) {
    addThinkingStep(thinkingEl, 'query-2', `🔍 Digging deeper: ${DEMO_RESPONSES.queries[1].slice(0, 55)}...`);
    await sleep(850);
    updateThinkingStep(thinkingEl, 'query-2', 'done');
    addThinkingStep(thinkingEl, 'obs-2', '📊 Correlating with deployment events...');
    await sleep(600);
    updateThinkingStep(thinkingEl, 'obs-2', 'done');
  }

  addThinkingStep(thinkingEl, 'synthesize', '🧩 Synthesizing root cause analysis...');
  await sleep(800);
  updateThinkingStep(thinkingEl, 'synthesize', 'done');

  return DEMO_RESPONSES;
}

function getDemoResponses(question) {
  const q = question.toLowerCase();

  if (q.includes('slow') || q.includes('latency') || q.includes('response')) {
    return {
      question,
      answer: `**Root Cause: Latency regression in \`payment-svc\` after v2.4.1 deployment**\n\nInvestigation found that p99 response times for \`payment-svc\` increased from **320ms → 2,840ms** at 14:23 UTC, correlating exactly with the v2.4.1 deployment. The primary bottleneck is the \`/checkout/finalize\` endpoint, which shows a 9× slowdown in database query execution (avg query time rose from 18ms → 164ms).\n\nThe \`payment_items\` table is missing an index on \`(user_id, status)\` — added in the query pattern introduced in v2.4.1 but the migration was not applied to production.`,
      confidence: 0.92,
      queries_run: [
        { spl: "status>=200 | stats p99(response_time_ms) as p99_ms by service | sort -p99_ms | head 10", rows: 8 },
        { spl: "service=payment-svc | timechart span=5m avg(response_time_ms) as avg_ms, count as requests", rows: 24 },
      ],
      evidence: [
        "payment-svc p99 latency: 2,840ms (baseline: 320ms) — 9× spike",
        "/checkout/finalize: avg_ms = 1,890ms across 4,200 requests in the last hour",
        "Latency spike started at 14:23 UTC, matching deployment timestamp",
        "DB query time: avg 164ms (was 18ms) — missing index on payment_items(user_id, status)",
      ],
      recommendations: [
        "Apply the missing database index migration: `CREATE INDEX idx_payment_items_user_status ON payment_items (user_id, status);`",
        "Consider rolling back v2.4.1 to payment-svc while the migration is applied",
        "Add p99 latency alert (threshold: 1000ms) to catch regressions before they impact users",
        "Run `EXPLAIN ANALYZE` on the slow query to confirm index is used after migration",
      ],
      spl_to_monitor: "index=* service=payment-svc | stats p99(response_time_ms) as p99_ms | where p99_ms > 1000",
      status: "complete",
      iterations: 2,
    };
  }

  if (q.includes('error') || q.includes('500') || q.includes('fail')) {
    return {
      question,
      answer: `**Root Cause: \`inventory-api\` throwing 500s due to Redis connection pool exhaustion**\n\nDetected **1,847 HTTP 500 errors** from \`inventory-api\` in the last hour (error rate: 12.7%). All errors originate from the \`/api/stock/check\` endpoint. Stack traces in Splunk show \`redis.exceptions.ConnectionError: max connections exceeded\`.\n\nThe Redis max_connections pool is set to 10 in the config. Under current traffic (≈145 req/s), the pool is overwhelmed. This started 23 minutes ago, coinciding with a marketing campaign that increased product page traffic by 4×.`,
      confidence: 0.95,
      queries_run: [
        { spl: "status>=500 | stats count as errors, dc(user_id) as users_affected by service, uri_path | sort -errors | head 10", rows: 12 },
        { spl: "service=inventory-api error_message=* | stats count by error_message | sort -count | head 5", rows: 3 },
      ],
      evidence: [
        "inventory-api: 1,847 errors in last 60 min (12.7% error rate)",
        "/api/stock/check accounts for 98% of all 500s",
        "Error message: 'redis.exceptions.ConnectionError: max connections exceeded' (1,802 occurrences)",
        "Traffic to inventory-api increased 4× at 18:40 UTC (marketing campaign launch)",
        "3,240 unique users affected",
      ],
      recommendations: [
        "Increase Redis connection pool size: set `REDIS_MAX_CONNECTIONS=50` in inventory-api config and restart",
        "Add connection pool metrics to Splunk monitoring dashboard",
        "Implement circuit breaker for Redis calls to prevent cascading failures",
        "Set up auto-scaling for inventory-api when RPS exceeds 100",
      ],
      spl_to_monitor: "index=* service=inventory-api status>=500 | stats count as errors | where errors > 50",
      status: "complete",
      iterations: 2,
    };
  }

  if (q.includes('deploy') || q.includes('release') || q.includes('version')) {
    return {
      question,
      answer: `**Root Cause: v2.3.5 deployment to \`checkout-api\` introduced regression in cart calculation logic**\n\nComparing pre-deployment (14:00-15:00 UTC) vs post-deployment (15:00-16:00 UTC) metrics:\n- Error rate: 0.1% → 4.3% (43× increase)\n- P99 latency: 240ms → 890ms (3.7× increase)\n- Affected endpoint: \`POST /cart/calculate\`\n\nThe regression appears to be in the tax calculation module — 100% of 500s include \`TaxCalculationException: negative tax value\` in the stack trace, likely a rounding edge case in the new localization logic.`,
      confidence: 0.89,
      queries_run: [
        { spl: "index=* | eval period=if(_time>1749812400,'post','pre') | stats count(eval(status>=500)) as errors, count as total by service, version, period | eval error_pct=round(errors/total*100,2)", rows: 18 },
        { spl: "service=checkout-api version=v2.3.5 status>=500 error_message=* | stats count by error_message", rows: 4 },
      ],
      evidence: [
        "checkout-api error rate pre-deploy: 0.1% | post-deploy: 4.3%",
        "P99 latency pre-deploy: 240ms | post-deploy: 890ms",
        "All 500s contain: 'TaxCalculationException: negative tax value'",
        "v2.3.4 is healthy (0.08% error rate on other hosts)",
        "867 users encountered checkout errors in the last 30 min",
      ],
      recommendations: [
        "Roll back checkout-api to v2.3.4 immediately to restore service",
        "Investigate the tax calculation edge case in `TaxCalculationService.calculateTotal()` — likely a currency rounding issue with certain locales",
        "Add unit tests covering negative tax edge cases before re-deploying",
        "Implement automatic rollback when post-deploy error rate > 2% within 10 minutes",
      ],
      spl_to_monitor: "index=* service=checkout-api | stats count(eval(status>=500)) as errors, count as total | eval error_pct=round(errors/total*100,2) | where error_pct > 2",
      status: "complete",
      iterations: 2,
    };
  }

  // Generic fallback
  return {
    question,
    answer: `**Investigation Complete** (2 iterations, confidence: 78%)\n\nDevLens analyzed your Splunk data using the Cisco Foundation AI model and Splunk MCP Server tools. Based on the data in the last hour:\n\n- **Overall system health**: 96.2% (4 services healthy, 1 degraded)\n- **Error rate**: 1.3% across all services\n- **P99 latency**: 420ms (within normal range)\n- **Active anomalies**: payment-svc showing elevated latency (p99: 2,100ms)\n\nFor a more specific analysis, try asking about a particular service or symptom.`,
    confidence: 0.78,
    queries_run: [
      { spl: "| stats count as requests, count(eval(status>=500)) as errors, avg(response_time_ms) as avg_ms by service | eval health=round((1-errors/requests)*100,1)", rows: 6 },
    ],
    evidence: [
      "6 active services reporting telemetry",
      "Overall error rate: 1.3% (threshold: 5%)",
      "payment-svc p99 latency: 2,100ms (elevated)",
    ],
    recommendations: [
      "Investigate payment-svc elevated latency (p99: 2,100ms vs baseline 340ms)",
      "Set up latency alerts for services exceeding your SLO targets",
      "Enable Splunk AI Agent Monitoring to track this agent's performance",
    ],
    spl_to_monitor: "index=* | stats count(eval(status>=500)) as errors, count as total | eval error_pct=round(errors/total*100,2)",
    status: "complete",
    iterations: 1,
  };
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------
function appendUserMessage(text) {
  const template = document.getElementById('userMsgTemplate');
  const clone = template.content.cloneNode(true);

  clone.querySelector('.dl-msg-text').textContent = text;
  clone.querySelector('.dl-msg-meta').textContent = formatTime(new Date());

  dom.chatFeed.appendChild(clone);
  scrollToBottom();
}

function appendThinkingMessage() {
  const template = document.getElementById('thinkingTemplate');
  const clone = template.content.cloneNode(true);
  const el = clone.firstElementChild || clone.querySelector('.dl-msg-thinking');

  // We need a real DOM element to return and manipulate
  const wrapper = document.createElement('div');
  wrapper.innerHTML = `
    <div class="dl-msg dl-msg-agent dl-msg-thinking" id="thinkingMsg_${Date.now()}">
      <div class="dl-msg-avatar dl-avatar-agent">🔭</div>
      <div class="dl-msg-content">
        <div class="dl-msg-text">
          <div class="dl-thinking-steps" id="thinkingSteps">
            <div class="dl-thinking-step active" data-step-id="plan">🧠 Planning investigation strategy...</div>
          </div>
        </div>
      </div>
    </div>
  `;
  const msgEl = wrapper.firstElementChild;
  dom.chatFeed.appendChild(msgEl);
  scrollToBottom();
  return msgEl;
}

function addThinkingStep(thinkingEl, stepId, text) {
  const steps = thinkingEl.querySelector('.dl-thinking-steps');
  const div = document.createElement('div');
  div.className = 'dl-thinking-step active';
  div.dataset.stepId = stepId;
  div.textContent = text;
  steps.appendChild(div);
  scrollToBottom();
}

function updateThinkingStep(thinkingEl, stepId, status) {
  const step = thinkingEl.querySelector(`[data-step-id="${stepId}"]`);
  if (!step) return;
  step.className = `dl-thinking-step ${status}`;
  if (status === 'done') {
    step.textContent = '✓ ' + step.textContent.replace(/^[^\s]+\s/, '');
  }
}

function appendAgentMessage(result) {
  const template = document.getElementById('agentMsgTemplate');
  const clone = template.content.cloneNode(true);
  const msgEl = clone.querySelector('.dl-msg');

  // Render main answer (support basic markdown-like bold)
  const textEl = clone.querySelector('.dl-msg-text');
  textEl.innerHTML = renderMarkdown(result.answer || 'No response received.');

  // Confidence bar
  if (result.confidence !== undefined) {
    const conf = result.confidence;
    const confClass = conf >= 0.8 ? 'high' : conf >= 0.5 ? 'med' : 'low';
    const confPct = Math.round(conf * 100);
    const confBar = document.createElement('div');
    confBar.className = 'dl-confidence-bar';
    confBar.innerHTML = `
      <span class="dl-confidence-label">Confidence</span>
      <div class="dl-confidence-track">
        <div class="dl-confidence-fill ${confClass}" style="width: ${confPct}%"></div>
      </div>
      <span style="font-size:11px;color:var(--dl-text-secondary);min-width:32px">${confPct}%</span>
    `;
    textEl.after(confBar);
  }

  // Evidence panel
  if (result.evidence && result.evidence.length > 0) {
    const evidEl = clone.querySelector('.dl-msg-evidence');
    evidEl.style.display = 'block';
    evidEl.innerHTML = `<div class="dl-evidence-title">📋 Evidence</div>` +
      result.evidence.map(e => `
        <div class="dl-evidence-item">
          <span class="dl-evidence-bullet">▸</span>
          <span>${escapeHtml(e)}</span>
        </div>
      `).join('');
  }

  // SPL Queries run
  if (result.queries_run && result.queries_run.length > 0) {
    const queriesEl = clone.querySelector('.dl-msg-queries');
    queriesEl.style.display = 'block';

    const spl = result.queries_run.map(q => q.spl).join('\n\n');
    queriesEl.innerHTML = `
      <div class="dl-query-header">
        <span class="dl-query-label">🔍 SPL Queries Run (${result.queries_run.length})</span>
        <button class="dl-query-copy" onclick="copyToClipboard('${escapeHtml(spl)}', this)">Copy</button>
      </div>
      <pre class="dl-query-code">${result.queries_run.map((q, i) => `-- Query ${i+1} (${q.rows ?? '?'} rows)\n${escapeHtml(q.spl)}`).join('\n\n')}</pre>
    `;
  }

  // Recommendations
  if (result.recommendations && result.recommendations.length > 0) {
    const recEl = clone.querySelector('.dl-msg-recommendations');
    recEl.style.display = 'block';
    recEl.innerHTML = `<div class="dl-rec-title">✅ Recommendations</div>` +
      result.recommendations.map((r, i) => `
        <div class="dl-rec-item">
          <span class="dl-rec-num">${i + 1}.</span>
          <span>${renderMarkdown(r)}</span>
        </div>
      `).join('');
  }

  // Monitoring SPL
  if (result.spl_to_monitor) {
    const monEl = clone.querySelector('.dl-msg-monitor-spl');
    monEl.style.display = 'block';
    monEl.innerHTML = `
      <div class="dl-monitor-label"><strong>💾 Save as Alert:</strong> Run this in Splunk to monitor ongoing:</div>
      <div class="dl-monitor-code" onclick="copyToClipboard('${escapeHtml(result.spl_to_monitor)}', this)" title="Click to copy">
        ${escapeHtml(result.spl_to_monitor)}
      </div>
    `;
  }

  // Meta
  const metaEl = clone.querySelector('.dl-msg-meta');
  metaEl.textContent = `${formatTime(new Date())} · ${result.iterations ?? 1} iteration(s) · Splunk Hosted Models`;

  dom.chatFeed.appendChild(clone);
  scrollToBottom();
}

function appendErrorMessage(message) {
  const div = document.createElement('div');
  div.className = 'dl-msg dl-msg-agent';
  div.innerHTML = `
    <div class="dl-msg-avatar dl-avatar-agent">🔭</div>
    <div class="dl-msg-content">
      <div class="dl-msg-text" style="border-color:var(--dl-red);background:var(--dl-red-muted);">
        ⚠️ ${escapeHtml(message)}
      </div>
    </div>
  `;
  dom.chatFeed.appendChild(div);
  scrollToBottom();
}

// ---------------------------------------------------------------------------
// Suggestion chips
// ---------------------------------------------------------------------------
function prefillQuestion(btn) {
  dom.questionInput.value = btn.textContent.trim();
  dom.questionInput.focus();
  resizeTextarea(dom.questionInput);
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function setButtonState(state) {
  const btn = dom.sendBtn;
  if (state === 'loading') {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span><span>Investigating...</span>';
  } else {
    btn.disabled = false;
    btn.innerHTML = '<span class="dl-send-icon">▶</span><span>Investigate</span>';
  }
}

function setupTextarea() {
  const ta = dom.questionInput;
  ta.addEventListener('input', () => resizeTextarea(ta));
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      investigate();
    }
  });
}

function resizeTextarea(ta) {
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 140) + 'px';
}

function setupTimeButtons() {
  document.querySelectorAll('.dl-time-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.dl-time-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentTimerange = btn.dataset.range;
    });
  });
}

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Ctrl+K or Cmd+K to focus input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      dom.questionInput.focus();
      dom.questionInput.select();
    }
  });
}

async function checkSplunkConnection() {
  try {
    const resp = await fetch('/en-US/splunkd/__raw/services/server/info?output_mode=json', {
      credentials: 'same-origin',
    });
    if (resp.ok) {
      updateStatus('online', 'Splunk Connected');
    } else {
      updateStatus('offline', 'Splunk Offline');
    }
  } catch {
    updateStatus('offline', 'Splunk Offline');
  }
}

function updateStatus(status, text) {
  const pill = dom.statusPill;
  const dot = pill.querySelector('.dl-status-dot');
  dot.className = 'dl-status-dot ' + status;
  pill.querySelector('span:last-child').textContent = text;
}

function scrollToBottom() {
  const feed = dom.chatFeed;
  feed.scrollTop = feed.scrollHeight;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function formatTime(date) {
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderMarkdown(text) {
  // Basic markdown: **bold**, `code`, line breaks
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="font-family:var(--dl-font-mono);color:var(--dl-text-code);background:var(--dl-bg-primary);padding:1px 4px;border-radius:3px">$1</code>')
    .replace(/\n/g, '<br>');
}

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const orig = btn.textContent || btn.innerHTML;
    if (btn.tagName === 'BUTTON') {
      btn.textContent = 'Copied!';
      setTimeout(() => btn.textContent = 'Copy', 2000);
    } else {
      const origColor = btn.style.color;
      btn.style.color = 'var(--dl-green)';
      setTimeout(() => btn.style.color = origColor, 1500);
    }
  } catch (e) {
    console.error('Copy failed:', e);
  }
}
