import pandas as pd
import psycopg2
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_CONFIG

def fetch_data_from_db() -> dict[str, pd.DataFrame]:
    conn = psycopg2.connect(**DB_CONFIG)

    print("[ATOTI] Fetching data from database")
    df_artikel = pd.read_sql("""
        SELECT
            fa.artikel_id, fa.url, fa.judul, fa.waktu_id,
            fa.kategori_id, fa.penulis_id, fa.sentimen_id,
            fa.sentimen_score, fa.jumlah_kata, fa.tags,
            fa.tanggal_publikasi
        FROM fact_artikel fa
    """, conn)

    if "tags" in df_artikel.columns:
        df_artikel["tags"] = df_artikel["tags"].apply(lambda x: ", ".join(x) if isinstance(x, list) else str(x))

    df_waktu = pd.read_sql("SELECT * FROM dim_waktu", conn)
    df_kategori = pd.read_sql("SELECT * FROM dim_kategori", conn)
    df_penulis = pd.read_sql("SELECT * FROM dim_penulis", conn)
    df_sentimen = pd.read_sql("SELECT * FROM dim_sentimen", conn)
    df_entitas = pd.read_sql("SELECT * FROM dim_entitas", conn)

    df_bridge = pd.read_sql("SELECT * FROM bridge_artikel_entitas", conn)
    df_trending = pd.read_sql("SELECT * FROM fact_trending", conn)

    df_mv_kategori = pd.read_sql("SELECT * FROM mv_artikel_per_kategori_bulan", conn)
    df_mv_sentimen = pd.read_sql("SELECT * FROM mv_sentimen_harian", conn)
    df_mv_entitas = pd.read_sql("SELECT * FROM mv_top_entitas", conn)

    conn.close()

    print(f"  fact_artikel: {len(df_artikel)} rows")
    print(f"  dim_waktu: {len(df_waktu)} rows")
    print(f"  dim_kategori: {len(df_kategori)} rows")
    print(f"  fact_trending: {len(df_trending)} rows")

    return {
        "fact_artikel": df_artikel,
        "dim_waktu": df_waktu,
        "dim_kategori": df_kategori,
        "dim_penulis": df_penulis,
        "dim_sentimen": df_sentimen,
        "dim_entitas": df_entitas,
        "bridge_artikel_entitas": df_bridge,
        "fact_trending": df_trending,
        "mv_kategori_bulan": df_mv_kategori,
        "mv_sentimen_harian": df_mv_sentimen,
        "mv_top_entitas": df_mv_entitas,
    }


def create_cube(data: dict = None):
    import atoti as tt

    if data is None:
        data = fetch_data_from_db()

    print("\n[ATOTI] Creating OLAP session")
    content_dir = Path(__file__).parent / "content"
    session = tt.Session.start(
        tt.SessionConfig(
            port=11875,
            user_content_storage=content_dir
        )
    )
    
    trending_table = None
    trending_cube = None

    df_fact = data["fact_artikel"]
    df_waktu = data["dim_waktu"]
    df_kategori = data["dim_kategori"]
    df_penulis = data["dim_penulis"]
    df_sentimen = data["dim_sentimen"]

    df_merged = df_fact.merge(df_waktu, on="waktu_id", how="left")
    df_merged = df_merged.merge(df_kategori, on="kategori_id", how="left")
    df_merged = df_merged.merge(df_penulis, on="penulis_id", how="left")
    df_merged = df_merged.merge(df_sentimen, on="sentimen_id", how="left")

    import datetime
    fill_values = {
        "tahun": 0,
        "kuartal": 0,
        "nama_bulan": "Unknown",
        "tanggal": datetime.date(1970, 1, 1),
        "nama_kategori": "Unknown",
        "label": "Unknown",
        "nama_penulis": "Unknown"
    }
    for col, val in fill_values.items():
        if col in df_merged.columns:
            df_merged[col] = df_merged[col].fillna(val)

    print("[ATOTI] Loading artikel table")
    artikel_table = session.read_pandas(
        df_merged,
        keys={"artikel_id"},
        table_name="Artikel",
        default_values={k: v for k, v in fill_values.items() if k in df_merged.columns}
    )

    print("[ATOTI] Loading trending table")
    df_trending = data["fact_trending"]
    if not df_trending.empty:
        df_trending_merged = df_trending.merge(df_waktu, on="waktu_id", how="left")
        
        for col, val in fill_values.items():
            if col in df_trending_merged.columns:
                df_trending_merged[col] = df_trending_merged[col].fillna(val)
                
        trending_table = session.read_pandas(
            df_trending_merged,
            keys={"trending_id"},
            table_name="Trending",
            default_values={k: v for k, v in fill_values.items() if k in df_trending_merged.columns}
        )

    df_bridge = data["bridge_artikel_entitas"]
    df_entitas = data["dim_entitas"]
    if not df_bridge.empty and not df_entitas.empty:
        df_entity_merged = df_bridge.merge(df_entitas, on="entitas_id", how="left")
        entity_table = session.read_pandas(
            df_entity_merged,
            keys={"id"},
            table_name="ArtikelEntitas",
        )

    print("[ATOTI] Creating OLAP cube")
    cube = session.create_cube(artikel_table, name="KompasNewsCube")

    h = cube.hierarchies

    h["Waktu"] = {
        "Tahun": artikel_table["tahun"],
        "Kuartal": artikel_table["kuartal"],
        "Bulan": artikel_table["nama_bulan"],
        "Tanggal": artikel_table["tanggal"],
    }
    
    # Independent hierarchies for easy UI dragging without drill-down constraints
    h["Tahun"] = {"Tahun": artikel_table["tahun"]}
    h["Bulan"] = {"Bulan": artikel_table["nama_bulan"]}
    h["Tanggal"] = {"Tanggal": artikel_table["tanggal"]}

    h["Kategori"] = {
        "Nama Kategori": artikel_table["nama_kategori"],
    }
    h["Sentimen"] = {
        "Label": artikel_table["label"],
    }

    h["Penulis"] = {
        "Nama Penulis": artikel_table["nama_penulis"],
    }

    m = cube.measures

    m["Jumlah Artikel"] = tt.agg.count_distinct(artikel_table["artikel_id"])

    m["Rata-rata Sentimen"] = tt.agg.mean(artikel_table["sentimen_score"])

    m["Rata-rata Kata"] = tt.agg.mean(artikel_table["jumlah_kata"])

    m["Persen Positif"] = tt.filter(
        m["Jumlah Artikel"],
        h["Sentimen"]["Label"] == "positive"
    ) / m["Jumlah Artikel"]

    m["Persen Negatif"] = tt.filter(
        m["Jumlah Artikel"],
        h["Sentimen"]["Label"] == "negative"
    ) / m["Jumlah Artikel"]

    if not df_trending.empty and trending_table is not None:
        print("[ATOTI] Creating Trending OLAP cube")
        trending_cube = session.create_cube(trending_table, name="TrendingCube")
        
        th = trending_cube.hierarchies
        th["Waktu"] = {
            "Tahun": trending_table["tahun"],
            "Kuartal": trending_table["kuartal"],
            "Bulan": trending_table["nama_bulan"],
        }
        th["Keyword"] = {
            "Keyword": trending_table["keyword"],
        }
        
        tm = trending_cube.measures
        tm["Skor Trending"] = tt.agg.mean(trending_table["skor_trending"])
        tm["Frekuensi"] = tt.agg.sum(trending_table["frekuensi"])

    print("\n[ATOTI] Cube created successfully!")
    print(f"  Hierarchies: {list(h.keys())}")
    print(f"  Measures: {list(m.keys())}")
    print(f"\n  Access Atoti UI: {session.link}")

    return session, cube


def olap_rollup(cube):
    print("OLAP OPERATION 1: ROLL-UP (Tanggal -> Bulan -> Tahun per Kategori)")
    m = cube.measures
    h = cube.hierarchies

    # Roll-up: Tanggal -> Bulan -> Tahun per Kategori
    print("\n [Granular] Volume Artikel per Tanggal & Kategori (10 Baris Pertama):")
    df_tanggal = cube.query(m["Jumlah Artikel"], levels=[h["Kategori"]["Nama Kategori"], h["Waktu"]["Tanggal"]])
    print(df_tanggal.head(10))

    print("\n [Roll-up to Bulan] Volume Artikel per Bulan & Kategori (10 Baris Pertama):")
    df_bulan = cube.query(m["Jumlah Artikel"], levels=[h["Kategori"]["Nama Kategori"], h["Waktu"]["Bulan"]])
    print(df_bulan.head(10))

    print("\n [Roll-up to Tahun] Volume Artikel per Tahun & Kategori:")
    df_tahun = cube.query(m["Jumlah Artikel"], levels=[h["Kategori"]["Nama Kategori"], h["Waktu"]["Tahun"]])
    print(df_tahun.head(10))


def olap_drilldown(cube, tahun=2026, bulan="Mei"):
    print(f"  OLAP OPERATION 2: DRILL-DOWN (Tahun {tahun} -> Bulan {bulan})")
    m = cube.measures
    h = cube.hierarchies

    # Drill-down: Filter Tahun, rincian ke Bulan, lalu ke Tanggal
    print(f"\n [Drill-Down to Bulan] Distribusi Artikel per Kategori di Tahun {tahun}:")
    df_bulan = cube.query(
        m["Jumlah Artikel"],
        levels=[h["Kategori"]["Nama Kategori"], h["Waktu"]["Bulan"]],
        filter=(h["Waktu"]["Tahun"] == tahun)
    )
    print(df_bulan.head(10))

    print(f"\n [Drill-Down to Tanggal] Rincian Artikel per Hari pada Bulan {bulan} {tahun}:")
    df_hari = cube.query(
        m["Jumlah Artikel"],
        m["Rata-rata Sentimen"],
        levels=[h["Waktu"]["Tanggal"]],
        filter=((h["Waktu"]["Tahun"] == tahun) & (h["Waktu"]["Bulan"] == bulan))
    )
    print(df_hari.head(15))


def olap_slice(cube, kategori="Finansial"):
    print(f"  OLAP OPERATION 3: SLICE (Kategori = '{kategori}')")
    m = cube.measures
    h = cube.hierarchies

    # Slice: Mengiris data berdasarkan satu dimensi (Kategori = 'Finansial')
    df_slice = cube.query(
        m["Jumlah Artikel"],
        m["Rata-rata Sentimen"],
        levels=[h["Waktu"]["Tahun"], h["Waktu"]["Bulan"]],
        filter=(h["Kategori"]["Nama Kategori"] == kategori)
    )
    print(df_slice.head(12))


def olap_dice(cube, kategori="Bandung", tahun=2026, sentimen="neutral"):
    print(f"  OLAP OPERATION 4: DICE (Kategori = '{kategori}' AND Tahun = {tahun} AND Sentimen = '{sentimen}')")
    m = cube.measures
    h = cube.hierarchies

    # Dice: Mengiris data berdasarkan multi-dimensi sekaligus (Kategori, Tahun, Sentimen)
    df_dice = cube.query(
        m["Jumlah Artikel"],
        m["Rata-rata Sentimen"],
        levels=[h["Waktu"]["Tanggal"]],
        filter=(
            (h["Kategori"]["Nama Kategori"] == kategori) &
            (h["Waktu"]["Tahun"] == tahun) &
            (h["Sentimen"]["Label"] == sentimen)
        )
    )
    print(df_dice.head(15))


def semantic_search(query_text: str, top_k: int = 5):
    from preprocessor.embedding_generator import get_generator

    generator = get_generator()
    query_embedding = generator.generate(query_text)
    emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT judul, url, 1 - (embedding <=> %s::vector) AS similarity
        FROM fact_artikel
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (emb_str, emb_str, top_k))

    results = cur.fetchall()
    conn.close()

    print(f"\n[SEMANTIC SEARCH] Query: '{query_text}'")
    print(f"  Top {top_k} similar articles:")
    for i, (title, url, sim) in enumerate(results, 1):
        print(f"  {i}. [{sim:.4f}] {title}")
        print(f"     {url}")

    return results


if __name__ == "__main__":
    session, cube = create_cube()
    
    # Jalankan seluruh 4 operasi OLAP interaktif
    olap_rollup(cube)
    olap_drilldown(cube, tahun=2026, bulan="Mei")
    olap_slice(cube, kategori="Finansial")
    olap_dice(cube, kategori="Bandung", tahun=2026, sentimen="neutral")

    print(f"  Atoti UI tersedia secara persisten di: {session.link}")
    print("  Jaringan OLAP aktif. Tekan Ctrl+C untuk menghentikan.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Session closed.")