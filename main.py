"""
ذخیره‌سازی اخبار در Turso با HTTP API
=====================================================
از HTTP API استفاده می‌کنیم تا روی همه پلتفرم‌ها کار کنه
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import requests

from config import Config
from rss_parser import NewsItem
from slug_generator import generate_unique_slug

logger = logging.getLogger(__name__)


# ============================================================
# Turso HTTP Client
# ============================================================
class TursoClient:
    def __init__(self, url: str, auth_token: str):
        # تبدیل libsql:// به https://
        self.base_url = url.replace("libsql://", "https://")
        self.auth_token = auth_token
        self.headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
    
    def execute(self, sql: str, params: list = None) -> dict:
        """اجرای یک کوئری روی Turso."""
        if params is None:
            params = []
        
        # تبدیل params به فرمت Turso
        args = []
        for p in params:
            if p is None:
                args.append({"type": "null"})
            elif isinstance(p, bool):
                args.append({"type": "integer", "value": str(int(p))})
            elif isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": p})
            else:
                args.append({"type": "text", "value": str(p)})
        
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": args,
                    }
                },
                {"type": "close"}
            ]
        }
        
        response = requests.post(
            f"{self.base_url}/v2/pipeline",
            json=payload,
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    
    def fetch_one(self, sql: str, params: list = None) -> tuple | None:
        """گرفتن یک سطر."""
        result = self.execute(sql, params)
        try:
            rows = result["results"][0]["response"]["result"]["rows"]
            if not rows:
                return None
            return tuple(
                col.get("value") if col.get("type") != "null" else None
                for col in rows[0]
            )
        except (KeyError, IndexError):
            return None
    
    def fetch_all(self, sql: str, params: list = None) -> list[tuple]:
        """گرفتن همه سطرها."""
        result = self.execute(sql, params)
        try:
            rows = result["results"][0]["response"]["result"]["rows"]
            return [
                tuple(
                    col.get("value") if col.get("type") != "null" else None
                    for col in row
                )
                for row in rows
            ]
        except (KeyError, IndexError):
            return []


def get_client() -> TursoClient:
    """ساخت client برای Turso."""
    return TursoClient(
        url=Config.TURSO_DATABASE_URL,
        auth_token=Config.TURSO_AUTH_TOKEN,
    )


# ============================================================
# ساخت جدول
# ============================================================
def init_db():
    """ساخت جدول‌های مورد نیاز در Turso."""
    client = get_client()
    
    client.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            title_fa TEXT NOT NULL,
            summary TEXT,
            summary_fa TEXT,
            content TEXT,
            content_fa TEXT,
            link TEXT NOT NULL,
            normalized_link TEXT NOT NULL,
            image_url TEXT,
            source_name TEXT NOT NULL,
            source_name_fa TEXT NOT NULL,
            language TEXT NOT NULL,
            category TEXT DEFAULT 'سیاسی',
            importance_score INTEGER DEFAULT 5,
            is_breaking INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            published_at TEXT,
            created_at TEXT NOT NULL,
            title_hash TEXT
        )
    """)
    
    client.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_link ON articles(normalized_link)")
    client.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_slug ON articles(slug)")
    client.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_hash ON articles(title_hash)")
    client.execute("CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)")
    client.execute("CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at DESC)")
    client.execute("CREATE INDEX IF NOT EXISTS idx_articles_breaking ON articles(is_breaking, created_at DESC)")
    
    logger.info("✅ Turso database آماده است")


# ============================================================
# هش عنوان
# ============================================================
def _title_hash(title: str) -> str:
    normalized = re.sub(r"[^\w\s]", "", title.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


# ============================================================
# تشخیص تکراری
# ============================================================
def is_duplicate(item: NewsItem) -> tuple[bool, str]:
    client = get_client()
    
    result = client.fetch_one(
        "SELECT 1 FROM articles WHERE normalized_link = ? LIMIT 1",
        [item.normalized_link]
    )
    if result:
        return True, "URL تکراری"

    t_hash = _title_hash(item.title_clean)
    result = client.fetch_one(
        "SELECT 1 FROM articles WHERE title_hash = ? LIMIT 1",
        [t_hash]
    )
    if result:
        return True, "عنوان تکراری"

    return False, ""


def filter_new_items(items: list[NewsItem]) -> list[NewsItem]:
    url_seen = set()
    hash_seen = set()
    unique = []
    for item in items:
        url_key = item.normalized_link
        hash_key = _title_hash(item.title_clean)
        if url_key in url_seen or hash_key in hash_seen:
            continue
        url_seen.add(url_key)
        hash_seen.add(hash_key)
        unique.append(item)

    new_items = []
    for item in unique:
        is_dup, reason = is_duplicate(item)
        if not is_dup:
            new_items.append(item)

    logger.info(f"🔍 از {len(items)} خبر، {len(new_items)} تای جدید")
    return new_items


# ============================================================
# ذخیره خبر
# ============================================================
def save_article(
    item: NewsItem,
    title_fa: str,
    summary_fa: str,
    category: str,
    importance_score: int,
    is_breaking: bool,
    content: str = "",
    content_fa: str = "",
    image_url: str | None = None,
) -> int | None:
    try:
        slug = generate_unique_slug(title_fa, item.title_clean)
        client = get_client()
        
        client.execute("""
            INSERT INTO articles (
                slug, title, title_fa, summary, summary_fa,
                content, content_fa, link, normalized_link, image_url,
                source_name, source_name_fa, language, category,
                importance_score, is_breaking, published_at, created_at, title_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            slug,
            item.title_clean,
            title_fa,
            item.summary_clean or "",
            summary_fa,
            content,
            content_fa,
            item.link,
            item.normalized_link,
            image_url,
            item.source_name,
            item.source_name_fa,
            item.language,
            category,
            importance_score,
            1 if is_breaking else 0,
            item.published.isoformat() if item.published else None,
            datetime.now().isoformat(),
            _title_hash(item.title_clean),
        ])
        
        # گرفتن id آخرین رکورد
        result = client.fetch_one("SELECT last_insert_rowid()")
        article_id = result[0] if result else None
        
        logger.info(f"💾 ذخیره شد: {title_fa[:60]}... (id={article_id})")
        return article_id
    except Exception as e:
        logger.error(f"❌ خطا در ذخیره: {e}")
        return None


# ============================================================
# پاکسازی محتوای اخبار قدیمی (فقط content و content_fa رو NULL می‌کنه)
# ============================================================
def cleanup_old_content(keep_recent: int = 100) -> int:
    """پاک کردن content و content_fa برای اخبار قدیمی‌تر از N خبر آخر.
    
    این تابع:
      - آخرین `keep_recent` خبر رو نگه می‌داره (content_fa می‌مونه)
      - بقیه اخبار: content و content_fa NULL می‌شن
      - عنوان، خلاصه، تصویر، دسته‌بندی همچنان باقی می‌مونن
      - اخبار قدیمی روی سایت به صفحه منبع اصلی لینک می‌شن
    
    خروجی: تعداد ردیف‌هایی که content‌شون پاک شد
    """
    try:
        client = get_client()
        
        # پیدا کردن created_at برای مرزی که آخرین 100 خبر از اون به بعد باشن
        result = client.fetch_one(f"""
            SELECT created_at FROM articles 
            ORDER BY created_at DESC 
            LIMIT 1 OFFSET {keep_recent}
        """)
        
        if not result:
            logger.info(f"📊 کمتر از {keep_recent} خبر در دیتابیس هست - پاکسازی نمی‌شه")
            return 0
        
        cutoff_date = result[0]
        
        # شمردن اخباری که content دارن و قدیمی‌تر از این تاریخن
        count_result = client.fetch_one("""
            SELECT COUNT(*) FROM articles 
            WHERE created_at < ? 
              AND (content IS NOT NULL OR content_fa IS NOT NULL)
              AND (content != '' OR content_fa != '')
        """, [cutoff_date])
        
        affected = int(count_result[0]) if count_result else 0
        
        if affected == 0:
            logger.info(f"✅ نیازی به پاکسازی نیست - همه محتواها به‌روزن")
            return 0
        
        # NULL کردن content برای اخبار قدیمی
        client.execute("""
            UPDATE articles 
            SET content = NULL, content_fa = NULL 
            WHERE created_at < ?
              AND (content IS NOT NULL OR content_fa IS NOT NULL)
        """, [cutoff_date])
        
        logger.info(f"🧹 محتوای {affected} خبر قدیمی پاک شد (آخرین {keep_recent} خبر حفظ شد)")
        return affected
        
    except Exception as e:
        logger.error(f"❌ خطا در cleanup_old_content: {e}")
        return 0


# ============================================================
# پاکسازی کامل (حذف اخبار خیلی قدیمی از دیتابیس)
# ============================================================
def cleanup_old_articles(keep_days: int = 60) -> int:
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    client = get_client()
    client.execute("DELETE FROM articles WHERE created_at < ?", [cutoff])
    return 0


# ============================================================
# آمار
# ============================================================
def get_stats() -> dict:
    client = get_client()
    total = client.fetch_one("SELECT COUNT(*) FROM articles")
    breaking = client.fetch_one("SELECT COUNT(*) FROM articles WHERE is_breaking = 1")
    today = client.fetch_one("SELECT COUNT(*) FROM articles WHERE date(created_at) = date('now')")
    with_content = client.fetch_one("SELECT COUNT(*) FROM articles WHERE content_fa IS NOT NULL AND content_fa != ''")
    
    return {
        "total": int(total[0]) if total else 0,
        "breaking": int(breaking[0]) if breaking else 0,
        "today": int(today[0]) if today else 0,
        "with_content": int(with_content[0]) if with_content else 0,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    stats = get_stats()
    print(f"📊 آمار: {stats}")
