import argparse
import json
import time
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SCRAPE_START_DATE, SCRAPE_END_DATE, RAW_DIR, PROCESSED_DIR

def run_collect_urls(start_date: date, end_date: date):
    from scraper.sitemap_parser import collect_all_urls
    return collect_all_urls(start_date, end_date)

def run_scrape_batch(articles_info: list[dict], batch_date: str):
    from scraper.article_scraper import scrape_batch
    return scrape_batch(articles_info, batch_date)

def run_transform_batch(articles: list[dict], batch_date: str):
    from preprocessor.text_cleaner import clean_batch
    from preprocessor.sentiment_analyzer import analyze_articles, get_analyzer
    from preprocessor.embedding_generator import generate_article_embeddings, get_generator
    from preprocessor.ner_extractor import extract_article_entities
    from preprocessor.nel_linker import link_article_entities
    from preprocessor.trending_detector import process_trending

    print(f"\nTRANSFORM {batch_date} ({len(articles)} articles)")

    # Step 1: Clean text
    print("[1/6] Cleaning text")
    articles = clean_batch(articles)
    print(f"  After cleaning: {len(articles)} articles")

    if not articles:
        return articles, []

    # Step 2: Sentiment analysis
    print("[2/6] Analyzing sentiment")
    analyzer = get_analyzer()
    articles = analyze_articles(articles, analyzer)

    # Step 3: Generate embeddings
    print("[3/6] Generating embeddings")
    generator = get_generator()
    articles = generate_article_embeddings(articles, generator)

    # Step 4: Extract entities (NER)
    print("[4/6] Extracting entities")
    articles = extract_article_entities(articles)

    # Step 5: Link entities to knowledge base (NEL)
    print("[5/6] Linking entities (NEL)")
    articles = link_article_entities(articles)

    # Step 6: Detect trending topics
    print("[6/6] Detecting trending topics")
    trending = process_trending(articles, batch_date)

    # Save processed data
    output_path = PROCESSED_DIR / f"{batch_date}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        # Save without embeddings (too large for JSON)
        save_data = []
        for a in articles:
            a_copy = {k: v for k, v in a.items() if k != "embedding"}
            a_copy["has_embedding"] = "embedding" in a
            save_data.append(a_copy)
        json.dump(save_data, f, ensure_ascii=False, indent=2)

    return articles, trending

def run_load_batch(articles: list[dict], trending: list[dict]):
    try:
        from feeder.loader import load_batch
        return load_batch(articles, trending)
    except (ImportError, Exception):
        # Fallback to REST loader if psycopg2 is missing (e.g. on Airflow server)
        from feeder.rest_loader import load_batch as load_batch_rest
        return load_batch_rest(articles, trending)

def run_full_pipeline(start_date: date, end_date: date, skip_scraping: bool = False):
    print("\nKOMPAS.COM DATA WAREHOUSE - FULL PIPELINE")
    print(f"Date range: {start_date} to {end_date}")

    start_time = time.time()

    if not skip_scraping:
        url_index = run_collect_urls(start_date, end_date)
    else:
        from scraper.sitemap_parser import load_url_index
        url_index = load_url_index()

    if not url_index:
        print("[ERROR] No URLs collected. Exiting.")
        return

    sorted_dates = sorted(url_index.keys())
    total_dates = len(sorted_dates)
    total_articles = sum(len(v) for v in url_index.values())

    print(f"\n  Processing {total_dates} dates, ~{total_articles} articles total")
    print(f"  This will simulate {total_dates} daily batch runs\n")

    for idx, batch_date in enumerate(sorted_dates, 1):
        print(f"\nBATCH {idx}/{total_dates}: {batch_date}")

        articles_info = url_index[batch_date]
        if not skip_scraping:
            articles = run_scrape_batch(articles_info, batch_date)
        else:
            from scraper.article_scraper import load_batch as load_scraped
            articles = load_scraped(batch_date)
            if not articles:
                articles = run_scrape_batch(articles_info, batch_date)

        if not articles:
            print(f"  [SKIP] No articles for {batch_date}")
            continue

        articles, trending = run_transform_batch(articles, batch_date)

        if not articles:
            continue
        MAX_RETRIES = 3
        RETRY_BACKOFF = 2
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                loaded = run_load_batch(articles, trending)
                print(f"  [BATCH COMPLETE] {batch_date}: loaded {loaded} articles")
                break
            except Exception as e:
                print(f"  [ERROR] Load attempt {attempt}/{MAX_RETRIES} failed for {batch_date}: {e}")
                if attempt < MAX_RETRIES:
                    wait_time = RETRY_BACKOFF * attempt
                    print(f"          Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"  [ERROR] All load retries failed for {batch_date}. Continuing to next batch.")

    try:
        try:
            from feeder.loader import refresh_materialized_views, get_db_stats
        except (ImportError, Exception):
            from feeder.rest_loader import refresh_materialized_views, get_db_stats
            
        refresh_materialized_views()
        stats = get_db_stats()
        print(f"\nPIPELINE COMPLETE")
        print(f"Total time: {time.time()-start_time:.1f} seconds")
        print(f"Database stats: {stats}")
    except Exception as e:
        print(f"\n  Pipeline finished. DB stats/refresh failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Kompas.com DW Pipeline Runner")
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="Start date (YYYY-MM-DD). Default: 2 years ago"
    )
    parser.add_argument(
        "--end-date", type=str, default=None,
        help="End date (YYYY-MM-DD). Default: today"
    )
    parser.add_argument(
        "--collect-urls-only", action="store_true",
        help="Only collect URLs, don't scrape or process"
    )
    parser.add_argument(
        "--process-only", action="store_true",
        help="Skip URL collection and scraping, process existing data"
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else SCRAPE_START_DATE
    end = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else SCRAPE_END_DATE

    if args.collect_urls_only:
        run_collect_urls(start, end)
    else:
        run_full_pipeline(start, end, skip_scraping=args.process_only)


if __name__ == "__main__":
    main()