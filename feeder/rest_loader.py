import requests
import json
import time
from datetime import datetime, date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SUPABASE_URL, SUPABASE_KEY

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

CACHE = {
    "waktu": {},
    "kategori": {},
    "penulis": {},
    "sentimen": {},
    "entitas": {}
}

def supabase_request(method, table, data=None, params=None, upsert=False):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = HEADERS.copy()
    
    if upsert:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    else:
        headers["Prefer"] = "return=representation"

    try:
        if method == "POST":
            response = requests.post(url, headers=headers, json=data, params=params)
        elif method == "GET":
            response = requests.get(url, headers=headers, params=params)
        else:
            return None
        
        if response.status_code in [200, 201]:
            return response.json()
        return None
    except Exception as e:
        print(f"  [REST ERROR] {method} {table}: {e}")
        return None

def upsert_dim_waktu(tanggal: date) -> int:
    date_str = str(tanggal)
    if date_str in CACHE["waktu"]:
        return CACHE["waktu"][date_str]
    
    res = supabase_request("GET", "dim_waktu", params={"tanggal": f"eq.{date_str}"})
    if res:
        w_id = res[0]["waktu_id"]
        CACHE["waktu"][date_str] = w_id
        return w_id
    
    data = {
        "tanggal": date_str,
        "hari": tanggal.strftime("%A"),
        "hari_dalam_minggu": tanggal.isoweekday(),
        "minggu": tanggal.isocalendar()[1],
        "bulan": tanggal.month,
        "nama_bulan": tanggal.strftime("%B"),
        "kuartal": (tanggal.month - 1) // 3 + 1,
        "tahun": tanggal.year
    }
    res = supabase_request("POST", "dim_waktu", data=data, upsert=True)
    if res:
        w_id = res[0]["waktu_id"]
        CACHE["waktu"][date_str] = w_id
        return w_id
    return None

def upsert_dim_kategori(nama: str) -> int:
    if nama in CACHE["kategori"]:
        return CACHE["kategori"][nama]
    
    res = supabase_request("GET", "dim_kategori", params={"nama_kategori": f"eq.{nama}"})
    if res:
        k_id = res[0]["kategori_id"]
        CACHE["kategori"][nama] = k_id
        return k_id
    
    res = supabase_request("POST", "dim_kategori", data={"nama_kategori": nama}, upsert=True)
    if res:
        k_id = res[0]["kategori_id"]
        CACHE["kategori"][nama] = k_id
        return k_id
    return None

def upsert_dim_penulis(nama: str) -> int:
    if nama in CACHE["penulis"]:
        return CACHE["penulis"][nama]
    
    res = supabase_request("GET", "dim_penulis", params={"nama_penulis": f"eq.{nama}"})
    if res:
        p_id = res[0]["penulis_id"]
        CACHE["penulis"][nama] = p_id
        return p_id
    
    res = supabase_request("POST", "dim_penulis", data={"nama_penulis": nama}, upsert=True)
    if res:
        p_id = res[0]["penulis_id"]
        CACHE["penulis"][nama] = p_id
        return p_id
    return None

def get_sentimen_id(label: str) -> int:
    if label in CACHE["sentimen"]:
        return CACHE["sentimen"][label]
    
    res = supabase_request("GET", "dim_sentimen", params={"label": f"eq.{label}"})
    if res:
        s_id = res[0]["sentimen_id"]
        CACHE["sentimen"][label] = s_id
        return s_id
    return 1

def upsert_dim_entitas(entity: dict) -> int:
    nama = entity["name"]
    tipe = entity["type"]
    cache_key = f"{nama}|{tipe}"
    
    if cache_key in CACHE["entitas"]:
        return CACHE["entitas"][cache_key]
    
    res = supabase_request("GET", "dim_entitas", params={
        "nama_entitas": f"eq.{nama}",
        "tipe_entitas": f"eq.{tipe}"
    })
    
    if res:
        e_id = res[0]["entitas_id"]
        CACHE["entitas"][cache_key] = e_id
        return e_id
    
    data = {
        "nama_entitas": nama,
        "tipe_entitas": tipe,
        "wikidata_id": entity.get("wikidata_id"),
        "wikipedia_url": entity.get("wikipedia_url"),
        "deskripsi": entity.get("deskripsi"),
        "nel_matched": entity.get("nel_matched", False),
        "nel_score": entity.get("nel_score", 0.0),
        "nel_similarity": entity.get("nel_similarity", 0.0)
    }
    res = supabase_request("POST", "dim_entitas", data=data, upsert=True)
    if res:
        e_id = res[0]["entitas_id"]
        CACHE["entitas"][cache_key] = e_id
        return e_id
    return None

def load_article(article: dict):
    try:
        pub_date = datetime.strptime(article["pub_date"], "%Y-%m-%d").date()
        w_id = upsert_dim_waktu(pub_date)
        k_id = upsert_dim_kategori(article.get("category", "Lainnya"))
        p_id = upsert_dim_penulis(article.get("author", "Kompas.com"))
        s_id = get_sentimen_id(article.get("sentiment_label", "neutral"))
        
        data = {
            "url": article["url"],
            "judul": article["title"],
            "konten": article.get("content", ""),
            "waktu_id": w_id,
            "kategori_id": k_id,
            "penulis_id": p_id,
            "sentimen_id": s_id,
            "sentimen_score": article.get("sentiment_score"),
            "embedding": article.get("embedding"),
            "jumlah_kata": article.get("word_count", 0),
            "tags": article.get("tags", []),
            "tanggal_publikasi": str(pub_date)
        }
        
        res = supabase_request("POST", "fact_artikel", data=data, upsert=True)
        if not res:
            return None
            
        artikel_id = res[0]["artikel_id"]
        
        # Load entities to bridge
        if article.get("entities"):
            for entity in article["entities"]:
                e_id = upsert_dim_entitas(entity)
                if e_id:
                    supabase_request("POST", "bridge_artikel_entitas", data={
                        "artikel_id": artikel_id,
                        "entitas_id": e_id,
                        "frekuensi": entity.get("count", 1)
                    }, upsert=True)
                    
        return artikel_id
    except Exception as e:
        print(f"  [ERROR] Load article failed: {e}")
        return None

def load_trending(trending_topics: list[dict]):
    for topic in trending_topics:
        try:
            pub_date = datetime.strptime(topic["date"], "%Y-%m-%d").date()
            w_id = upsert_dim_waktu(pub_date)
            data = {
                "waktu_id": w_id,
                "keyword": topic["keyword"],
                "frekuensi": topic["frequency"],
                "avg_frekuensi": topic.get("avg_frequency", 0),
                "skor_trending": topic["trending_score"],
                "tanggal": topic["date"]
            }
            supabase_request("POST", "fact_trending", data=data, upsert=True)
        except Exception as e:
            print(f"  [ERROR] Load trending failed: {e}")

def load_batch(articles: list[dict], trending: list[dict] = None):
    loaded = 0
    for article in articles:
        if load_article(article):
            loaded += 1
    
    if trending:
        load_trending(trending)
        
    return loaded

def refresh_materialized_views():
    print("[LOAD] Requesting view refresh via RPC")
    url = f"{SUPABASE_URL}/rest/v1/rpc/refresh_all_views"
    requests.post(url, headers=HEADERS)

def get_db_stats():
    stats = {}
    for table in ["fact_artikel", "fact_trending"]:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select=count"
        res = requests.get(url, headers=HEADERS)
        if res.status_code == 200:
            stats[table] = "N/A (REST)"
    return stats