import sys
import os
import requests
import time
import random
from bs4 import BeautifulSoup
from datetime import datetime
from tqdm import tqdm
import re

# Menambahkan path root agar folder feeder, preprocessor, dll bisa terbaca
sys.path.append(os.getcwd())

from feeder.loader import load_batch, get_connection
from preprocessor.sentiment_analyzer import SentimentAnalyzer
from preprocessor.embedding_generator import EmbeddingGenerator

SAMPLES_PER_MONTH = 100
START_YEAR = 2024
END_YEAR = 2026
END_MONTH = 4

analyzer = SentimentAnalyzer()
embedder = EmbeddingGenerator()

def get_articles_from_month(year, month):
    sitemap_url = f"https://www.kompas.com/sitemap_{year}_{str(month).zfill(2)}.xml"
    print(f"\n[+] Mencoba sitemap: {sitemap_url}")
    
    try:
        resp = requests.get(sitemap_url, timeout=20)
        if resp.status_code != 200:
            return []
            
        soup = BeautifulSoup(resp.content, "xml")
        urls = [loc.text for loc in soup.find_all("loc")]
        
        if not urls:
            return []
            
        # Ambil sampel acak supaya data menyebar di seluruh bulan tersebut
        sample_size = min(len(urls), SAMPLES_PER_MONTH)
        return random.sample(urls, sample_size)
    except Exception as e:
        print(f"[-] Error: {e}")
        return []

def scrape_article_detail(url):
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200: return None
        soup = BeautifulSoup(resp.content, "html.parser")
        
        title = soup.find("h1").get_text(strip=True) if soup.find("h1") else "No Title"
        content_div = soup.find("div", class_="read__content") or soup.find("div", class_="article__content")
        content = content_div.get_text(strip=True) if content_div else ""
        
        # Ekstrak tanggal dari URL atau meta
        # Format URL Kompas biasanya: .../read/YYYY/MM/DD/...
        date_match = re.search(r'/read/(\d{4})/(\d{2})/(\d{2})/', url)
        if date_match:
            pub_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
        else:
            pub_date = datetime.now().strftime("%Y-%m-%d")

        return {
            "url": url,
            "title": title,
            "content": content,
            "published_at": pub_date,
            "category": url.split('/')[2].split('.')[0] if len(url.split('/')) > 2 else "news",
            "author": "Kompas Scraper"
        }
    except:
        return None

import re # Tambahkan import re di atas

def run_historical_extraction():
    conn = get_connection()
    print(f"[*] Memulai penarikan data historis {START_YEAR} - {END_YEAR}")
    
    total_inserted = 0
    
    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):
            if year == END_YEAR and month > END_MONTH:
                break
                
            urls = get_articles_from_month(year, month)
            if not urls: continue
            
            batch_data = []
            print(f"[*] Memproses {len(urls)} artikel untuk {year}-{month}...")
            
            for url in tqdm(urls, desc=f"Scraping {year}-{month}"):
                raw_art = scrape_article_detail(url)
                if raw_art and len(raw_art['content']) > 100:
                    # Jalankan AI Pipeline (Sentiment & Embedding)
                    sentiment_res = analyzer.analyze(raw_art['content'])
                    raw_art['sentiment_score'] = sentiment_res['score']
                    raw_art['sentiment_label'] = sentiment_res['label']
                    raw_art['embedding'] = embedder.generate(raw_art['content'])
                    
                    batch_data.append(raw_art)
            
            if batch_data:
                load_batch(conn, batch_data)
                total_inserted += len(batch_data)
                print(f"[OK] Berhasil memasukkan {len(batch_data)} artikel untuk {year}-{month}")

    conn.close()
    print(f"\n[DONE] Selesai! Total {total_inserted} data historis baru telah masuk ke Supabase.")

if __name__ == "__main__":
    run_historical_extraction()