"""
منابع خبری ربات اخبار ایران
============================
تمام فیدهای RSS معتبر فارسی و انگلیسی برای اخبار ایران.

معیار انتخاب منبع:
  - معتبر و رسمی باشند (نه منابع ناشناس)
  - RSS رایگان ارائه دهند
  - پوشش خبری از ایران داشته باشند

اولویت منبع برای تشخیص خبر فوری (Breaking News):
  PRIORITY_BREAKING = اولویت بالا → در صورت مشاهده، احتمال خبر فوری بیشتر
  PRIORITY_NORMAL = اولویت عادی
"""
from dataclasses import dataclass


@dataclass
class Source:
    name: str           # نام نمایشی منبع
    url: str            # لینک فید RSS
    language: str       # "fa" یا "en"
    priority: str       # "breaking" یا "normal"

    @property
    def display_name(self) -> str:
        names = {
            "BBC Persian": "بی‌بی‌سی فارسی",
            "Iran International": "ایران اینترنشنال",
            "Radio Farda": "رادیو فردا",
            "Deutsche Welle FA": "دویچه وله",
            "VOA Persian": "صدای آمریکا",
            "Etemad Online": "اعتماد",
            "ISNA": "ایسنا",
            "Tasnim": "تسنیم",
        }
        return names.get(self.name, self.name)


# ============================================================
# منابع فارسی
# ============================================================
PERSIAN_SOURCES: list[Source] = [
    Source(
        name="BBC Persian",
        url="https://feeds.bbci.co.uk/persian/rss.xml",
        language="fa",
        priority="normal",
    ),
    # Iran International: پوشش از طریق Google News (RSS رسمی غیرفعال است)
    Source(
        name="Iran International",
        url="https://news.google.com/rss/search?q=site:irintl.com+when:2d&hl=fa&gl=IR&ceid=IR:fa",
        language="fa",
        priority="breaking",
    ),
    # Radio Farda: جستجوی موضوعی Google News (RSS مستقیم غیرفعال است)
    Source(
        name="Radio Farda",
        url="https://news.google.com/rss/search?q=site:radiofarda.com+when:2d&hl=fa&gl=IR&ceid=IR:fa",
        language="fa",
        priority="normal",
    ),
    # Deutsche Welle فارسی - پوشش از Google News (RSS رسمی غیرفعال است)
    Source(
        name="Deutsche Welle FA",
        url="https://news.google.com/rss/search?q=site:dw.com+Iran+when:2d&hl=fa&gl=IR&ceid=IR:fa",
        language="fa",
        priority="normal",
    ),
    # VOA Persian: جستجوی موضوعی Google News
    Source(
        name="VOA Persian",
        url="https://news.google.com/rss/search?q=site:voanews.com+Iran+when:2d&hl=fa&gl=IR&ceid=IR:fa",
        language="fa",
        priority="normal",
    ),
    Source(
        name="Etemad Online",
        url="https://www.etemadonline.com/feed",
        language="fa",
        priority="normal",
    ),
]


# ============================================================
# منابع انگلیسی (مخصوصاً با موضوع ایران)
# ============================================================
# لینک‌های «جستجوی موضوعی» با Google News RSS که یک موضوع خاص (ایران) را پوشش می‌دهند.
# این مزیت را دارد که نیازی به فیلتر کلمات کلیدی ندارند - خود فید فقط اخبار ایران است.
ENGLISH_SOURCES: list[Source] = [
    Source(
        name="Google News - Iran",
        url="https://news.google.com/rss/search?q=Iran+when:1d&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="normal",
    ),
    # خبر فوری بین‌المللی - اگر شامل ایران باشد احتمالاً مهم است
    Source(
        name="Google News Breaking - Iran",
        url="https://news.google.com/rss/search?q=(Iran+OR+Tehran+OR+Khamenei)+when:1h&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="breaking",
    ),
    Source(
        name="Reuters World",
        url="https://news.google.com/rss/search?q=site:reuters.com+Iran+when:2d&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="normal",
    ),
    Source(
        name="AP News - Iran",
        url="https://news.google.com/rss/search?q=site:apnews.com+Iran+when:2d&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="normal",
    ),
    Source(
        name="Al Jazeera - Iran",
        url="https://www.aljazeera.com/xml/rss/all.xml",
        language="en",
        priority="normal",
    ),
    Source(
        name="The Guardian - Iran tag",
        url="https://www.theguardian.com/world/iran/rss",
        language="en",
        priority="normal",
    ),
]


def get_all_sources() -> list[Source]:
    """همه منابع فارسی و انگلیسی را برمی‌گرداند."""
    return PERSIAN_SOURCES + ENGLISH_SOURCES


def get_breaking_sources() -> list[Source]:
    """فقط منابع با اولویت خبر فوری را برمی‌گرداند."""
    return [s for s in get_all_sources() if s.priority == "breaking"]


def get_regular_sources() -> list[Source]:
    """فقط منابع با اولویت عادی را برمی‌گرداند."""
    return [s for s in get_all_sources() if s.priority == "normal"]


if __name__ == "__main__":
    # تست سریع منابع
    print(f"📊 کل منابع: {len(get_all_sources())}")
    print(f"   📰 منابع عادی: {len(get_regular_sources())}")
    print(f"   🚨 منابع خبر فوری: {len(get_breaking_sources())}")
    for s in get_all_sources():
        icon = "🚨" if s.priority == "breaking" else "📰"
        print(f"   {icon} {s.display_name} ({s.language})")
