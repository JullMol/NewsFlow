ENABLE_EXTENSIONS = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""

CREATE_DIM_WAKTU = """
CREATE TABLE IF NOT EXISTS dim_waktu (
    waktu_id        SERIAL PRIMARY KEY,
    tanggal         DATE NOT NULL UNIQUE,
    hari            VARCHAR(10) NOT NULL,
    hari_dalam_minggu INTEGER NOT NULL,
    minggu          INTEGER NOT NULL,
    bulan           INTEGER NOT NULL,
    nama_bulan      VARCHAR(20) NOT NULL,
    kuartal         INTEGER NOT NULL,
    tahun           INTEGER NOT NULL
);
"""

CREATE_DIM_KATEGORI = """
CREATE TABLE IF NOT EXISTS dim_kategori (
    kategori_id     SERIAL PRIMARY KEY,
    nama_kategori   VARCHAR(100) NOT NULL UNIQUE
);
"""

CREATE_DIM_PENULIS = """
CREATE TABLE IF NOT EXISTS dim_penulis (
    penulis_id      SERIAL PRIMARY KEY,
    nama_penulis    VARCHAR(255) NOT NULL UNIQUE
);
"""

CREATE_DIM_SENTIMEN = """
CREATE TABLE IF NOT EXISTS dim_sentimen (
    sentimen_id     SERIAL PRIMARY KEY,
    label           VARCHAR(20) NOT NULL UNIQUE,
    deskripsi       TEXT
);

-- Pre-populate sentiment dimension
INSERT INTO dim_sentimen (label, deskripsi) VALUES
    ('positive', 'Sentimen positif - berita bernada baik/optimis'),
    ('neutral', 'Sentimen netral - berita bernada objektif/informatif'),
    ('negative', 'Sentimen negatif - berita bernada buruk/pesimis')
ON CONFLICT (label) DO NOTHING;
"""

CREATE_DIM_ENTITAS = """
CREATE TABLE IF NOT EXISTS dim_entitas (
    entitas_id      SERIAL PRIMARY KEY,
    nama_entitas    VARCHAR(255) NOT NULL,
    tipe_entitas    VARCHAR(20) NOT NULL CHECK (tipe_entitas IN ('PERSON', 'ORGANIZATION', 'LOCATION')),
    UNIQUE (nama_entitas, tipe_entitas)
);
"""

CREATE_FACT_ARTIKEL = """
CREATE TABLE IF NOT EXISTS fact_artikel (
    artikel_id          SERIAL,
    url                 TEXT NOT NULL,
    judul               TEXT NOT NULL,
    konten              TEXT,
    waktu_id            INTEGER REFERENCES dim_waktu(waktu_id),
    kategori_id         INTEGER REFERENCES dim_kategori(kategori_id),
    penulis_id          INTEGER REFERENCES dim_penulis(penulis_id),
    sentimen_id         INTEGER REFERENCES dim_sentimen(sentimen_id),
    sentimen_score      FLOAT,
    embedding           vector(384),
    jumlah_kata         INTEGER DEFAULT 0,
    tags                TEXT[],
    tanggal_publikasi   DATE NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (artikel_id, tanggal_publikasi)
) PARTITION BY RANGE (tanggal_publikasi);
"""

CREATE_FACT_ARTIKEL_NO_PARTITION = """
CREATE TABLE IF NOT EXISTS fact_artikel (
    artikel_id          SERIAL PRIMARY KEY,
    url                 TEXT NOT NULL UNIQUE,
    judul               TEXT NOT NULL,
    konten              TEXT,
    waktu_id            INTEGER REFERENCES dim_waktu(waktu_id),
    kategori_id         INTEGER REFERENCES dim_kategori(kategori_id),
    penulis_id          INTEGER REFERENCES dim_penulis(penulis_id),
    sentimen_id         INTEGER REFERENCES dim_sentimen(sentimen_id),
    sentimen_score      FLOAT,
    embedding           vector(384),
    jumlah_kata         INTEGER DEFAULT 0,
    tags                TEXT[],
    tanggal_publikasi   DATE NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW()
);
"""

# Bridge table for many-to-many article-entity relationship
CREATE_BRIDGE_ARTIKEL_ENTITAS = """
CREATE TABLE IF NOT EXISTS bridge_artikel_entitas (
    id              SERIAL PRIMARY KEY,
    artikel_id      INTEGER NOT NULL,
    entitas_id      INTEGER NOT NULL REFERENCES dim_entitas(entitas_id),
    frekuensi       INTEGER DEFAULT 1,
    UNIQUE (artikel_id, entitas_id)
);
"""

CREATE_FACT_TRENDING = """
CREATE TABLE IF NOT EXISTS fact_trending (
    trending_id     SERIAL PRIMARY KEY,
    waktu_id        INTEGER REFERENCES dim_waktu(waktu_id),
    keyword         VARCHAR(255) NOT NULL,
    frekuensi       INTEGER NOT NULL,
    avg_frekuensi   FLOAT,
    skor_trending   FLOAT NOT NULL,
    tanggal         DATE NOT NULL
);
"""

def generate_partition_ddl(start_year: int = 2024, end_year: int = 2026) -> str:
    ddl = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month = 1
                next_year = year + 1
            partition_name = f"fact_artikel_{year}_{month:02d}"
            ddl.append(f"""
CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF fact_artikel
    FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01');
""")
    return "\n".join(ddl)

PARTITION_DDL = generate_partition_ddl()

CREATE_URL_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_artikel_url
    ON fact_artikel (url, tanggal_publikasi);
"""

CREATE_INDEXES = """
-- Indexes on fact_artikel
CREATE INDEX IF NOT EXISTS idx_fact_artikel_waktu ON fact_artikel(waktu_id);
CREATE INDEX IF NOT EXISTS idx_fact_artikel_kategori ON fact_artikel(kategori_id);
CREATE INDEX IF NOT EXISTS idx_fact_artikel_sentimen ON fact_artikel(sentimen_id);
CREATE INDEX IF NOT EXISTS idx_fact_artikel_penulis ON fact_artikel(penulis_id);
CREATE INDEX IF NOT EXISTS idx_fact_artikel_tanggal ON fact_artikel(tanggal_publikasi);

-- Trigram index for text search on title
CREATE INDEX IF NOT EXISTS idx_fact_artikel_judul_trgm
    ON fact_artikel USING gin (judul gin_trgm_ops);

-- pgvector index for similarity search (IVFFlat)
-- Only create after loading sufficient data (>1000 rows)
-- CREATE INDEX IF NOT EXISTS idx_fact_artikel_embedding
--     ON fact_artikel USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Indexes on bridge table
CREATE INDEX IF NOT EXISTS idx_bridge_artikel ON bridge_artikel_entitas(artikel_id);
CREATE INDEX IF NOT EXISTS idx_bridge_entitas ON bridge_artikel_entitas(entitas_id);

-- Indexes on fact_trending
CREATE INDEX IF NOT EXISTS idx_trending_waktu ON fact_trending(waktu_id);
CREATE INDEX IF NOT EXISTS idx_trending_tanggal ON fact_trending(tanggal);
CREATE INDEX IF NOT EXISTS idx_trending_keyword ON fact_trending(keyword);
"""

CREATE_MATERIALIZED_VIEWS = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_artikel_per_kategori_bulan AS
SELECT
    dk.nama_kategori,
    dw.tahun,
    dw.bulan,
    dw.nama_bulan,
    COUNT(*) AS jumlah_artikel,
    AVG(fa.sentimen_score) AS avg_sentimen_score,
    SUM(CASE WHEN ds.label = 'positive' THEN 1 ELSE 0 END) AS jumlah_positif,
    SUM(CASE WHEN ds.label = 'neutral' THEN 1 ELSE 0 END) AS jumlah_netral,
    SUM(CASE WHEN ds.label = 'negative' THEN 1 ELSE 0 END) AS jumlah_negatif,
    AVG(fa.jumlah_kata) AS avg_jumlah_kata
FROM fact_artikel fa
JOIN dim_kategori dk ON fa.kategori_id = dk.kategori_id
JOIN dim_waktu dw ON fa.waktu_id = dw.waktu_id
JOIN dim_sentimen ds ON fa.sentimen_id = ds.sentimen_id
GROUP BY dk.nama_kategori, dw.tahun, dw.bulan, dw.nama_bulan;

-- MV: Daily sentiment trend
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_sentimen_harian AS
SELECT
    dw.tanggal,
    dw.tahun,
    dw.bulan,
    dw.hari,
    COUNT(*) AS total_artikel,
    AVG(fa.sentimen_score) AS avg_sentimen,
    SUM(CASE WHEN ds.label = 'positive' THEN 1 ELSE 0 END) AS positif,
    SUM(CASE WHEN ds.label = 'neutral' THEN 1 ELSE 0 END) AS netral,
    SUM(CASE WHEN ds.label = 'negative' THEN 1 ELSE 0 END) AS negatif
FROM fact_artikel fa
JOIN dim_waktu dw ON fa.waktu_id = dw.waktu_id
JOIN dim_sentimen ds ON fa.sentimen_id = ds.sentimen_id
GROUP BY dw.tanggal, dw.tahun, dw.bulan, dw.hari;

-- MV: Top entities
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_top_entitas AS
SELECT
    de.nama_entitas,
    de.tipe_entitas,
    COUNT(DISTINCT bae.artikel_id) AS jumlah_artikel,
    SUM(bae.frekuensi) AS total_sebutan
FROM bridge_artikel_entitas bae
JOIN dim_entitas de ON bae.entitas_id = de.entitas_id
GROUP BY de.nama_entitas, de.tipe_entitas;
"""

REFRESH_MATERIALIZED_VIEWS = """
REFRESH MATERIALIZED VIEW mv_artikel_per_kategori_bulan;
REFRESH MATERIALIZED VIEW mv_sentimen_harian;
REFRESH MATERIALIZED VIEW mv_top_entitas;
"""

def get_full_schema_ddl(use_partition: bool = True) -> str:
    parts = [
        ENABLE_EXTENSIONS,
        CREATE_DIM_WAKTU,
        CREATE_DIM_KATEGORI,
        CREATE_DIM_PENULIS,
        CREATE_DIM_SENTIMEN,
        CREATE_DIM_ENTITAS,
        CREATE_FACT_ARTIKEL if use_partition else CREATE_FACT_ARTIKEL_NO_PARTITION,
    ]
    if use_partition:
        parts.append(PARTITION_DDL)
        parts.append(CREATE_URL_UNIQUE_INDEX)
    parts.extend([
        CREATE_BRIDGE_ARTIKEL_ENTITAS,
        CREATE_FACT_TRENDING,
        CREATE_INDEXES,
        CREATE_MATERIALIZED_VIEWS,
    ])
    return "\n".join(parts)