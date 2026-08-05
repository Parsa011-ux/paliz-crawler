"""
پالیز نیوز - Crawler اصلی
==========================
اجرای یکباره: python main.py --once
اجرای مداوم: python main.py
"""
import logging
import sys
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ai_filter import evaluate_news, _fallback_evaluation
from config import Config
from content_scraper import scrape_article_content
from rss_parser import fetch_all_news
from storage import (
    cleanup_old_articles, filter_new_items,
    get_stats, init_db, save_article,
)
from translator import translate_to_persian

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("paliz-news")


def crawl_cycle():
    """یک سیکل کامل: دریافت + فیلتر + ذخیره."""
    logger.info("📰 شروع سیکل جمع‌آوری اخبار...")
    try:
        # 1. دریافت اخبار
        items = fetch_all_news(timeout=15)
        if not items:
            logger.info("   خبر جدیدی نبود")
            return

        # 2. حذف تکراری
        new_items = filter_new_items(items)
        if not new_items:
            logger.info("   همه اخبار تکراری بودند")
            return

        # 3. مرتب‌سازی و انتخاب بهترین‌ها با fallback (رایگان)
        evaluated_basic = [(it, _fallback_evaluation(it)) for it in new_items]
        evaluated_basic.sort(key=lambda x: x[1].importance_score, reverse=True)
        top_news = evaluated_basic[:Config.MAX_NEWS_PER_CYCLE]

        logger.info(f"📊 {len(top_news)} خبر برتر برای ذخیره‌سازی")

        # 4. برای هر خبر: AI evaluation + scrape + save
        saved_count = 0
        for item, fallback_ev in top_news:
            try:
                # ارزیابی با Gemini
                try:
                    ev = evaluate_news(item)
                except Exception:
                    ev = fallback_ev

                if not ev.is_relevant:
                    logger.debug(f"⏭ نامرتبط: {item.title_clean[:50]}")
                    continue

                # استخراج تصویر و محتوا
                content = ""
                content_fa = ""
                image_url = None
                
                # اولویت 1: تصویر از RSS
                if hasattr(item, 'image_url') and item.image_url:
                    image_url = item.image_url
                    logger.debug(f"📷 تصویر از RSS: {image_url[:60]}")
                
                # scrape محتوای کامل (و تصویر اگر RSS نداشت)
                if Config.SCRAPE_FULL_CONTENT:
                    content, scraped_image = scrape_article_content(item.link)
                    
                    # اگر عکس RSS نداشت، از عکس scrape شده استفاده کن
                    if not image_url and scraped_image:
                        image_url = scraped_image
                        logger.debug(f"📷 تصویر از scrape: {image_url[:60]}")
                    
                    # ترجمه محتوا اگه انگلیسی بود
                    if content and item.language == "en":
                        try:
                            content_fa = translate_to_persian(content[:2000])
                        except Exception:
                            content_fa = ""
                    else:
                        content_fa = content

                # ذخیره
                save_article(
                    item=item,
                    title_fa=ev.title_fa,
                    summary_fa=ev.summary_fa,
                    category=ev.category,
                    importance_score=ev.importance_score,
                    is_breaking=ev.is_breaking,
                    content=content,
                    content_fa=content_fa,
                    image_url=image_url,
                )
                saved_count += 1
                time.sleep(1)
            except Exception as e:
                logger.error(f"❌ خطا در پردازش خبر: {e}")
                continue

        logger.info(f"✅ {saved_count} خبر جدید ذخیره شد")
    except Exception as e:
        logger.error(f"❌ خطا در crawl_cycle: {e}", exc_info=True)


def cleanup_cycle():
    """پاکسازی اخبار قدیمی."""
    try:
        cleanup_old_articles(keep_days=60)
    except Exception as e:
        logger.error(f"❌ خطا در cleanup: {e}")


def run_once():
    """اجرای یکباره (برای cron)."""
    errors = Config.validate()
    if errors:
        for e in errors:
            logger.error(f"❌ {e}")
        sys.exit(1)

    init_db()
    crawl_cycle()

    import random
    if random.random() < 0.05:
        cleanup_cycle()

    stats = get_stats()
    logger.info(f"📊 آمار: کل={stats['total']} | فوری={stats['breaking']} | امروز={stats['today']}")


def run_scheduler():
    """اجرای مداوم با scheduler."""
    errors = Config.validate()
    if errors:
        for e in errors:
            logger.error(f"❌ {e}")
        sys.exit(1)

    init_db()
    stats = get_stats()
    logger.info(f"📊 آمار اولیه: {stats}")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        crawl_cycle,
        IntervalTrigger(minutes=Config.CHECK_INTERVAL_MINUTES),
        next_run_time=datetime.now(),
    )
    scheduler.add_job(cleanup_cycle, IntervalTrigger(hours=24))
    scheduler.start()

    logger.info(f"🚀 پالیز نیوز شروع شد - هر {Config.CHECK_INTERVAL_MINUTES} دقیقه چک می‌کند")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
        logger.info("🛑 توقف شد")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_once()
    else:
        run_scheduler()
