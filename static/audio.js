/* Voice layer: 'tts' (Web Speech, per-character pitch/rate), 'beep' (Animal
   Crossing style blips via WebAudio), 'off'. One global queue so lines play
   sequentially. 真人声音克隆不做。 */
const Voice = (() => {
  let mode = "tts";
  let queue = [];
  let playing = false;
  let ctx = null;

  const PROFILES = {};   // persona_id -> {pitch, rate}
  function setProfiles(roster) {
    for (const c of roster) {
      const vp = c.voice_profile || {};
      PROFILES[c.id] = { pitch: vp.pitch || 1.0, rate: vp.rate || 1.0 };
    }
    PROFILES["solana"] = PROFILES["solana"] || { pitch: 0.85, rate: 1.0 };
  }

  function setMode(m) { mode = m; if (m === "off") stop(); }

  function stop() {
    queue = [];
    if (window.speechSynthesis) speechSynthesis.cancel();
    playing = false;
  }

  function enVoice() {
    const vs = speechSynthesis.getVoices();
    return vs.find(v => /en[-_]US/i.test(v.lang) && /Samantha|Daniel|Alex|Google US/i.test(v.name))
        || vs.find(v => /^en/i.test(v.lang)) || null;
  }
  function zhVoice() {
    const vs = speechSynthesis.getVoices();
    return vs.find(v => /zh[-_]CN/i.test(v.lang)) || vs.find(v => /^zh/i.test(v.lang)) || null;
  }

  function speakTTS(text, profile, lang, done) {
    if (!window.speechSynthesis) return done();
    const u = new SpeechSynthesisUtterance(text);
    const v = lang === "zh" ? zhVoice() : enVoice();
    if (v) u.voice = v;
    u.pitch = profile.pitch; u.rate = profile.rate * (lang === "zh" ? 1.05 : 1.0);
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
    if (mode === "off" || !text) { setTimeout(done, 200); return; }
    if (mode === "beep") return speakBeep(text, profile, done);
    speakTTS(text, profile, lang, done);
  }

  function say(text, personaId, lang, onstart) {
    queue.push({ text, personaId, lang, onstart });
    pump();
  }

  return { say, stop, setMode, setProfiles };
})();
