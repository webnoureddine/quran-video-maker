"""
i18n.py — every message the server can show to a user, in English and Arabic.

Code raises AppError("key", **params); the server translates it for the
language the browser sends in the X-Lang header ("en" | "ar").
"""

MESSAGES = {
    # ── Quran range ──
    "range_required": ("Please choose a surah and an ayah range.", "يرجى اختيار سورة ونطاق الآيات."),
    "surah_invalid": ("Please choose a valid surah.", "يرجى اختيار سورة صحيحة."),
    "range_invalid": ("{surah} has {n} ayahs — choose a range between 1 and {n}.",
                      "سورة {surah} عدد آياتها {n} — اختر نطاقًا بين 1 و {n}."),
    "range_too_long": ("Please choose at most {n} ayahs per video.", "يرجى اختيار {n} آية كحد أقصى لكل فيديو."),
    "no_ayah": ("No ayah found in that range.", "لم يتم العثور على آيات في هذا النطاق."),
    "quran_unreachable": ("The Quran text service could not be reached. Please try again.",
                          "تعذر الوصول إلى خدمة نص القرآن. يرجى المحاولة مرة أخرى."),
    "recitation_download": ("The recitation could not be downloaded. Please try again.",
                            "تعذر تنزيل التلاوة. يرجى المحاولة مرة أخرى."),
    # ── audio ──
    "audio_required": ("Please choose a recitation audio file.", "يرجى اختيار ملف صوتي للتلاوة."),
    "audio_type": ("Please upload an MP3, WAV, M4A, AAC, OGG or FLAC file.",
                   "يرجى رفع ملف بصيغة MP3 أو WAV أو M4A أو AAC أو OGG أو FLAC."),
    "audio_invalid": ("This file does not contain any audio.", "هذا الملف لا يحتوي على صوت."),
    "audio_short": ("This audio file is empty or too short.", "الملف الصوتي فارغ أو قصير جدًا."),
    "audio_long": ("This recitation is {dur} minutes long; the maximum is {max} minutes.",
                   "مدة هذه التلاوة {dur} دقيقة، والحد الأقصى {max} دقيقة."),
    "audio_reupload": ("Please upload the recitation audio again.", "يرجى رفع ملف التلاوة مرة أخرى."),
    "audio_unreadable": ("The recitation audio could not be read. Please upload a valid MP3, WAV or M4A file.",
                         "تعذرت قراءة ملف التلاوة. يرجى رفع ملف MP3 أو WAV أو M4A صالح."),
    "detect_failed": ("The surah and ayahs could not be recognised. Please choose them above.",
                      "تعذر التعرف على السورة والآيات. يرجى اختيارها في الأعلى."),
    "detect_unavailable": ("Automatic recognition is not installed on this server. Please choose the surah and ayahs above.",
                           "التعرف التلقائي غير مثبت على هذا الخادم. يرجى اختيار السورة والآيات في الأعلى."),
    "reciter_required": ("Please choose a reciter.", "يرجى اختيار القارئ."),
    # ── media ──
    "file_too_large": ("“{name}” is larger than {mb} MB.", "حجم «{name}» أكبر من {mb} ميغابايت."),
    "file_empty": ("“{name}” is empty.", "الملف «{name}» فارغ."),
    "upload_too_large": ("The upload is too large (maximum {mb} MB per file).",
                         "حجم الرفع كبير جدًا (الحد الأقصى {mb} ميغابايت لكل ملف)."),
    "media_type": ("“{name}” is not a supported image (PNG, JPG, WEBP) or video (MP4, MOV, WEBM).",
                   "«{name}» ليس صورة مدعومة (PNG أو JPG أو WEBP) ولا فيديو مدعومًا (MP4 أو MOV أو WEBM)."),
    "image_invalid": ("This file is not a valid image.", "هذا الملف ليس صورة صالحة."),
    "image_small": ("This image is too small to be used as a background (minimum 200 px).",
                    "هذه الصورة صغيرة جدًا لاستخدامها كخلفية (الحد الأدنى 200 بكسل)."),
    "video_invalid": ("This file is not a valid video.", "هذا الملف ليس فيديو صالحًا."),
    "logo_type": ("The logo must be a PNG, JPG or WEBP image (PNG with transparency works best).",
                  "يجب أن يكون الشعار صورة PNG أو JPG أو WEBP (يفضل PNG بخلفية شفافة)."),
    "font_type": ("Please upload a font file: TTF, OTF, WOFF or WOFF2.", "يرجى رفع ملف خط بصيغة TTF أو OTF أو WOFF أو WOFF2."),
    "font_invalid": ("This file is not a valid font.", "هذا الملف ليس خطًا صالحًا."),
    "font_unusable": ("This font cannot display Arabic or Latin text in videos. Please try another font.",
                      "لا يمكن لهذا الخط عرض النص العربي أو اللاتيني في الفيديو. يرجى تجربة خط آخر."),
    "font_required": ("Please choose a font file.", "يرجى اختيار ملف خط."),
    "logo_required": ("Please choose a logo image.", "يرجى اختيار صورة الشعار."),
    "media_required": ("Please choose at least one image or video.", "يرجى اختيار صورة أو فيديو واحد على الأقل."),
    "bg_required": ("Please choose at least one background image or video.",
                    "يرجى اختيار صورة أو فيديو خلفية واحد على الأقل."),
    "bg_too_many": ("Please choose at most {n} backgrounds.", "يرجى اختيار {n} خلفية كحد أقصى."),
    "media_invalid": ("Invalid media selection.", "اختيار وسائط غير صالح."),
    "media_unavailable": ("This media item is not available.", "عنصر الوسائط هذا غير متاح."),
    "media_gone": ("This media item is no longer available.", "عنصر الوسائط هذا لم يعد متاحًا."),
    "media_load_failed": ("“{name}” could not be loaded from the media library.",
                          "تعذر تحميل «{name}» من مكتبة الوسائط."),
    "media_save_failed": ("“{name}” could not be saved. Please try again.", "تعذر حفظ «{name}». يرجى المحاولة مرة أخرى."),
    "library_readonly": ("Library items can only be removed by the administrator.",
                         "لا يمكن حذف عناصر المكتبة إلا من قبل المسؤول."),
    "library_failed": ("The media library could not be loaded. Please try again.",
                       "تعذر تحميل مكتبة الوسائط. يرجى المحاولة مرة أخرى."),
    "logo_failed": ("The logo could not be saved. Please try again.", "تعذر حفظ الشعار. يرجى المحاولة مرة أخرى."),
    "bg_unsupported": ("Unsupported background file: {name}", "ملف خلفية غير مدعوم: {name}"),
    "bg_broken": ("The background “{name}” could not be processed. Please choose another image or video.",
                  "تعذرت معالجة الخلفية «{name}». يرجى اختيار صورة أو فيديو آخر."),
    # ── account / jobs ──
    "sign_in": ("Please sign in to continue.", "يرجى تسجيل الدخول للمتابعة."),
    "daily_limit": ("You have reached the limit of {n} videos per day. Please try again tomorrow.",
                    "لقد وصلت إلى الحد اليومي ({n} فيديو). يرجى المحاولة غدًا."),
    "prefs_large": ("Preferences are too large.", "الإعدادات كبيرة جدًا."),
    "prefs_failed": ("Your settings could not be saved.", "تعذر حفظ إعداداتك."),
    "too_long_audio": ("The recitation is {dur} minutes long. The maximum is {max} minutes — please choose fewer ayahs.",
                       "مدة التلاوة {dur} دقيقة والحد الأقصى {max} دقيقة — يرجى اختيار آيات أقل."),
    "render_failed": ("The video could not be generated. Please try again, or choose different backgrounds.",
                      "تعذر إنشاء الفيديو. يرجى المحاولة مرة أخرى أو اختيار خلفيات مختلفة."),
    "server_error": ("Something went wrong on our side. Please try again.", "حدث خطأ من جهتنا. يرجى المحاولة مرة أخرى."),
}


class AppError(ValueError):
    """An error whose message is shown to the user (translated)."""

    def __init__(self, key: str, **params):
        self.key, self.params = key, params
        super().__init__(t(key, "en", **params))


def t(key: str, lang: str = "en", **params) -> str:
    en, ar = MESSAGES.get(key, (key, key))
    text = ar if lang == "ar" else en
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        return text
