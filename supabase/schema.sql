-- ════════════════════════════════════════════════════════════════════
--  Make Quran Video — Supabase schema, RLS policies and storage buckets
--  Run once in the Supabase dashboard → SQL Editor (safe to re-run).
-- ════════════════════════════════════════════════════════════════════

-- ───────── Surah metadata (public, read-only) ─────────
create table if not exists public.surahs (
  number      int primary key check (number between 1 and 114),
  name_ar     text not null,
  name_en     text not null,
  ayah_count  int  not null
);
alter table public.surahs enable row level security;
drop policy if exists "surahs are public" on public.surahs;
create policy "surahs are public" on public.surahs for select using (true);

-- ───────── Caption styles (extra/overriding styles, public read) ─────────
-- config holds any keys of app/captions.py DEFAULTS, e.g.
-- {"ar_color":"#FFD700","show_translation":true,"box":true,"box_opacity":0.5}
create table if not exists public.caption_styles (
  id          text primary key,
  label       text not null,
  description text default '',
  sort        int  default 99,
  is_active   boolean default true,
  config      jsonb not null default '{}'::jsonb
);
alter table public.caption_styles enable row level security;
drop policy if exists "caption styles are public" on public.caption_styles;
create policy "caption styles are public" on public.caption_styles for select using (is_active);

-- ───────── User preferences (one row per user, own row only) ─────────
create table if not exists public.user_preferences (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  prefs      jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table public.user_preferences enable row level security;
drop policy if exists "own preferences" on public.user_preferences;
create policy "own preferences" on public.user_preferences
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ───────── Render jobs (history + daily limit; written by the server) ─────────
create table if not exists public.render_jobs (
  id          text primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  status      text not null default 'queued' check (status in ('queued','running','done','error','cancelled')),
  title       text,
  surah       int references public.surahs(number),
  ayah_start  int,
  ayah_end    int,
  output_path text,
  error       text,
  created_at  timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists render_jobs_user_created on public.render_jobs (user_id, created_at desc);
alter table public.render_jobs enable row level security;
drop policy if exists "read own jobs" on public.render_jobs;
create policy "read own jobs" on public.render_jobs for select using (auth.uid() = user_id);
-- no insert/update policy: only the server (service key) writes jobs

-- ───────── Storage buckets (all private; the server hands out signed URLs) ─────────
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('library', 'library', false, 52428800, array['image/png','image/jpeg','image/webp','video/mp4','video/quicktime','video/webm','video/x-matroska']),
  ('uploads', 'uploads', false, 52428800, array['image/png','image/jpeg','image/webp','video/mp4','video/quicktime','video/webm','video/x-matroska']),
  ('outputs', 'outputs', false, 52428800, array['video/mp4'])
on conflict (id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Signed-in users may read the shared library, and read/write/delete only
-- inside their own folder (<user id>/...) of uploads, and read their outputs.
drop policy if exists "library readable by users" on storage.objects;
create policy "library readable by users" on storage.objects for select to authenticated
  using (bucket_id = 'library');
drop policy if exists "own uploads" on storage.objects;
create policy "own uploads" on storage.objects for all to authenticated
  using (bucket_id = 'uploads' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = 'uploads' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "own outputs" on storage.objects;
create policy "own outputs" on storage.objects for select to authenticated
  using (bucket_id = 'outputs' and (storage.foldername(name))[1] = auth.uid()::text);

-- ───────── Seed: the 114 surahs ─────────
insert into public.surahs (number, name_ar, name_en, ayah_count) values
  (1, 'الفاتحة', 'Al-Fatihah', 7),
  (2, 'البقرة', 'Al-Baqarah', 286),
  (3, 'آل عمران', 'Aal-E-Imran', 200),
  (4, 'النساء', 'An-Nisa', 176),
  (5, 'المائدة', 'Al-Ma''idah', 120),
  (6, 'الأنعام', 'Al-An''am', 165),
  (7, 'الأعراف', 'Al-A''raf', 206),
  (8, 'الأنفال', 'Al-Anfal', 75),
  (9, 'التوبة', 'At-Tawbah', 129),
  (10, 'يونس', 'Yunus', 109),
  (11, 'هود', 'Hud', 123),
  (12, 'يوسف', 'Yusuf', 111),
  (13, 'الرعد', 'Ar-Ra''d', 43),
  (14, 'إبراهيم', 'Ibrahim', 52),
  (15, 'الحجر', 'Al-Hijr', 99),
  (16, 'النحل', 'An-Nahl', 128),
  (17, 'الإسراء', 'Al-Isra', 111),
  (18, 'الكهف', 'Al-Kahf', 110),
  (19, 'مريم', 'Maryam', 98),
  (20, 'طه', 'Taha', 135),
  (21, 'الأنبياء', 'Al-Anbiya', 112),
  (22, 'الحج', 'Al-Hajj', 78),
  (23, 'المؤمنون', 'Al-Mu''minun', 118),
  (24, 'النور', 'An-Nur', 64),
  (25, 'الفرقان', 'Al-Furqan', 77),
  (26, 'الشعراء', 'Ash-Shu''ara', 227),
  (27, 'النمل', 'An-Naml', 93),
  (28, 'القصص', 'Al-Qasas', 88),
  (29, 'العنكبوت', 'Al-Ankabut', 69),
  (30, 'الروم', 'Ar-Rum', 60),
  (31, 'لقمان', 'Luqman', 34),
  (32, 'السجدة', 'As-Sajdah', 30),
  (33, 'الأحزاب', 'Al-Ahzab', 73),
  (34, 'سبأ', 'Saba', 54),
  (35, 'فاطر', 'Fatir', 45),
  (36, 'يس', 'Ya-Sin', 83),
  (37, 'الصافات', 'As-Saffat', 182),
  (38, 'ص', 'Sad', 88),
  (39, 'الزمر', 'Az-Zumar', 75),
  (40, 'غافر', 'Ghafir', 85),
  (41, 'فصلت', 'Fussilat', 54),
  (42, 'الشورى', 'Ash-Shura', 53),
  (43, 'الزخرف', 'Az-Zukhruf', 89),
  (44, 'الدخان', 'Ad-Dukhan', 59),
  (45, 'الجاثية', 'Al-Jathiyah', 37),
  (46, 'الأحقاف', 'Al-Ahqaf', 35),
  (47, 'محمد', 'Muhammad', 38),
  (48, 'الفتح', 'Al-Fath', 29),
  (49, 'الحجرات', 'Al-Hujurat', 18),
  (50, 'ق', 'Qaf', 45),
  (51, 'الذاريات', 'Adh-Dhariyat', 60),
  (52, 'الطور', 'At-Tur', 49),
  (53, 'النجم', 'An-Najm', 62),
  (54, 'القمر', 'Al-Qamar', 55),
  (55, 'الرحمن', 'Ar-Rahman', 78),
  (56, 'الواقعة', 'Al-Waqi''ah', 96),
  (57, 'الحديد', 'Al-Hadid', 29),
  (58, 'المجادلة', 'Al-Mujadilah', 22),
  (59, 'الحشر', 'Al-Hashr', 24),
  (60, 'الممتحنة', 'Al-Mumtahanah', 13),
  (61, 'الصف', 'As-Saff', 14),
  (62, 'الجمعة', 'Al-Jumu''ah', 11),
  (63, 'المنافقون', 'Al-Munafiqun', 11),
  (64, 'التغابن', 'At-Taghabun', 18),
  (65, 'الطلاق', 'At-Talaq', 12),
  (66, 'التحريم', 'At-Tahrim', 12),
  (67, 'الملك', 'Al-Mulk', 30),
  (68, 'القلم', 'Al-Qalam', 52),
  (69, 'الحاقة', 'Al-Haqqah', 52),
  (70, 'المعارج', 'Al-Ma''arij', 44),
  (71, 'نوح', 'Nuh', 28),
  (72, 'الجن', 'Al-Jinn', 28),
  (73, 'المزمل', 'Al-Muzzammil', 20),
  (74, 'المدثر', 'Al-Muddaththir', 56),
  (75, 'القيامة', 'Al-Qiyamah', 40),
  (76, 'الإنسان', 'Al-Insan', 31),
  (77, 'المرسلات', 'Al-Mursalat', 50),
  (78, 'النبأ', 'An-Naba', 40),
  (79, 'النازعات', 'An-Nazi''at', 46),
  (80, 'عبس', 'Abasa', 42),
  (81, 'التكوير', 'At-Takwir', 29),
  (82, 'الانفطار', 'Al-Infitar', 19),
  (83, 'المطففين', 'Al-Mutaffifin', 36),
  (84, 'الانشقاق', 'Al-Inshiqaq', 25),
  (85, 'البروج', 'Al-Buruj', 22),
  (86, 'الطارق', 'At-Tariq', 17),
  (87, 'الأعلى', 'Al-A''la', 19),
  (88, 'الغاشية', 'Al-Ghashiyah', 26),
  (89, 'الفجر', 'Al-Fajr', 30),
  (90, 'البلد', 'Al-Balad', 20),
  (91, 'الشمس', 'Ash-Shams', 15),
  (92, 'الليل', 'Al-Layl', 21),
  (93, 'الضحى', 'Ad-Duha', 11),
  (94, 'الشرح', 'Ash-Sharh', 8),
  (95, 'التين', 'At-Tin', 8),
  (96, 'العلق', 'Al-Alaq', 19),
  (97, 'القدر', 'Al-Qadr', 5),
  (98, 'البينة', 'Al-Bayyinah', 8),
  (99, 'الزلزلة', 'Az-Zalzalah', 8),
  (100, 'العاديات', 'Al-Adiyat', 11),
  (101, 'القارعة', 'Al-Qari''ah', 11),
  (102, 'التكاثر', 'At-Takathur', 8),
  (103, 'العصر', 'Al-Asr', 3),
  (104, 'الهمزة', 'Al-Humazah', 9),
  (105, 'الفيل', 'Al-Fil', 5),
  (106, 'قريش', 'Quraysh', 4),
  (107, 'الماعون', 'Al-Ma''un', 7),
  (108, 'الكوثر', 'Al-Kawthar', 3),
  (109, 'الكافرون', 'Al-Kafirun', 6),
  (110, 'النصر', 'An-Nasr', 3),
  (111, 'المسد', 'Al-Masad', 5),
  (112, 'الإخلاص', 'Al-Ikhlas', 4),
  (113, 'الفلق', 'Al-Falaq', 5),
  (114, 'الناس', 'An-Nas', 6)
on conflict (number) do update set name_ar = excluded.name_ar, name_en = excluded.name_en, ayah_count = excluded.ayah_count;
