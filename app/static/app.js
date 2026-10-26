/* Make Quran Video — front-end (no build step, no framework). */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const S = {
    cfg: null, sb: null, surahs: [], styles: [], reciters: [], translations: [], fonts: [], ayahs: [],
    audioSrc: "reciter", audioUpload: null, styleId: null, opts: {}, trEdition: "en.sahih",
    media: { library: [], uploads: [] }, tab: "library", selected: [], bgMode: "single", bgMotion: true,
    format: "landscape", frame: { enabled: false, radius: 40, padding: 40, bg_color: "#10231C", shadow: true },
    wm: { enabled: false, logo: null, position: "br", size_pct: 12, opacity: 0.85 },
    job: null, pollTimer: null, booted: false,
  };
  const FORMATS = { landscape: [1920, 1080, "16:9"], portrait: [1080, 1920, "9:16"], square: [1080, 1080, "1:1"] };
  const HL_SWATCHES = ["#FFD54A", "#FFC93C", "#FF9F1C", "#6BFFD0", "#4FC3F7", "#B388FF", "#FF7AA2", "#FFFFFF"];
  const SWATCHES = ["#FFFFFF", "#FFD700", "#F5E6C8", "#E8C068", "#8FFFD4", "#9EC9FF", "#FFB4A2", "#111111"];

  // ───────────────────────────── language ─────────────────────────────
  let LANG = document.documentElement.lang === "ar" ? "ar" : "en";
  function t(key, params) {
    let s = (window.I18N[LANG] && window.I18N[LANG][key]) || window.I18N.en[key] || key;
    if (params) for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(v);
    return s;
  }
  function applyI18n() {
    document.documentElement.lang = LANG; document.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
    document.title = t("app_name");
    document.querySelectorAll("[data-i18n]").forEach((n) => (n.textContent = t(n.dataset.i18n)));
    document.querySelectorAll("[data-i18n-title]").forEach((n) => (n.title = t(n.dataset.i18nTitle)));
    $("langBtn").textContent = LANG === "ar" ? "English" : "العربية";
    $("langBtn").lang = LANG === "ar" ? "en" : "ar";
  }
  function setLang(l) {
    LANG = l; try { localStorage.setItem("mqv-lang", l); } catch (e) { /* private mode */ }
    applyI18n();
    if (S.booted) { fillSelects(); renderStyles(); validateRange(); renderAyahList(); renderGallery(); refreshAll(); loadRecent(); if (S.job) showProgress(S.job); }
  }
  $("langBtn").addEventListener("click", () => setLang(LANG === "ar" ? "en" : "ar"));

  // ───────────────────────────── theme ─────────────────────────────
  const isDark = () => document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  $("themeBtn").addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("mqv-theme", next); } catch (e) { /* private mode */ }
  });

  // ───────────────────────────── helpers ─────────────────────────────
  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    kids.flat().forEach((c) => c != null && n.append(c));
    return n;
  }
  let toastT;
  function toast(msg) {
    const tt = $("toast"); tt.textContent = msg; tt.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(() => (tt.hidden = true), 4200);
  }
  const debounce = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };
  const toArabicDigits = (n) => String(n).replace(/\d/g, (d) => "٠١٢٣٤٥٦٧٨٩"[d]);
  const hexA = (hex, a) => {
    const h = (hex || "#000000").replace("#", "");
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
  };
  const up = (c) => (c || "#FFFFFF").toUpperCase();

  // ── animated caption sample (style cards + live preview) ──
  // one clock for every sample: the "recited" word advances every 450 ms
  const WORD_ANIMS = ["karaoke", "highlight", "word_reveal", "glow_word"];
  const quranWords = (text) => (text || "").split(/\s+/).filter(Boolean).reduce((out, w) => {
    if (out.length && !/\p{L}/u.test(w)) out[out.length - 1] += " " + w; else out.push(w);
    return out;
  }, []);
  function captionLine(words, o, ayah, last) {
    const toks = words.slice();
    const num = ayah ? toArabicDigits(ayah) : "";
    const br = o.brackets || "full";
    if (br === "full") { toks[0] = "﴿" + toks[0]; toks[toks.length - 1] += (last && num ? " " + num : "") + "﴾"; }
    else if (br === "number" && last && num) toks[toks.length - 1] += " ﴿" + num + "﴾";
    const line = el("span", { class: `cl anim-${o.anim || "fade"}` });
    line.dataset.n = toks.length;
    toks.forEach((w, i) => { if (i) line.append(" "); line.append(el("span", { class: "cw", text: w })); });
    const oc = o.outline_color || "#000", ow = Math.max(0, +(o.outline ?? 3));
    line.style.setProperty("--ar", o.ar_color || "#fff");
    line.style.setProperty("--hl", o.hl_color || "#FFD54A");
    line.style.setProperty("--glow", o.glow_color || o.hl_color || "#FFD54A");
    line.style.setProperty("--up", String(o.upcoming_alpha ?? 0.45));
    const stroke = ow ? `0 0 ${Math.min(ow, 4) * 0.6}px ${oc}, 0 0 ${Math.min(ow, 4) * 0.6}px ${oc}` : "";
    const shadow = +(o.shadow ?? 2) ? "0 2px 4px rgba(0,0,0,.6)" : "";
    line.style.setProperty("--ts", [stroke, shadow].filter(Boolean).join(", ") || "none");
    line.classList.toggle("glow", !!o.glow);
    return line;
  }
  let capTick = 0;
  setInterval(() => {
    capTick++;
    document.querySelectorAll(".cl").forEach((line) => {
      const n = +line.dataset.n || 1, k = capTick % (n + 3);       // 3 ticks of pause at the end
      if (k === 0) { line.classList.remove("enter"); void line.offsetWidth; line.classList.add("enter"); }
      line.querySelectorAll(".cw").forEach((w, i) => {
        w.classList.toggle("past", i < k); w.classList.toggle("cur", i === k || (k >= n && i === n - 1));
      });
    });
  }, 450);

  async function token() {
    if (!S.sb) return null;
    const { data } = await S.sb.auth.getSession();
    return data.session ? data.session.access_token : null;
  }
  async function api(path, opts = {}) {
    const headers = Object.assign({ "X-Lang": LANG }, opts.headers || {});
    const tk = await token();
    if (tk) headers.Authorization = "Bearer " + tk;
    let body = opts.body;
    if (body && !(body instanceof FormData)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
    let r;
    try { r = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body }); }
    catch (e) { throw new Error(t("connection")); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* not json */ }
    if (r.status === 401 && S.sb) showAuth();
    if (!r.ok && !(opts.allowPartial && data)) throw new Error((data && data.error) || t("generic_error"));
    return data;
  }
  function setPressed(groupSel, attr, val) {
    document.querySelectorAll(`${groupSel} [data-${attr}]`).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset[attr] === val)));
  }

  // ───────────────────────────── auth ─────────────────────────────
  let authMode = "signin";
  function showAuth() { $("authView").hidden = false; $("appView").hidden = true; $("userChip").hidden = true; }
  async function showApp(user) {
    $("authView").hidden = true; $("appView").hidden = false;
    if (user) { $("userChip").hidden = false; $("userEmail").textContent = user.email || ""; }
    if (!S.booted) { S.booted = true; await boot(); }
  }
  function setAuthMode(m) {
    authMode = m;
    $("authTitle").textContent = t(m === "signin" ? "sign_in" : "create_your_account");
    $("authBtn").textContent = t(m === "signin" ? "sign_in" : "create_account");
    $("authSwitchText").textContent = t(m === "signin" ? "new_here" : "have_account");
    $("authSwitch").textContent = t(m === "signin" ? "create_account" : "sign_in");
    $("authPass").autocomplete = m === "signin" ? "current-password" : "new-password";
    $("authErr").hidden = true;
  }
  $("authSwitch").addEventListener("click", () => setAuthMode(authMode === "signin" ? "signup" : "signin"));
  $("authForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("authEmail").value.trim(), password = $("authPass").value;
    const errBox = $("authErr"); errBox.hidden = true;
    if (!email || password.length < 6) { errBox.textContent = t("auth_invalid"); errBox.hidden = false; return; }
    $("authBtn").disabled = true;
    try {
      const fn = authMode === "signin" ? S.sb.auth.signInWithPassword : S.sb.auth.signUp;
      const { data, error } = await fn.call(S.sb.auth, { email, password });
      if (error) throw error;
      if (authMode === "signup" && !data.session) { errBox.textContent = t("auth_confirm"); errBox.hidden = false; setAuthMode("signin"); }
    } catch (err) { errBox.textContent = err.message || t("auth_failed"); errBox.hidden = false; }
    finally { $("authBtn").disabled = false; }
  });
  $("signOut").addEventListener("click", async () => { await S.sb.auth.signOut(); location.reload(); });

  // ───────────────────────────── boot ─────────────────────────────
  async function init() {
    applyI18n();
    try { S.cfg = await api("/api/public-config"); }
    catch (e) { document.body.append(el("p", { class: "alert", style: "margin:20px", text: e.message })); return; }
    if (S.cfg.auth_required) {
      if (!window.supabase) { document.body.append(el("p", { class: "alert", style: "margin:20px", text: t("auth_unavailable") })); return; }
      S.sb = window.supabase.createClient(S.cfg.supabase_url, S.cfg.supabase_anon_key);
      const { data } = await S.sb.auth.getSession();
      S.sb.auth.onAuthStateChange((_ev, session) => { if (session) showApp(session.user); });
      if (data.session) showApp(data.session.user); else showAuth();
    } else showApp(null);
  }

  async function boot() {
    const [surahs, styles, reciters, translations, fonts, prefs] = await Promise.all([
      api("/api/surahs"), api("/api/caption-styles"), api("/api/quran/reciters"), api("/api/quran/translations"),
      api("/api/fonts").catch(() => []), api("/api/preferences").catch(() => ({})),
    ]);
    Object.assign(S, { surahs, styles, reciters, translations, fonts });
    addFontFaces(fonts);
    fillSelects();
    applyPrefs(prefs || {});
    renderStyles();
    updateRangeLimits(false);
    loadMedia(); loadRecent(); refreshAll(); fetchAyahs();
  }

  // web fonts for the live preview (built-in from /fonts, uploaded from their own URL)
  function addFontFaces(fonts) {
    const css = fonts.map((f) => `@font-face{font-family:"${f.family}";src:url("${f.user ? f.url : "/fonts/" + encodeURIComponent(f.file)}");font-display:swap}`).join("");
    document.head.append(el("style", { text: css }));
  }

  function fillSelects() {
    const keep = (id) => $(id).value;
    const sv = keep("surah"), rv = keep("reciter"), tv = keep("trEdition");
    $("surah").replaceChildren(...S.surahs.map((s) => el("option", { value: s.number,
      text: LANG === "ar" ? `${s.number}. ${s.name_ar}` : `${s.number}. ${s.name_en} — ${s.name_ar}` })));
    $("reciter").replaceChildren(...S.reciters.map((r) => el("option", { value: r.id, text: LANG === "ar" ? (r.name_ar || r.name) : r.name })));
    $("trEdition").replaceChildren(...S.translations.map((x) => el("option", { value: x.id, text: LANG === "ar" ? (x.name_ar || x.name) : x.name })));
    const fname = (f) => (LANG === "ar" && f.name_ar ? f.name_ar : f.family);
    const opt = (f) => el("option", { value: f.family, text: f.user ? `★ ${fname(f)} (${t("your_font")})` : fname(f) });
    const ar = S.fonts.filter((f) => f.script === "arabic");
    $("arFont").replaceChildren(
      el("optgroup", { label: t("fonts_uthmani") }, ...ar.filter((f) => f.quran_ok).map(opt)),
      el("optgroup", { label: t("fonts_display") }, ...ar.filter((f) => !f.quran_ok).map(opt)));
    $("trFont").replaceChildren(...S.fonts.filter((f) => f.script === "latin" || f.latin).map(opt));
    if (sv) $("surah").value = sv; if (rv) $("reciter").value = rv; if (tv) $("trEdition").value = tv;
    if (S.opts.ar_font) { $("arFont").value = S.opts.ar_font; $("trFont").value = S.opts.tr_font; }
  }

  function applyPrefs(p) {
    if (p.reciter && S.reciters.some((r) => r.id === p.reciter)) $("reciter").value = p.reciter;
    if (p.translation_edition) S.trEdition = p.translation_edition;
    S.styleId = S.styles.some((s) => s.id === p.caption_style) ? p.caption_style : (S.styles[0] && S.styles[0].id);
    S.opts = Object.assign({}, styleById(S.styleId).options, p.caption_options || {});
    if (FORMATS[p.format]) S.format = p.format;
    if (p.bg_mode) S.bgMode = p.bg_mode;
    if (typeof p.bg_motion === "boolean") S.bgMotion = p.bg_motion;
    if (p.frame) Object.assign(S.frame, p.frame);
    if (p.watermark) Object.assign(S.wm, p.watermark);
    syncControls();
  }
  const savePrefs = debounce(() => {
    api("/api/preferences", { body: {
      caption_style: S.styleId, caption_options: S.opts, format: S.format, bg_mode: S.bgMode, bg_motion: S.bgMotion,
      frame: S.frame, watermark: S.wm, reciter: $("reciter").value, translation_edition: S.trEdition,
    } }).catch(() => {});
  }, 800);

  // ───────────────────────────── 1. Quran audio ─────────────────────────────
  const surahObj = () => S.surahs.find((s) => s.number === +$("surah").value) || S.surahs[0];
  const surahName = (s) => (LANG === "ar" ? s.name_ar : s.name_en);
  function updateRangeLimits(resetRange) {
    const s = surahObj(); if (!s) return;
    $("ayahFrom").max = s.ayah_count; $("ayahTo").max = s.ayah_count;
    if (resetRange) { $("ayahFrom").value = 1; $("ayahTo").value = Math.min(s.ayah_count, 7); }
    validateRange();
  }
  function rangeState() {
    const s = surahObj(); const a = parseInt($("ayahFrom").value, 10), b = parseInt($("ayahTo").value, 10);
    if (!s || !a || !b) return { ok: false, msg: t("range_enter") };
    if (a < 1 || b > s.ayah_count) return { ok: false, msg: t("range_max", { surah: surahName(s), n: s.ayah_count }) };
    if (a > b) return { ok: false, msg: t("range_order") };
    if (b - a + 1 > S.cfg.limits.max_ayahs) return { ok: false, msg: t("range_limit", { n: S.cfg.limits.max_ayahs }) };
    return { ok: true, s, a, b, msg: t("range_ok", { n: b - a + 1 }) };
  }
  function validateRange() {
    const r = rangeState();
    $("rangeHint").textContent = r.msg; $("rangeHint").className = "hint" + (r.ok ? "" : " err");
    return r;
  }
  $("surah").addEventListener("change", () => { updateRangeLimits(true); fetchAyahs(); refreshAll(); });
  ["ayahFrom", "ayahTo"].forEach((id) => $(id).addEventListener("input", () => { validateRange(); fetchAyahsDebounced(); refreshAll(); }));

  let previewSeq = 0, ayahMsg = "";
  async function fetchAyahs() {
    const r = rangeState();
    if (!r.ok) { S.ayahs = []; ayahMsg = r.msg; renderAyahList(); renderPreview(); return; }
    const seq = ++previewSeq;
    ayahMsg = t("loading_ayahs_list"); S.ayahs = []; renderAyahList();
    try {
      const data = await api("/api/quran/preview", { body: { surah: r.s.number, ayah_start: r.a, ayah_end: r.b, translation_edition: S.trEdition, ar_font: S.opts.ar_font } });
      if (seq !== previewSeq) return;
      S.ayahs = data.ayahs; ayahMsg = "";
    } catch (e) { if (seq !== previewSeq) return; S.ayahs = []; ayahMsg = e.message; }
    renderAyahList(); renderPreview(); refreshChecklist();
  }
  function renderAyahList() {
    const box = $("ayahBox");
    if (!S.ayahs.length) { box.replaceChildren(el("div", { class: "empty", text: ayahMsg || t("loading_ayahs_list") })); return; }
    box.replaceChildren(...S.ayahs.map((x) => el("div", { class: "ayah" },
      el("div", { class: "ar", lang: "ar", dir: "rtl", text: `${x.text} ﴿${toArabicDigits(x.ayah)}﴾` }),
      x.translation && S.opts.show_translation ? el("div", { class: "tr", dir: "ltr", text: `${x.ayah}. ${x.translation}` }) : null)));
  }
  const fetchAyahsDebounced = debounce(fetchAyahs, 400);

  document.querySelectorAll("[data-src]").forEach((b) => b.addEventListener("click", () => {
    S.audioSrc = b.dataset.src; setPressed(".step", "src", S.audioSrc);
    $("reciterBlock").hidden = S.audioSrc !== "reciter"; $("uploadBlock").hidden = S.audioSrc !== "upload";
    refreshChecklist();
  }));
  $("reciter").addEventListener("change", () => { savePrefs(); refreshChecklist(); });

  const audioDrop = $("audioDrop");
  ["dragover", "dragenter"].forEach((ev) => audioDrop.addEventListener(ev, (e) => { e.preventDefault(); audioDrop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => audioDrop.addEventListener(ev, () => audioDrop.classList.remove("over")));
  audioDrop.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) uploadAudio(e.dataTransfer.files[0]); });
  $("audioFile").addEventListener("change", (e) => { if (e.target.files[0]) uploadAudio(e.target.files[0]); e.target.value = ""; });
  async function uploadAudio(file) {
    const mb = S.cfg.limits.max_upload_mb;
    if (file.size > mb * 1048576) { toast(t("too_big", { names: file.name, mb })); return; }
    $("audioDropTitle").textContent = t("uploading"); $("audioDropSub").textContent = file.name;
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api("/api/audio/upload", { body: fd });
      S.audioUpload = r;
      $("audioDropTitle").textContent = `✓ ${r.name}`;
      $("audioDropSub").textContent = `${Math.floor(r.duration / 60)}:${String(Math.round(r.duration % 60)).padStart(2, "0")} — ${t("click_replace")}`;
      detectAudio(r.audio_id);
    } catch (e) {
      S.audioUpload = null;
      $("audioDropTitle").textContent = t("upload_rec_title"); $("audioDropSub").textContent = e.message;
    }
    refreshChecklist();
  }

  // recognise the surah and ayahs in the uploaded recitation, then fill the fields
  async function detectAudio(audioId) {
    const note = $("detectNote");
    S.detecting = true; note.hidden = false; note.className = "detect busy";
    note.replaceChildren(el("span", { class: "spinner" }), el("span", { text: t("detecting") }));
    refreshChecklist();
    try {
      await api("/api/audio/detect", { body: { audio_id: audioId } });
      for (let k = 0; k < 400; k++) {
        await new Promise((res) => setTimeout(res, 2000));
        if (!S.audioUpload || S.audioUpload.audio_id !== audioId) return;      // replaced meanwhile
        const d = await api(`/api/audio/detect/${encodeURIComponent(audioId)}`);
        if (d.status === "running") continue;
        if (d.status === "done") {
          const r = d.result;
          $("surah").value = r.surah; updateRangeLimits(false);
          $("ayahFrom").value = r.ayah_start; $("ayahTo").value = r.ayah_end;
          validateRange(); fetchAyahs();
          const name = LANG === "ar" ? r.name_ar : r.name_en;
          const range = r.ayah_end > r.ayah_start ? `${r.ayah_start}–${r.ayah_end}` : r.ayah_start;
          note.className = "detect ok";
          note.replaceChildren(el("b", { text: t("detected", { surah: name, range }) }), el("span", { text: t("detected_sub") }));
        } else {
          note.className = "detect err"; note.replaceChildren(el("span", { text: d.error || t("generic_error") }));
        }
        break;
      }
    } catch (e) {
      note.className = "detect err"; note.replaceChildren(el("span", { text: e.message }));
    } finally { S.detecting = false; refreshAll(); }
  }

  // ───────────────────────────── 2. Captions ─────────────────────────────
  const styleById = (id) => S.styles.find((s) => s.id === id) || S.styles[0] || { options: {} };
  const styleLabel = (st) => (LANG === "ar" && st.label_ar) ? st.label_ar : st.label;
  const styleDesc = (st) => (LANG === "ar" && st.description_ar) ? st.description_ar : st.description;
  function renderStyles() {
    $("styles").replaceChildren(...S.styles.map((st) => {
      const o = st.options;
      const f = S.fonts.find((x) => x.family === o.ar_font);
      const txt = f && !f.quran_ok ? "بِسْمِ اللَّهِ الرَّحْمَٰنِ" : "بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ";
      const sample = el("span", { class: "ar", lang: "ar", dir: "rtl" }, captionLine(txt.split(" "), o, 1, true));
      sample.style.fontFamily = `"${o.ar_font || "Amiri"}", serif`;
      if (o.box) {
        sample.style.background = hexA(o.box_color || "#000", o.box_opacity ?? 0.5);
        if (o.card_border) sample.style.outline = `2px solid ${o.border_color || "#9A7A36"}`, sample.style.outlineOffset = "-5px";
      }
      const sw = el("div", { class: "sw" + (o.band ? " band" : "") + (o.ornament ? " orn" : "") }, sample);
      if (o.ornament) sw.style.setProperty("--orn", o.ornament_color || "#D4AF37");
      return el("button", { type: "button", class: "style-card", role: "radio", "aria-checked": String(st.id === S.styleId), onclick: () => pickStyle(st.id) },
        sw,
        el("div", { class: "meta" }, el("b", { text: styleLabel(st) }), el("span", { text: styleDesc(st) || "" })));
    }));
    requestAnimationFrame(fitSamples);
    if (document.fonts) document.fonts.ready.then(fitSamples);
  }
  // shrink a card sample that is wider than its card
  function fitSamples() {
    document.querySelectorAll(".style-card .sw .ar").forEach((a) => {
      a.style.fontSize = ""; const box = a.parentElement.clientWidth * 0.94;
      if (a.scrollWidth > box) a.style.fontSize = Math.max(11, 19 * box / a.scrollWidth) + "px";
    });
  }
  function pickStyle(id) {
    S.styleId = id;
    // keep the user's font choice when switching styles
    const keepFonts = { ar_font: S.opts.ar_font, tr_font: S.opts.tr_font };
    S.opts = Object.assign({}, styleById(id).options, keepFonts.ar_font ? keepFonts : {});
    renderStyles(); syncControls(); fetchAyahsIfTranslation(); refreshAll(); savePrefs();
  }
  function renderSwatches() {
    const cur = up(S.opts.ar_color);
    const picker = el("input", { type: "color", class: "swatch-custom", "aria-label": t("custom"), title: t("custom") });
    picker.value = cur;
    picker.addEventListener("input", (e) => setOpt("ar_color", e.target.value));
    $("arSwatches").replaceChildren(...SWATCHES.map((c) => el("button", {
      type: "button", class: "swatch", style: `background:${c}`, "aria-pressed": String(c === cur), title: c,
      onclick: () => setOpt("ar_color", c),
    })), picker);
  }
  function renderHlSwatches() {
    const cur = up(S.opts.hl_color || "#FFD54A");
    const picker = el("input", { type: "color", class: "swatch-custom", "aria-label": t("custom"), title: t("custom") });
    picker.value = cur;
    picker.addEventListener("input", (e) => setOpt("hl_color", e.target.value));
    $("hlSwatches").replaceChildren(...HL_SWATCHES.map((c) => el("button", {
      type: "button", class: "swatch", style: `background:${c}`, "aria-pressed": String(c === cur), title: c,
      onclick: () => setOpt("hl_color", c),
    })), picker);
  }
  function setOpt(k, v) { S.opts[k] = v; syncControls(); renderPreview(); renderAyahList(); savePrefs(); }
  function syncControls() {
    const o = S.opts;
    if (o.ar_font && [...$("arFont").options].some((x) => x.value === o.ar_font)) $("arFont").value = o.ar_font;
    if (o.tr_font && [...$("trFont").options].some((x) => x.value === o.tr_font)) $("trFont").value = o.tr_font;
    renderSwatches();
    const anim = o.anim || "fade";
    setPressed("#animChips", "anim", anim);
    renderHlSwatches();
    $("hlField").hidden = !(WORD_ANIMS.includes(anim) || o.glow);
    $("glowOn").checked = !!o.glow; $("bandOn").checked = !!o.band; $("ornOn").checked = !!o.ornament;
    $("brackets").value = o.brackets || "full";
    $("outline").value = o.outline ?? 3; $("outlineVal").textContent = Math.round(o.outline ?? 3);
    $("trColor").value = up(o.tr_color); $("refColor").value = up(o.ref_color || "#D9D9D9"); $("outColor").value = up(o.outline_color || "#000000");
    $("arSize").value = o.ar_size ?? 0.1; $("arSizeVal").textContent = Math.round((o.ar_size ?? 0.1) * 1000);
    $("maxWords").value = o.max_words_per_line ?? 7; $("maxWordsVal").textContent = o.max_words_per_line ?? 7;
    $("centerY").value = o.center_y ?? 0.55;
    const off = +(o.sync_offset || 0);
    $("syncOffset").value = off;
    $("syncOffsetVal").textContent = off === 0 ? t("auto") : `${Math.abs(off).toFixed(2)} s ${t(off < 0 ? "earlier" : "later")}`; $("waqf").checked = !!o.break_at_waqf;
    $("showTr").checked = !!o.show_translation; $("trPanel").hidden = !o.show_translation;
    $("trEdition").value = S.trEdition; $("trSize").value = o.tr_ratio ?? 0.42;
    $("showRef").checked = o.show_reference !== false;
    $("capBox").checked = !!o.box; $("boxPanel").hidden = !o.box;
    $("boxColor").value = up(o.box_color || "#000000"); $("boxOpacity").value = o.box_opacity ?? 0.5; $("boxRadius").value = o.box_radius ?? 0.03;
    setPressed(".step", "fmt", S.format); setPressed(".step", "bg", S.bgMode);
    $("bgMotion").checked = S.bgMotion;
    $("frameOn").checked = S.frame.enabled; $("framePanel").hidden = !S.frame.enabled;
    $("frameRadius").value = S.frame.radius; $("framePad").value = S.frame.padding;
    $("frameColor").value = up(S.frame.bg_color || "#10231C"); $("frameShadow").checked = !!S.frame.shadow;
    $("wmOn").checked = S.wm.enabled; $("wmPanel").hidden = !S.wm.enabled;
    $("wmSize").value = S.wm.size_pct; $("wmOpacity").value = S.wm.opacity;
    setPressed("#wmPos", "pos", S.wm.position);
    if (S.wm.logo) { $("logoThumb").src = S.wm.logo.url; $("logoThumb").hidden = false; }
  }
  const bindOpt = (id, key, parse = (v) => v, evt = "input") => $(id).addEventListener(evt, (e) =>
    setOpt(key, parse(e.target.type === "checkbox" ? e.target.checked : e.target.value)));
  $("arFont").addEventListener("change", (e) => {
    const was = S.fonts.find((f) => f.family === S.opts.ar_font), now = S.fonts.find((f) => f.family === e.target.value);
    setOpt("ar_font", e.target.value);
    if (!!(was && was.quran_ok) !== !!(now && now.quran_ok)) fetchAyahs();     // Uthmani <-> standard script
  });
  document.querySelectorAll("#animChips [data-anim]").forEach((b) => b.addEventListener("click", () => setOpt("anim", b.dataset.anim)));
  bindOpt("glowOn", "glow", Boolean, "change"); bindOpt("bandOn", "band", Boolean, "change");
  bindOpt("ornOn", "ornament", Boolean, "change"); bindOpt("brackets", "brackets", String, "change");
  bindOpt("outline", "outline", parseFloat); bindOpt("trFont", "tr_font", String, "change");
  bindOpt("trColor", "tr_color"); bindOpt("refColor", "ref_color"); bindOpt("outColor", "outline_color");
  bindOpt("arSize", "ar_size", parseFloat); bindOpt("maxWords", "max_words_per_line", (v) => parseInt(v, 10));
  bindOpt("centerY", "center_y", parseFloat); bindOpt("waqf", "break_at_waqf", Boolean, "change");
  bindOpt("trSize", "tr_ratio", parseFloat); bindOpt("syncOffset", "sync_offset", parseFloat);
  $("fontFile").addEventListener("change", async (e) => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    $("fontBtnText").textContent = t("uploading"); $("fontWarn").hidden = true;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await api("/api/fonts/upload", { body: fd });
      const font = { ...r, user: true };
      S.fonts = S.fonts.filter((x) => x.id !== r.id).concat(font);
      addFontFaces([font]); fillSelects();
      setOpt(r.script === "arabic" ? "ar_font" : "tr_font", r.family);
      toast(t("font_added", { name: r.family }));
      if (r.script === "arabic" && !r.quran_ok) { $("fontWarn").textContent = t("font_marks_warn", { name: r.family }); $("fontWarn").hidden = false; }
    } catch (err) { $("fontWarn").textContent = err.message; $("fontWarn").hidden = false; }
    finally { $("fontBtnText").textContent = t("upload_font"); }
  });
  bindOpt("showRef", "show_reference", Boolean, "change"); bindOpt("capBox", "box", Boolean, "change");
  bindOpt("boxColor", "box_color"); bindOpt("boxOpacity", "box_opacity", parseFloat); bindOpt("boxRadius", "box_radius", parseFloat);
  $("showTr").addEventListener("change", (e) => { setOpt("show_translation", e.target.checked); fetchAyahsIfTranslation(); });
  $("trEdition").addEventListener("change", (e) => { S.trEdition = e.target.value; fetchAyahs(); savePrefs(); });
  function fetchAyahsIfTranslation() { if (S.opts.show_translation && S.ayahs.length && !S.ayahs[0].translation) fetchAyahs(); }

  // ───────────────────────────── 3. Background media ─────────────────────────────
  async function loadMedia() {
    $("gallery").replaceChildren(el("div", { class: "empty", text: t("loading_media") }));
    try { S.media = await api("/api/media"); }
    catch (e) { $("gallery").replaceChildren(el("div", { class: "empty", text: e.message })); return; }
    const known = new Set([...S.media.library, ...S.media.uploads].map((m) => m.id));
    S.selected = S.selected.filter((id) => known.has(id));
    if (!S.media.library.length && S.media.uploads.length && S.tab === "library") S.tab = "uploads";
    renderGallery(); refreshAll();
  }
  const mediaById = (id) => [...S.media.library, ...S.media.uploads].find((m) => m.id === id);
  function renderGallery() {
    setPressed(".step", "tab", S.tab);
    const items = S.media[S.tab] || [];
    if (!items.length) { $("gallery").replaceChildren(el("div", { class: "empty", text: t(S.tab === "library" ? "lib_empty" : "up_empty") })); return; }
    $("gallery").replaceChildren(...items.map((m) => {
      const idx = S.selected.indexOf(m.id);
      const thumb = m.kind === "video"
        ? el("video", { src: m.url + "#t=0.5", muted: true, preload: "metadata", playsinline: true, loop: true })
        : el("img", { src: m.url, alt: m.name, loading: "lazy" });
      const tile = el("button", { type: "button", class: "tile", "aria-pressed": String(idx >= 0), title: m.name, onclick: () => toggleMedia(m.id) },
        thumb, el("span", { class: "kind", text: t(m.kind === "video" ? "video" : "image") }),
        idx >= 0 ? el("span", { class: "badge", text: String(idx + 1) }) : null,
        m.source === "uploads" ? el("span", { class: "del", role: "button", tabindex: "0", "aria-label": t("delete"), text: "×",
          onclick: (e) => { e.stopPropagation(); deleteMedia(m); } }) : null);
      if (m.kind === "video") {
        tile.addEventListener("mouseenter", () => thumb.play().catch(() => {}));
        tile.addEventListener("mouseleave", () => thumb.pause());
      }
      return tile;
    }));
  }
  function toggleMedia(id) {
    const i = S.selected.indexOf(id);
    if (i >= 0) S.selected.splice(i, 1);
    else if (S.selected.length >= S.cfg.limits.max_bg_items) { toast(t("max_bg", { n: S.cfg.limits.max_bg_items })); return; }
    else S.selected.push(id);
    renderGallery(); refreshAll();
  }
  async function deleteMedia(m) {
    if (!window.confirm(t("confirm_delete", { name: m.name }))) return;
    try { await api("/api/media", { method: "DELETE", body: { id: m.id } }); S.selected = S.selected.filter((x) => x !== m.id); loadMedia(); }
    catch (e) { toast(e.message); }
  }
  document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { S.tab = b.dataset.tab; renderGallery(); }));
  $("bgFiles").addEventListener("change", async (e) => {
    const files = [...e.target.files]; e.target.value = "";
    if (!files.length) return;
    const mb = S.cfg.limits.max_upload_mb;
    const tooBig = files.filter((f) => f.size > mb * 1048576);
    if (tooBig.length) toast(t("too_big", { names: tooBig.map((f) => f.name).join(", "), mb }));
    const ok = files.filter((f) => f.size <= mb * 1048576);
    if (!ok.length) return;
    const fd = new FormData(); ok.forEach((f) => fd.append("files", f));
    $("uploadBtnText").textContent = t("uploading");
    try {
      const r = await api("/api/media/upload", { body: fd, allowPartial: true });
      if (r.errors && r.errors.length) toast(r.errors.join(" "));
      (r.items || []).forEach((it) => { if (!S.selected.includes(it.id) && S.selected.length < S.cfg.limits.max_bg_items) S.selected.push(it.id); });
      S.tab = "uploads"; await loadMedia();
    } catch (err) { toast(err.message); }
    finally { $("uploadBtnText").textContent = t("upload_device"); }
  });
  document.querySelectorAll("[data-bg]").forEach((b) => b.addEventListener("click", () => { if (b.disabled) return; S.bgMode = b.dataset.bg; refreshAll(); savePrefs(); }));
  $("bgMotion").addEventListener("change", (e) => { S.bgMotion = e.target.checked; savePrefs(); });

  // ───────────────────────────── 4. Watermark & layout ─────────────────────────────
  document.querySelectorAll("[data-fmt]").forEach((b) => b.addEventListener("click", () => { S.format = b.dataset.fmt; syncControls(); renderPreview(); savePrefs(); }));
  const bindFrame = (id, key, parse, evt = "input") => $(id).addEventListener(evt, (e) => {
    S.frame[key] = parse(e.target.type === "checkbox" ? e.target.checked : e.target.value); syncControls(); renderPreview(); savePrefs();
  });
  bindFrame("frameOn", "enabled", Boolean, "change"); bindFrame("frameRadius", "radius", Number); bindFrame("framePad", "padding", Number);
  bindFrame("frameColor", "bg_color", String); bindFrame("frameShadow", "shadow", Boolean, "change");
  $("wmOn").addEventListener("change", (e) => { S.wm.enabled = e.target.checked; syncControls(); renderPreview(); refreshChecklist(); savePrefs(); });
  $("wmSize").addEventListener("input", (e) => { S.wm.size_pct = +e.target.value; renderPreview(); savePrefs(); });
  $("wmOpacity").addEventListener("input", (e) => { S.wm.opacity = +e.target.value; renderPreview(); savePrefs(); });
  document.querySelectorAll("#wmPos [data-pos]").forEach((b) => b.addEventListener("click", () => { S.wm.position = b.dataset.pos; syncControls(); renderPreview(); savePrefs(); }));
  $("logoFile").addEventListener("change", async (e) => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    $("logoHint").textContent = t("uploading");
    try {
      const r = await api("/api/logo/upload", { body: fd });
      S.wm.logo = { id: r.id, url: r.url }; $("logoHint").textContent = r.name;
      syncControls(); renderPreview(); refreshChecklist(); savePrefs();
    } catch (err) { $("logoHint").textContent = err.message; }
  });

  // ───────────────────────────── preview ─────────────────────────────
  let shownShot = null;
  function renderPreview() {
    const [W, H, label] = FORMATS[S.format];
    const stage = $("stage"); stage.className = "stage " + S.format; $("fmtLabel").textContent = label;
    const sw = stage.clientWidth || 360, scale = sw / W;
    const first = mediaById(S.selected[0]);
    const key = first ? first.id : "";
    if (key !== shownShot) {
      shownShot = key;
      $("pvShot").replaceChildren(first
        ? (first.kind === "video" ? el("video", { src: first.url, muted: true, autoplay: true, loop: true, playsinline: true }) : el("img", { src: first.url, alt: "" }))
        : el("div", { class: "placeholder" }));
      const v = $("pvShot").querySelector("video"); if (v) { v.muted = true; v.play().catch(() => {}); }
    }
    const shot = $("pvShot");
    if (S.frame.enabled) {
      const p = S.frame.padding;
      $("pvFrameBg").style.background = S.frame.bg_color;
      Object.assign(shot.style, { left: (p / W * 100) + "%", right: (p / W * 100) + "%", top: (p / H * 100) + "%", bottom: (p / H * 100) + "%",
        borderRadius: (S.frame.radius * scale) + "px", boxShadow: S.frame.shadow ? "0 6px 18px rgba(0,0,0,.55)" : "none" });
    } else {
      $("pvFrameBg").style.background = "none";
      Object.assign(shot.style, { left: 0, right: 0, top: 0, bottom: 0, borderRadius: 0, boxShadow: "none" });
    }
    // first line of the first ayah, exactly as the video starts
    const o = S.opts, a = S.ayahs[0];
    const cap = $("pvCap"), ar = $("pvAr"), tr = $("pvTr");
    const mwl = o.max_words_per_line || 7;
    const words = quranWords(a ? a.text : "بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ");
    const line = words.slice(0, mwl);
    const sig = JSON.stringify([line, o, a && a.ayah]);
    if (ar.dataset.sig !== sig) { ar.dataset.sig = sig; ar.replaceChildren(captionLine(line, o, a ? a.ayah : 1, words.length <= mwl)); }
    ar.style.fontFamily = `"${o.ar_font || "Amiri"}", serif`;
    ar.style.fontSize = `calc(${(o.ar_size || 0.1) * 100} * 1cqmin)`;
    const oc = o.outline_color || "#000";
    $("stage").classList.toggle("band", !!o.band);
    cap.classList.toggle("orn", !!o.ornament);
    cap.style.setProperty("--orn", o.ornament_color || "#D4AF37");
    cap.style.outline = o.box && o.card_border ? `2px solid ${o.border_color || "#9A7A36"}` : "none";
    cap.style.outlineOffset = "-6px";
    tr.hidden = !(o.show_translation && a && a.translation);
    tr.textContent = a && a.translation ? a.translation : "";
    tr.style.color = o.tr_color || "#fff";
    tr.style.fontFamily = `"${o.tr_font || "DejaVu Sans"}", sans-serif`;
    tr.style.fontStyle = o.tr_italic ? "italic" : "normal";
    tr.style.fontSize = `calc(${(o.ar_size || 0.1) * 100 * (o.tr_ratio || 0.42)} * 1cqmin)`;
    tr.style.textShadow = `0 0 2px ${oc}, 0 1px 2px ${oc}`;
    cap.style.top = ((o.center_y || 0.55) * 100) + "%"; $("stage").style.setProperty("--cy", ((o.center_y || 0.55) * 100) + "%");
    cap.classList.toggle("boxed", !!o.box);
    cap.style.background = o.box ? hexA(o.box_color, o.box_opacity ?? 0.5) : "none";
    cap.style.borderRadius = o.box ? `calc(${(o.box_radius ?? 0.03) * 100} * 1cqmin)` : "0";
    const s = surahObj();
    $("pvRef").textContent = o.show_reference !== false && s ? `${s.name_en} : ${a ? a.ayah : 1}` : "";
    $("pvRef").style.color = o.ref_color || "#d9d9d9";
    const wm = $("pvWm");
    if (S.wm.enabled && S.wm.logo) {
      wm.hidden = false; if (wm.src !== new URL(S.wm.logo.url, location.href).href) wm.src = S.wm.logo.url;
      const box = S.frame.enabled ? { x: S.frame.padding / W, y: S.frame.padding / H } : { x: 0, y: 0 };
      const m = 0.03, w = S.wm.size_pct / 100 * (1 - 2 * box.x);
      wm.style.width = (w * 100) + "%"; wm.style.opacity = S.wm.opacity;
      wm.style.left = wm.style.right = wm.style.top = wm.style.bottom = "auto"; wm.style.transform = "none";
      const pos = S.wm.position;
      const hx = (box.x + m) * 100 + "%", vy = (box.y + m * W / H * (H > W ? 1 : 0.6)) * 100 + "%";
      if (pos[1] === "l") wm.style.left = hx; else if (pos[1] === "r") wm.style.right = hx; else { wm.style.left = "50%"; wm.style.transform = "translateX(-50%)"; }
      if (pos[0] === "t") wm.style.top = vy; else wm.style.bottom = vy;
    } else wm.hidden = true;
  }
  window.addEventListener("resize", debounce(renderPreview, 150));

  // ───────────────────────────── 5. Generate ─────────────────────────────
  function checks() {
    const r = rangeState();
    const rec = S.reciters.find((x) => x.id === $("reciter").value);
    return [
      { ok: r.ok && S.ayahs.length > 0, text: r.ok ? t("ck_range", { surah: surahName(r.s), range: r.b > r.a ? `${r.a}–${r.b}` : r.a }) : t("ck_range_need") },
      { ok: S.audioSrc === "reciter" || (!!S.audioUpload && !S.detecting), text: S.audioSrc === "upload" && S.detecting ? t("detecting") : S.audioSrc === "reciter"
        ? t("ck_reciter", { name: rec ? (LANG === "ar" ? rec.name_ar || rec.name : rec.name) : "…" }) : t(S.audioUpload ? "ck_upload" : "ck_upload_need") },
      { ok: !!S.styleId, text: t("ck_style", { name: styleLabel(styleById(S.styleId)) || "…" }) },
      { ok: S.selected.length > 0, text: S.selected.length ? t("ck_bg", { n: S.selected.length }) : t("ck_bg_need") },
      ...(S.wm.enabled ? [{ ok: !!S.wm.logo, text: t(S.wm.logo ? "ck_logo" : "ck_logo_need") }] : []),
    ];
  }
  function refreshChecklist() {
    const cs = checks();
    $("checklist").replaceChildren(...cs.map((c) => el("li", { class: c.ok ? "ok" : "", text: c.text })));
    const running = S.job && ["queued", "running"].includes(S.job.status);
    $("genBtn").disabled = !cs.every((c) => c.ok) || running;
    $("step1").classList.toggle("done", cs[0].ok && cs[1].ok);
    $("step2").classList.toggle("done", cs[2].ok);
    $("step3").classList.toggle("done", cs[3].ok);
  }
  function refreshAll() {
    const n = S.selected.length;
    const multiBtn = document.querySelector('[data-bg="multi"]');
    multiBtn.disabled = n < 2; if (n < 2 && S.bgMode === "multi") S.bgMode = "single";
    setPressed(".step", "bg", S.bgMode);
    $("selNote").textContent = !n ? t("sel_none") : n === 1 ? t("sel_one") : t(S.bgMode === "multi" ? "sel_multi" : "sel_single", { n });
    renderPreview(); refreshChecklist();
  }

  $("genBtn").addEventListener("click", async () => {
    const r = rangeState(); if (!r.ok) return;
    $("genErr").hidden = true; $("result").hidden = true;
    const body = {
      surah: r.s.number, ayah_start: r.a, ayah_end: r.b,
      audio: S.audioSrc === "upload" ? { source: "upload", audio_id: S.audioUpload && S.audioUpload.audio_id } : { source: "reciter", reciter: $("reciter").value },
      caption: { style: S.styleId, options: S.opts, translation_edition: S.trEdition },
      backgrounds: S.bgMode === "multi" ? S.selected : S.selected.slice(0, 1), bg_mode: S.bgMode, bg_motion: S.bgMotion,
      format: S.format, frame: S.frame,
      watermark: { enabled: S.wm.enabled && !!S.wm.logo, logo_id: S.wm.logo && S.wm.logo.id, position: S.wm.position, size_pct: S.wm.size_pct, opacity: S.wm.opacity },
    };
    $("genBtn").disabled = true;
    try { S.job = await api("/api/generate", { body }); showProgress(S.job); poll(); }
    catch (e) { showError(e.message); refreshChecklist(); }
  });
  function showError(msg) { $("genErr").textContent = msg; $("genErr").hidden = false; $("progress").hidden = true; }
  function showProgress(j) {
    if (!["queued", "running"].includes(j.status)) return;
    $("progress").hidden = false;
    const pct = Math.max(1, Math.min(100, j.progress || 0));
    $("pBar").style.width = pct + "%"; $("pPct").textContent = pct + "%";
    $("pStage").textContent = j.status === "queued" && j.queue_position ? t("queue", { n: j.queue_position }) : t("st_" + (j.stage || "waiting"));
  }
  function poll() {
    clearTimeout(S.pollTimer);
    S.pollTimer = setTimeout(async () => {
      try {
        const j = await api(`/api/jobs/${S.job.id}`); S.job = j;
        if (j.status === "done") return finish(j);
        if (j.status === "error") { showError(j.error || t("generic_error")); refreshChecklist(); loadRecent(); return; }
        if (j.status === "cancelled") { $("progress").hidden = true; refreshChecklist(); toast(t("cancelled_toast")); return; }
        showProgress(j);
      } catch (e) { /* transient — keep polling */ }
      poll();
    }, 1500);
  }
  function finish(j) {
    $("progress").hidden = true; $("result").hidden = false;
    $("resultVideo").src = j.video_url; $("dlBtn").href = j.download_url;
    refreshChecklist(); loadRecent();
    $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  $("cancelBtn").addEventListener("click", async () => {
    if (!S.job) return;
    try { S.job = await api(`/api/jobs/${S.job.id}/cancel`, { method: "POST" }); } catch (e) { /* ignore */ }
  });
  $("againBtn").addEventListener("click", () => { $("result").hidden = true; $("resultVideo").removeAttribute("src"); window.scrollTo({ top: 0, behavior: "smooth" }); });

  async function loadRecent() {
    let jobs = [];
    try { jobs = await api("/api/jobs"); } catch (e) { return; }
    const done = jobs.filter((j) => j.status === "done" || j.status === "error").slice(0, 6);
    $("recent").hidden = !done.length;
    $("recentList").replaceChildren(...done.map((j) => el("li", {},
      el("span", { text: j.title }),
      j.status === "done" ? el("a", { href: j.download_url, text: t("download") }) : el("span", { class: "status-pill", text: t("failed") }))));
    const active = jobs.find((j) => ["queued", "running"].includes(j.status));
    if (active && !S.job) { S.job = active; showProgress(active); poll(); refreshChecklist(); }
  }

  init();
})();
