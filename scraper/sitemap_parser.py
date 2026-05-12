import re
import json
import time
import requests
from datetime import date, datetime, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
from tqdm import tqdm
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    SITEMAP_INDEX_URL, INDEKS_BASE_URL,
    REQUEST_HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY,
    SCRAPE_START_DATE, SCRAPE_END_DATE,
    RAW_DIR,
)

def fetch_xml(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.content, "lxml-xml")
    except Exception as e:
        print(f"  [ERROR] Failed to fetch {url}: {e}")
        return None

def parse_sitemap_index(sitemap_url: str = SITEMAP_INDEX_URL) -> list[str]:
    print(f"[SITEMAP] Fetching sitemap index: {sitemap_url}")
    soup = fetch_xml(sitemap_url)
    if not soup:
        return []

    sitemap_urls = []
    for sitemap in soup.find_all("sitemap"):
        loc = sitemap.find("loc")
        if loc:
            url = loc.get_text(strip=True)
            # Prefer archive sitemaps for historical data
            if "archive" in url or "news" in url:
                sitemap_urls.append(url)

    print(f"  Found {len(sitemap_urls)} sub-sitemaps")
    return sitemap_urls


def parse_sub_sitemap(sitemap_url: str) -> list[dict]:
    soup = fetch_xml(sitemap_url)
    if not soup:
        return []

    articles = []
    for url_tag in soup.find_all("url"):
        loc = url_tag.find("loc")
        if not loc:
            continue

        article_url = loc.get_text(strip=True)

        # Skip non-article URLs
        if "/read/" not in article_url and "/tren/read/" not in article_url:
            continue

        # Extract publication date from news:publication_date or URL
        pub_date_str = None
        news_date = url_tag.find("news:publication_date")
        if news_date:
            pub_date_str = news_date.get_text(strip=True)[:10]  # YYYY-MM-DD
        else:
            # Try to extract date from URL pattern:
            # https://xxx.kompas.com/read/YYYY/MM/DD/...
            match = re.search(r"/read/(\d{4})/(\d{2})/(\d{2})/", article_url)
            if match:
                pub_date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

        # Extract title from news:title if available
        title = None
        news_title = url_tag.find("news:title")
        if news_title:
            title = news_title.get_text(strip=True)

        # Extract keywords from news:keywords if available
        keywords = []
        news_kw = url_tag.find("news:keywords")
        if news_kw:
            keywords = [k.strip() for k in news_kw.get_text().split(",")]

        articles.append({
            "url": article_url,
            "title": title,
            "pub_date": pub_date_str,
            "keywords": keywords,
        })

    return articles


def collect_urls_from_sitemaps(
    start_date: date = SCRAPE_START_DATE,
    end_date: date = SCRAPE_END_DATE,
) -> dict[str, list[dict]]:
    print(f"\nSITEMAP URL COLLECTION")
    print(f"Range: {start_date} to {end_date}\n")

    # Step 1: Get all sub-sitemap URLs
    sitemap_urls = parse_sitemap_index()

    # Step 2: Parse each sub-sitemap
    all_articles = []
    for url in tqdm(sitemap_urls, desc="Parsing sitemaps"):
        articles = parse_sub_sitemap(url)
        all_articles.extend(articles)
        time.sleep(0.5)  # Be polite

    # Step 3: Filter by date range and group by date
    grouped = defaultdict(list)
    for article in all_articles:
        if not article["pub_date"]:
            continue
        try:
            pub = datetime.strptime(article["pub_date"], "%Y-%m-%d").date()
            if start_date <= pub <= end_date:
                grouped[article["pub_date"]].append(article)
        except ValueError:
            continue

    print(f"\n  Total articles from sitemaps: {len(all_articles)}")
    print(f"  Articles in date range: {sum(len(v) for v in grouped.values())}")
    print(f"  Days covered: {len(grouped)}")

    return dict(grouped)


def collect_urls_from_indeks(
    target_date: date,
    max_pages: int = 20,
) -> list[dict]:
    articles = []
    date_str = target_date.strftime("%Y-%m-%d")

    for page in range(1, max_pages + 1):
        url = f"{INDEKS_BASE_URL}?site=all&date={date_str}&page={page}"
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Find article links on the index page
            article_links = soup.select("a.article__link")
            if not article_links:
                # Also try alternative selectors
                article_links = soup.select(".articleList a[href*='/read/']")

            if not article_links:
                break  # No more articles on this page

            for link in article_links:
                href = link.get("href", "")
                if "/read/" in href:
                    title_el = link.select_one("h2, h3, .article__title")
                    title = title_el.get_text(strip=True) if title_el else None

                    articles.append({
                        "url": href,
                        "title": title,
                        "pub_date": date_str,
                        "keywords": [],
                    })

            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"  [WARN] Error fetching indeks page {page} for {date_str}: {e}")
            break

    return articles


def collect_all_urls(
    start_date: date = SCRAPE_START_DATE,
    end_date: date = SCRAPE_END_DATE,
    use_indeks_fallback: bool = True,
) -> dict[str, list[dict]]:
    # Try sitemaps first
    grouped = collect_urls_from_sitemaps(start_date, end_date)

    # Fill gaps using indeks.kompas.com
    if use_indeks_fallback:
        total_days = (end_date - start_date).days + 1
        all_dates = [start_date + timedelta(days=i) for i in range(total_days)]
        missing_dates = [d for d in all_dates if d.strftime("%Y-%m-%d") not in grouped]

        if missing_dates:
            print(f"\n[INDEKS] Filling {len(missing_dates)} missing dates via indeks.kompas.com")
            for d in tqdm(missing_dates, desc="Fetching from indeks"):
                articles = collect_urls_from_indeks(d)
                if articles:
                    grouped[d.strftime("%Y-%m-%d")] = articles
                time.sleep(0.5)

    # Deduplicate URLs across dates
    seen_urls = set()
    for date_str in grouped:
        unique = []
        for article in grouped[date_str]:
            if article["url"] not in seen_urls:
                seen_urls.add(article["url"])
                unique.append(article)
        grouped[date_str] = unique

    # Save to file
    output_path = RAW_DIR / "url_index.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(grouped, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in grouped.values())
    print(f"\nURL COLLECTION COMPLETE")
    print(f"Total unique URLs: {total}")
    print(f"Days covered: {len(grouped)}")
    print(f"Saved to: {output_path}")

    return grouped

def load_url_index() -> dict[str, list[dict]]:
    path = RAW_DIR / "url_index.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

if __name__ == "__main__":
    from datetime import date
    urls = collect_all_urls(
        start_date=date(2025, 5, 1),
        end_date=date(2025, 5, 2),
    )
    for d, articles in sorted(urls.items()):
        print(f"  {d}: {len(articles)} articles")