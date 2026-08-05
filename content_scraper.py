"""
استخراج محتوای کامل خبر از URL منبع
======================================
از BeautifulSoup برای استخراج متن اصلی و تصویر مقاله استفاده می‌کند.
پشتیبانی از Google News redirect و استخراج تصاویر معتبر.
"""
import logging
import re
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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

REMOVE_TAGS = [
    "script", "style", "nav", "header", "footer", "aside",
    "iframe", "form", "button", "noscript",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def scrape_article_content(url: str, timeout: int = 20) -> tuple[str, str | None]:
    """
    استخراج محتوای کامل مقاله و تصویر اصلی.
    خروجی: (متن مقاله, URL تصویر)
    """
    try:
        real_url = _resolve_google_news_url(url, timeout)
        
        with httpx.Client(
            timeout=timeout, 
            follow_redirects=True, 
            headers=BROWSER_HEADERS,
        ) as client:
            response = client.get(real_url)
            response.raise_for_status()
            html = response.text
            final_url = str(response.url)

        soup = BeautifulSoup(html, "lxml")
        image_url = _extract_main_image(soup, final_url)

        for tag_name in REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        content = _extract_main_content(soup)

        return content, image_url

    except httpx.TimeoutException:
        logger.warning(f"⏰ تایم‌اوت در scrape: {url[:80]}")
        return "", None
    except Exception as e:
        logger.warning(f"⚠️ خطا در scrape {url[:80]}: {e}")
        return "", None


def _resolve_google_news_url(url: str, timeout: int = 15) -> str:
    """اگر URL از Google News باشه، لینک واقعی مقاله رو پیدا می‌کنه."""
    if "news.google.com" not in url:
        return url
    
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=BROWSER_HEADERS,
        ) as client:
            response = client.get(url)
            final_url = str(response.url)
            
            if "news.google.com" in final_url:
                soup = BeautifulSoup(response.text, "lxml")
                
                # Meta refresh
                meta_refresh = soup.find("meta", attrs={"http-equiv": "refresh"})
                if meta_refresh and meta_refresh.get("content"):
                    content = meta_refresh["content"]
                    match = re.search(r'url=([^"\'>\s]+)', content, re.IGNORECASE)
                    if match:
                        return match.group(1)
                
                # Canonical link
                canonical = soup.find("link", rel="canonical")
                if canonical and canonical.get("href"):
                    href = canonical["href"]
                    if "news.google.com" not in href:
                        return href
                
                # JavaScript redirect
                for script in soup.find_all("script"):
                    if script.string:
                        match = re.search(
                            r'window\.location\.replace\(["\']([^"\']+)["\']',
                            script.string
                        )
                        if match:
                            return match.group(1)
                        
                        match = re.search(
                            r'"(https?://(?!news\.google\.com)[^"]+)"',
                            script.string
                        )
                        if match:
                            return match.group(1)
                
                # Article links
                article_link = soup.find("a", attrs={"data-n-tid": True})
                if article_link and article_link.get("href"):
                    href = article_link["href"]
                    if href.startswith("http") and "news.google.com" not in href:
                        return href
            
            return final_url
    except Exception as e:
        logger.debug(f"نتوانستم Google News URL رو حل کنم: {e}")
        return url


def _extract_main_image(soup: BeautifulSoup, base_url: str = "") -> str | None:
    """استخراج تصویر اصلی با اولویت‌بندی."""
    candidates = []
    
    # Open Graph
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        candidates.append(og_image["content"])
    
    og_image_secure = soup.find("meta", property="og:image:secure_url")
    if og_image_secure and og_image_secure.get("content"):
        candidates.append(og_image_secure["content"])
    
    # Twitter card
    tw_image = soup.find("meta", attrs={"name": "twitter:image"})
    if tw_image and tw_image.get("content"):
        candidates.append(tw_image["content"])
    
    tw_image_src = soup.find("meta", attrs={"name": "twitter:image:src"})
    if tw_image_src and tw_image_src.get("content"):
        candidates.append(tw_image_src["content"])
    
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        if script.string:
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict):
                    img = data.get("image")
                    if isinstance(img, str):
                        candidates.append(img)
                    elif isinstance(img, dict):
                        candidates.append(img.get("url", ""))
                    elif isinstance(img, list) and img:
                        first = img[0]
                        if isinstance(first, str):
                            candidates.append(first)
                        elif isinstance(first, dict):
                            candidates.append(first.get("url", ""))
            except Exception:
                pass
    
    # Article images
    article = soup.find("article") or soup.find("main")
    if article:
        for img in article.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                candidates.append(src)
    
    # Featured image classes
    for cls in ["featured-image", "post-thumbnail", "article-image", "hero-image"]:
        elem = soup.find(class_=re.compile(cls, re.I))
        if elem:
            img = elem.find("img")
            if img:
                src = img.get("src") or img.get("data-src")
                if src:
                    candidates.append(src)
    
    for candidate in candidates:
        if not candidate:
            continue
        
        if _is_bad_image(candidate):
            continue
        
        full_url = _make_absolute_url(candidate, base_url)
        
        if full_url:
            return full_url
    
    return None


def _is_bad_image(url: str) -> bool:
    """تشخیص تصاویر ناخواسته (لوگو، placeholder، ...)."""
    if not url:
        return True
    
    url_lower = url.lower()
    
    bad_patterns = [
        "news.google.com/img",
        "gstatic.com/images/branding",
        "google.com/logos",
        "google-news-logo",
        "googlenews",
        "logo.png",
        "logo.svg",
        "logo.jpg",
        "placeholder",
        "default-thumb",
        "avatar",
        "1x1.png",
        "pixel.png",
        "spacer.gif",
        "blank.gif",
    ]
    
    for pattern in bad_patterns:
        if pattern in url_lower:
            return True
    
    if url_lower.endswith(".svg"):
        return True
    
    if "gravatar.com" in url_lower:
        return True
    
    return False


def _make_absolute_url(url: str, base_url: str = "") -> str:
    """تبدیل URL نسبی به مطلق."""
    if not url:
        return ""
    
    url = url.strip()
    
    if url.startswith("//"):
        return "https:" + url
    
    if url.startswith("http://") or url.startswith("https://"):
        return url
    
    if url.startswith("/") and base_url:
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    
    if base_url:
        return urljoin(base_url, url)
    
    return url


def _extract_main_content(soup: BeautifulSoup) -> str:
    """استخراج متن اصلی مقاله."""
    for selector in CONTENT_SELECTORS:
        element = soup.select_one(selector)
        if element:
            paragraphs = element.find_all("p")
            if paragraphs and len(paragraphs) >= 2:
                text = "\n\n".join(
                    p.get_text(strip=True) 
                    for p in paragraphs 
                    if p.get_text(strip=True)
                )
                if len(text) > 200:
                    return text

    paragraphs = soup.find_all("p")
    text = "\n\n".join(
        p.get_text(strip=True) 
        for p in paragraphs 
        if p.get_text(strip=True)
    )
    return text[:10000]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_url = "https://www.bbc.com/persian/articles/c9wdrd4qglpo"
    content, image = scrape_article_content(test_url)
    print(f"📸 Image: {image}")
    print(f"📝 Content ({len(content)} chars):")
    print(content[:500])
