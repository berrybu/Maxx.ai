// Maxx frontend logic: knowledge-graph visualization + Agent activity stream + actions
const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  setTimeout(() => (t.hidden = true), 2600);
}

const esc = (s) => (s == null ? "" : String(s)).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// ---------- Cytoscape ----------
let cy;
let GRAPH = { nodes: [], edges: [] };
const nodeLabel = (id) => { const n = GRAPH.nodes.find((x) => x.id === id); return n ? n.label : id; };
const NODE_COLORS = { person: "#0071e3", company: "#34c759", us_company: "#30b0c7", employee: "#5e5ce6", email_thread: "#ff9f0a", topic: "#af52de", industry: "#8e8e93", product: "#ff2d92" };

const GRAPH_LAYOUT = { name: "cose", animate: true, padding: 55, nodeRepulsion: 14000, idealEdgeLength: 125, edgeElasticity: 90, gravity: 0.22, nodeOverlap: 28, componentSpacing: 150, numIter: 1500, coolingFactor: 0.95, randomize: true };

function initCy() {
  cy = cytoscape({
    container: $("cy"),
    style: [
      { selector: "node", style: {
        "background-color": (n) => NODE_COLORS[n.data("type")] || "#8e8e93",
        "border-width": 3, "border-color": "#ffffff", "border-opacity": 1,
        label: "data(label)", color: "#1d1d1f", "font-size": 11,
        "font-family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif", "font-weight": 500,
        "text-valign": "bottom", "text-margin-y": 7, width: 34, height: 34,
        "text-wrap": "wrap", "text-max-width": 96,
        "transition-property": "border-color, border-width, background-color", "transition-duration": "0.18s",
      }},
      { selector: 'node[type="company"]', style: { width: 48, height: 48, shape: "round-rectangle" } },
      { selector: 'node[type="us_company"]', style: { width: 54, height: 54, shape: "round-rectangle", "border-color": "#30b0c7", "border-width": 4 } },
      { selector: 'node[type="employee"]', style: { shape: "star", width: 34, height: 34 } },
      { selector: 'node[type="email_thread"]', style: { shape: "diamond", width: 28, height: 28 } },
      { selector: "node:selected", style: { "border-color": "#0071e3", "border-width": 4 } },
      { selector: "edge", style: {
        width: 1.2, "line-color": "#d8d8de", "target-arrow-color": "#d8d8de",
        "target-arrow-shape": "triangle", "arrow-scale": 0.8, "curve-style": "bezier",
        label: "data(label)", "font-size": 8, "font-family": "Inter, sans-serif", color: "#8e8e93",
        "text-rotation": "autorotate", "text-opacity": 0,
        "text-background-color": "#ffffff", "text-background-opacity": 0.9, "text-background-padding": 2,
      }},
      { selector: 'edge[status="confirmed"]', style: { "line-color": "#34c759", "target-arrow-color": "#34c759" } },
      { selector: 'edge[status="proposed"]', style: { "line-style": "dashed", "line-color": "#ff9f0a", "target-arrow-color": "#ff9f0a" } },
      { selector: "edge.show-lbl", style: { "text-opacity": 1, "z-index": 20 } },
      { selector: "node.hl", style: { "border-color": "#0071e3", "border-width": 4 } },
      { selector: "edge.hl", style: { width: 2.4, "line-color": "#0071e3", "target-arrow-color": "#0071e3", "text-opacity": 1, "z-index": 20 } },
      { selector: ".faded", style: { opacity: 0.1, "text-opacity": 0 } },
      { selector: "node.typehidden", style: { display: "none" } },
    ],
    layout: GRAPH_LAYOUT,
  });
  cy.on("tap", "node", (e) => { showDetail(e.target); focusNode(e.target); });
  cy.on("tap", "edge", (e) => { showEdgeDetail(e.target); e.target.addClass("show-lbl"); });
  cy.on("tap", (e) => { if (e.target === cy) { document.getElementById("detail-panel").hidden = true; clearFocus(); } });
  cy.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("show-lbl"));
  cy.on("mouseout", "node", (e) => { if (!FOCUSED) e.target.connectedEdges().removeClass("show-lbl"); });
  cy.on("mouseover", "edge", (e) => e.target.addClass("show-lbl"));
  cy.on("mouseout", "edge", (e) => { if (!FOCUSED) e.target.removeClass("show-lbl"); });
  wireLegend();
}

let FOCUSED = null;
function focusNode(node) {
  FOCUSED = node.id();
  cy.elements().addClass("faded");
  node.closedNeighborhood().removeClass("faded");
  node.addClass("hl");
  node.connectedEdges().removeClass("faded").addClass("show-lbl");
}
function clearFocus() {
  FOCUSED = null;
  cy.elements().removeClass("faded hl show-lbl");
}

const HIDDEN_TYPES = new Set();
const LEG_TYPE = { person: "person", company: "company", "us-company": "us_company", rep: "employee", thread: "email_thread" };
function applyTypeFilter() {
  cy.nodes().forEach((n) => n.toggleClass("typehidden", HIDDEN_TYPES.has(n.data("type"))));
}
function wireLegend() {
  document.querySelectorAll(".graph-legend .leg-item").forEach((item) => {
    const dot = item.querySelector(".leg-dot");
    if (!dot) return;
    const cls = Array.from(dot.classList).find((c) => c !== "leg-dot");
    const type = LEG_TYPE[cls];
    if (!type) return;
    item.classList.add("leg-toggle");
    item.onclick = () => {
      if (HIDDEN_TYPES.has(type)) HIDDEN_TYPES.delete(type); else HIDDEN_TYPES.add(type);
      item.classList.toggle("leg-off", HIDDEN_TYPES.has(type));
      applyTypeFilter();
    };
  });
}

async function refreshGraph() {
  const g = await api("/api/graph");
  GRAPH = g;
  $("node-count").textContent = g.nodes.length;
  $("edge-count").textContent = g.edges.filter((e) => e.status !== "retired").length;
  const els = [];
  const nodeIds = new Set(g.nodes.map((n) => n.id));
  for (const n of g.nodes) els.push({ data: { id: n.id, label: n.label, type: n.type, props: n.props } });
  for (const e of g.edges) {
    if (e.status === "retired") continue;
    // Only connect object-property edges between nodes; literal properties are not drawn
    if (typeof e.object === "string" && nodeIds.has(e.object)) {
      els.push({ data: { id: e.id, source: e.subject, target: e.object, label: e.predicate, status: e.status } });
    }
  }
  cy.elements().remove();
  cy.add(els);
  cy.layout(GRAPH_LAYOUT).run();
  applyTypeFilter();
  clearFocus();
}

function showDetail(node) {
  const id = node.data().id;
  const n = GRAPH.nodes.find((x) => x.id === id);
  if (!n) return;
  const panel = $("detail-panel");
  const nodeIds = new Set(GRAPH.nodes.map((x) => x.id));
  const out = GRAPH.edges.filter((e) => e.subject === id && e.status !== "retired");
  const attrs = [];
  const rels = [];
  for (const e of out) {
    if (typeof e.object === "string" && nodeIds.has(e.object)) {
      rels.push(`<div class="kv"><span class="k">${esc(e.predicate)}</span><span class="v">${esc(nodeLabel(e.object))}</span></div>`);
    } else {
      attrs.push(`<div class="kv"><span class="k">${esc(e.predicate)}</span><span class="v">${esc(String(e.object))}</span></div>`);
    }
  }
  const incoming = GRAPH.edges
    .filter((e) => e.object === id && e.status !== "retired" && nodeIds.has(e.subject))
    .map((e) => `<div class="kv"><span class="k">${esc(nodeLabel(e.subject))} \u00b7 ${esc(e.predicate)}</span><span class="v">\u2192</span></div>`);
  let html = `<h4>${esc(n.label)}</h4><div class="meta">Type: ${esc(n.type)}</div>`;
  if (attrs.length) html += `<div class="detail-sec">Attributes</div>${attrs.join("")}`;
  if (rels.length) html += `<div class="detail-sec">Relations</div>${rels.join("")}`;
  if (incoming.length) html += `<div class="detail-sec">Referenced by</div>${incoming.join("")}`;
  if (!attrs.length && !rels.length && !incoming.length) html += `<div class="meta" style="margin-top:8px">No properties.</div>`;
  panel.innerHTML = `<button class="detail-close" id="detail-close">&times;</button><div id="detail-content">${html}</div>`;
  panel.hidden = false;
  $("detail-close").onclick = () => (panel.hidden = true);
}

function showEdgeDetail(edge) {
  const d = edge.data();
  const panel = $("detail-panel");
  const html = `<h4>${esc(d.label)}</h4>`
    + `<div class="detail-sec">Relation</div>`
    + `<div class="kv"><span class="k">from</span><span class="v">${esc(nodeLabel(d.source))}</span></div>`
    + `<div class="kv"><span class="k">predicate</span><span class="v">${esc(d.label)}</span></div>`
    + `<div class="kv"><span class="k">to</span><span class="v">${esc(nodeLabel(d.target))}</span></div>`
    + `<div class="kv"><span class="k">status</span><span class="v">${esc(d.status)}</span></div>`;
  panel.innerHTML = `<button class="detail-close" id="detail-close">&times;</button><div id="detail-content">${html}</div>`;
  panel.hidden = false;
  $("detail-close").onclick = () => (panel.hidden = true);
}

// ---------- Activity stream ----------
function streamEvent(ev) {
  const wrap = $("stream-items");
  const div = document.createElement("div");
  div.className = `stream-item ${ev.status || ""}`;
  div.innerHTML = `<span class="st-status">${ev.status}</span>${ev.message}`;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
}

async function playActivity(events) {
  $("stream-items").innerHTML = "";
  $("activity-stream").hidden = false;
  const hdr = $("stream-header");
  if (hdr) hdr.innerHTML = '<span class="stream-pulse"></span> Cala Agent activity';
  for (const ev of events) {
    streamEvent(ev);
    await new Promise((r) => setTimeout(r, 450));
  }
  if (hdr) hdr.innerHTML = '<span class="stream-done">\u2713</span> Cala expansion complete';
}

// ---------- 1. Scan card ----------
async function loadSamples() {
  const s = await api("/api/samples");
  const sel = $("card-select");
  sel.innerHTML = s.cards.map((c) => `<option value="${c}">${c} card</option>`).join("");
}

// Uploaded card image (base64 data URL), used for real OCR
let cardImageDataUrl = null;
$("card-file").onchange = (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) { cardImageDataUrl = null; $("file-name").textContent = ""; $("card-preview").hidden = true; return; }
  const reader = new FileReader();
  reader.onload = () => {
    cardImageDataUrl = reader.result; // data:image/...;base64,XXXX
    $("file-name").textContent = file.name;
    $("card-preview").src = cardImageDataUrl;
    $("card-preview").hidden = false;
  };
  reader.readAsDataURL(file);
};

$("scan-btn").onclick = async () => {
  const btn = $("scan-btn");
  btn.disabled = true; btn.textContent = cardImageDataUrl ? "OCR recognizing..." : "Scanning...";
  try {
    const payload = cardImageDataUrl
      ? { image_b64: cardImageDataUrl }
      : { card_key: $("card-select").value };
    const res = await api("/api/scan", { method: "POST", body: JSON.stringify(payload) });
    await playActivity(res.activity);
    await refreshGraph();
    const c = res.card;
    const ocrBlock = res.ocr_text
      ? `<div class="kv"><b>OCR raw text</b></div><pre class="email">${res.ocr_text}</pre>`
      : "";
    $("scan-result").innerHTML = `<div class="card"><h4>${c.full_name || "?"} @ ${c.company || "?"}</h4>
      ${ocrBlock}
      <div class="kv"><b>Title</b> ${c.job_title || "-"}</div>
      <div class="kv"><b>Email</b> ${c.email || "-"}</div>
      <div class="kv"><b>Extraction</b> ${c._method}${res.ocr_text ? "(gpt-4o real OCR)" : ""}</div>
      <div class="meta">${res.facts_written} facts auto-merged into the graph · Cala (${res.cala_source || (res.cala_mock ? "mock" : "real")})</div>
      <div class="actions"><button class="btn btn-primary" onclick="composeForContact('${res.person_id}','${(c.full_name || "").replace(/'/g, "")}')">Write a cold email to ${c.full_name || "them"}</button></div></div>`;
    toast(cardImageDataUrl ? "OCR + Cala expansion complete" : "Scan + Cala expansion complete");
  } catch (e) { toast("Error: " + e.message); }
  finally { btn.disabled = false; btn.textContent = "Scan and expand"; }
};

window.composeFor = async (personId) => {
  switchTab("scan");
  toast("Generating email...");
  try {
    const res = await api("/api/mail/send", { method: "POST", body: JSON.stringify({ person_id: personId, use_agent_tool: false }) });
    const sr = res.send_result || {};
    $("scan-result").insertAdjacentHTML("beforeend",
      `<div class="card"><h4>Sent: ${res.draft.subject}</h4>
       <pre class="email">${res.draft.body}</pre>
       <div class="meta">Send mode ${sr.mode || "?"} · transport ${sr.transport || "?"} · thread ${res.thread_id}</div>
       <div class="actions"><button class="btn" onclick="simulateReply('${res.thread_id}')">Simulate customer reply → AI replies again</button></div></div>`);
    await refreshGraph();
    toast("Email sent (via MCP tool)");
  } catch (e) { toast("Send failed: " + e.message); }
};

window.simulateReply = async (threadId) => {
  // Route to "4. Sessions" for the human-confirmed auto-reply flow
  switchTab("sessions");
  await refreshSessions();
  await window.mockReply(threadId);
};

// ---------- 2. Smart prospecting ----------
// 1. Prospect: use only Cala to find new companies
$("scout-btn").onclick = async () => {
  const btn = $("scout-btn"); const orig = btn.textContent;
  btn.disabled = true; btn.textContent = "Prospecting\u2026";
  $("target-result").innerHTML = '<div class="card loading-card"><span class="spinner"></span> Asking Cala to discover new companies\u2026</div>';
  try {
    const res = await api("/api/scout", { method: "POST", body: JSON.stringify({ text: $("target-text").value }) });
    renderScout(res);
  } catch (e) { toast("Prospect failed: " + e.message); $("target-result").innerHTML = ""; }
  finally { btn.disabled = false; btn.textContent = orig; }
};

// 2. Filter: query only our own CRM network
$("filter-btn").onclick = async () => {
  const btn = $("filter-btn"); const orig = btn.textContent;
  btn.disabled = true; btn.textContent = "Filtering CRM\u2026";
  $("target-result").innerHTML = '<div class="card loading-card"><span class="spinner"></span> Searching our CRM network (incl. warm leads)\u2026</div>';
  try {
    const res = await api("/api/filter", { method: "POST", body: JSON.stringify({ text: $("target-text").value }) });
    renderFilter(res);
  } catch (e) { toast("Filter failed: " + e.message); $("target-result").innerHTML = ""; }
  finally { btn.disabled = false; btn.textContent = orig; }
};

function renderTarget(res) {
  const f = res.filters || {};
  const targets = res.targets || [];
  const list = targets.map((t) => `<div class="kv"><b>${t.name}</b> · ${t.title || "-"} · ${t.email || "no email"}</div>`).join("") || '<div class="meta">No matches</div>';
  $("target-result").innerHTML = `<div class="card">
    <h4>Matched ${res.count} people</h4>
    <div class="meta">Parse(${f._method}): country=${f.country || "-"} industry=${f.industry || "-"} employees≥${f.min_employees || "-"} | CRM: ${f.crm_employee || "-"} sent≥${f.crm_min_messages || "-"} emails</div>
    <div class="meta">Cala (${res.cala_source || (res.cala_mock ? "mock" : "real")}) matched companies: ${(res.cala_companies || []).join(", ") || "-"}</div>
    <div style="margin-top:10px">${list}</div></div>`;
}

// 1. Prospect result: companies Cala found, marking which are brand-new prospects
function renderScout(res) {
  const f = res.filters || {};
  const rows = (res.companies || []).map((c) => `<div class="kv">
    ${c.is_new ? '<span class="pill" style="background:#16a34a">New</span>' : '<span class="pill" style="background:#94a3b8">Existing</span>'}
    <b>${c.company}</b> · ${c.industry || "-"} · employees ${c.employees || "?"} · ${c.country || "-"} · ${c.revenue || ""}
  </div>`).join("") || '<div class="meta">No results</div>';
  $("target-result").innerHTML = `<div class="card">
    <h4>1. Prospect: Cala found ${res.count} companies, of which ${res.new_count} are brand-new prospects</h4>
    <div class="meta">Data source Cala (${res.cala_source}) · Parse(${f._method}): country=${f.country || "-"} industry=${f.industry || "-"} employees≥${f.min_employees || "-"}</div>
    <div style="margin-top:10px">${rows}</div></div>`;
}

// 2. Filter result: people in our own network, each can be emailed in one click
function renderFilter(res) {
  if (res.mode === "warm_lead") return renderWarmLeads(res);
  const f = res.filters || {};
  const list = (res.targets || []).map((t) => `<div class="kv">
    <b>${t.name}</b> · ${t.title || "-"} · ${t.email || "no email"}
    <button class="btn btn-mini" onclick="composeForContact('${t.person_id}','${(t.name || "").replace(/'/g, "")}')">✍️ Write</button>
  </div>`).join("") || '<div class="meta">No matches</div>';
  $("target-result").innerHTML = `<div class="card">
    <h4>2. Filter: matched ${res.count} people in our network (no Cala call)</h4>
    <div class="meta">Parse(${f._method}): country=${f.country || "-"} industry=${f.industry || "-"} employees≥${f.min_employees || "-"} | CRM: ${f.crm_employee || "-"} sent≥${f.crm_min_messages || "-"} emails</div>
    <div style="margin-top:10px">${list}</div></div>`;
}


// 2b. Warm leads: past-deal contacts who moved to a not-yet-won account
function renderWarmLeads(res) {
  const list = (res.leads || []).map((l) => `<div class="kv" style="display:block;margin-bottom:8px">
    <b>${l.name}</b> · ${l.title || "-"} · ${l.email || "no email"}
    <div class="meta">✅ We closed a deal with them at <b>${l.won_company}</b>${l.won_deal_value ? ` (${l.won_deal_value})` : ""} → ➡️ now at <b>${l.current_company}</b> <span class="pill" style="background:#16a34a">no deal yet</span></div>
    ${l.current_supplier ? `<div class="meta">Incumbent supplier: ${l.current_supplier}${l.contract_end ? ` · contract ends ${l.contract_end}` : ""}</div>` : ""}
    <button class="btn btn-mini" onclick="composeForContact('${l.person_id}','${(l.name || "").replace(/'/g, "")}')">✍️ Write warm intro</button>
  </div>`).join("") || '<div class="meta">No warm leads found</div>';
  $("target-result").innerHTML = `<div class="card">
    <h4>Warm leads: ${res.count} past-deal contact(s) now at a not-yet-won account</h4>
    <div class="meta">Pure graph traversal · won deal → contact → current employer (no won deal) · no Cala call</div>
    <div style="margin-top:10px">${list}</div></div>`;
}

// 3. Write: product-doc RAG drafts a personalized email, shown in an editable modal
let MAIL_CTX = { personId: null, name: null };

window.composeForContact = async (personId, name) => {
  toast("Generating email with product-manual RAG...");
  try {
    const res = await api("/api/mail/compose", { method: "POST", body: JSON.stringify({ person_id: personId }) });
    openMailModal(personId, name, res);
  } catch (e) { toast("Write failed: " + e.message); }
};

function openMailModal(personId, name, res) {
  MAIL_CTX = { personId, name };
  $("mail-to").textContent = "To  " + (name || "\u2014");
  $("mail-subject").value = res.subject || "";
  $("mail-body").value = res.body || "";
  $("mail-meta").textContent = "RAG product manual + customer profile \u00b7 LLM " + (res.llm ? "gpt-4o" : "template fallback");
  const ov = $("mail-overlay"), modal = $("mail-modal"), btn = $("mail-send");
  modal.classList.remove("sending");
  btn.classList.remove("is-sending");
  btn.disabled = false;
  ov.classList.remove("closing", "sending");
  ov.hidden = false;
}

function closeMailModal() {
  const ov = $("mail-overlay");
  ov.classList.add("closing");
  setTimeout(() => { ov.hidden = true; ov.classList.remove("closing"); }, 230);
}

$("mail-close").onclick = closeMailModal;
$("mail-cancel").onclick = closeMailModal;
$("mail-overlay").addEventListener("click", (e) => { if (e.target === $("mail-overlay")) closeMailModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("mail-overlay").hidden) closeMailModal(); });

$("mail-send").onclick = async () => {
  const { personId, name } = MAIL_CTX;
  if (!personId) return;
  const subject = $("mail-subject").value;
  const body = $("mail-body").value;
  const btn = $("mail-send");
  btn.disabled = true;
  btn.classList.add("is-sending");
  try {
    const res = await api("/api/mail/send", { method: "POST", body: JSON.stringify({ person_id: personId, subject, body }) });
    const sr = res.send_result || {};
    await flyToLetterbox();
    closeMailModal();
    toast(`Sent to ${name} (${sr.mode || "mock"})`);
    switchTab("sessions");
    await Promise.all([refreshGraph(), refreshSessions()]);
  } catch (e) {
    btn.disabled = false;
    btn.classList.remove("is-sending");
    toast("Send failed: " + e.message);
  }
};

// Animate the letter shrinking into the Sessions tab, like posting it in a letterbox
function flyToLetterbox() {
  return new Promise((resolve) => {
    const modal = $("mail-modal");
    const overlay = $("mail-overlay");
    const tab = document.querySelector('.tab[data-tab="sessions"]');
    if (!modal || !tab) return resolve();
    const m = modal.getBoundingClientRect();
    const t = tab.getBoundingClientRect();
    const dx = (t.left + t.width / 2) - (m.left + m.width / 2);
    const dy = (t.top + t.height / 2) - (m.top + m.height / 2);
    modal.style.setProperty("--fly-x", dx + "px");
    modal.style.setProperty("--fly-y", dy + "px");
    overlay.classList.add("sending");
    modal.classList.add("sending");
    setTimeout(() => {
      tab.classList.add("letterbox-hit");
      setTimeout(() => tab.classList.remove("letterbox-hit"), 600);
    }, 600);
    setTimeout(() => { overlay.classList.remove("sending"); resolve(); }, 860);
  });
}

// ---------- 4. Sessions (session management + AI auto-reply, human-confirmed) ----------
let SESSIONS = [];

async function refreshSessions() {
  const res = await api("/api/sessions");
  SESSIONS = res.sessions || [];
  $("sessions-badge").textContent = SESSIONS.length;
  if (!SESSIONS.length) {
    $("sessions-list").innerHTML = '<div class="meta">No sessions yet. Go to "Smart prospecting" to filter and send a cold email first.</div>';
    return;
  }
  $("sessions-list").innerHTML = SESSIONS.map(renderSession).join("");
  // Safely fill the pending draft (assign value directly to avoid HTML escaping issues)
  for (const s of SESSIONS) {
    if (s.pending_reply) {
      const subj = $(`reply-subj-${s.thread_id}`);
      const bodyEl = $(`reply-body-${s.thread_id}`);
      if (subj) subj.value = s.pending_reply.subject || "";
      if (bodyEl) bodyEl.value = s.pending_reply.body || "";
    }
  }
}

function renderSession(s) {
  const history = (s.messages || []).map((m) => {
    const who = m.direction === "inbound" ? "📥 Customer" : "📤 Us";
    return `${who} · ${esc(m.subject || "")}\n${esc(m.body || "")}`;
  }).join("\n\n— — — — —\n\n") || "(no messages yet)";

  let action;
  if (s.pending_reply) {
    action = `<div class="meta" style="margin-top:8px">🤖 AI auto-drafted a reply (pending human confirmation, editable)</div>
      <input class="session-input" id="reply-subj-${s.thread_id}" placeholder="Subject" />
      <textarea class="session-input" id="reply-body-${s.thread_id}" rows="6"></textarea>
      <div class="actions">
        <button class="btn btn-primary" onclick="confirmSendReply('${s.thread_id}')">✅ Confirm send</button>
        <button class="btn" onclick="mockReply('${s.thread_id}')">↻ Re-simulate reply</button>
      </div>`;
  } else {
    action = `<div class="actions"><button class="btn" onclick="mockReply('${s.thread_id}')">📥 Simulate incoming customer reply</button></div>`;
  }

  return `<div class="card">
    <h4>Session: ${esc(s.company || "?")} · ${esc(s.person || "?")}</h4>
    <div class="meta">Status ${esc(s.status)} · turns ${s.message_count} · ${esc(s.email || "no email")}</div>
    <pre class="email">${history}</pre>
    ${action}</div>`;
}

window.mockReply = async (threadId) => {
  toast("Simulating customer reply; AI is drafting a response...");
  try {
    await api(`/api/sessions/${threadId}/mock_reply`, { method: "POST", body: JSON.stringify({}) });
    await refreshSessions();
    await refreshGraph();
    toast("Customer reply received; AI has drafted a response (awaiting your confirmation)");
  } catch (e) { toast("Failed: " + e.message); }
};

window.confirmSendReply = async (threadId) => {
  const subject = ($(`reply-subj-${threadId}`) || {}).value || "";
  const body = ($(`reply-body-${threadId}`) || {}).value || "";
  try {
    await api(`/api/sessions/${threadId}/send_reply`, { method: "POST", body: JSON.stringify({ subject, body }) });
    await refreshSessions();
    await refreshGraph();
    toast("Reply sent (mock); long-term memory updated");
  } catch (e) { toast("Send failed: " + e.message); }
};

// ---------- tabs ----------
window.clearSessions = async () => {
  if (!window.confirm("Clear all sessions? This permanently removes every email thread and its history.")) return;
  try {
    const res = await api("/api/sessions", { method: "DELETE" });
    await Promise.all([refreshSessions(), refreshGraph()]);
    toast(`Cleared ${res.cleared} session(s)`);
  } catch (e) { toast("Clear failed: " + e.message); }
};

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + name));
  if (name === "sessions") refreshSessions();
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => switchTab(t.dataset.tab)));

// ---------- init ----------
(async function () {
  initCy();
  await loadSamples();
  await refreshGraph();
  try {
    const h = await api("/api/health");
    $("cala-badge").textContent = "Cala: " + (h.cala_source || (h.cala_mock ? "mock" : "real"));
  } catch (e) {}
})();


// ====================================================================
// Pipeline view (Attio-style deals grid)
// ====================================================================
let DEALS = [];
let PIPE_STAGES = ["lead", "qualified", "quoted", "won", "lost"];
let PIPE_FILTER = new Set();
let PIPE_SORT = { key: "stage", dir: "asc" };
let ACTIVE_MENU = null;

const STAGE_LABELS = { lead: "Lead", qualified: "Qualified", quoted: "Quoted", won: "Won", lost: "Lost" };
const STAGE_ORDER = { won: 0, qualified: 1, quoted: 2, lead: 3, lost: 4 };
const STAGE_DOT = { lead: "#8e8e93", qualified: "#0071e3", quoted: "#ff9f0a", won: "#34c759", lost: "#ff3b30" };
const STRENGTH_LABELS = { very_strong: "Very strong", strong: "Strong", good: "Good", weak: "Weak", very_weak: "Very weak", none: "No contact" };
const PALETTE = ["#0071e3", "#34c759", "#ff9f0a", "#5e5ce6", "#ff2d92", "#30b0c7", "#af52de", "#ff3b30", "#e6a700", "#8e8e93"];

function hashColor(str) { let h = 0; str = str || ""; for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0; return PALETTE[h % PALETTE.length]; }
function initials(str) { const p = (str || "?").trim().split(" ").filter(Boolean); const a = (p[0] || "?")[0]; const b = p.length > 1 ? p[p.length - 1][0] : ""; return (a + b).toUpperCase(); }
function valueNum(v) { return Number((v || "").replace(/[^0-9.]/g, "")) || 0; }

async function loadDeals() {
  try {
    const res = await api("/api/deals");
    DEALS = res.deals || [];
    PIPE_STAGES = res.stages || PIPE_STAGES;
    renderPipeline();
  } catch (e) { toast("Load deals failed: " + e.message); }
}

function sigBars(st) {
  const lvl = ({ very_strong: 4, strong: 3, good: 3, weak: 2, very_weak: 1, none: 0 })[st] ?? 0;
  const tone = ({ very_strong: "#34c759", strong: "#34c759", good: "#30b0c7", weak: "#ff9f0a", very_weak: "#ff3b30", none: "#c7c7cc" })[st] || "#c7c7cc";
  let b = "";
  for (let i = 1; i <= 4; i++) b += "<i" + (i <= lvl ? ' style="background:' + tone + '"' : "") + "></i>";
  return '<span class="sig">' + b + "</span>";
}

function renderPipeline() {
  let rows = DEALS.slice();
  if (PIPE_FILTER.size) rows = rows.filter((r) => PIPE_FILTER.has(r.stage));
  const dir = PIPE_SORT.dir === "desc" ? -1 : 1;
  rows.sort((a, b) => {
    if (PIPE_SORT.key === "value") return (valueNum(a.value) - valueNum(b.value)) * dir;
    if (PIPE_SORT.key === "company") return a.company.localeCompare(b.company) * dir;
    return (((STAGE_ORDER[a.stage] ?? 9) - (STAGE_ORDER[b.stage] ?? 9)) * dir) || a.company.localeCompare(b.company);
  });
  const total = $("pipe-total");
  if (total) total.textContent = rows.length;
  const body = $("pipe-body");
  if (!rows.length) { body.innerHTML = '<tr><td colspan="8" class="pipe-empty">No deals match this filter.</td></tr>'; return; }
  body.innerHTML = rows.map((r) => {
    const co = esc(r.company), ci = esc(initials(r.company)), cc = hashColor(r.company);
    const st = r.connection_strength || "none";
    const next = r.next_step ? '<span class="next-pill">' + esc(r.next_step) + '</span>' : '<span class="cell-dim">&mdash;</span>';
    const val = r.value ? esc(r.value) : '<span class="cell-dim">&mdash;</span>';
    const conn = '<span class="cell-conn-wrap">' + sigBars(st) + '<span class="sig-label">' + esc(STRENGTH_LABELS[st] || st) + '</span></span>';
    const contact = r.contact
      ? '<span class="cell-contact"><span class="av" style="background:' + hashColor(r.contact) + '">' + esc(initials(r.contact)) + '</span>' + esc(r.contact) + '</span>'
      : '<span class="cell-dim">&mdash;</span>';
    return '<tr>'
      + '<td class="col-check"><label class="row-check"><input type="checkbox"></label></td>'
      + '<td class="col-company"><span class="cell-company"><span class="co-icon" style="background:' + cc + '">' + ci + '</span>' + co + '</span></td>'
      + '<td class="col-stage"><span class="stage-pill stage-' + r.stage + '" onclick="openStageMenu(event,\'' + r.deal_id + '\',\'' + r.stage + '\')"><span class="dot"></span>' + (STAGE_LABELS[r.stage] || r.stage) + '</span></td>'
      + '<td class="col-next">' + next + '</td>'
      + '<td class="col-arr">' + val + '</td>'
      + '<td class="col-conn">' + conn + '</td>'
      + '<td class="col-contact">' + contact + '</td>'
      + '<td class="col-add"></td>'
      + '</tr>';
  }).join("");
}

function closeMenus() {
  if (ACTIVE_MENU) { ACTIVE_MENU.remove(); ACTIVE_MENU = null; }
  const f = $("pipe-filter-menu"), so = $("pipe-sort-menu");
  if (f) f.hidden = true;
  if (so) so.hidden = true;
}
document.addEventListener("click", closeMenus);

function stageDot(s) { return '<span style="background:' + STAGE_DOT[s] + ';width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:8px"></span>'; }

window.openStageMenu = (ev, dealId, current) => {
  ev.stopPropagation();
  closeMenus();
  const menu = document.createElement("div");
  menu.className = "pipe-menu";
  menu.style.position = "fixed";
  menu.style.left = Math.min(ev.clientX, window.innerWidth - 200) + "px";
  menu.style.top = (ev.clientY + 8) + "px";
  menu.style.zIndex = 60;
  menu.innerHTML = PIPE_STAGES.map((s) =>
    '<div class="pipe-menu-item ' + (s === current ? "sel" : "") + '" onclick="setStage(\'' + dealId + '\',\'' + s + '\')">' + stageDot(s) + (STAGE_LABELS[s] || s) + (s === current ? '<span class="check">✓</span>' : '') + '</div>'
  ).join("");
  document.body.appendChild(menu);
  ACTIVE_MENU = menu;
};

window.setStage = async (dealId, stage) => {
  closeMenus();
  try {
    await api("/api/deals/" + dealId + "/stage", { method: "POST", body: JSON.stringify({ stage }) });
    const d = DEALS.find((x) => x.deal_id === dealId);
    if (d) d.stage = stage;
    renderPipeline();
    refreshGraph();
    toast("Stage updated to " + (STAGE_LABELS[stage] || stage));
  } catch (e) { toast("Update failed: " + e.message); }
};

function buildFilterMenu() {
  const m = $("pipe-filter-menu");
  m.innerHTML = PIPE_STAGES.map((s) =>
    '<div class="pipe-menu-item" onclick="event.stopPropagation();toggleFilter(\'' + s + '\')">' + stageDot(s) + (STAGE_LABELS[s] || s) + '<span class="check">' + (PIPE_FILTER.has(s) ? "✓" : "") + '</span></div>'
  ).join("");
}
window.toggleFilter = (s) => {
  if (PIPE_FILTER.has(s)) PIPE_FILTER.delete(s); else PIPE_FILTER.add(s);
  const c = $("pipe-filter-count");
  c.textContent = PIPE_FILTER.size;
  c.hidden = !PIPE_FILTER.size;
  buildFilterMenu();
  renderPipeline();
};

function buildSortMenu() {
  const m = $("pipe-sort-menu");
  const opts = [["stage", "asc", "Stage (pipeline order)"], ["value", "desc", "Estimated value (high → low)"], ["value", "asc", "Estimated value (low → high)"], ["company", "asc", "Company (A → Z)"]];
  m.innerHTML = opts.map((o) =>
    '<div class="pipe-menu-item ' + (PIPE_SORT.key === o[0] && PIPE_SORT.dir === o[1] ? "sel" : "") + '" onclick="event.stopPropagation();setSort(\'' + o[0] + '\',\'' + o[1] + '\')">' + o[2] + '<span class="check">' + (PIPE_SORT.key === o[0] && PIPE_SORT.dir === o[1] ? "✓" : "") + '</span></div>'
  ).join("");
}
window.setSort = (k, d) => { PIPE_SORT = { key: k, dir: d }; buildSortMenu(); closeMenus(); renderPipeline(); };

if ($("pipe-filter-btn")) $("pipe-filter-btn").onclick = (e) => { e.stopPropagation(); const m = $("pipe-filter-menu"); const open = !m.hidden; closeMenus(); if (!open) { buildFilterMenu(); m.hidden = false; } };
if ($("pipe-sort-btn")) $("pipe-sort-btn").onclick = (e) => { e.stopPropagation(); const m = $("pipe-sort-menu"); const open = !m.hidden; closeMenus(); if (!open) { buildSortMenu(); m.hidden = false; } };
if ($("pipe-refresh-btn")) $("pipe-refresh-btn").onclick = () => { loadDeals(); toast("Pipeline refreshed"); };

// ---------- view switching ----------
function switchView(view) {
  document.querySelectorAll(".view-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  const g = $("view-graph"), pv = $("view-pipeline");
  if (g) g.hidden = view !== "graph";
  if (pv) pv.hidden = view !== "pipeline";
  if (view === "pipeline") loadDeals();
  if (view === "graph" && cy) setTimeout(() => { cy.resize(); cy.fit(undefined, 40); }, 60);
}
document.querySelectorAll(".view-tab").forEach((t) => (t.onclick = () => switchView(t.dataset.view)));
