"""
منابع خبری ربات اخبار ایران
============================
منابع RSS مستقیم + Google News (با decoder).
"""
from dataclasses import dataclass


@dataclass
class Source:
    name: str
    url: str
    language: str
    priority: str

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
            "Mehr News": "مهر",
            "IRNA": "ایرنا",
            "Fars News": "فارس",
            "Al Jazeera": "الجزیره",
            "The Guardian": "گاردین",
            "Reuters World": "رویترز",
            "AP News": "آسوشیتدپرس",
            "Times of Israel": "تایمز آو اسرائیل",
            "Tehran Times": "تهران تایمز",
            "Press TV": "پرس تی‌وی",
            "Middle East Eye": "میدل ایست آی",
            "Middle East Monitor": "میدل ایست مانیتور",
            "Google News - Iran": "گوگل نیوز",
        }
        return names.get(self.name, self.name)


# ============================================================
# منابع فارسی
# ============================================================
PERSIAN_SOURCES: list[Source] = [
    # BBC Persian - RSS مستقیم
    Source(
        name="BBC Persian",
        url="https://feeds.bbci.co.uk/persian/rss.xml",
        language="fa",
        priority="normal",
    ),
    # Etemad Online
    Source(
        name="Etemad Online",
        url="https://www.etemadonline.com/feed",
        language="fa",
        priority="normal",
    ),
    # ISNA
    Source(
        name="ISNA",
        url="https://www.isna.ir/rss",
        language="fa",
        priority="normal",
    ),
    # Tasnim News
    Source(
        name="Tasnim",
        url="https://www.tasnimnews.com/fa/rss/feed/0/8/0/%D8%B3%DB%8C%D8%A7%D8%B3%DB%8C",
        language="fa",
        priority="normal",
    ),
    # Mehr News
    Source(
        name="Mehr News",
        url="https://www.mehrnews.com/rss",
        language="fa",
        priority="normal",
    ),
    # IRNA
    Source(
        name="IRNA",
        url="https://www.irna.ir/rss",
        language="fa",
        priority="normal",
    ),
    # Fars News
    Source(
        name="Fars News",
        url="https://www.farsnews.ir/rss",
        language="fa",
        priority="normal",
    ),
    # Iran International (Google News - با decoder)
    Source(
        name="Iran International",
        url="https://news.google.com/rss/search?q=site:irintl.com+when:2d&hl=fa&gl=IR&ceid=IR:fa",
        language="fa",
        priority="breaking",
    ),
    # Radio Farda (Google News - با decoder)
    Source(
        name="Radio Farda",
        url="https://news.google.com/rss/search?q=site:radiofarda.com+when:2d&hl=fa&gl=IR&ceid=IR:fa",
        language="fa",
        priority="normal",
    ),
]


# ============================================================
# منابع انگلیسی
# ============================================================
ENGLISH_SOURCES: list[Source] = [
    # Al Jazeera - RSS رسمی
    Source(
        name="Al Jazeera",
        url="https://www.aljazeera.com/xml/rss/all.xml",
        language="en",
        priority="normal",
    ),
    # The Guardian - Iran
    Source(
        name="The Guardian",
        url="https://www.theguardian.com/world/iran/rss",
        language="en",
        priority="normal",
    ),
    # Times of Israel - Iran
    Source(
        name="Times of Israel",
        url="https://www.timesofisrael.com/topic/iran/feed/",
        language="en",
        priority="breaking",
    ),
    # Middle East Eye
    Source(
        name="Middle East Eye",
        url="https://www.middleeasteye.net/rss.xml",
        language="en",
        priority="normal",
    ),
    # Middle East Monitor
    Source(
        name="Middle East Monitor",
        url="https://www.middleeastmonitor.com/feed/",
        language="en",
        priority="normal",
    ),
    # Press TV
    Source(
        name="Press TV",
        url="https://www.presstv.ir/rss.xml",
        language="en",
        priority="normal",
    ),
    # Tehran Times
    Source(
        name="Tehran Times",
        url="https://www.tehrantimes.com/rss",
        language="en",
        priority="normal",
    ),
    # Reuters (از طریق Google News - با decoder)
    Source(
        name="Reuters World",
        url="https://news.google.com/rss/search?q=site:reuters.com+Iran+when:2d&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="normal",
    ),
    # AP News (از طریق Google News - با decoder)
    Source(
        name="AP News",
        url="https://news.google.com/rss/search?q=site:apnews.com+Iran+when:2d&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="normal",
    ),
    # Google News - Breaking Iran News
    Source(
        name="Google News - Iran",
        url="https://news.google.com/rss/search?q=Iran+when:1d&hl=en-US&gl=US&ceid=US:en",
        language="en",
        priority="breaking",
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
    print(f"📊 کل منابع: {len(get_all_sources())}")
    print(f"   📰 منابع عادی: {len(get_regular_sources())}")
    print(f"   🚨 منابع خبر فوری: {len(get_breaking_sources())}")
    for s in get_all_sources():
        icon = "🚨" if s.priority == "breaking" else "📰"
        print(f"   {icon} {s.display_name} ({s.language})")
