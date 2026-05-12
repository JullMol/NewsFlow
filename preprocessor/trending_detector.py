import re
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import TRENDING_WINDOW_DAYS, TRENDING_THRESHOLD, PROCESSED_DIR

# Indonesian stop words (common words to exclude)
STOP_WORDS = set("""
yang di dan ini itu dengan untuk pada dari tidak ada akan
adalah atau ke juga sudah oleh sebuah dalam bisa saat itu
mereka tersebut bukan hal kami saya ia dia anda kalau bahwa
karena seperti jika masih telah secara menjadi antara memiliki
namun sampai setelah kemudian serta tetapi begitu lalu kita
para bagi hingga pun lebih sangat hanya beberapa semua
sedang dapat maka kata orang kata satu dua tiga banyak
lain baru tahun hari waktu ujar kata mengatakan
seorang salah masing hampir paling selama per tanpa
sebagai terhadap melalui menurut tentang lainnya
kompas com baca juga selain ketika demikian
""".split())


def extract_keywords(text: str, min_length: int = 3) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) >= min_length]
    return keywords


def compute_daily_frequencies(articles: list[dict], date_str: str) -> dict:
    keyword_counts = Counter()

    for article in articles:
        # Extract keywords from title (weighted x3) and content
        title = article.get("title", "")
        content = article.get("content", "")

        title_kw = extract_keywords(title)
        content_kw = extract_keywords(content)

        # Title keywords count more
        keyword_counts.update(title_kw * 3)
        keyword_counts.update(content_kw)

        # Also count entity names as keywords
        for entity in article.get("entities", []):
            name = entity["name"].lower()
            keyword_counts[name] += entity["count"] * 2

    return dict(keyword_counts)

def detect_trending(
    current_date: str,
    current_freq: dict,
    history_dir: Path = PROCESSED_DIR,
    window_days: int = TRENDING_WINDOW_DAYS,
    threshold: float = TRENDING_THRESHOLD,
) -> list[dict]:
    # Load historical frequencies
    historical_freqs = []
    current_dt = datetime.strptime(current_date, "%Y-%m-%d")

    for i in range(1, window_days + 1):
        past_date = (current_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        hist_path = history_dir / f"freq_{past_date}.json"
        if hist_path.exists():
            with open(hist_path, "r", encoding="utf-8") as f:
                historical_freqs.append(json.load(f))

    if not historical_freqs:
        # No history available, save current and return top keywords
        trending = [
            {"keyword": kw, "frequency": count, "trending_score": 1.0, "date": current_date}
            for kw, count in sorted(current_freq.items(), key=lambda x: -x[1])[:20]
        ]
        # Save current frequencies
        freq_path = history_dir / f"freq_{current_date}.json"
        with open(freq_path, "w", encoding="utf-8") as f:
            json.dump(current_freq, f, ensure_ascii=False)
        return trending

    # Calculate rolling average for each keyword
    all_keywords = set(current_freq.keys())
    for hf in historical_freqs:
        all_keywords.update(hf.keys())

    trending = []
    for keyword in all_keywords:
        current_count = current_freq.get(keyword, 0)
        if current_count < 3:
            continue  # Skip very rare keywords

        # Average from historical data
        hist_counts = [hf.get(keyword, 0) for hf in historical_freqs]
        avg_count = sum(hist_counts) / len(hist_counts) if hist_counts else 0

        # Calculate trending score
        if avg_count > 0:
            score = current_count / avg_count
        elif current_count > 5:
            score = float(current_count)  # New keyword with significant presence
        else:
            continue

        if score >= threshold:
            trending.append({
                "keyword": keyword,
                "frequency": current_count,
                "avg_frequency": round(avg_count, 2),
                "trending_score": round(score, 2),
                "date": current_date,
            })

    # Sort by trending score
    trending.sort(key=lambda x: -x["trending_score"])

    # Save current frequencies for future reference
    freq_path = history_dir / f"freq_{current_date}.json"
    with open(freq_path, "w", encoding="utf-8") as f:
        json.dump(current_freq, f, ensure_ascii=False)

    return trending[:50]  # Top 50 trending topics


def process_trending(articles: list[dict], date_str: str) -> list[dict]:
    print(f"[TRENDING] Detecting trending topics for {date_str}")

    # Compute frequencies
    freq = compute_daily_frequencies(articles, date_str)

    # Detect trending
    trending = detect_trending(date_str, freq)

    print(f"  Found {len(trending)} trending topics")
    if trending:
        top3 = trending[:3]
        for t in top3:
            print(f"    #{t['keyword']}: score={t['trending_score']}, freq={t['frequency']}")

    return trending


if __name__ == "__main__":
    test_articles = [
        {"title": "Banjir Jakarta Meluas ke Bekasi", "content": "Banjir besar melanda Jakarta dan sekitarnya.", "entities": [{"name": "Jakarta", "count": 2, "type": "LOCATION"}]},
        {"title": "Banjir Bandang di Jakarta Selatan", "content": "Hujan deras menyebabkan banjir bandang.", "entities": [{"name": "Jakarta", "count": 1, "type": "LOCATION"}]},
    ]
    trending = process_trending(test_articles, "2025-01-15")
    print(f"\nTrending: {json.dumps(trending[:5], indent=2)}")