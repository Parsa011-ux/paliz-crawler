"""
دریافت و پارس RSS
=================
این ماژول فیدهای RSS را دریافت کرده و اخبار خام را استخراج می‌کند.

وظایف:
  1. دریافت فید از هر منبع (با timeout و retry ساده)
  2. استخراج فیلدهای خبر (عنوان، لینک، خلاصه، تاریخ، منبع، تصویر)
  3. نرمال‌سازی URL برای جلوگیری از تکرار
  4. فیلتر اولیه با کلمات کلیدی (برای کاهش حجم قبل از هوش مصنوعی)
  5. فیلتر سن خبر (حذف اخبار قدیمی‌تر از MAX_NEWS_AGE_HOURS ساعت)
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx

from config import Config
from sources import Source, get_all_sources, get_breaking_sources, get_regular_sources

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """نمایانگر یک خبر خام از RSS."""
    title: str
    link: str
    summary: str
    source_name: str
    source_name_fa: str
    language: str
    priority: str
    published: datetime | None
    fetched_at: datetime
    image_url: str | None = None

    @property
    def normalized_link(self) -> str:
        """URL نرمال‌شده برای مقایسه تکراری."""
        try:
            parsed = urlparse(self.link)
            clean = parsed._replace(query="", fragment="")
            return urlunparse(clean).rstrip("/")
        except Exception:
            return self.link

    @property
    def title_clean(self) -> str:
        """عنوان پاک‌سازی شده."""
        title = self.title.strip()
        title = re.sub(r"\s*[-–|]\s*[\w\s\.]+$", "", title).strip()
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
        """خلاصه پاک‌سازی شده."""
        summary = _strip_html(self.summary)
        if not summary:
            return ""
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
        headers = {
            "User-Agent": "IranNewsBot/1.0 (+https://github.com/yourrepo)"
        }
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(source.url)
            response.raise_for_status()
            content = response.content

        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            logger.warning(f"⚠️ فید مشکل دارد: {source.name} - {feed.bozo_exception}")
            return items

        for entry in feed.entries:
            try:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                summary = _strip_html(summary)

                if not title or not link:
                    continue

                real_source_name, real_source_fa = _extract_real_source(entry, source)
                published = _parse_date(entry)
                
                # استخراج تصویر از RSS
                rss_image = _extract_rss_image(entry)

                items.append(NewsItem(
                    title=title,
                    link=link,
                    summary=summary[:500],
                    source_name=real_source_name,
                    source_name_fa=real_source_fa,
                    language=source.language,
                    priority=source.priority,
                    published=published,
                    fetched_at=datetime.now(),
                    image_url=rss_image,
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
    """بررسی می‌کند که آیا خبر مرتبط با ایران است یا خیر."""
    text = f"{item.title} {item.summary}".lower()

    if item.language == "en":
        keywords = [k.lower() for k in Config.ENGLISH_KEYWORDS]
    else:
        keywords = [k.lower() for k in Config.PERSIAN_KEYWORDS + Config.PERSIAN_KEYWORDS_EXTRA]

    return any(kw in text for kw in keywords)


# ============================================================
# استخراج تصویر از RSS
# ============================================================
def _extract_rss_image(entry) -> str | None:
    """استخراج تصویر از RSS entry.
    چک می‌کند: media_content, media_thumbnail, enclosure, links."""
    
    # روش 1: media_content (رایج در Google News)
    media_content = entry.get("media_content", [])
    if media_content:
        for media in media_content:
            url = media.get("url", "")
            media_type = media.get("type", "")
            if url and ("image" in media_type or _looks_like_image(url)):
                if not _is_bad_rss_image(url):
                    return url
    
    # روش 2: media_thumbnail
    media_thumbnails = entry.get("media_thumbnail", [])
    if media_thumbnails:
        for thumb in media_thumbnails:
            url = thumb.get("url", "")
            if url and not _is_bad_rss_image(url):
                return url
    
    # روش 3: enclosure
    enclosures = entry.get("enclosures", [])
    if enclosures:
        for enc in enclosures:
            url = enc.get("href", enc.get("url", ""))
            enc_type = enc.get("type", "")
            if url and ("image" in enc_type or _looks_like_image(url)):
                if not _is_bad_rss_image(url):
                    return url
    
    # روش 4: links با type image
    links = entry.get("links", [])
    for link_item in links:
        link_type = link_item.get("type", "")
        link_url = link_item.get("href", "")
        if "image" in link_type and link_url:
            if not _is_bad_rss_image(link_url):
                return link_url
    
    # روش 5: تصویر داخل summary HTML
    summary = entry.get("summary", "")
    if summary:
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
        if img_match:
            img_url = img_match.group(1)
            if not _is_bad_rss_image(img_url):
                return img_url
    
    return None


def _looks_like_image(url: str) -> bool:
    """آیا URL شبیه یک تصویر هست."""
    url_lower = url.lower()
    return any(url_lower.endswith(ext) for ext in [
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"
    ]) or any(keyword in url_lower for keyword in [
        "image", "img", "photo", "picture", "thumb", "media"
    ])


def _is_bad_rss_image(url: str) -> bool:
    """آیا تصویر ناخواسته هست (لوگو، آیکون و ...)."""
    if not url:
        return True
    
    url_lower = url.lower()
    bad_patterns = [
        "logo", "icon", "favicon", "avatar",
        "1x1", "pixel", "spacer", "blank",
        "gstatic.com/images/branding",
        "google.com/logos",
        ".svg",
    ]
    return any(p in url_lower for p in bad_patterns)


# ============================================================
# توابع کمکی
# ============================================================
_SOURCE_NAME_FA = {
    "BBC Persian": "بی‌بی‌سی فارسی", "BBC News": "بی‌بی‌سی",
    "Reuters": "رویترز", "AP News": "آسوشیتدپرس", "AP": "آسوشیتدپرس",
    "Al Jazeera": "الجزیره", "The Guardian": "گاردین",
    "Iran International": "ایران اینترنشنال", "Radio Farda": "رادیو فردا",
    "VOA Persian": "صدای آمریکا", "Deutsche Welle FA": "دویچه وله",
    "DW": "دویچه وله", "Etemad Online": "اعتماد",
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
    """استخراج منبع واقعی خبر از Google News."""
    src = entry.get("source")
    if src and isinstance(src, dict):
        title = src.get("title", "").strip()
        if title:
            return title, _SOURCE_NAME_FA.get(title, title)

    if "Google News" not in source.name:
        return source.name, source.display_name

    href = (src or {}).get("href", "") if src else ""
    if href:
        try:
            domain = urlparse(href).netloc.replace("www.", "")
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
    """حذف تگ‌های HTML و entity ها از متن."""
    import html
    
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _parse_date(entry) -> datetime | None:
    """پارس تاریخ انتشار از entry RSS."""
    for field_name in ["published_parsed", "updated_parsed", "created_parsed"]:
        t = entry.get(field_name)
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
    """بررسی می‌کند که آیا خبر جدید است یا قدیمی."""
    if max_age_hours is None:
        max_age_hours = Config.MAX_NEWS_AGE_HOURS

    if item.published is None:
        return True

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    return item.published >= cutoff


# ============================================================
# توابع عمومی
# ============================================================
def fetch_all_news(only_breaking: bool = False, timeout: int = 15) -> list[NewsItem]:
    """همه اخبار از همه منابع را دریافت می‌کند."""
    sources = get_breaking_sources() if only_breaking else get_all_sources()
    all_items: list[NewsItem] = []

    for source in sources:
        items = fetch_feed(source, timeout=timeout)
        filtered = [
            item for item in items
            if keyword_filter(item) and age_filter(item)
        ]
        all_items.extend(filtered)
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
        img_status = "✅" if item.image_url else "❌"
        print(f"{i}. {icon} [{item.source_name}] {item.title_clean}")
        print(f"   📷 {img_status} تصویر: {item.image_url[:60] if item.image_url else 'ندارد'}")
        print(f"   🔗 {item.normalized_link}\n")
