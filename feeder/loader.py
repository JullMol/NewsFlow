import json
import psycopg2
import psycopg2.extras
from datetime import datetime, date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_CONFIG

# English day/month names
HARI_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BULAN_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

# Simple in-memory cache to avoid redundant DB lookups
DIM_CACHE = {
    "waktu": {},     # date -> id
    "kategori": {},  # name -> id
    "penulis": {},   # name -> id
    "entitas": {},   # (name, type) -> id
    "sentimen": {},  # label -> id
}

def get_connection():
    config = DB_CONFIG.copy()
    config["connect_timeout"] = 15  # 15 seconds to connect
    config["options"] = "-c statement_timeout=30000"  # 30 seconds query timeout
    return psycopg2.connect(**config)

def upsert_dim_waktu(conn, tanggal: date) -> int:
    if tanggal in DIM_CACHE["waktu"]:
        return DIM_CACHE["waktu"][tanggal]

    cur = conn.cursor()
    cur.execute("SELECT waktu_id FROM dim_waktu WHERE tanggal = %s", (tanggal,))
    row = cur.fetchone()
    if row:
        DIM_CACHE["waktu"][tanggal] = row[0]
        return row[0]

    hari = HARI_NAMES[tanggal.weekday()]
    cur.execute("""
        INSERT INTO dim_waktu (tanggal, hari, hari_dalam_minggu, minggu, bulan, nama_bulan, kuartal, tahun)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (tanggal) DO NOTHING
        RETURNING waktu_id
    """, (
        tanggal, hari, tanggal.isoweekday(),
        tanggal.isocalendar()[1], tanggal.month,
        BULAN_NAMES[tanggal.month],
        (tanggal.month - 1) // 3 + 1, tanggal.year,
    ))
    result = cur.fetchone()
    if result:
        w_id = result[0]
    else:
        # If conflict, fetch again
        cur.execute("SELECT waktu_id FROM dim_waktu WHERE tanggal = %s", (tanggal,))
        w_id = cur.fetchone()[0]
    
    DIM_CACHE["waktu"][tanggal] = w_id
    return w_id

def upsert_dim_kategori(conn, nama: str) -> int:
    if nama in DIM_CACHE["kategori"]:
        return DIM_CACHE["kategori"][nama]

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dim_kategori (nama_kategori)
        VALUES (%s)
        ON CONFLICT (nama_kategori) DO NOTHING
        RETURNING kategori_id
    """, (nama,))
    result = cur.fetchone()
    if result:
        k_id = result[0]
    else:
        cur.execute("SELECT kategori_id FROM dim_kategori WHERE nama_kategori = %s", (nama,))
        k_id = cur.fetchone()[0]
    
    DIM_CACHE["kategori"][nama] = k_id
    return k_id

def upsert_dim_penulis(conn, nama: str) -> int:
    if nama in DIM_CACHE["penulis"]:
        return DIM_CACHE["penulis"][nama]

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dim_penulis (nama_penulis)
        VALUES (%s)
        ON CONFLICT (nama_penulis) DO NOTHING
        RETURNING penulis_id
    """, (nama,))
    result = cur.fetchone()
    if result:
        p_id = result[0]
    else:
        cur.execute("SELECT penulis_id FROM dim_penulis WHERE nama_penulis = %s", (nama,))
        p_id = cur.fetchone()[0]
    
    DIM_CACHE["penulis"][nama] = p_id
    return p_id

def get_sentimen_id(conn, label: str) -> int:
    if label in DIM_CACHE["sentimen"]:
        return DIM_CACHE["sentimen"][label]

    cur = conn.cursor()
    cur.execute("SELECT sentimen_id FROM dim_sentimen WHERE label = %s", (label,))
    row = cur.fetchone()
    s_id = row[0] if row else 1
    
    DIM_CACHE["sentimen"][label] = s_id
    return s_id

def upsert_dim_entitas(conn, nama: str, tipe: str) -> int:
    cache_key = (nama, tipe)
    if cache_key in DIM_CACHE["entitas"]:
        return DIM_CACHE["entitas"][cache_key]

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dim_entitas (nama_entitas, tipe_entitas)
        VALUES (%s, %s)
        ON CONFLICT (nama_entitas, tipe_entitas) DO NOTHING
        RETURNING entitas_id
    """, (nama, tipe))
    result = cur.fetchone()
    if result:
        e_id = result[0]
    else:
        cur.execute(
            "SELECT entitas_id FROM dim_entitas WHERE nama_entitas = %s AND tipe_entitas = %s",
            (nama, tipe)
        )
        e_id = cur.fetchone()[0]
    
    DIM_CACHE["entitas"][cache_key] = e_id
    return e_id

def _invalidate_dim_cache(pub_date, category, author):
    """
    Buang entri DIM_CACHE yang mungkin sudah stale akibat rollback.
    Dipanggil setiap kali ada error agar ghost-ID tidak dipakai ulang.
    """
    DIM_CACHE["waktu"].pop(pub_date, None)
    DIM_CACHE["kategori"].pop(category, None)
    DIM_CACHE["penulis"].pop(author, None)


def load_article(conn, article: dict) -> int | None:
    cur = conn.cursor()

    # Parse date
    pub_date_str = article.get("pub_date")
    if not pub_date_str:
        return None
    try:
        pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    category = article.get("category", "Lainnya")
    author   = article.get("author", "Kompas.com")

    # ── Upsert dimensions ──
    # Dimensi di-upsert dulu. Jika berhasil, mereka visible dalam
    # transaksi yang sama. Kita pakai SAVEPOINT agar jika fact insert
    # gagal, hanya fact yang di-rollback — bukan dimension-nya.
    try:
        waktu_id    = upsert_dim_waktu(conn, pub_date)
        kategori_id = upsert_dim_kategori(conn, category)
        penulis_id  = upsert_dim_penulis(conn, author)
        sentimen_id = get_sentimen_id(conn, article.get("sentiment_label", "neutral"))
    except Exception as e:
        print(f"  [ERROR] Dim upsert failed for {article['url']}: {e}")
        conn.rollback()
        _invalidate_dim_cache(pub_date, category, author)
        return None

    # Prepare embedding
    embedding = article.get("embedding")
    embedding_str = None
    if embedding:
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    tags = article.get("tags", [])

    # ── Fact insert — protected by SAVEPOINT ──
    # Rollback ke savepoint hanya membatalkan fact insert,
    # dimension upserts di atas tetap ada dalam transaksi.
    artikel_id = None
    try:
        cur.execute("SAVEPOINT sp_fact")
        cur.execute("""
            INSERT INTO fact_artikel (
                url, judul, konten, waktu_id, kategori_id, penulis_id,
                sentimen_id, sentimen_score, embedding, jumlah_kata,
                tags, tanggal_publikasi
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s
            )
            ON CONFLICT (url, tanggal_publikasi) DO UPDATE SET
                judul          = EXCLUDED.judul,
                konten         = EXCLUDED.konten,
                sentimen_id    = EXCLUDED.sentimen_id,
                sentimen_score = EXCLUDED.sentimen_score,
                embedding      = EXCLUDED.embedding,
                jumlah_kata    = EXCLUDED.jumlah_kata,
                tags           = EXCLUDED.tags
            RETURNING artikel_id
        """, (
            article["url"], article["title"], article.get("content", ""),
            waktu_id, kategori_id, penulis_id,
            sentimen_id, article.get("sentiment_score"),
            embedding_str, article.get("word_count", 0),
            tags, pub_date,
        ))
        result = cur.fetchone()
        artikel_id = result[0] if result else None
        cur.execute("RELEASE SAVEPOINT sp_fact")
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT sp_fact")
        cur.execute("RELEASE SAVEPOINT sp_fact")
        print(f"  [ERROR] Fact insert failed for {article['url']}: {e}")
        # Invalidate cache agar ID tidak dipakai ulang di artikel berikutnya
        _invalidate_dim_cache(pub_date, category, author)
        return None

    # ── Load entities ke bridge table ──
    if artikel_id and article.get("entities"):
        for entity in article["entities"]:
            try:
                cur.execute("SAVEPOINT sp_entity")
                entitas_id = upsert_dim_entitas(conn, entity["name"], entity["type"])
                cur.execute("""
                    INSERT INTO bridge_artikel_entitas (artikel_id, entitas_id, frekuensi)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (artikel_id, entitas_id) DO UPDATE SET
                        frekuensi = EXCLUDED.frekuensi
                """, (artikel_id, entitas_id, entity.get("count", 1)))
                cur.execute("RELEASE SAVEPOINT sp_entity")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_entity")
                cur.execute("RELEASE SAVEPOINT sp_entity")

    return artikel_id

def load_trending(conn, trending_topics: list[dict]):
    cur = conn.cursor()
    for topic in trending_topics:
        try:
            tanggal = datetime.strptime(topic["date"], "%Y-%m-%d").date()
            waktu_id = upsert_dim_waktu(conn, tanggal)
            cur.execute("""
                INSERT INTO fact_trending (waktu_id, keyword, frekuensi, avg_frekuensi, skor_trending, tanggal)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                waktu_id, topic["keyword"], topic["frequency"],
                topic.get("avg_frequency", 0), topic["trending_score"], tanggal,
            ))
        except Exception as e:
            print(f"  [ERROR] Loading trending '{topic['keyword']}': {e}")
            conn.rollback()


def load_batch(articles: list[dict], trending: list[dict] = None):
    conn = get_connection()
    loaded = 0
    errors = 0

    try:
        for article in articles:
            result = load_article(conn, article)
            if result:
                loaded += 1
            else:
                errors += 1
        
        # Commit once per batch instead of per article
        conn.commit()

        if trending:
            load_trending(conn, trending)
            conn.commit()

        print(f"  [LOAD] Loaded {loaded} articles, {errors} errors")

    except Exception as e:
        print(f"  [ERROR] Batch load failed: {e}")
        conn.rollback()
    finally:
        conn.close()

    return loaded

def refresh_materialized_views():
    conn = get_connection()
    cur = conn.cursor()
    try:
        print("[LOAD] Refreshing materialized views")
        cur.execute("REFRESH MATERIALIZED VIEW mv_artikel_per_kategori_bulan;")
        cur.execute("REFRESH MATERIALIZED VIEW mv_sentimen_harian;")
        cur.execute("REFRESH MATERIALIZED VIEW mv_top_entitas;")
        conn.commit()
        print("  Materialized views refreshed!")
    except Exception as e:
        print(f"  [ERROR] Refresh failed: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_db_stats():
    conn = get_connection()
    cur = conn.cursor()
    stats = {}
    try:
        for table in ["fact_artikel", "dim_waktu", "dim_kategori", "dim_penulis",
                       "dim_entitas", "bridge_artikel_entitas", "fact_trending"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cur.fetchone()[0]
    except Exception as e:
        print(f"  [ERROR] Stats query failed: {e}")
    finally:
        conn.close()
    return stats