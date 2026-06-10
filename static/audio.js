/* Voice layer: 'tts' (Web Speech, per-character pitch/rate), 'beep' (Animal
   Crossing style blips via WebAudio), 'off'. One global queue so lines play
   sequentially. 真人声音克隆不做。 */
const Voice = (() => {
  let mode = "tts";
  let queue = [];
  let playing = false;
  let ctx = null;

  const PROFILES = {};   // persona_id -> {pitch, rate, gender}
  function setProfiles(roster) {
    for (const c of roster) {
      const vp = c.voice_profile || {};
      PROFILES[c.id] = {
        pitch: vp.pitch || 1.0, rate: vp.rate || 1.0,
        gender: /female/i.test(vp.hint || "") ? "f" : "m",
      };
    }
    PROFILES["solana"] = PROFILES["solana"] || { pitch: 0.85, rate: 1.0, gender: "m" };
    PROFILES["human"] = { pitch: 1.0, rate: 1.0, gender: "m" };
  }

  function setMode(m) { mode = m; if (m === "off") stop(); }

  function stop() {
    queue = [];
    if (window.speechSynthesis) speechSynthesis.cancel();
    playing = false;
  }

  // ---- gender-aware voice pools ----
  // 浏览器音色名没有性别字段，靠常见音色名清单判性别；判不出的进 unknown 池。
  const MALE_NAMES = /\b(Daniel|Alex|Fred|Aaron|Arthur|Gordon|Rishi|Oliver|Thomas|James|Bruce|Lee|Ralph|Reed|Eddy|Grandpa|David|Mark|Guy|George|Ryan|male)\b/i;
  const FEMALE_NAMES = /\b(Samantha|Victoria|Karen|Moira|Tessa|Serena|Fiona|Kate|Susan|Allison|Ava|Joelle|Kathy|Nicky|Shelley|Sandy|Grandma|Zira|Aria|Jenny|Michelle|Sonia|Natasha|Tingting|Ting-Ting|Meijia|Mei-Jia|Sinji|Sin-ji|Yue|female)\b/i;
  let pools = null;            // {en: {m:[], f:[]}, zh: {m:[], f:[]}}
  const assigned = {};         // personaId|lang -> voice

  function genderOf(v) {
    if (/Female/i.test(v.name)) return "f";
    if (/Male/i.test(v.name)) return "m";
    if (FEMALE_NAMES.test(v.name)) return "f";
    if (MALE_NAMES.test(v.name)) return "m";
    return "?";
  }

  // macOS 13+ 的卡通腔家族(每个有 9 国语言变体)——只配当兜底，绝不优先
  const CARTOONISH = /\b(Eddy|Flo|Grandma|Grandpa|Reed|Rocko|Sandy|Shelley|Junior|Ralph|Fred|Kathy|Albert)\b/i;
  // 各平台公认的高质量音色，优先抢
  const PREMIUM = /\b(Daniel|Alex|Aaron|Arthur|Oliver|Thomas|Gordon|Rishi|Samantha|Karen|Moira|Tessa|Serena|Fiona|Kate|Ava|Allison|Susan|Tingting|Ting-Ting|Meijia|Mei-Jia|Sinji|Sin-ji|Google|Microsoft)\b/i;

  function buildPools() {
    const vs = speechSynthesis.getVoices();
    if (!vs.length) return null;
    const out = { en: { m: [], f: [], "?": [] }, zh: { m: [], f: [], "?": [] } };
    for (const v of vs) {
      const lang = /^en/i.test(v.lang) ? "en" : (/^zh/i.test(v.lang) ? "zh" : null);
      if (!lang) continue;
      if (/Eloquence|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Jester|Organ|Trinoids|Whisper|Wobble|Zarvox|Superstar/i.test(v.name)) continue; // novelty voices
      out[lang][genderOf(v)].push(v);
    }
    const score = (v) => (PREMIUM.test(v.name) ? 4 : 0) + (CARTOONISH.test(v.name) ? -4 : 0)
      + (v.localService ? 1 : 0) + (v.default ? 1 : 0);
    for (const lang of ["en", "zh"]) for (const g of ["m", "f", "?"])
      out[lang][g].sort((a, b) => score(b) - score(a));
    return out;
  }

  function hashStr(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return h;
  }

  const usedVoices = { };   // lang|gender -> Set of voice names already assigned

  function pickVoice(personaId, gender, lang) {
    const key = personaId + "|" + lang;
    if (assigned[key]) return assigned[key];
    if (!pools) pools = buildPools();
    if (!pools) return { voice: null, pitchAdj: 1.0 };
    const P = pools[lang] || pools.en;
    let pool = P[gender];
    let pitchAdj = 1.0;
    if (!pool || !pool.length) {
      // 没有该性别音色：用未知池，再不行用全部；男声压 pitch、女声抬 pitch 补偿
      pool = (P["?"].length ? P["?"] : P.m.concat(P.f));
      pitchAdj = gender === "m" ? 0.8 : 1.25;
    }
    if (!pool.length) return { voice: null, pitchAdj: 1.0 };
    // 去重: 高分段(前一半)里按 hash 起点找未用过的；全用过才复用(靠 pitch 区分)
    const poolKey = lang + "|" + gender;
    const used = usedVoices[poolKey] || (usedVoices[poolKey] = new Set());
    const start = hashStr(personaId) % pool.length;
    let v = null;
    for (let i = 0; i < pool.length; i++) {
      const cand = pool[(start + i) % pool.length];
      // 优先级: 未用过的非卡通 > 未用过的任意 > 按 hash 复用
      if (!used.has(cand.name) && !CARTOONISH.test(cand.name)) { v = cand; break; }
    }
    if (!v) for (let i = 0; i < pool.length; i++) {
      const cand = pool[(start + i) % pool.length];
      if (!used.has(cand.name)) { v = cand; break; }
    }
    if (!v) v = pool[start];
    used.add(v.name);
    const r = { voice: v, pitchAdj };
    assigned[key] = r;
    return r;
  }

  if (window.speechSynthesis) {
    speechSynthesis.onvoiceschanged = () => { pools = null; for (const k in assigned) delete assigned[k]; };
  }

  function speakTTS(text, personaId, profile, lang, done) {
    if (!window.speechSynthesis) return done();
    const u = new SpeechSynthesisUtterance(text);
    const { voice, pitchAdj } = pickVoice(personaId, profile.gender, lang === "zh" ? "zh" : "en");
    if (voice) u.voice = voice;
    u.pitch = Math.max(0.1, Math.min(2, profile.pitch * pitchAdj));
    u.rate = profile.rate * (lang === "zh" ? 1.05 : 1.0);
    u.onend = done; u.onerror = done;
    speechSynthesis.speak(u);
    // safari sometimes stalls; watchdog
    setTimeout(() => { if (speechSynthesis.speaking) return; done(); }, Math.min(20000, 350 * text.split(/\s+/).length + 4000));
  }

  function speakBeep(text, profile, done) {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    const n = Math.min(26, Math.max(6, Math.floor(text.length / 3)));
    const base = 180 + profile.pitch * 220;
    let t = ctx.currentTime;
    for (let i = 0; i < n; i++) {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "square";
      o.frequency.value = base + (Math.sin(i * 2.7) * 60) + Math.random() * 40;
      g.gain.setValueAtTime(0.06, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.07);
      o.connect(g); g.connect(ctx.destination);
      o.start(t); o.stop(t + 0.08);
      t += 0.075 / profile.rate;
    }
    setTimeout(done, (t - ctx.currentTime) * 1000 + 60);
  }

  function pump() {
    if (playing || !queue.length) return;
    playing = true;
    const { text, personaId, lang, onstart } = queue.shift();
    const profile = PROFILES[personaId] || { pitch: 1.0, rate: 1.0 };
    if (onstart) onstart();
    const done = () => { playing = false; pump(); };
    if (!text) { setTimeout(done, 200); return; }
    // 静音/哔哔档按文字长度停留,保证字幕读得完(打字机节奏)
    const dwell = Math.min(9000, 600 + text.length * 60);
    if (mode === "off") { setTimeout(done, dwell); return; }
    if (mode === "beep") { speakBeep(text, profile, () => {}); setTimeout(done, dwell); return; }
    speakTTS(text, personaId, profile, lang, done);
  }

  function say(text, personaId, lang, onstart) {
    queue.push({ text, personaId, lang, onstart });
    pump();
  }

  function debugVoice(personaId, lang) {
    const p = PROFILES[personaId] || { gender: "m", pitch: 1, rate: 1 };
    const { voice, pitchAdj } = pickVoice(personaId, p.gender, lang || "en");
    return { persona: personaId, gender: p.gender, voice: voice ? voice.name : null,
             vlang: voice ? voice.lang : null, pitch: +(p.pitch * pitchAdj).toFixed(2) };
  }

  return { say, stop, setMode, setProfiles, debugVoice };
})();
