"""
ذخیره‌سازی اخبار در Turso (SQLite ابری) - libsql
=====================================================
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta

import libsql

from config import Config
from rss_parser import NewsItem
from slug_generator import generate_unique_slug

logger = logging.getLogger(__name__)


# ============================================================
# اتصال به Turso
# ============================================================
def get_client():
    """ساخت client برای Turso."""
    return libsql.connect(
        database=Config.TURSO_DATABASE_URL,
        auth_token=Config.TURSO_AUTH_TOKEN,
    )


def init_db():
    """ساخت جدول‌های مورد نیاز در Turso."""
    conn = get_client()
    conn.execute("""
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
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_link ON articles(normalized_link)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_slug ON articles(slug)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_hash ON articles(title_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_breaking ON articles(is_breaking, created_at DESC)")
    conn.commit()
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
    """بررسی آیا خبر قبلاً ذخیره شده."""
    conn = get_client()
    
    result = conn.execute(
        "SELECT 1 FROM articles WHERE normalized_link = ? LIMIT 1",
        (item.normalized_link,)
    ).fetchone()
    if result:
        return True, "URL تکراری"

    t_hash = _title_hash(item.title_clean)
    result = conn.execute(
        "SELECT 1 FROM articles WHERE title_hash = ? LIMIT 1",
        (t_hash,)
    ).fetchone()
    if result:
        return True, "عنوان تکراری"

    return False, ""


def filter_new_items(items: list[NewsItem]) -> list[NewsItem]:
    """فیلتر اخبار جدید (غیرتکراری)."""
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
# ذخیره خبر جدید
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
    """ذخیره یک خبر جدید."""
    try:
        slug = generate_unique_slug(title_fa, item.title_clean)
        conn = get_client()
        
        conn.execute("""
            INSERT INTO articles (
                slug, title, title_fa, summary, summary_fa,
                content, content_fa, link, normalized_link, image_url,
                source_name, source_name_fa, language, category,
                importance_score, is_breaking, published_at, created_at, title_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
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
        ))
        conn.commit()
        
        result = conn.execute("SELECT last_insert_rowid()").fetchone()
        article_id = result[0] if result else None
        
        logger.info(f"💾 ذخیره شد: {title_fa[:60]}... (id={article_id})")
        return article_id
    except Exception as e:
        logger.error(f"❌ خطا در ذخیره: {e}")
        return None


# ============================================================
# پاکسازی
# ============================================================
def cleanup_old_articles(keep_days: int = 60) -> int:
    """حذف اخبار قدیمی."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
    conn = get_client()
    conn.execute("DELETE FROM articles WHERE created_at < ?", (cutoff,))
    conn.commit()
    return 0


# ============================================================
# آمار
# ============================================================
def get_stats() -> dict:
    conn = get_client()
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    breaking = conn.execute("SELECT COUNT(*) FROM articles WHERE is_breaking = 1").fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE date(created_at) = date('now')"
    ).fetchone()[0]
    return {"total": total, "breaking": breaking, "today": today}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    stats = get_stats()
    print(f"📊 آمار: {stats}")