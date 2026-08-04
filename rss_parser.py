"""
دریافت و پارس RSS
=================
این ماژول فیدهای RSS را دریافت کرده و اخبار خام را استخراج می‌کند.

وظایف:
  1. دریافت فید از هر منبع (با timeout و retry ساده)
  2. استخراج فیلدهای خبر (عنوان، لینک، خلاصه، تاریخ، منبع)
  3. نرمال‌سازی URL برای جلوگیری از تکرار
  4. فیلتر اولیه با کلمات کلیدی (برای کاهش حجم قبل از هوش مصنوعی)
  5. فیلتر سن خبر (حذف اخبار قدیمی‌تر از MAX_NEWS_AGE_HOURS ساعت)
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qs

import feedparser
import httpx

from config import Config
from sources import Source, get_all_sources, get_breaking_sources, get_regular_sources

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """نمایانگر یک خبر خام از RSS."""
    title: str               # عنوان خبر
    link: str                # لینک اصلی خبر
    summary: str             # خلاصه (HTML یا متن)
    source_name: str         # نام منبع (مثلاً BBC Persian)
    source_name_fa: str      # نام فارسی منبع
    language: str            # fa یا en
    priority: str            # breaking یا normal
    published: datetime | None  # زمان انتشار (در صورت وجود)
    fetched_at: datetime     # زمان دریافت توسط ربات

    @property
    def normalized_link(self) -> str:
        """URL نرمال‌شده برای مقایسه تکراری.
        بخش‌های ردیابی (query params) و fragment حذف می‌شوند."""
        try:
            parsed = urlparse(self.link)
            # حذف query string و fragment
            clean = parsed._replace(query="", fragment="")
            return urlunparse(clean).rstrip("/")
        except Exception:
            return self.link

    @property
    def title_clean(self) -> str:
        """عنوان پاک‌سازی شده.
        پسوندهای منبع که در RSS معمول است (مثل '- Devdiscourse', '| Reuters') حذف می‌شوند."""
        import re
        title = self.title.strip()

        # حذف پسوندهای رایج منبع با الگوهای "- نام منبع" یا "| نام منبع" در انتها
        # این الگو هر متن بعد از " - " یا " | " در انتها را حذف می‌کند
        title = re.sub(r"\s*[-–|]\s*[\w\s\.]+$", "", title).strip()

        # حذف پسوندهای مشخص و رایج
        suffixes = [
            " - BBC News", " - BBC Persian", " - Reuters", " - AP News",
            " - Al Jazeera", " - The Guardian", " | Reuters", " | AP News",
            " | Al Jazeera", " - Google News",
        ]
        for s in suffixes:
            if title.endswith(s):
                title = title[: -len(s)].strip()

        return title

    @property
    def summary_clean(self) -> str:
        """خلاصه پاک‌سازی شده.
        اگر خلاصه دقیقاً همان عنوان باشد (مشکل رایج Google News)، خالی برمی‌گرداند."""
        summary = _strip_html(self.summary)
        if not summary:
            return ""
        # اگر خلاصه با عنوان یکی است یا تقریباً یکی است، خالی برگردان
        if (summary.lower() == self.title_clean.lower()
                or self.title_clean.lower() in summary.lower()):
            return ""
        return summary


# ============================================================
# دریافت فید
# ============================================================
def fetch_feed(source: Source, timeout: int = 15) -> list[NewsItem]:
    """یک فید RSS را دریافت کرده و لیست NewsItem برمی‌گرداند."""
    items: list[NewsItem] = []
    try:
        # استفاده از httpx برای timeout کنترل‌شده
        headers = {
            "User-Agent": "IranNewsBot/1.0 (+https://github.com/yourrepo)"
        }
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(source.url)
            response.raise_for_status()
            content = response.content

        # پارس فید با feedparser
        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            logger.warning(f"⚠️ فید مشکل دارد: {source.name} - {feed.bozo_exception}")
            return items

        for entry in feed.entries:
            try:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()

                # حذف تگ‌های HTML ساده از خلاصه
                summary = _strip_html(summary)

                if not title or not link:
                    continue

                # استخراج منبع واقعی از Google News (به جای "Google News")
                real_source_name, real_source_fa = _extract_real_source(entry, source)

                # پارس تاریخ انتشار
                published = _parse_date(entry)

                items.append(NewsItem(
                    title=title,
                    link=link,
                    summary=summary[:500],  # محدود کردن طول خلاصه
                    source_name=real_source_name,
                    source_name_fa=real_source_fa,
                    language=source.language,
                    priority=source.priority,
                    published=published,
                    fetched_at=datetime.now(),
                ))
            except Exception as e:
                logger.debug(f"خطا در پارس یک entry از {source.name}: {e}")
                continue

        logger.info(f"📥 {source.name}: {len(items)} خبر دریافت شد")
    except httpx.TimeoutException:
        logger.warning(f"⏰ تایم‌اوت در دریافت {source.name}")
    except Exception as e:
        logger.error(f"❌ خطا در دریافت فید {source.name}: {e}")

    return items


# ============================================================
# فیلتر اولیه با کلمات کلیدی
# ============================================================
def keyword_filter(item: NewsItem) -> bool:
    """بررسی می‌کند که آیا خبر مرتبط با ایران است یا خیر.
    این فیلتر سریع است و حجم اخبار را قبل از ارسال به AI کاهش می‌دهد."""
    text = f"{item.title} {item.summary}".lower()

    if item.language == "en":
        keywords = [k.lower() for k in Config.ENGLISH_KEYWORDS]
    else:
        keywords = [k.lower() for k in Config.PERSIAN_KEYWORDS + Config.PERSIAN_KEYWORDS_EXTRA]

    return any(kw in text for kw in keywords)


# ============================================================
# توابع کمکی
# ============================================================
# نگاشت نام منابع انگلیسی به فارسی (برای نمایش در کانال)
_SOURCE_NAME_FA = {
    # منابع اصلی
    "BBC Persian": "بی‌بی‌سی فارسی", "BBC News": "بی‌بی‌سی",
    "Reuters": "رویترز", "AP News": "آسوشیتدپرس", "AP": "آسوشیتدپرس",
    "Al Jazeera": "الجزیره", "The Guardian": "گاردین",
    "Iran International": "ایران اینترنشنال", "Radio Farda": "رادیو فردا",
    "VOA Persian": "صدای آمریکا", "Deutsche Welle FA": "دویچه وله",
    "DW": "دویچه وله", "Etemad Online": "اعتماد",
    # منابع بین‌المللی پرتکرار Google News
    "WSJ": "وال‌استریت ژورنال", "Wall Street Journal": "وال‌استریت ژورنال",
    "NYTimes": "نیویورک تایمز", "New York Times": "نیویورک تایمز",
    "The New York Times": "نیویورک تایمز",
    "Washington Post": "واشنگتن‌پست", "The Washington Post": "واشنگتن‌پست",
    "CNN": "سی‌ان‌ان", "Fox News": "فاکس‌نیوز",
    "Bloomberg": "بلومبرگ", "Financial Times": "فایننشال تایمز",
    "Times of Israel": "تایمز آو اسرائیل",
    "Jerusalem Post": "جروزالم پست",
    "The Times": "تایمز", "The Telegraph": "تلگراف",
    "TIME": "تایم", "Forbes": "فوربز",
    "Newsweek": "نیوزویک", "The Hill": "هیل",
    "Politico": "پلیتیکو", "ABC News": "ای‌بی‌سی نیوز",
    "CBS News": "سی‌بی‌اس نیوز", "NBC News": "ان‌بی‌سی نیوز",
    "NPR": "ان‌پی‌آر", "The Economist": "اکونومیست",
    "Middle East Eye": "میدل ایست آی",
    "Middle East Monitor": "میدل ایست مانیتور",
    "Devdiscourse": "دیسکورس",
    "Tehran Times": "تهران تایمز",
    "Press TV": "پرس تی‌وی", "Mehr News": "مهر",
    "Tasnim": "تسنیم", "ISNA": "ایسنا", "IRNA": "ایرنا",
    "Kayhan": "کیهان", "Entekhab": "انتخاب",
    "Khaan Press": "خان پرس",
}


def _extract_real_source(entry, source: Source) -> tuple[str, str]:
    """استخراج منبع واقعی خبر از Google News.
    Google News در فیلد 'source' اطلاعات منبع اصلی را می‌دهد.
    خروجی: (نام انگلیسی، نام فارسی)"""
    # 1. تلاش با فیلد source در entry (روش اصلی Google News)
    src = entry.get("source")
    if src and isinstance(src, dict):
        title = src.get("title", "").strip()
        if title:
            return title, _SOURCE_NAME_FA.get(title, title)

    # 2. اگر منبع Google News نیست، از source اصلی فید استفاده کن
    if "Google News" not in source.name:
        return source.name, source.display_name

    # 3. تلاش با استخراج از URL منبع
    href = (src or {}).get("href", "") if src else ""
    if href:
        try:
            from urllib.parse import urlparse
            domain = urlparse(href).netloc.replace("www.", "")
            # تبدیل domain به نام نمایشی
            domain_names = {
                "reuters.com": "Reuters", "apnews.com": "AP News",
                "bbc.com": "BBC News", "bbc.co.uk": "BBC News",
                "aljazeera.com": "Al Jazeera", "theguardian.com": "The Guardian",
                "wsj.com": "WSJ", "nytimes.com": "New York Times",
                "washingtonpost.com": "Washington Post", "cnn.com": "CNN",
                "bloomberg.com": "Bloomberg", "ft.com": "Financial Times",
            }
            name = domain_names.get(domain, domain)
            return name, _SOURCE_NAME_FA.get(name, name)
        except Exception:
            pass

    return source.name, source.display_name


def _strip_html(text: str) -> str:
    """حذف تگ‌های HTML و entity ها از متن.
    نمونه‌هایی که پاک می‌شوند: <b>...</b>, &nbsp;, &amp;, &#8230; و ..."""
    import re
    import html

    if not text:
        return ""

    # 1. ابتدا entity های HTML را به کاراکتر واقعی تبدیل کن
    # این کار &nbsp; را به فضای غیرشکن (U+00A0) و &amp; را به & تبدیل می‌کند
    text = html.unescape(text)

    # 2. حذف تگ‌های HTML
    text = re.sub(r"<[^>]+>", "", text)

    # 3. جایگزینی فضای غیرشکن (nbsp) با فاصله معمولی
    text = text.replace("\xa0", " ")

    # 4. حذف کاراکترهای کنترلی و فاصله‌های صفر-عرض
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

    # 5. فشرده‌سازی چندین فاصله پشت سر هم به یک فاصله
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _parse_date(entry) -> datetime | None:
    """پارس تاریخ انتشار از entry RSS."""
    # feedparser معمولاً struct_time در entry.published_parsed می‌دهد
    for field in ["published_parsed", "updated_parsed", "created_parsed"]:
        t = entry.get(field)
        if t:
            try:
                return datetime(*t[:6])
            except Exception:
                continue
    return None


# ============================================================
# فیلتر سن خبر
# ============================================================
def age_filter(item: NewsItem, max_age_hours: int | None = None) -> bool:
    """بررسی می‌کند که آیا خبر جدید است یا قدیمی.
    اگر published مشخص نباشد، خبر نگه داشته می‌شود (محتاطانه)."""
    if max_age_hours is None:
        max_age_hours = Config.MAX_NEWS_AGE_HOURS

    # اگر زمان انتشار موجود نیست، خبر را نگه می‌داریم
    # (ممکن است از RSS گرفته نشده باشد ولی واقعاً جدید باشد)
    if item.published is None:
        return True

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    return item.published >= cutoff


# ============================================================
# توابع عمومی
# ============================================================
def fetch_all_news(only_breaking: bool = False, timeout: int = 15) -> list[NewsItem]:
    """همه اخبار از همه منابع را دریافت می‌کند.
    اگر only_breaking=True باشد، فقط منابع خبر فوری چک می‌شوند.
    اخبار قدیمی‌تر از MAX_NEWS_AGE_HOURS ساعت فیلتر می‌شوند."""
    sources = get_breaking_sources() if only_breaking else get_all_sources()
    all_items: list[NewsItem] = []

    for source in sources:
        items = fetch_feed(source, timeout=timeout)
        # فیلتر کلمات کلیدی + فیلتر سن خبر
        filtered = [
            item for item in items
            if keyword_filter(item) and age_filter(item)
        ]
        all_items.extend(filtered)
        # مکث کوتاه برای محترم شمردن سرورها
        time.sleep(0.3)

    logger.info(
        f"📊 مجموع: {len(all_items)} خبر مرتبط با ایران "
        f"(پس از فیلتر کلمات کلیدی و فیلتر سن {Config.MAX_NEWS_AGE_HOURS} ساعت)"
    )
    return all_items


def fetch_regular_news(timeout: int = 15) -> list[NewsItem]:
    """اخبار منابع عادی (غیر فوری) را دریافت می‌کند."""
    all_items: list[NewsItem] = []
    for source in get_regular_sources():
        items = fetch_feed(source, timeout=timeout)
        filtered = [
            item for item in items
            if keyword_filter(item) and age_filter(item)
        ]
        all_items.extend(filtered)
        time.sleep(0.3)
    return all_items


def fetch_breaking_news(timeout: int = 10) -> list[NewsItem]:
    """اخبار منابع خبر فوری را دریافت می‌کند."""
    all_items: list[NewsItem] = []
    for source in get_breaking_sources():
        items = fetch_feed(source, timeout=timeout)
        filtered = [
            item for item in items
            if keyword_filter(item) and age_filter(item)
        ]
        all_items.extend(filtered)
        time.sleep(0.2)
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    print("🔍 تست دریافت اخبار...")
    news = fetch_all_news()
    print(f"\n📌 {len(news)} خبر مرتبط با ایران پیدا شد:\n")
    for i, item in enumerate(news[:10], 1):
        icon = "🚨" if item.priority == "breaking" else "📰"
        print(f"{i}. {icon} [{item.source_name}] {item.title_clean}")
        print(f"   🔗 {item.normalized_link}\n")
