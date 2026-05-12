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

    # Dimension tables
    df_waktu = pd.read_sql("SELECT * FROM dim_waktu", conn)
    df_kategori = pd.read_sql("SELECT * FROM dim_kategori", conn)
    df_penulis = pd.read_sql("SELECT * FROM dim_penulis", conn)
    df_sentimen = pd.read_sql("SELECT * FROM dim_sentimen", conn)
    df_entitas = pd.read_sql("SELECT * FROM dim_entitas", conn)

    # Bridge & Trending
    df_bridge = pd.read_sql("SELECT * FROM bridge_artikel_entitas", conn)
    df_trending = pd.read_sql("SELECT * FROM fact_trending", conn)

    # Materialized views
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
    session = tt.Session.start()

    # Denormalize fact table with dimensions
    df_fact = data["fact_artikel"]
    df_waktu = data["dim_waktu"]
    df_kategori = data["dim_kategori"]
    df_penulis = data["dim_penulis"]
    df_sentimen = data["dim_sentimen"]

    # Merge dimensions into fact
    df_merged = df_fact.merge(df_waktu, on="waktu_id", how="left")
    df_merged = df_merged.merge(df_kategori, on="kategori_id", how="left")
    df_merged = df_merged.merge(df_penulis, on="penulis_id", how="left")
    df_merged = df_merged.merge(df_sentimen, on="sentimen_id", how="left")

    # Create main table
    print("[ATOTI] Loading artikel table")
    artikel_table = session.read_pandas(
        df_merged,
        keys={"artikel_id"},
        table_name="Artikel",
    )

    # Create trending table
    print("[ATOTI] Loading trending table")
    df_trending = data["fact_trending"]
    if not df_trending.empty:
        df_trending_merged = df_trending.merge(df_waktu, on="waktu_id", how="left")
        trending_table = session.read_pandas(
            df_trending_merged,
            keys={"trending_id"},
            table_name="Trending",
        )

    # Create entity table
    df_bridge = data["bridge_artikel_entitas"]
    df_entitas = data["dim_entitas"]
    if not df_bridge.empty and not df_entitas.empty:
        df_entity_merged = df_bridge.merge(df_entitas, on="entitas_id", how="left")
        entity_table = session.read_pandas(
            df_entity_merged,
            keys={"id"},
            table_name="ArtikelEntitas",
        )

    # Create cube
    print("[ATOTI] Creating OLAP cube")
    cube = session.create_cube(artikel_table, name="KompasNewsCube")

    # Define Hierarchies
    h = cube.hierarchies

    # Time hierarchy: Tahun > Kuartal > Bulan > Hari
    h["Waktu"] = {
        "Tahun": artikel_table["tahun"],
        "Kuartal": artikel_table["kuartal"],
        "Bulan": artikel_table["nama_bulan"],
        "Tanggal": artikel_table["tanggal"],
    }

    # Category hierarchy
    h["Kategori"] = {
        "Nama Kategori": artikel_table["nama_kategori"],
    }

    # Sentiment hierarchy
    h["Sentimen"] = {
        "Label": artikel_table["label"],
    }

    # Author hierarchy
    h["Penulis"] = {
        "Nama Penulis": artikel_table["nama_penulis"],
    }

    # Define Measures
    m = cube.measures

    # Count articles
    m["Jumlah Artikel"] = tt.agg.count(artikel_table["artikel_id"])

    # Average sentiment score
    m["Rata-rata Sentimen"] = tt.agg.mean(artikel_table["sentimen_score"])

    # Average word count
    m["Rata-rata Kata"] = tt.agg.mean(artikel_table["jumlah_kata"])

    # Sentiment ratios
    m["Persen Positif"] = tt.where(
        artikel_table["label"] == "positive",
        m["Jumlah Artikel"],
    ) / m["Jumlah Artikel"]

    m["Persen Negatif"] = tt.where(
        artikel_table["label"] == "negative",
        m["Jumlah Artikel"],
    ) / m["Jumlah Artikel"]

    print("\n[ATOTI] Cube created successfully!")
    print(f"  Hierarchies: {list(h.keys())}")
    print(f"  Measures: {list(m.keys())}")
    print(f"\n  Access Atoti UI: {session.link}")

    return session, cube


def run_sample_queries(cube):
    m = cube.measures
    h = cube.hierarchies

    print("\nSAMPLE OLAP QUERIES")

    # Query 1: Articles per category
    print("\ Articles per Category")
    result = cube.query(m["Jumlah Artikel"], levels=[h["Kategori"]["Nama Kategori"]])
    print(result.head(10))

    # Query 2: Sentiment by month
    print("\ Sentiment by Month")
    result = cube.query(
        m["Rata-rata Sentimen"],
        m["Jumlah Artikel"],
        levels=[h["Waktu"]["Bulan"]],
    )
    print(result.head(12))

    # Query 3: CUBE query (multidimensional)
    print("\ Multidimensional: Category x Sentiment")
    result = cube.query(
        m["Jumlah Artikel"],
        levels=[h["Kategori"]["Nama Kategori"], h["Sentimen"]["Label"]],
    )
    print(result.head(20))


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
    run_sample_queries(cube)

    # Keep session alive for interactive use
    print("\n[ATOTI] Session running. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nSession closed.")