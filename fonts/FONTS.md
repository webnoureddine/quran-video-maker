Fonts — all SIL Open Font License 1.1 (OFL-Amiri.txt has the licence text),
except DejaVu Sans (Bitstream Vera / DejaVu licence). Sources: github.com/google/fonts
and github.com/aliftype/amiri. Variable fonts were pinned to one weight
(static instance) because libass draws only the default instance.

Full Uthmani (Mushaf) text — every Quranic mark:
- Amiri Quran, Amiri — Khaled Hosny
- Scheherazade New — SIL International
- Noto Naskh Arabic, Noto Sans Arabic, Noto Kufi Arabic — Google
- Jomhuria — KB Studio

Display fonts — used with the standard "simple" Quran script (quran-simple
edition: same words, standard tashkeel, no Uthmani-only marks):
- Aref Ruqaa (Bold) — Abdullah Aref        · Ruq'ah
- Reem Kufi (700) — Khaled Hosny           · Kufi
- Kufam (700), Changa (600), Lalezar, Rakkas, Lemonada (600), Marhey (600)
- Cairo (700), Tajawal (Bold), Readex Pro (600)
- El Messiri (700), Markazi Text (600), Mirza, Katibeh, Vibes

Latin (translation):
- Montserrat (600), Playfair Display Italic, Lora, DejaVu Sans

Add any .ttf/.otf here; it appears in the font picker automatically if it
renders Arabic correctly in libass (checked at startup and cached).
