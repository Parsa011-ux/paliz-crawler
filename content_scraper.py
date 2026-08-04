"""
استخراج محتوای کامل خبر از URL منبع
======================================
از BeautifulSoup برای استخراج متن اصلی مقاله استفاده می‌کند.
"""
import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# تگ‌هایی که معمولاً محتوای اصلی رو دارن
CONTENT_SELECTORS = [
    "article",
    "[role='article']",
    ".article-body",
    ".article-content",
    ".story-body",
    ".post-content",
    ".entry-content",
    "main",
]

# تگ‌هایی که باید حذف بشن
REMOVE_TAGS = [
    "script", "style", "nav", "header", "footer", "aside",
    "iframe", "form", "button", "noscript",
]


def scrape_article_content(url: str, timeout: int = 15) -> tuple[str, str | None]:
    """
    استخراج محتوای کامل مقاله و تصویر اصلی.
    خروجی: (متن مقاله, URL تصویر)
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "lxml")

        # 1. استخراج تصویر اصلی (Open Graph)
        image_url = _extract_main_image(soup)

        # 2. حذف تگ‌های اضافی
        for tag_name in REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 3. پیدا کردن محتوای اصلی
        content = _extract_main_content(soup)

        return content, image_url

    except httpx.TimeoutException:
        logger.warning(f"⏰ تایم‌اوت در scrape: {url}")
        return "", None
    except Exception as e:
        logger.warning(f"⚠️ خطا در scrape {url}: {e}")
        return "", None


def _extract_main_image(soup: BeautifulSoup) -> str | None:
    """استخراج تصویر اصلی از Open Graph یا Twitter card."""
    # Open Graph
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return og_image["content"]

    # Twitter card
    tw_image = soup.find("meta", attrs={"name": "twitter:image"})
    if tw_image and tw_image.get("content"):
        return tw_image["content"]

    # اولین تصویر بزرگ در article
    article = soup.find("article")
    if article:
        img = article.find("img")
        if img and img.get("src"):
            return img["src"]

    return None


def _extract_main_content(soup: BeautifulSoup) -> str:
    """استخراج متن اصلی مقاله."""
    # تلاش با selector های رایج
    for selector in CONTENT_SELECTORS:
        element = soup.select_one(selector)
        if element:
            paragraphs = element.find_all("p")
            if paragraphs and len(paragraphs) >= 2:
                text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
                if len(text) > 200:
                    return text

    # Fallback: همه <p> های صفحه
    paragraphs = soup.find_all("p")
    text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
    return text[:10000]  # حداکثر ۱۰ هزار کاراکتر


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_url = "https://www.bbc.com/persian/articles/c9wdrd4qglpo"
    content, image = scrape_article_content(test_url)
    print(f"📸 Image: {image}")
    print(f"📝 Content ({len(content)} chars):")
    print(content[:500])