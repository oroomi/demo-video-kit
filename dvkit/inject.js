/* demo-video kit: page-side helpers, injected with add_init_script before any site script runs.
   Nothing here touches the site's files; it only runs inside the recording browser.
   window.__dv.marks is a timeline of what the page did, in epoch seconds (same clock as the Python harness). */
(() => {
  if (window.__dv) return;
  const cfg = window.__DV_CFG || {};
  const dv = window.__dv = { marks: [], cfg };
  dv.mark = (name, data) => { dv.marks.push({ name, t: Date.now() / 1000, data: data === undefined ? null : data }); };
  dv.take = () => { const m = dv.marks; dv.marks = []; return m; };

  /* ---- what the audio elements do (the assistant's reply plays through one) ---- */
  const note = (e) => {
    const a = e.target;
    if (!a || a.tagName !== "AUDIO") return;
    dv.mark("audio_" + e.type, { src: String(a.currentSrc || a.src || "").slice(0, 90), dur: isFinite(a.duration) ? a.duration : null, t: a.currentTime });
  };
  for (const ev of ["play", "playing", "pause", "ended", "error"]) document.addEventListener(ev, note, true);

  /* ---- the microphone: log when the page opens it ---- */
  try {
    const md = navigator.mediaDevices;
    if (md && md.getUserMedia) {
      const orig = md.getUserMedia.bind(md);
      md.getUserMedia = (c) => {
        dv.mark("gum_request", c);
        return orig(c).then((s) => { dv.mark("gum_open", null); return s; }, (err) => { dv.mark("gum_fail", String(err)); throw err; });
      };
    }
  } catch (e) { /* ignore */ }

  /* ---- cursor ring (the X pointer is not driven by Playwright, so draw one; shown only while moving or clicking) ---- */
  const color = cfg.cursor || "#00E5D4";
  const mk = () => {
    if (document.getElementById("__dvcur")) return;
    const d = document.createElement("div"); d.id = "__dvcur";
    d.style.cssText = "position:fixed;left:0;top:0;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;border:3px solid " + color +
      ";background:rgba(0,229,212,.25);box-shadow:0 0 0 1px rgba(0,0,0,.55);pointer-events:none;z-index:2147483647;opacity:0;transition:opacity .15s,transform .12s;";
    document.documentElement.appendChild(d);
    document.addEventListener("mousemove", (e) => { d.style.left = e.clientX + "px"; d.style.top = e.clientY + "px"; }, true);
    document.addEventListener("mousedown", () => { d.style.transform = "scale(.7)"; }, true);
    document.addEventListener("mouseup", () => { d.style.transform = "scale(1)"; }, true);
    window.__curShow = (v) => { d.style.opacity = v ? "1" : "0"; };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mk); else mk();


  /* ---- watchers: log attribute / text changes of an element with page-clock timestamps ---- */
  dv.watchAttr = (sel, attr, name) => {
    const el = document.querySelector(sel); if (!el) return false;
    dv.mark(name, el.getAttribute(attr));
    new MutationObserver(() => dv.mark(name, el.getAttribute(attr))).observe(el, { attributes: true, attributeFilter: [attr] });
    return true;
  };
  dv.watchText = (sel, name) => {
    const el = document.querySelector(sel); if (!el) return false;
    let last = "";
    new MutationObserver(() => { const t = (el.innerText || "").trim(); if (t !== last) { last = t; dv.mark(name, t); } })
      .observe(el, { childList: true, subtree: true, characterData: true });
    return true;
  };

  /* ---- sync slate: a white flash and a 1 kHz beep fired in the same task; assemble finds both and aligns picture and sound ---- */
  dv.slate = () => {
    const f = document.createElement("div");
    f.style.cssText = "position:fixed;inset:0;background:#ff00ff;z-index:2147483647;";
    document.documentElement.appendChild(f);
    let ac;
    try {
      ac = new (window.AudioContext || window.webkitAudioContext)();
      const o = ac.createOscillator(), g = ac.createGain();
      o.frequency.value = 1000; g.gain.value = 0.6; o.connect(g); g.connect(ac.destination);
      o.start(); o.stop(ac.currentTime + 0.3);
    } catch (e) { /* no audio context: the flash alone still works for picture marks */ }
    dv.mark("slate", null);
    setTimeout(() => { f.remove(); }, 200); setTimeout(() => { try { ac && ac.close(); } catch (e) { /* ignore */ } }, 600);
  };

  /* ---- speech-recognition stand-in ----
     Chromium builds without Google's speech key cannot recognise anything (the real API fails with "network"). When cfg.srStub is on,
     the stub below takes its place so the site's own voice flow (live transcript, 1.5 s pause, send, thinking, spoken answer) runs
     unchanged.  The harness plays the question audio and calls __dv.srSay() at the same moment; the words appear over `ms` milliseconds. */
  if (cfg.srStub) {
    class StubSR {
      constructor() { this.lang = "en-US"; this.interimResults = true; this.continuous = true; this.maxAlternatives = 1; this._on = false; this._timers = []; }
      start() { this._on = true; dv.mark("sr_start", null); if (this.onstart) this.onstart(); window.__dvSR = this; }
      stop() { this._end(); }
      abort() { this._end(true); }
      _end(abort) { this._on = false; this._timers.forEach(clearTimeout); this._timers = []; if (!abort && this.onend) { const f = this.onend; this.onend = null; f(); } }
      _emit(text, final) {
        const alt = { transcript: text, confidence: 0.93 };
        const res = [Object.assign([alt], { isFinal: final })];
        res.item = (i) => res[i];
        if (this.onresult) this.onresult({ resultIndex: 0, results: res });
      }
      say(text, ms) {
        if (!this._on) return false;
        const words = text.split(/\s+/);
        const total = text.length; let acc = 0;
        words.forEach((w, i) => {
          acc += w.length + 1;
          const at = Math.max(0, (acc / (total + 1)) * ms - 60);
          this._timers.push(setTimeout(() => { if (this._on) this._emit(words.slice(0, i + 1).join(" "), false); }, at));
        });
        this._timers.push(setTimeout(() => { if (this._on) { this._emit(text, true); dv.mark("sr_final", text); } }, ms + 120));
        dv.mark("sr_say", { text, ms });
        return true;
      }
    }
    window.SpeechRecognition = StubSR; window.webkitSpeechRecognition = StubSR;
    dv.srSay = (text, ms) => (window.__dvSR ? window.__dvSR.say(text, ms) : false);
  }
})();
