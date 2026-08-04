"""
پیکربندی مرکزی پالیز نیوز
==========================
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH, override=True)


class Config:
    # --- Turso Database ---
    TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "")
    TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")

    # --- Gemini AI ---
    GEMINI_API_KEYS: list[str] = [
        k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",")
        if k.strip()
    ] or [
        k.strip() for k in os.getenv("GEMINI_API_KEY", "").split(",")
        if k.strip()
    ]
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # --- سازگاری با کد قدیمی (برای ai_filter.py) ---
    @classmethod
    @property
    def GEMINI_API_KEY(cls) -> str:
        return cls.GEMINI_API_KEYS[0] if cls.GEMINI_API_KEYS else ""

    # --- Crawler Settings ---
    MAX_NEWS_PER_CYCLE: int = int(os.getenv("MAX_NEWS_PER_CYCLE", "10"))
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))
    MAX_NEWS_AGE_HOURS: int = int(os.getenv("MAX_NEWS_AGE_HOURS", "12"))
    SCRAPE_FULL_CONTENT: bool = os.getenv("SCRAPE_FULL_CONTENT", "true").lower() == "true"
    KEYWORD_FALLBACK_ENABLED: bool = True
    TRANSLATE_TO_PERSIAN: bool = True
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Local DB (برای development) ---
    DB_PATH: str = os.getenv("DB_PATH", "paliz_news.db")

    # --- کلمات کلیدی (بدون تغییر) ---
    PERSIAN_KEYWORDS = [
        "ایران", "تهران", "اصفهان", "مشهد", "تبریز",
        "خامنه‌ای", "خامنه اي", "روحانی", "رئیسی", "مشایی",
        "گشت ارشاد", "مجلس شورا", "جمهوری اسلامی", "سپاه",
        "برجام", "تحریم", "آرامکو", "انرژی اتمی",
        "مهسا", "اعتراض", "بازداشت",
        "ملی‌فوتبال", "تیم ملی", "پرسپولیس", "استقلال",
    ]
    PERSIAN_KEYWORDS_EXTRA = [
        "مردم ایران", "بازار ایران", "اقتصاد ایران", "ورزش ایران",
    ]
    ENGLISH_KEYWORDS = [
        "iran", "iranian", "tehran", "khamenei", "rouhani", "raisi",
        "kharg island", "pars", "israel-iran", "us-iran", "iran-deal",
        "jcpoa", "sanctions on iran", "iranian revolution", "irgc",
        "persian gulf", "iran nuclear", "iranian woman", "iran election",
    ]

    @classmethod
    def all_keywords(cls) -> list[str]:
        return cls.PERSIAN_KEYWORDS + cls.PERSIAN_KEYWORDS_EXTRA + cls.ENGLISH_KEYWORDS

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if not cls.TURSO_DATABASE_URL:
            errors.append("TURSO_DATABASE_URL تنظیم نشده است.")
        if not cls.TURSO_AUTH_TOKEN:
            errors.append("TURSO_AUTH_TOKEN تنظیم نشده است.")
        if not cls.GEMINI_API_KEYS:
            errors.append("GEMINI_API_KEYS تنظیم نشده است.")
        return errors


if __name__ == "__main__":
    errors = Config.validate()
    if errors:
        print("❌ خطاها:")
        for e in errors:
            print(f"   - {e}")
    else:
        print("✅ تنظیمات درست است")
        print(f"   • Turso URL: {Config.TURSO_DATABASE_URL[:30]}...")
        print(f"   • Gemini Keys: {len(Config.GEMINI_API_KEYS)} کلید")