import sys
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random
import re
import csv
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import REQUEST_HEADERS, CATEGORY_MAP
from preprocessor.sentiment_analyzer import SentimentAnalyzer
from preprocessor.embedding_generator import EmbeddingGenerator
from preprocessor.ner_extractor import extract_article_entities
from preprocessor.nel_linker import link_article_entities
from preprocessor.trending_detector import process_trending
from feeder.loader import load_batch

SAMPLES_PER_MONTH = 5
PAGES_PER_DATE    = 5
DELAY_BETWEEN_REQUESTS = 1.5
MAX_RETRIES = 3
RETRY_BACKOFF = 2
DELAY_BETWEEN_ARTICLES = 0.8

START_DATE = date.today() - timedelta(days=730)
END_DATE   = date.today()

CSV_OUTPUT = ROOT_DIR / "data" / "raw" / "kompas_historical.csv"

CSV_FIELDNAMES = [
    "url", "title", "content", "author", "category",
    "tags", "published_at", "word_count",
    "sentiment_label", "sentiment_score",
    "scraped_at", "is_valid",
]

def load_already_scraped_months() -> set[tuple[int, int]]:
    from collections import defaultdict
    completed_months = set()
    dates_per_month = defaultdict(set)
    
    if not CSV_OUTPUT.exists():
        return completed_months
        
    try:
        with open(CSV_OUTPUT, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pub = row.get("published_at", "")
                if pub and len(pub) >= 10:
                    try:
                        dt = datetime.strptime(pub[:10], "%Y-%m-%d")
                        dates_per_month[(dt.year, dt.month)].add(pub[:10])
                    except:
                        pass
                        
        for month_tuple, dates in dates_per_month.items():
            if len(dates) >= SAMPLES_PER_MONTH:
                completed_months.add(month_tuple)
    except Exception as e:
        pass
    return completed_months

def generate_sample_dates(
    start: date, end: date, samples_per_month: int, completed_months: set[tuple[int, int]]
) -> list[date]:
    dates_by_month: dict[tuple, list[date]] = {}
    current = start
    while current <= end:
        key = (current.year, current.month)
        if key not in completed_months:
            dates_by_month.setdefault(key, []).append(current)
        current += timedelta(days=1)

    sampled: list[date] = []
    random.seed(42)
    for (year, month), days in sorted(dates_by_month.items()):
        n = min(samples_per_month, len(days))
        sampled.extend(sorted(random.sample(days, n)))

    return sampled

def extract_category_from_url(url: str) -> str:
    try:
        parts = url.split("/")
        domain_part = parts[2]

        if domain_part.startswith("www."):
            if len(parts) > 3 and parts[3] != "read":
                section = parts[3].lower()
                return CATEGORY_MAP.get(section, section.title())
            return "News"
        else:
            subdomain = domain_part.split(".")[0].lower()
            return CATEGORY_MAP.get(subdomain, subdomain.title())
    except Exception:
        return "Other"

def get_article_urls_from_indeks(
    target_date: date, max_pages: int = PAGES_PER_DATE
) -> list[dict]:
    all_articles: list[dict] = []
    seen_urls: set[str] = set()
    date_str = target_date.strftime("%Y-%m-%d")

    for page in range(1, max_pages + 1):
        url = f"https://indeks.kompas.com/?site=all&date={date_str}&page={page}"

        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
            if resp.status_code != 200:
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            candidate_links = soup.select("a.article-link")

            if not candidate_links:
                candidate_links = [
                    a for a in soup.find_all("a", href=True)
                    if "/read/" in a.get("href", "")
                    and "kompas.com" in a.get("href", "")
                ]

            raw_count = 0
            for link in candidate_links:
                href = link.get("href", "")
                if not href or "/read/" not in href or "kompas.com" not in href:
                    continue
                raw_count += 1

                if href in seen_urls:
                    continue
                seen_urls.add(href)

                title_text = link.get_text(strip=True)
                if not title_text or len(title_text) < 10:
                    continue

                date_match = re.search(r"/read/(\d{4})/(\d{2})/(\d{2})/", href)
                article_date = (
                    f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                    if date_match else date_str
                )

                all_articles.append({
                    "url":      href,
                    "title":    title_text,
                    "category": extract_category_from_url(href),
                    "pub_date": article_date,
                })

            if raw_count < 3:
                break

            time.sleep(DELAY_BETWEEN_REQUESTS)

        except Exception as e:
            print(f"[WARN] Error parsing index {date_str} page {page}: {e}")
            break

    return all_articles

def _create_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

_http_session = _create_session()

def scrape_article_content(url: str) -> dict | None:
    try:
        resp = _http_session.get(url, headers=REQUEST_HEADERS, timeout=20)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else None
        if not title:
            og = soup.find("meta", property="og:title")
            title = og.get("content", "").strip() if og else None
        if not title:
            return None

        content_div = (
            soup.find("div", class_="read__content")
            or soup.find("div", class_="article__content")
            or soup.find("div", {"itemprop": "articleBody"})
            or soup.find("article")
        )
        content = ""
        if content_div:
            for el in content_div.find_all(
                ["script", "style", "ins", "aside"],
            ):
                el.decompose()
            paragraphs = content_div.find_all("p")
            content = " ".join(
                p.get_text(strip=True) for p in paragraphs
                if p.get_text(strip=True)
            )

        if len(content) < 50:
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                content = og_desc.get("content", "").strip()

        if len(content) < 50:
            return None

        author_tag = (
            soup.find("div", class_="read__credit")
            or soup.find("span", class_="read__author")
            or soup.find("a", class_="read__author")
            or soup.find("meta", attrs={"name": "author"})
        )
        if author_tag:
            author = (
                author_tag.get("content", "")
                if author_tag.name == "meta"
                else author_tag.get_text(strip=True)
            )
        else:
            author = "Kompas.com"
            
        author = (
            author.replace("Penulis:", "")
                  .replace("Kontributor:", "")
                  .strip()
        )
        if not author or len(author) > 200:
            author = "Kompas.com"

        tags: list[str] = []
        tag_container = soup.find("ul", class_="tag__article__wrap")
        if tag_container:
            tags = [
                li.get_text(strip=True)
                for li in tag_container.find_all("li")
                if li.get_text(strip=True)
            ]
        if not tags:
            meta_kw = soup.find("meta", attrs={"name": "keywords"})
            if meta_kw and meta_kw.get("content"):
                tags = [t.strip() for t in meta_kw["content"].split(",") if t.strip()]

        return {
            "title":      title,
            "content":    content,
            "author":     author,
            "tags":       tags,
            "word_count": len(content.split()),
        }

    except requests.exceptions.ConnectionError as e:
        print(f"\n[WARN] Connection error for {url}: {e}")
        return None
    except requests.exceptions.Timeout:
        print(f"\n[WARN] Timeout for {url}")
        return None
    except Exception:
        return None

def run_historical_extraction():
    print("Kompas.com Historical Data Scraper")
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Sampling: {SAMPLES_PER_MONTH} dates/month | {PAGES_PER_DATE} pages/date\n")

    completed_months = load_already_scraped_months()
    all_sample_dates = generate_sample_dates(START_DATE, END_DATE, SAMPLES_PER_MONTH, set())
    sample_dates = generate_sample_dates(START_DATE, END_DATE, SAMPLES_PER_MONTH, completed_months)

    skipped = len(all_sample_dates) - len(sample_dates)
    print(f"[1/4] Sample dates : {len(all_sample_dates)} total")
    print(f"      Already scraped: {skipped} dates (skipped)")
    print(f"      Remaining      : {len(sample_dates)} dates")

    print("\n[2/4] Loading NLP models")
    analyzer = SentimentAnalyzer()
    embedder = EmbeddingGenerator()

    db_available = False
    print("\n[2.5/4] Testing DB connection")
    try:
        from feeder.loader import get_connection
        test_conn = get_connection()
        test_conn.close()
        print("  [OK] Database connected!")
        db_available = True
    except Exception as e:
        print(f"  [WARN] Database unreachable: {e}")
        print(f"  [WARN] Scraping will continue data saved to CSV only.")
        print(f"  [TIP]  Jika Supabase free-tier, buka dashboard dan klik 'Restore project'.")

    print("\n[3/4] Starting data extraction\n")

    total_scraped = 0
    total_loaded  = 0
    failed_dates:  list[date] = []

    csv_exists = CSV_OUTPUT.exists()
    csv_file   = open(CSV_OUTPUT, "a", newline="", encoding="utf-8")
    csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
    if not csv_exists:
        csv_writer.writeheader()

    for idx, target_date in enumerate(sample_dates, 1):
        month_label = target_date.strftime("%Y-%m")
        print(f"\n[{idx}/{len(sample_dates)}] {target_date} (Month: {month_label})")

        article_infos = get_article_urls_from_indeks(target_date, PAGES_PER_DATE)
        if not article_infos:
            print(f"[WARN] No articles found for {target_date}")
            failed_dates.append(target_date)
            continue

        start_str = START_DATE.strftime("%Y-%m-%d")
        end_str   = END_DATE.strftime("%Y-%m-%d")
        before = len(article_infos)
        article_infos = [
            a for a in article_infos
            if start_str <= a["pub_date"] <= end_str
        ]
        filtered_out = before - len(article_infos)

        if not article_infos:
            print(f"[WARN] All articles outside date range, skipping")
            continue

        msg = f"[INFO] Found {len(article_infos)} article URLs"
        if filtered_out:
            msg += f" ({filtered_out} filtered out of range)"
        print(msg)

        batch_articles: list[dict] = []
        for art_info in tqdm(article_infos, desc=f"Scraping {target_date}", leave=True):
            detail = scrape_article_content(art_info["url"])
            if detail is None:
                continue

            article: dict = {
                "url":       art_info["url"],
                "title":     detail["title"],
                "content":   detail["content"],
                "author":    detail["author"],
                "category":  art_info["category"],
                "tags":      detail["tags"],
                "pub_date":  art_info["pub_date"],
                "published_at": art_info["pub_date"],
                "word_count": detail["word_count"],
                "scraped_at": datetime.now().isoformat(),
            }

            try:
                sent = analyzer.predict_single(
                    f"{article['title']}. {article['content'][:500]}"
                )
                article["sentiment_label"] = sent["label"]
                article["sentiment_score"] = sent["score"]
            except Exception:
                article["sentiment_label"] = "neutral"
                article["sentiment_score"] = 0.5

            try:
                article["embedding"] = embedder.generate(
                    f"{article['title']}. {article['content'][:512]}"
                )
            except Exception:
                article["embedding"] = None

            batch_articles.append(article)

            csv_writer.writerow({
                "url":             article["url"],
                "title":           article["title"],
                "content":         article["content"][:2000],
                "author":          article["author"],
                "category":        article["category"],
                "tags":            ", ".join(article["tags"]) if article["tags"] else "",
                "published_at":    article["pub_date"],
                "word_count":      article["word_count"],
                "sentiment_label": article["sentiment_label"],
                "sentiment_score": article["sentiment_score"],
                "scraped_at":      article["scraped_at"],
                "is_valid":        True,
            })

            time.sleep(DELAY_BETWEEN_ARTICLES)

        total_scraped += len(batch_articles)

        csv_file.flush()

        trending_data = []
        if batch_articles:
            print(f"  [NER] Extracting entities")
            batch_articles = extract_article_entities(batch_articles)
            print(f"  [NEL] Linking entities to Wikipedia/Wikidata")
            batch_articles = link_article_entities(batch_articles)

            print(f"  [TRENDING] Detecting trending topics")
            date_str = target_date.strftime("%Y-%m-%d")
            trending_data = process_trending(batch_articles, date_str)

        if batch_articles and db_available:
            db_ok = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    try:
                        from feeder.loader import load_batch as load_batch_sql
                        loaded = load_batch_sql(batch_articles, trending=trending_data)
                    except (ImportError, Exception):
                        from feeder.rest_loader import load_batch as load_batch_rest
                        loaded = load_batch_rest(batch_articles, trending=trending_data)
                        
                    total_loaded += loaded
                    print(f"[OK] {len(batch_articles)} articles scraped, {loaded} loaded to DB")
                    db_ok = True
                    break
                except Exception as e:
                    print(f"[ERR] DB attempt {attempt}/{MAX_RETRIES}: {e}")
                    if attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF * attempt
                        print(f"       Retrying in {wait}s")
                        time.sleep(wait)
            if not db_ok:
                db_available = False
                print(f"[WARN] DB load failed disabling DB for remaining batches.")
                print(f"       Data safe in CSV: {CSV_OUTPUT}")
        elif batch_articles:
            print(f"[OK] {len(batch_articles)} articles scraped (CSV only, DB skipped)")

    csv_file.close()

    print(f"\n[4/4] SUMMARY")
    print(f"Total dates sampled : {len(all_sample_dates)}")
    print(f"Dates skipped       : {skipped}")
    print(f"Dates processed     : {len(sample_dates)}")
    print(f"Total articles      : {total_scraped} scraped, {total_loaded} loaded")
    print(f"CSV saved at        : {CSV_OUTPUT}")
    if failed_dates:
        print(f"[WARN] Failed dates ({len(failed_dates)}): "
              f"{', '.join(str(d) for d in failed_dates[:10])}")

if __name__ == "__main__":
    run_historical_extraction()