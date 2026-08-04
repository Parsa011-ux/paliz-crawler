"""
تولید Slug برای URL خبر
=========================
مثال: "ایران در تنش با اسرائیل" → "iran-dar-tanesh-ba-esraeel-abc123"
"""
import hashlib
import re
from slugify import slugify


def generate_slug(title_fa: str, title_en: str = "", article_id: int | None = None) -> str:
    """ساخت slug سئو-فرندلی از عنوان."""
    # اولویت: عنوان انگلیسی اگه هست
    base = title_en if title_en else title_fa
    
    # slugify با پشتیبانی از یونیکد
    slug = slugify(base, max_length=60, lowercase=True)
    
    # اگه slug خالی شد (متن فقط فارسی و slugify نتونست)، از هش عنوان استفاده کن
    if not slug or len(slug) < 3:
        # ساخت slug از هش
        hash_str = hashlib.md5(title_fa.encode("utf-8")).hexdigest()[:10]
        slug = f"news-{hash_str}"
    
    # اضافه کردن id برای یکتایی
    if article_id:
        slug = f"{slug}-{article_id}"
    
    return slug


def generate_unique_slug(title_fa: str, title_en: str = "") -> str:
    """ساخت slug یکتا با hash کوتاه (بدون نیاز به ID)."""
    base = title_en if title_en else title_fa
    slug = slugify(base, max_length=50, lowercase=True)
    
    if not slug or len(slug) < 3:
        slug = "news"
    
    # اضافه کردن hash کوتاه برای یکتایی
    hash_suffix = hashlib.md5(title_fa.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{hash_suffix}"


if __name__ == "__main__":
    tests = [
        ("ایران در تنش با اسرائیل", "Iran tensions with Israel"),
        ("خبر جدید از تهران", ""),
        ("US sanctions on Iran", ""),
    ]
    for fa, en in tests:
        print(f"FA: {fa}")
        print(f"EN: {en}")
        print(f"Slug: {generate_unique_slug(fa, en)}")
        print("---")