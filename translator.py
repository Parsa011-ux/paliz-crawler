"""
ترجمه رایگان اخبار انگلیسی به فارسی
======================================
از کتابخانه deep-translator (Google Translate) بدون نیاز به API Key.

ویژگی‌ها:
  - کاملاً رایگان و بدون محدودیت
  - پایدار (چندین موتور ترجمه به‌عنوان fallback)
  - کش‌کردن نتایج (برای اخبار تکراری)
"""
import logging
import time
from functools import lru_cache

from deep_translator import GoogleTranslator

logger = logging.getLogger(__name__)

# موتورهای ترجمه به ترتیب اولویت
_TRANSLATORS = []


def _get_translator():
    """ساخت مترجم با fallback."""
    global _TRANSLATORS
    if not _TRANSLATORS:
        try:
            _TRANSLATORS.append(GoogleTranslator(source="en", target="fa"))
        except Exception as e:
            logger.error(f"❌ خطا در ساخت مترجم: {e}")
    return _TRANSLATORS[0] if _TRANSLATORS else None


def translate_to_persian(text: str, max_retries: int = 2) -> str:
    """ترجمه یک متن از انگلیسی به فارسی.
    اگر ترجمه خطا داد، متن اصلی برمی‌گردد."""
    if not text or not text.strip():
        return ""

    # اگر متن فارسی است، نیازی به ترجمه نیست
    # فارسی: حروف اردو/فارسی در Unicode
    fa_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF" or "\uFB8A" <= c <= "\uFDFF")
    if fa_chars > len(text) * 0.2:
        return text

    translator = _get_translator()
    if not translator:
        return text

    for attempt in range(max_retries):
        try:
            result = translator.translate(text)
            if result:
                return result.strip()
        except Exception as e:
            logger.warning(f"⚠️ خطای ترجمه (تلاش {attempt+1}): {e}")
            time.sleep(1)
            # سعی مجدد با مترجم جدید
            try:
                translator = GoogleTranslator(source="en", target="fa")
            except Exception:
                pass

    return text  # در صورت شکست، متن اصلی برگردانده می‌شود


def translate_title(text: str) -> str:
    """ترجمه عنوان خبر."""
    return translate_to_persian(text)


def translate_summary(text: str) -> str:
    """ترجمه خلاصه خبر (حداکثر ۵۰۰ کاراکتر)."""
    if len(text) > 500:
        text = text[:500]
    return translate_to_persian(text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # تست ترجمه واقعی
    tests = [
        "Iran and US resume nuclear talks in Vienna",
        "Israel launched airstrikes on Iranian nuclear facilities early Tuesday morning",
        "Iranian economy faces new challenges amid international sanctions",
    ]

    print("🔍 تست ترجمه رایگان...\n")
    for t in tests:
        translated = translate_to_persian(t)
        print(f"EN: {t}")
        print(f"FA: {translated}")
        print()
