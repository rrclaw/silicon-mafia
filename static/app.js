/* MAFIA @ Tosca Café — frontend. Polling (1.2s) + progressive chat playback
   with typewriter + voice queue. Forked from the avalon app.js pattern. */
"use strict";

const $ = (id) => document.getElementById(id);
const API = "";
let META = null;
let GAME_ID = localStorage.getItem("mafia_game_id") || null;
let POLL = null;
let chatCursor = 0;
let lastState = null;
let selected = new Set();
let lang = "bilingual";
let playedBubbles = 0;
let actionSig = "";

const ROLE_ZH = { mafia: "黑手党 MAFIA", sheriff: "警长 SHERIFF", angel: "天使 ANGEL", town: "村民 TOWN" };
const ROLE_EMOJI = { mafia: "🔪", sheriff: "🔍", angel: "🪽", town: "🏠" };
const PHASE_ZH = {
  night: "夜晚", day_discussion: "白天讨论", nomination: "提名审判",
  trial: "审判席", verdict: "公开投票", game_over: "终局",
};

// ---------- lobby ----------

async function initLobby() {
  META = await (await fetch(API + "/api/meta")).json();
  Voice.setProfiles(META.roster);
  $("lb-backend").textContent = `引擎后端: ${META.backend}`;
  const grid = $("cast-grid");
  grid.innerHTML = "";
  for (const c of META.roster) {
    const card = document.createElement("div");
    card.className = "cast-card";
    card.dataset.id = c.id;
    card.innerHTML = `
      <span class="csrc">${c.source === "ep001_transcript" ? "EP001" : "GUEST"}</span>
      <button class="cinfo" title="人物档案">?</button>
      <img src="/static/sprites/${c.id}_idle.png" alt="${c.name_en}">
      <div class="cname">${c.name_en}</div>
      <div class="cnick">${c.nickname_zh || ""}</div>`;
    card.title = c.tagline_zh || "";
    card.onclick = () => toggleCast(c.id);
    card.querySelector(".cinfo").onclick = (e) => { e.stopPropagation(); openBio(c.id); };
    grid.appendChild(card);
  }
  $("bt-ep001").onclick = () => { selected = new Set(pickEleven(META.ep001)); renderSel(); };
  $("bt-allstar").onclick = () => {
    const stars = ["musk", "altman", "zuck", "gates", "bezos", "cook", "pichai",
                   "jensen", "son", "dario", "ilya"];
    selected = new Set(stars.filter(id => META.roster.some(c => c.id === id)).slice(0, 11));
    renderSel();
  };
  $("bt-random").onclick = () => {
    const ids = META.roster.map(c => c.id).sort(() => Math.random() - 0.5);
    selected = new Set(ids.slice(0, 11)); renderSel();
  };
  $("bt-clear").onclick = () => { selected = new Set(); renderSel(); };
  $("bt-start").onclick = startGame;
  $("bt-again").onclick = () => { localStorage.removeItem("mafia_game_id"); location.reload(); };
  selected = new Set(pickEleven(META.ep001));
  renderSel();

  if (GAME_ID) {
    try {
      const r = await fetch(`${API}/api/game/${GAME_ID}`);
      if (r.ok) { enterGame(); return; }
    } catch (e) { /* fall through */ }
    localStorage.removeItem("mafia_game_id");
    GAME_ID = null;
  }
}

function pickEleven(ids) {
  if (ids.length <= 11) return ids;
  const out = [...ids];
  out.splice(Math.floor(Math.random() * out.length), 1);
  return out;
}

function openBio(id) {
  const c = META.roster.find(x => x.id === id);
  if (!c) return;
  $("bio-img").src = `/static/sprites/${id}_idle.png`;
  $("bio-name").textContent = c.name_zh || c.name_en;
  $("bio-nick").textContent = `“${c.nickname_zh || c.nickname_en}” · ${c.source === "ep001_transcript" ? "EP001 原班" : "特邀嘉宾"}`;
  $("bio-company").textContent = c.company_zh || "";
  $("bio-text").textContent = (c.bio_zh || "").trim();
  $("bio-style").textContent = c.tagline_zh || "";
  const t = $("bio-toggle");
  const refresh = () => {
    t.textContent = selected.has(id) ? "✓ 已入座 · 点击移出" : "+ 请他入座";
  };
  refresh();
  t.onclick = () => { toggleCast(id); refresh(); };
  $("bio-modal").classList.remove("hidden");
}
$("bio-close").onclick = () => $("bio-modal").classList.add("hidden");
$("bio-modal").onclick = (e) => { if (e.target === $("bio-modal")) $("bio-modal").classList.add("hidden"); };

function toggleCast(id) {
  if (selected.has(id)) selected.delete(id);
  else if (selected.size < 11) selected.add(id);
  renderSel();
}

function renderSel() {
  document.querySelectorAll(".cast-card").forEach(el =>
    el.classList.toggle("sel", selected.has(el.dataset.id)));
  $("lb-count").textContent = `已选 ${selected.size} / 11`;
  $("bt-start").disabled = selected.size !== 11;
}

async function startGame() {
  lang = $("lb-lang").value;
  Voice.setMode($("lb-voice").value);
  const body = {
    cast: [...selected],
    human_name: $("lb-name").value.trim() || "rr",
    lang, waves: parseInt($("lb-waves").value, 10),
  };
  // 练习/导演模式: /?role=mafia 强制身份 &seed=N 固定发牌 &demo=1 剧本驱动(录demo用)
  const qs = new URLSearchParams(location.search);
  if (qs.get("role")) body.role = qs.get("role");
  if (qs.get("seed")) body.seed = parseInt(qs.get("seed"), 10);
  if (qs.get("demo")) body.demo = true;
  const r = await fetch(API + "/api/game/new", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) { alert("开局失败: " + await r.text()); return; }
  GAME_ID = (await r.json()).game_id;
  localStorage.setItem("mafia_game_id", GAME_ID);
  enterGame();
}

function enterGame() {
  $("lobby").classList.add("hidden");
  $("game").classList.remove("hidden");
  lang = $("lb-lang").value;
  Voice.setMode($("lb-voice").value);
  chatCursor = 0; playedBubbles = 0; actionSig = "";
  $("log").innerHTML = "";
  poll();
  POLL = setInterval(poll, 1200);
}

// ---------- polling & render ----------

async function poll() {
  let st;
  try {
    const r = await fetch(`${API}/api/game/${GAME_ID}`);
    if (!r.ok) throw new Error(r.status);
    st = await r.json();
  } catch (e) { return; }
  lastState = st;
  renderSeats(st);
  renderPhase(st);
  playNewChat(st);
  renderAction(st);
  if (st.winner) renderGameOver(st);
}

function seatPos(i, n) {
  // ellipse around the table; seat 0 (human) at bottom center
  const a = Math.PI / 2 + (i / n) * Math.PI * 2;
  return { x: 50 + 41 * Math.cos(a), y: 56 + 36 * Math.sin(a) };
}

function renderSeats(st) {
  const wrap = $("seats");
  const n = st.players.length;
  for (const p of st.players) {
    let el = document.getElementById("seat-" + p.seat);
    if (!el) {
      el = document.createElement("div");
      el.id = "seat-" + p.seat;
      el.className = "seat";
      const pos = seatPos(p.seat, n);
      el.style.left = pos.x + "%";
      el.style.top = pos.y + "%";
      wrap.appendChild(el);
    }
    const sprite = p.is_human ? "human" : p.persona_id;
    const frame = p.alive ? "idle" : "dead";
    const roleBadge = p.role && (!p.alive || st.winner || p.is_human)
      ? `<div class="srole ${p.role === "mafia" ? "" : "good"}">${ROLE_EMOJI[p.role] || ""}${p.role}</div>` : "";
    el.innerHTML = `<img id="img-${p.seat}" src="/static/sprites/${sprite}_${frame}.png" alt="${p.name}">
      <div class="sname">${p.is_human ? "★ " : ""}${p.name}</div>${roleBadge}`;
    el.classList.toggle("dead", !p.alive);
    el.classList.toggle("me", !!p.is_human);
    el.classList.toggle("on-trial",
      (st.defendants || []).includes(p.seat) && ["trial", "verdict"].includes(st.phase));
  }
}

function renderPhase(st) {
  document.body.classList.toggle("day", st.phase !== "night");
  document.body.classList.toggle("night", st.phase === "night");
  $("phase-badge").textContent =
    `第${st.day}天 · ${PHASE_ZH[st.phase] || st.phase}` + (st.winner ? " · 结束" : "");
  const srv = st.server || {};
  $("ai-step").classList.toggle("hidden", !srv.ai_busy);
  $("ai-step-text").textContent = srv.step ? `${srv.step} (${srv.step_elapsed}s)` : "";
  if (srv.last_error) $("ai-step-text").textContent = "⚠ " + srv.last_error;
}

function playNewChat(st) {
  const lines = st.chat.slice(chatCursor);
  chatCursor = st.chat.length;
  for (const c of lines) enqueueLine(st, c);
}

function nameOf(st, seat) {
  if (seat === null || seat === undefined) return "SOLANA";
  const p = st.players.find(x => x.seat === seat);
  return p ? p.name : "?";
}

function enqueueLine(st, c) {
  const who = nameOf(st, c.seat);
  const main = lang === "zh" ? (c.zh || c.en) : c.en;
  const sub = lang === "bilingual" && c.zh && c.zh !== c.en ? c.zh : "";
  const personaId = c.seat === null ? "solana"
    : (st.players.find(x => x.seat === c.seat) || {}).persona_id || "human";
  const voiceText = lang === "zh" ? (c.zh || c.en) : c.en;
  const speakable = ["speech", "defense", "narration", "ghost"].includes(c.kind);

  Voice.say(speakable ? voiceText : "", personaId, lang, () => {
    addLogLine(c, who, main, sub);
    if (c.kind === "narration") typewriter($("narrator-text"), main);
    if (c.seat !== null && ["speech", "defense"].includes(c.kind)) showBubble(c.seat, main, sub);
    if (c.kind === "reveal" && c.seat === null) flashReveal(st, main);
  });
}

function addLogLine(c, who, main, sub) {
  const div = document.createElement("div");
  div.className = "line " + c.kind;
  const ghost = c.kind === "ghost" ? "👻 " : "";
  div.innerHTML = `<span class="who">${ghost}${who}:</span> ${esc(main)}` +
    (sub ? `<span class="zh">${esc(sub)}</span>` : "");
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}

function esc(s) {
  return (s || "").replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
}

let bubbleTimer = {};
function showBubble(seat, text, sub) {
  const seatEl = document.getElementById("seat-" + seat);
  if (!seatEl) return;
  document.querySelectorAll(`#bubble-${seat}`).forEach(e => e.remove());
  const b = document.createElement("div");
  b.id = "bubble-" + seat;
  b.className = "bubble";
  b.style.left = seatEl.style.left;
  b.style.top = seatEl.style.top;
  b.innerHTML = `<div class="b-en"></div>` + (sub ? `<div class="b-zh">${esc(sub)}</div>` : "");
  $("seats").appendChild(b);
  typewriter(b.querySelector(".b-en"), text);
  seatEl.classList.add("talking");
  setImg(seat, "talk");
  clearTimeout(bubbleTimer[seat]);
  const dur = Math.min(14000, 2500 + text.length * 45);
  bubbleTimer[seat] = setTimeout(() => {
    b.remove(); seatEl.classList.remove("talking"); setImg(seat, "idle");
  }, dur);
}

function setImg(seat, frame) {
  const p = (lastState?.players || []).find(x => x.seat === seat);
  if (!p || !p.alive) return;
  const img = document.getElementById("img-" + seat);
  if (img) img.src = `/static/sprites/${p.is_human ? "human" : p.persona_id}_${frame}.png`;
}

function typewriter(el, text) {
  el.textContent = "";
  let i = 0;
  const isCJK = /[一-鿿]/.test(text);
  const step = isCJK ? 1 : 2;
  const t = setInterval(() => {
    el.textContent = text.slice(0, i += step);
    if (i >= text.length) clearInterval(t);
  }, 28);
}

function flashReveal(st, text) {
  // shake the most recently revealed dead seat
  const dead = st.players.filter(p => !p.alive && p.role);
  if (dead.length) {
    const el = document.getElementById("seat-" + dead[dead.length - 1].seat);
    if (el) { el.classList.add("flip"); setTimeout(() => el.classList.remove("flip"), 900); }
  }
}

// ---------- action panel ----------

function renderAction(st) {
  const you = st.you;
  $("rolecard").innerHTML =
    `${ROLE_EMOJI[you.role]} 你的身份: <b>${ROLE_ZH[you.role]}</b>` +
    (you.teammates ? `<br>队友: ${you.teammates.map(s => nameOf(st, s)).join(", ")}` : "") +
    (you.checks?.length ? `<br>查验: ${you.checks.map(c => `${nameOf(st, c.seat)}${c.is_mafia ? "❌狼" : "✅好"}`).join(" ")}` : "") +
    (!you.alive ? "<br>💀 你已出局（围观模式）" : "");

  const sig = JSON.stringify([st.phase, st.pending, st.winner, you.alive]);
  if (sig === actionSig) return;
  actionSig = sig;
  const area = $("action-area");
  area.innerHTML = "";
  if (st.winner || !st.pending) {
    if (!you.alive && !st.winner) area.innerHTML = `<span class="action-label">你死了。大佬们继续，你看戏（ghost 视角）。</span>`;
    return;
  }
  const pd = st.pending;

  const mkTargets = (targets, fn, cls = "") => {
    for (const s of targets) {
      const b = document.createElement("button");
      b.className = "px-btn target-btn " + cls;
      b.textContent = nameOf(st, s);
      b.onclick = () => fn(s);
      area.appendChild(b);
    }
  };
  const mkLabel = (t) => {
    const l = document.createElement("div");
    l.className = "action-label"; l.textContent = t; area.appendChild(l);
  };
  const mkInput = (placeholder, onsend, extraBtn) => {
    const inp = document.createElement("input");
    inp.type = "text"; inp.placeholder = placeholder; inp.maxLength = 280;
    const b = document.createElement("button");
    b.className = "px-btn primary"; b.textContent = "发言";
    const send = () => { if (inp.value.trim()) { onsend(inp.value.trim()); inp.value = ""; } };
    b.onclick = send;
    inp.onkeydown = (e) => { if (e.key === "Enter") send(); };
    area.appendChild(inp); area.appendChild(b);
    if (extraBtn) area.appendChild(extraBtn);
  };

  if (pd.type === "kill") {
    mkLabel("🔪 你是黑手党。今晚刀谁？");
    mkTargets(pd.targets, s => act("night", { action: "kill", target: s }));
  } else if (pd.type === "check") {
    mkLabel("🔍 你是警长。今晚查谁？");
    mkTargets(pd.targets, async s => {
      const r = await act("night", { action: "check", target: s }, true);
      if (r && r.check_result !== null)
        alert(`查验结果：${nameOf(st, s)} ${r.check_result ? "是 MAFIA ❌" : "是好人 ✅"}`);
    });
  } else if (pd.type === "save") {
    mkLabel("🪽 你是天使。今晚守谁？（可守自己，不能连守同一人）");
    mkTargets(pd.targets, s => act("night", { action: "save", target: s }));
  } else if (pd.type === "speak_or_end") {
    const endBtn = document.createElement("button");
    endBtn.className = "px-btn"; endBtn.textContent = "⚖️ 进入提名";
    endBtn.onclick = () => act("end_discussion", {});
    mkInput("插话、指认、怼人……（回车发送）", t => act("speak", { text: t }), endBtn);
  } else if (pd.type === "nominate") {
    mkLabel("⚖️ 提名谁上审判席？");
    mkTargets(pd.targets, s => act("nominate", { target: s }));
    const ab = document.createElement("button");
    ab.className = "px-btn ghost-btn"; ab.textContent = "弃权";
    ab.onclick = () => act("nominate", { target: null });
    area.appendChild(ab);
  } else if (pd.type === "defense") {
    mkLabel("🎤 你被送上审判席！15 秒辩护：");
    mkInput("生死陈词……", t => act("defense", { text: t }));
  } else if (pd.type === "verdict") {
    mkLabel("🗳️ 公开投票，处决谁？");
    mkTargets(pd.targets, s => { flyChip(0, s); act("vote", { target: s }); });
    const ab = document.createElement("button");
    ab.className = "px-btn ghost-btn"; ab.textContent = "弃权";
    ab.onclick = () => act("vote", { target: null });
    area.appendChild(ab);
  }
}

async function act(path, body, wantJson = false) {
  try {
    const r = await fetch(`${API}/api/game/${GAME_ID}/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    actionSig = "";
    if (!r.ok) { console.warn(await r.text()); return null; }
    poll();
    return wantJson ? await r.json() : null;
  } catch (e) { return null; }
}

function flyChip(fromSeat, toSeat) {
  const a = document.getElementById("seat-" + fromSeat);
  const b = document.getElementById("seat-" + toSeat);
  if (!a || !b) return;
  const chip = document.createElement("div");
  chip.className = "chip";
  chip.style.left = a.style.left; chip.style.top = a.style.top;
  $("seats").appendChild(chip);
  requestAnimationFrame(() => {
    chip.style.left = b.style.left; chip.style.top = b.style.top;
  });
  setTimeout(() => chip.remove(), 800);
}

// ---------- game over ----------

function renderGameOver(st) {
  if (!$("gameover").classList.contains("hidden")) return;
  // delay until the voice/log queue likely drained
  setTimeout(() => {
    $("gameover").classList.remove("hidden");
    $("go-title").textContent = st.winner === "mafia" ? "THE MAFIA WINS" : "TOWN WINS";
    $("go-roles").innerHTML = st.players.map(p =>
      `<div class="${p.role === "mafia" ? "r-mafia" : ""}">${ROLE_EMOJI[p.role] || ""} ${p.name} — ${ROLE_ZH[p.role] || p.role}${p.alive ? "" : "（已死亡）"}</div>`
    ).join("");
    clearInterval(POLL);
    localStorage.removeItem("mafia_game_id");
  }, 4000);
}

initLobby();
