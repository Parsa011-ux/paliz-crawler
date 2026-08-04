"""
فیلتر هوش مصنوعی با Gemini
============================
این ماژول از Google Gemini (رایگان) برای:
  1. ارزیابی مرتبط بودن خبر با ایران
  2. ترجمه عناوین و خلاصه‌های انگلیسی به فارسی
  3. تولید خلاصه فارسی جذاب برای تلگرام
  4. تشخیص خبر فوری (Breaking News)

سیستم چرخش کلیدها (Round-Robin):
  - چندین کلید API پشتیبانی می‌شود
  - هر کلید 20 درخواست در روز مجاز است
  - اگر کلیدی لیمیت بخورد، خودکار به بعدی می‌رود
  - کلیدهای تمام‌شده روز بعد ریست می‌شوند

تاب‌آوری:
  - اگر همه کلیدها لیمیت بخورن، به فیلتر کلمات کلیدی + ترجمه رایگان برمی‌گرده
"""
import json
import logging
import time
from dataclasses import dataclass

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

from config import Config
from rss_parser import NewsItem

logger = logging.getLogger(__name__)


# ============================================================
# مدیریت چند کلید API (Round-Robin)
# ============================================================
class KeyManager:
    """مدیریت چرخش بین چندین کلید API Gemini.
    هر کلید 20 درخواست در روز مجاز است.
    اگر کلیدی لیمیت بخورد، تا روز بعد غیرفعال می‌شود."""

    def __init__(self, keys: list[str]):
        self.keys = [k for k in keys if k]
        # وضعیت هر کلید: (فعال؟, زمان ریست)
        self.disabled_until: dict[int, float] = {}
        self._current_index = 0

    @property
    def total_keys(self) -> int:
        return len(self.keys)

    @property
    def active_keys_count(self) -> int:
        now = time.time()
        return sum(1 for i in range(len(self.keys))
                   if i not in self.disabled_until or self.disabled_until[i] < now)

    def get_next_key(self) -> str | None:
        """کلید بعدی فعال را برمی‌گرداند (Round-Robin).
        اگر همه غیرفعال باشند، None برمی‌گرداند."""
        if not self.keys:
            return None

        now = time.time()
        # پاک‌سازی کلیدهایی که زمان غیرفعالیشون تموم شده
        expired = [i for i, t in self.disabled_until.items() if t < now]
        for i in expired:
            del self.disabled_until[i]

        # پیدا کردن کلید فعال بعدی
        for _ in range(len(self.keys)):
            idx = self._current_index % len(self.keys)
            self._current_index += 1
            if idx not in self.disabled_until:
                return self.keys[idx]

        # همه غیرفعالند
        return None

    def disable_key(self, key: str, seconds: int = 86400) -> None:
        """یک کلید را تا seconds ثانیه غیرفعال می‌کند (پیش‌فرض: 24 ساعت)."""
        try:
            idx = self.keys.index(key)
            self.disabled_until[idx] = time.time() + seconds
            logger.warning(
                f"🔑 کلید {idx+1}/{len(self.keys)} تا {seconds//3600} ساعت غیرفعال شد "
                f"({self.active_keys_count} کلید فعال باقی مانده)"
            )
        except ValueError:
            pass


# نمونه سراسری KeyManager
_key_manager: KeyManager | None = None


def _get_key_manager() -> KeyManager:
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyManager(Config.GEMINI_API_KEYS)
        logger.info(f"🔑 مدیریت کلیدها راه‌اندازی شد: {len(Config.GEMINI_API_KEYS)} کلید")
    return _key_manager


# ============================================================
# مدل داده خروجی AI
# ============================================================
@dataclass
class AIEvaluation:
    """نتیجه ارزیابی یک خبر توسط AI."""
    is_relevant: bool          # آیا به ایران مربوط است؟
    is_breaking: bool          # آیا خبر فوری است؟
    importance_score: int      # امتیاز اهمیت 1-10
    title_fa: str              # عنوان فارسی (ترجمه یا اصلی)
    summary_fa: str            # خلاصه فارسی 2-3 خطی
    category: str              # دسته‌بندی: سیاسی/اقتصادی/ورزشی/اجتماعی/نظامی
    reason: str                # دلیل ارزیابی (برای دیباگ)


# ============================================================
# راه‌اندازی Gemini
# ============================================================
_model = None


def _get_model():
    """ساخت مدل Gemini (Singleton)."""
    global _model
    if _model is None:
        if not Config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY تنظیم نشده است")
        genai.configure(api_key=Config.GEMINI_API_KEY)
        _model = genai.GenerativeModel(
            Config.GEMINI_MODEL,
            generation_config={
                "temperature": 0.3,        # کم‌تنظیم برای خروجی پایدارتر
                "top_p": 0.9,
                "max_output_tokens": 2048,
            },
        )
    return _model


def _extract_json(text: str) -> dict:
    """استخراج JSON از متن پاسخ Gemini.
    Gemini گاهی JSON را داخل بلوک کد یا با متن اضافه می‌فرستد."""
    import re
    import json
    if not text:
        return {}
    # حذف بلوک‌های کد markdown
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")
    # پیدا کردن اولین { و آخرین }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end + 1]
        return json.loads(json_str)
    return json.loads(text)


# ============================================================
# پرامپت ارزیابی
# ============================================================
EVAL_PROMPT = """تو یک ویراستار خبرگزاری فارسی‌زبان هستی. یک خبر به تو داده می‌شود.
وظیفه تو:
  1. تشخیص دهی که آیا این خبر واقعاً و مستقیماً به ایران مربوط است یا خیر
     (اخبار کشورهای دیگر که فقط اسم ایران در آن‌ها رد شده، مرتبط نیست).
  2. تشخیص دهی که آیا این خبر «فوری/مهم» است (مثل: حمله نظامی، زلزله،
     ترور، اعلام رسمی مهم، تحریم‌های جدید، رویداد بزرگ).
  3. اگر خبر انگلیسی است، عنوان و خلاصه را به فارسی روان و خبری ترجمه کن.
  4. یک خلاصه فارسی ۲-۳ خطی و جذاب بنویس که برای کانال تلگرام مناسب باشد.
  5. امتیاز اهمیت ۱ تا ۱۰ بده.

خروجی را فقط به صورت JSON زیر برگردان، بدون هیچ متن اضافه‌ای:
{
  "is_relevant": true یا false,
  "is_breaking": true یا false,
  "importance_score": عدد 1 تا 10,
  "title_fa": "عنوان فارسی خبر",
  "summary_fa": "خلاصه ۲-۳ خطی فارسی",
  "category": "سیاسی" یا "اقتصادی" یا "ورزشی" یا "اجتماعی" یا "نظامی" یا "فرهنگی",
  "reason": "دلیل کوتاه"
}

عنوان خبر: {title}
خلاصه خبر: {summary}
منبع: {source} ({language})
"""


# ============================================================
# ارزیابی یک خبر
# ============================================================
def evaluate_news(item: NewsItem) -> AIEvaluation:
    """ارزیابی یک خبر با Gemini. در صورت خطا، fallback می‌شود."""
    try:
        model = _get_model()
        prompt = EVAL_PROMPT.format(
            title=item.title_clean,
            summary=item.summary or "(خلاصه موجود نیست)",
            source=item.source_name,
            language="فارسی" if item.language == "fa" else "انگلیسی",
        )

        response = model.generate_content(prompt)
        data = _extract_json(response.text)

        return AIEvaluation(
            is_relevant=bool(data.get("is_relevant", True)),
            is_breaking=bool(data.get("is_breaking", False)),
            importance_score=int(data.get("importance_score", 5)),
            title_fa=str(data.get("title_fa", item.title_clean))[:200],
            summary_fa=str(data.get("summary_fa", item.summary))[:500],
            category=str(data.get("category", "سیاسی")),
            reason=str(data.get("reason", "")),
        )
    except json.JSONDecodeError as e:
        logger.warning(f"⚠️ پاسخ Gemini قابل پارس نبود: {e}")
        return _fallback_evaluation(item)
    except Exception as e:
        logger.error(f"❌ خطای Gemini در ارزیابی خبر: {e}")
        return _fallback_evaluation(item)


# ============================================================
# ارزیابی دسته‌ای (برای کاهش تعداد درخواست)
# ============================================================
BATCH_PROMPT = """تو یک ویراستار خبرگزاری فارسی‌زبان هستی. چند خبر به تو داده می‌شود.
برای هر خبر تشخیص بده:
  1. آیا واقعاً به ایران مربوط است؟
  2. آیا خبر فوری/مهم است؟
  3. عنوان و خلاصه فارسی مناسب برای تلگرام
  4. امتیاز اهمیت ۱-۱۰

خروجی فقط به صورت JSON با ساختار زیر:
{{
  "results": [
    {{
      "index": 0,
      "is_relevant": true/false,
      "is_breaking": true/false,
      "importance_score": 1-10,
      "title_fa": "عنوان فارسی",
      "summary_fa": "خلاصه ۲-۳ خطی فارسی",
      "category": "سیاسی|اقتصادی|ورزشی|اجتماعی|نظامی|فرهنگی"
    }}
  ]
}}

اخبار:
{news_list}
"""


def evaluate_batch(items: list[NewsItem], batch_size: int = 5) -> list[AIEvaluation | None]:
    """ارزیابی چند خبر در یک درخواست (صرفه‌جویی در API).
    اگر خطایی رخ دهد، برای آن مورد None برمی‌گرداند."""
    results: list[AIEvaluation | None] = []

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        try:
            news_text = "\n\n".join(
                f"[{idx}] عنوان: {it.title_clean}\n"
                f"    خلاصه: {it.summary or '—'}\n"
                f"    منبع: {it.source_name} ({it.language})"
                for idx, it in enumerate(batch)
            )
            prompt = BATCH_PROMPT.format(news_list=news_text)

            model = _get_model()
            response = model.generate_content(prompt)
            data = _extract_json(response.text)
            batch_results = data.get("results", [])

            for j, item in enumerate(batch):
                # پیدا کردن نتیجه مطابق index
                match = next((r for r in batch_results if r.get("index") == j), None)
                if match:
                    results.append(AIEvaluation(
                        is_relevant=bool(match.get("is_relevant", True)),
                        is_breaking=bool(match.get("is_breaking", False)),
                        importance_score=int(match.get("importance_score", 5)),
                        title_fa=str(match.get("title_fa", item.title_clean))[:200],
                        summary_fa=str(match.get("summary_fa", item.summary))[:500],
                        category=str(match.get("category", "سیاسی")),
                        reason="batch",
                    ))
                else:
                    results.append(_fallback_evaluation(item))

            # مکث برای محترم شمردن محدودیت rate limit
            time.sleep(1)
        except Exception as e:
            logger.error(f"❌ خطا در ارزیابی دسته‌ای: {e}")
            for item in batch:
                results.append(_fallback_evaluation(item))

    return results


# ============================================================
# حالت fallback (بدون AI) - با ترجمه رایگان
# ============================================================
def _fallback_evaluation(item: NewsItem) -> AIEvaluation:
    """ارزیابی بدون AI - فقط با اطلاعات موجود.
    این حالت زمانی استفاده می‌شود که Gemini در دسترس نباشد.
    اخبار انگلیسی با مترجم رایگان به فارسی ترجمه می‌شوند.
    امتیاز بر اساس منبع و طول خبر تعیین می‌شود."""
    from translator import translate_title, translate_summary

    # --- امتیازدهی هوشمند بر اساس منبع ---
    source_scores = {
        "BBC Persian": 8, "Al Jazeera": 8, "Reuters": 8,
        "Iran International": 7, "Radio Farda": 7,
        "AP News": 8, "The Guardian": 7,
        "VOA Persian": 6, "Deutsche Welle FA": 6,
        "Etemad Online": 5,
    }
    base_score = source_scores.get(item.source_name, 5)

    # افزایش امتیاز برای منابع خبر فوری
    if item.priority == "breaking":
        base_score = max(base_score, 7)

    # افزایش بر اساس طول خلاصه (خبرهای بلندتر معمولاً مهم‌ترند)
    summary_len = len(item.summary_clean) if hasattr(item, 'summary_clean') else len(item.summary or "")
    if summary_len > 300:
        base_score = min(base_score + 1, 9)

    # کاهش برای اخبار ورزشی (معمولاً کم‌اهمیت‌تر)
    sports_keywords = ["football", "soccer", "cricket", "tennis", "basketball",
                        "فوتبال", "کریکت", "تنیس", "بسکتبال", "لیگ", "مسابقه"]
    title_lower = item.title_clean.lower()
    if any(kw in title_lower for kw in sports_keywords):
        base_score = max(base_score - 2, 3)

    # --- ترجمه ---
    title_fa = item.title_clean
    summary_fa = ""
    category = "سیاسی"

    # تشخیص دسته‌بندی ساده
    if any(kw in title_lower for kw in ["football", "soccer", "فوتبال", "ورزش", "مسابقه", "olympic"]):
        category = "ورزشی"
        base_score = max(base_score - 1, 3)
    elif any(kw in title_lower for kw in ["earthquake", "زلزله", "flood", "سیل", "storm"]):
        category = "اجتماعی"
        base_score = min(base_score + 1, 9)
    elif any(kw in title_lower for kw in ["sanction", "تحریم", "economy", "اقتصاد", "oil", "نفت", "price"]):
        category = "اقتصادی"
    elif any(kw in title_lower for kw in ["attack", "strike", "حمله", "بمباران", "missile", "موشک", "military", "نظامی"]):
        category = "نظامی"
        base_score = min(base_score + 1, 9)

    # ترجمه فارسی عنوان
    if item.language == "en":
        try:
            title_fa = translate_title(item.title_clean)
        except Exception as e:
            logger.debug(f"ترجمه عنوان خطا داد: {e}")
            title_fa = item.title_clean

        # ترجمه خلاصه
        summary_text = item.summary_clean if hasattr(item, 'summary_clean') else item.summary
        if summary_text:
            try:
                summary_fa = translate_summary(summary_text)
            except Exception as e:
                logger.debug(f"ترجمه خلاصه خطا داد: {e}")
                summary_fa = summary_text
    else:
        summary_fa = item.summary_clean if hasattr(item, 'summary_clean') else (item.summary or "")

    is_breaking = item.priority == "breaking" and base_score >= 7

    return AIEvaluation(
        is_relevant=True,
        is_breaking=is_breaking,
        importance_score=base_score,
        title_fa=title_fa,
        summary_fa=summary_fa,
        category=category,
        reason="fallback + ترجمه رایگان + امتیاز هوشمند",
    )


# ============================================================
# فیلتر نهایی لیست اخبار
# ============================================================
def filter_and_enhance(items: list[NewsItem], use_batch: bool = True) -> list[tuple[NewsItem, AIEvaluation]]:
    """لیست اخبار را ارزیابی کرده و فقط موارد مرتبط را برمی‌گرداند.
    خروجی: لیست (خبر, ارزیابی) مرتب شده بر اساس اهمیت."""
    if not items:
        return []

    if Config.KEYWORD_FALLBACK_ENABLED is False and not Config.GEMINI_API_KEY:
        # بدون AI
        logger.warning("⚠️ Gemini فعال نیست - استفاده از فیلتر ساده")
        return [(it, _fallback_evaluation(it)) for it in items]

    logger.info(f"🤖 ارزیابی {len(items)} خبر با Gemini...")

    if use_batch:
        evaluations = evaluate_batch(items)
    else:
        evaluations = [evaluate_news(it) for it in items]
        time.sleep(0.5)

    # فقط اخبار مرتبط
    result: list[tuple[NewsItem, AIEvaluation]] = []
    for item, eval_result in zip(items, evaluations):
        if eval_result and eval_result.is_relevant:
            result.append((item, eval_result))

    # مرتب‌سازی بر اساس اهمیت (نزولی)
    result.sort(key=lambda x: x[1].importance_score, reverse=True)

    logger.info(f"✅ {len(result)} خبر از {len(items)} مورد مرتبط بود")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if not Config.GEMINI_API_KEY:
        print("❌ ابتدا GEMINI_API_KEY را در .env تنظیم کنید")
        exit(1)

    from rss_parser import fetch_all_news

    print("🔍 دریافت اخبار...")
    news = fetch_all_news()[:3]
    print(f"📊 {len(news)} خبر برای تست")

    for item in news:
        print(f"\n📌 ارزیابی: {item.title_clean[:60]}...")
        ev = evaluate_news(item)
        print(f"   مرتبط: {ev.is_relevant} | فوری: {ev.is_breaking} | امتیاز: {ev.importance_score}")
        print(f"   عنوان FA: {ev.title_fa}")
        print(f"   خلاصه FA: {ev.summary_fa[:100]}")
