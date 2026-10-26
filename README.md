# Make Quran Video

Create Quran recitation videos in one click: choose a surah and ayahs, a reciter (or upload your own recitation), a caption style and your backgrounds, then generate, preview and download.

- **Exact Quranic text.** The Uthmani text comes from the alquran.cloud API and is cached forever. It is never generated or edited by an AI, only displayed.
- **Synchronised captions.** Reciter audio gets exact per-ayah timing (measured while the audio is assembled). Uploaded recitations are timed by pause detection, guided by each ayah's length.
- **Only your media.** Backgrounds come from your curated library or from the user's uploads. There is no web search, no scraping, no AI imagery.
- **No music.** The recitation is the only audio track.

---

## 1. What changed (from VideoStudio)

| Area | Before | Now |
|---|---|---|
| Engine | `engine.py`, 10,709 lines (TTS, Whisper, LLM prompts, AI/stock/Pinterest images, 20 caption styles, music, shorts, rule cards…) | `app/engine.py`, about 780 lines. The Quran timing, Quran caption, GPU-encoder and rounded-frame functions are copied **unchanged**. The background step is replaced by a library-only builder. |
| Captions | Generic styles plus Quran mode | Quran-only style registry (`app/captions.py`). Each style is a JSON file in `caption_styles/` or a row in the `caption_styles` table. |
| Arabic rendering | Text pre-shaped with `arabic_reshaper` | Raw Unicode goes to libass, which shapes it with HarfBuzz and FriBidi using the **Amiri** font. Pre-shaping made libass fall back to another font and broke Quranic marks. Line widths are measured with real shaping (raqm), so long ayat always fit. |
| Backgrounds | AI generation, Unsplash, Pexels, Pixabay, Pinterest scraping, clip embeddings | Media library plus uploads (`app/media.py`). One background for the whole video, or one per ayah in your chosen order. |
| Watermark | `viral_fx.apply_watermark` | `app/watermark.py`, moved over **unchanged** |
| Rounded frame | `apply_rounded_frame` | Kept unchanged (radius, margin, colour, shadow). Added a **rounded caption box** style option. |
| UI | 10-tab studio (4,800 lines) | One page with five steps (audio → captions → media → watermark/layout → generate), a live preview, progress, a video player and a download button |
| Backend | Flask with a CLI flag builder, in-memory jobs, SSE | Flask with validated JSON API, bounded worker pool, engine in a child process (cancellable), progress polling, Supabase auth, storage and tables, automatic cleanup |

### Removed features
- Background music, music selection, AI music, ducking, sound effects
- Script/LLM generation (OpenRouter, Anthropic, ZenMux, GitHub Models), the post generator, `prompts.xlsx`, LLM translation in `arcine_style`
- TTS (ElevenLabs, OpenAI, Kokoro) and Whisper transcription
- AI images (Picsart, Stability, Pollinations, Together), stock search (Unsplash, Pexels, Pixabay), Pinterest scraping (Playwright), clip-library vision tagging and embeddings (`clip_ingest.py`, sentence-transformers)
- Shorts, rule cards (`viral_fx` cards), the follow/subscribe button (`follow_fx.py`), intros and retro grading (`intro_fx.py`, `retro_fx.py`), kinetic, viral and other generic caption styles (`caption_recipes.py`), overlay and finish clips, batch queue, presets, the API keys hard-coded in the old `CONFIG`

Their dependencies are gone too: faster-whisper, openai, anthropic, playwright, sentence-transformers, openpyxl and others. **Rotate any API keys that were in the old `engine.py`.**

### Version 2
- **Line-by-line sync.** A long ayah is shown one line at a time (max words per line). Each line change is matched to the reciter's real pauses inside the ayah, found from the audio's loudness (`app/sync.py`). Where there is no pause, the change is placed by how much text has been recited, counting speech time only. Optionally, lines can end at waqf marks (ۚ ۖ ۗ).
- **Text size is kept.** The size you choose is used. A line that would be too wide gets fewer words instead of a smaller font. Widths are measured with HarfBuzz, the same shaper libass uses.
- **Font picker.** Choose the Quran text font (Amiri, Noto Naskh Arabic, Noto Sans Arabic, Noto Kufi Arabic) and the translation font (DejaVu Sans, Lora). Any `.ttf` you add to `fonts/` appears automatically, but only after a startup check confirms it renders Quranic text in ffmpeg. Fonts that fail the render check are hidden (see Version 3: Amiri Quran and Scheherazade now render correctly).
- **Colours.** Quran text (preset swatches or a custom colour), translation, surah/ayah reference and outline.
- **Arabic interface.** Full Arabic UI with right-to-left layout, Arabic surah and reciter names, and server messages in Arabic (`app/i18n.py`, `app/static/i18n.js`).
- **Automatic surah & ayah detection for uploaded recitations** (`app/detect.py`). The start and end of the recording go through local speech recognition (faster-whisper, no API key) and are matched against the full Quran text. The detected surah and range are filled in automatically, and you can adjust them. Set the model with `WHISPER_MODEL` (default `small`; `medium` is more accurate). It is downloaded once on first use (about 500 MB for `small`). The recognised words are used only to find the passage; captions always use the published text.
- **Word-level sync** (`app/align.py`). The whole recitation goes through local speech recognition, and every recognised word is aligned to the exact Quran words, so each caption line appears when its first word is recited. Times are then snapped to the real sound onset in the audio. Ayah boundaries of uploaded recitations come from the same alignment, so they no longer depend on the reciter pausing between ayahs. If recognition is unavailable (or `SYNC_ASR=0`), the previous pause-based method is used.
- **Captions lead the voice.** Each ayah's caption is locked to the moment the reciter's voice starts (measured from the audio) and is fully visible 0.3 s before it. A **Caption timing** slider (±1.5 s) lets you fine-tune.
- **Upload your own font** (TTF, OTF, WOFF, WOFF2) from the Captions step. It is converted, checked in ffmpeg, and kept in your uploads. Fonts that cannot render are refused, and fonts missing some Quranic marks are accepted with a warning.
- **Dark mode toggle.** Follows the system setting by default and remembers your choice.

### Version 3: caption styles, animations and fonts
- **15 caption styles**, including viral ones: Karaoke gold, Word by word, Golden light, Neon mint, Cinematic (gradient band and italic translation), Mushaf page (cream card with a double border), Ruq'ah gold, Bold Kufi, Pop yellow, Ornament lines and Dark glass. The classic styles are kept. Style cards show a live animated sample.
- **Word animations that follow the recitation.** Karaoke (words turn the highlight colour as they are recited), Highlight word, Word by word (reveal) and Glowing word. Each word uses its recognised time from `app/align.py`, or the recitation length when recognition is off.
- **Line animations.** Fade, Slide up, Zoom in and Blur in.
- **Effects.** Glow behind the letters, a cinematic gradient band, ornament lines with a diamond, outline thickness, and an ayah ornament option (brackets, number only, or none).
- **Font list:** 23 Arabic fonts.
  - *Mushaf fonts, full Uthmani script:* Amiri Quran, Amiri, Scheherazade New, Noto Naskh / Sans / Kufi Arabic and Jomhuria.
  - *Display fonts:* Aref Ruqaa, Reem Kufi, Kufam, Changa, Lalezar, Rakkas, Lemonada, Marhey, Cairo, Tajawal, Readex Pro, El Messiri, Markazi Text, Mirza, Katibeh and Vibes. These fonts lack the Uthmani marks, so they automatically get the standard ("simple") script of the same published text (`quran-simple` edition). The text is never altered.
  - *Latin fonts:* Montserrat and Playfair Display Italic.
- **Rendering fix.** Captions are now burned with ffmpeg's `ass` filter with `shaping=complex`. Before this, the `subtitles` filter used "simple" shaping, which maps letters to legacy presentation forms. That broke Amiri Quran, Scheherazade and most modern Arabic fonts (they showed boxes) and dropped OpenType mark positioning. Styles also use `Encoding -1` (automatic right-to-left), so per-word animation tags keep the correct word order.

## 2. Project layout

```
app/
  server.py        Flask API + job runner + cleanup
  engine.py        render engine (runs as a child process per video)
  captions.py      caption styles, font discovery, ASS generator (one line at a time)
  sync.py          pause detection + line timing inside each ayah
  i18n.py          server messages (English / Arabic)
  quran_api.py     alquran.cloud text + reciter audio (cached)
  media.py         media library, uploads, validation
  watermark.py     logo watermark (unchanged)
  db.py            Supabase Auth / PostgREST / Storage (server-side, service key)
  surahs.py        114 surahs (Arabic name, transliteration, ayah count)
  config.py        all settings from environment variables
  static/          index.html, app.css, app.js, i18n.js
caption_styles/    one JSON file per caption style
fonts/             Amiri (OFL), DejaVu Sans
supabase/schema.sql
scripts/upload_library.py
Dockerfile, requirements.txt, .env.example
```

## 3. Run locally (no Supabase needed)

Requirements: Python 3.10+, and **ffmpeg** with libass (any current build: Ubuntu/Debian `apt install ffmpeg`, macOS `brew install ffmpeg`, Windows gyan.dev "full" build).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # leave the Supabase values empty
mkdir -p data/library && cp /path/to/your/backgrounds/* data/library/
python -m app.server                                   # http://localhost:8000
```

Without Supabase there is no sign-in. Uploads, preferences and videos are stored under `data/`.

## 4. Configure Supabase

1. Create a project at supabase.com.
2. In **SQL Editor**, run `supabase/schema.sql`. It creates the tables, Row Level Security policies and the three private storage buckets, and seeds the 114 surahs.
3. Under **Authentication → Providers**, enable Email. You can turn off "Confirm email" if you want users to start immediately.
4. Under **Project Settings → API**, copy the URL, the `anon` key and the `service_role` key into `.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_ANON_KEY=...        # public, sent to the browser for sign-in
   SUPABASE_SERVICE_KEY=...     # secret, server only
   ```
5. Fill your media library: `python scripts/upload_library.py ./my-backgrounds` (or upload into the `library` bucket from the dashboard; sub-folders work).
6. Optional: add caption styles as rows in `caption_styles` (`config` uses the same keys as the JSON files).

### Schema summary

| Table | Purpose | RLS |
|---|---|---|
| `surahs` | number, Arabic name, English name, ayah count | public read |
| `caption_styles` | extra or overriding styles (`config` jsonb) | public read of active rows |
| `user_preferences` | last-used settings per user | owner only |
| `render_jobs` | history, status, daily limit | owner read; server writes |

| Bucket | Content | Access |
|---|---|---|
| `library` | your curated backgrounds | signed-in users read |
| `uploads` | `<user_id>/backgrounds/*`, `<user_id>/logos/*` | owner's folder only |
| `outputs` | `<user_id>/<job>.mp4` (deleted after `RETENTION_DAYS`) | owner read |

All buckets are private. The server uses the service key and hands the browser short-lived signed URLs.

## 5. Deploy

Supabase handles accounts, data and file storage. **Rendering needs a real server with ffmpeg and CPU time**: it cannot run in Supabase Edge Functions or on serverless platforms with short timeouts.

**One container serves both the frontend and the backend.** The page, the API and the renders all run from the same image:

```bash
docker build -t make-quran-video .
docker run -d -p 8000:8000 --env-file .env -v mqv-data:/data make-quran-video
```

Good hosts: Render, Railway or Fly.io (Docker service with a persistent disk on `/data`), or any VPS (Hetzner, DigitalOcean) behind Caddy or nginx with HTTPS.

- **Size:** 2 vCPU and 4 GB RAM handles `WORKERS=1` comfortably. Raise `WORKERS` with more cores. A GPU (NVENC/QSV/AMF) is used automatically when present.
- **Keep one app process** (the Dockerfile runs gunicorn with `-w 1 --threads 16`). The job list lives in memory and renders are child processes. To scale out, run several containers behind a load balancer with **sticky sessions**, since the uploaded recitation and the job status live on the instance that received them.
- **Timeouts:** set the proxy's upload size to at least `MAX_UPLOAD_MB` × 10 and its timeout to 120 s or more.

## 6. External services still required

- **Supabase** (auth, database, storage). Optional for local use.
- **alquran.cloud API** and **cdn.islamic.network** for Quran text and reciter audio. Free, no key. Responses are cached in `data/cache/`.
- **Google Fonts** (Manrope, for the UI) and **jsDelivr** (supabase-js, only when sign-in is enabled).
- A host for the Docker container (see above).

## 7. Adding caption styles

Copy a file in `caption_styles/`, rename it (the file name is the style id) and edit it. Every key is optional:

```json
{ "label": "Night sky", "description": "Pale blue text, low on screen.", "sort": 5,
  "ar_font": "Amiri", "ar_color": "#CFE6FF", "ar_size": 0.08, "center_y": 0.72,
  "show_translation": true, "tr_color": "#FFFFFF", "show_reference": true, "max_words_per_line": 6, "break_at_waqf": true,
  "outline": 2, "shadow": 2, "box": false, "box_color": "#000000", "box_opacity": 0.5, "box_radius": 0.03,
  "anim": "karaoke", "hl_color": "#FFD54A", "upcoming_alpha": 0.45,
  "glow": false, "glow_color": "", "glow_size": 1.0,
  "band": false, "band_color": "#000000", "band_opacity": 0.7,
  "card_border": false, "border_color": "#B8860B",
  "ornament": false, "ornament_color": "#D4AF37",
  "brackets": "full", "tr_italic": false }
```

`anim` can be `fade`, `slide_up`, `zoom_in`, `blur_in`, `karaoke`, `highlight`, `word_reveal` or `glow_word`. `brackets` can be `full`, `number` or `none`.

To use another Arabic font, put the `.ttf` in `fonts/`. It appears in the font picker after a restart if it renders Arabic correctly in ffmpeg. Fonts with the Uthmani marks show the Uthmani script; others show the standard script.

## 8. Test checklist

- [ ] `GET /api/health` returns `{"ok": true, "ffmpeg": true}`
- [ ] Sign up, sign in and sign out work (Supabase mode); without a token the API answers 401
- [ ] The surah list shows all 114 surahs; an invalid ayah range shows a clear message; the ayah text and translation appear
- [ ] Reciter: generate Al-Fatihah 1–7. Each caption changes exactly when the reciter starts the next ayah
- [ ] A long ayah (e.g. Al-Baqarah 255) with max 6 words per line: one line on screen at a time, each line changing as the reciter resumes after a pause
- [ ] Font picker, colour swatches, Arabic interface (العربية button) and dark mode toggle
- [ ] Upload a recitation (MP3/WAV): the surah and ayah range are detected and filled in automatically (the first run downloads the speech model). Captions follow the pauses. A non-audio file is rejected
- [ ] Each caption style renders correct Arabic with harakat, the ﴿ ﴾ brackets and RTL order. Translation and reference toggles work
- [ ] Library tab lists your media; uploading images and videos works; an invalid or oversized file is rejected with a message; delete removes your own upload
- [ ] "One background" and "Change with each ayah" both work with images and videos
- [ ] Landscape, portrait and square outputs; rounded frame with shadow; rounded caption box
- [ ] Watermark: upload a logo, try each position, size and opacity
- [ ] Progress bar updates, cancel works, the video plays in the page and downloads as `Quran_<Surah>_<range>.mp4`
- [ ] The only audio in the video is the recitation; the file is under `OUTPUT_LIMIT_MB`
- [ ] After a render, `WORK_DIR` contains no leftover job folders
