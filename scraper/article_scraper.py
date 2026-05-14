import re
import json
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone, date
from urllib.parse import urlparse
from pathlib import Path
from bs4 import BeautifulSoup
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    REQUEST_HEADERS, REQUEST_TIMEOUT, REQUEST_DELAY,
    CATEGORY_MAP, RAW_DIR,
)

MAX_RETRIES = 3
RETRY_DELAY = 3

def _create_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

_http_session = _create_session()

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.replace("\xa0", " ").replace("\u200b", "").strip()


def extract_category_from_url(url: str) -> str:
    try:
        parts = urlparse(url).path.strip("/").split("/")
        cat = parts[0] if parts else ""
        return CATEGORY_MAP.get(cat, cat.capitalize() if cat else "Lainnya")
    except Exception:
        return "Lainnya"


def extract_tags(soup: BeautifulSoup) -> list[str]:
    tags = []
    meta = soup.find("meta", attrs={"name": "keywords"})
    if meta and meta.get("content"):
        tags = [t.strip() for t in meta["content"].split(",") if t.strip()]
    if not tags:
        tag_div = soup.find("div", class_=re.compile(r"tag|keyword|label", re.I))
        if tag_div:
            tags = [a.text.strip() for a in tag_div.find_all("a") if a.text.strip()]
    return tags[:20]


def extract_author(soup: BeautifulSoup) -> str:
    for tag, attrs in [
        ("div",  {"class": re.compile(r"author|penulis|reporter", re.I)}),
        ("span", {"class": re.compile(r"author|penulis|reporter", re.I)}),
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
    ]:
        el = soup.find(tag, attrs)
        if el:
            val = el.get("content", "") if tag == "meta" else el.get_text()
            val = clean_text(val)
            if val and len(val) < 120:
                return val
    return "Kompas Cyber Media"


def scrape_article(url: str, pub_date_hint: date = None) -> dict | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _http_session.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, "lxml")

            # Title
            title = ""
            h1 = soup.find("h1")
            if h1:
                title = clean_text(h1.get_text())
            if not title:
                og = soup.find("meta", property="og:title")
                if og:
                    title = clean_text(og.get("content", ""))

            if not title:
                return None

            # Content
            content = ""
            body = (
                soup.find("div", class_=re.compile(
                    r"read__content|article-body|content__text|artikel__content|"
                    r"detail__body|main-content|article__content|story-content",
                    re.I
                ))
                or soup.find("article")
                or soup.find("main")
            )
            
            if body:
                # Clean unwanted elements
                for el in body.find_all(
                    ["script", "style", "ins", "figure", "figcaption", "aside", "div"],
                    class_=re.compile(
                        r"iklan|ads|baca.?juga|related|share|social|"
                        r"rekomendasi|popular|trending",
                        re.I
                    ),
                ):
                    el.decompose()
                    
                paragraphs = body.find_all("p")
                content = " ".join(
                    clean_text(p.get_text())
                    for p in paragraphs
                    if p.get_text(strip=True)
                )

            if len(content) < 50:
                og_desc = soup.find("meta", property="og:description")
                if og_desc:
                    content = clean_text(og_desc.get("content", ""))

            # Publication Date
            published_at = ""
            pt = soup.find("meta", property="article:published_time")
            if pt and pt.get("content"):
                try:
                    pub_dt_obj = datetime.fromisoformat(pt["content"].replace("Z", "+00:00"))
                    published_at = pub_dt_obj.strftime("%Y-%m-%d")
                except Exception:
                    pass

            if not published_at and pub_date_hint:
                published_at = str(pub_date_hint)
            
            # Extract date from URL as last fallback
            if not published_at:
                match = re.search(r"/read/(\d{4})/(\d{2})/(\d{2})/", url)
                if match:
                    published_at = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

            category = extract_category_from_url(url)

            return {
                "url": url,
                "title": title,
                "content": content,
                "author": extract_author(soup),
                "category": category,
                "tags": extract_tags(soup),
                "pub_date": published_at,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "word_count": len(content.split()) if content else 0,
            }

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                print(f"  [TIMEOUT] {url}")
                return None
        except Exception as e:
            print(f"  [ERROR] {url}: {e}")
            return None
    return None


def scrape_batch(
    articles_info: list[dict],
    batch_date: str,
    delay: float = REQUEST_DELAY,
) -> list[dict]:
    output_path = RAW_DIR / f"{batch_date}.json"

    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if len(existing) > 0:
            print(f"  [SKIP] {batch_date}: already scraped ({len(existing)} articles)")
            return existing

    results = []
    for info in tqdm(articles_info, desc=f"Scraping {batch_date}", leave=False):
        # Allow passing pub_date_hint if string is available
        hint = None
        if "pub_date" in info and info["pub_date"]:
            try:
                hint = datetime.strptime(info["pub_date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        article = scrape_article(info["url"], pub_date_hint=hint)
        if article:
            results.append(article)
        time.sleep(delay)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"  [DONE] {batch_date}: {len(results)}/{len(articles_info)} articles scraped")
    return results


def load_batch(batch_date: str) -> list[dict]:
    path = RAW_DIR / f"{batch_date}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []