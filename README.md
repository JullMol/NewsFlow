<p align="center">
  <img src="docs/architecture.png" width="700" alt="Architecture Diagram"/>
</p>

<h1 align="center">📰 Kompas.com News Data Warehouse</h1>

<p align="center">
  <strong>End-to-End ETL Pipeline dengan NLP untuk Analisis Tren dan Sentimen Berita Indonesia</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Airflow-2.10-017CEE?style=for-the-badge&logo=apacheairflow&logoColor=white"/>
  <img src="https://img.shields.io/badge/Atoti-OLAP-FF6B35?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/IndoBERT-NLP-FF4081?style=for-the-badge&logo=huggingface&logoColor=white"/>
</p>

---

## 📋 Daftar Isi

- [Tentang Proyek](#-tentang-proyek)
- [Rumusan Masalah](#-rumusan-masalah)
- [Arsitektur Sistem](#-arsitektur-sistem)
- [Skema Data Warehouse](#-skema-data-warehouse-star-schema)
- [Struktur Folder](#-struktur-folder)
- [Tech Stack](#-tech-stack)
- [Cara Instalasi](#-cara-instalasi)
- [Cara Menjalankan](#-cara-menjalankan)
- [Pipeline NLP](#-pipeline-nlp)
- [OLAP & Analisis](#-olap--analisis-multidimensi)
- [Orchestration dengan Airflow](#-orchestration-dengan-airflow)
- [Kontributor](#-kontributor)

---

## 🎯 Tentang Proyek

Proyek ini membangun sebuah **Data Warehouse** komprehensif yang mengakuisisi, mentransformasi, dan menganalisis data berita dari **Kompas.com** — portal berita terbesar di Indonesia. Sistem ini menerapkan pipeline ETL (Extract, Transform, Load) lengkap dengan komponen **Natural Language Processing (NLP)** untuk bahasa Indonesia, termasuk analisis sentimen, Named Entity Recognition (NER), dan pembuatan vector embedding untuk semantic search.

Data warehouse ini dirancang untuk mendukung analisis **longitudinal** (2+ tahun data historis) melalui OLAP cube menggunakan **Atoti**, memungkinkan eksplorasi tren berita, distribusi sentimen, dan deteksi topik trending secara multidimensi.

---

## 🔍 Rumusan Masalah

Kompas.com memproduksi **ratusan artikel berita per hari** lintas kategori (nasional, ekonomi, teknologi, olahraga, dll). Tantangan utama:

| No | Tantangan | Solusi yang Diterapkan |
|:--:|-----------|----------------------|
| 1 | Data berita bersifat **tidak terstruktur** dan tersebar di banyak halaman web | Web scraping berbasis **Sitemap XML** dan parsing halaman indeks |
| 2 | **Tidak ada API publik** resmi dari Kompas.com | Scraper otomatis dengan rate limiting dan error recovery |
| 3 | Analisis tren membutuhkan **NLP khusus bahasa Indonesia** | Pipeline IndoBERT (sentimen) + Multilingual SentenceTransformers (embedding) |
| 4 | Volume data sangat besar untuk analisis longitudinal | **Star Schema** dengan partitioning bulanan dan materialized views |
| 5 | Dibutuhkan eksplorasi data secara **multidimensi** | OLAP Cube via **Atoti** dengan hierarchies dan measures kustom |

### Target Insight

```
📊 Tren volume berita per kategori per bulan/tahun
📈 Distribusi dan tren sentimen berita harian
🏷️  Top entitas (orang, organisasi, lokasi) yang paling sering muncul
🔥 Deteksi topik trending berdasarkan frekuensi keyword
🔎 Semantic search: cari artikel berdasarkan kemiripan makna (vector similarity)
```

---

## 🏗 Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Apache Airflow (Orchestrator)                  │
│                    Menjalankan DAG harian secara otomatis            │
└──────────┬──────────┬──────────┬──────────┬──────────┬──────────────┘
           │          │          │          │          │
     ┌─────▼─────┐   │    ┌─────▼─────┐   │    ┌─────▼─────┐
     │  EXTRACT  │   │    │ TRANSFORM │   │    │   LOAD    │
     │           │   │    │           │   │    │           │
     │ • Sitemap │   │    │ • Clean   │   │    │ • Upsert  │
     │   Parser  │   │    │ • IndoBERT│   │    │   Dims    │
     │ • Article │   │    │   Sentimen│   │    │ • Insert  │
     │   Scraper │   │    │ • NER     │   │    │   Facts   │
     │ • Histori-│   │    │ • Embed-  │   │    │ • Refresh │
     │   cal     │   │    │   dings   │   │    │   MVs     │
     └───────────┘   │    │ • Trending│   │    └───────────┘
                     │    └───────────┘   │          │
                     │                    │    ┌─────▼─────┐
                     │                    │    │  Supabase  │
                     │                    │    │ PostgreSQL │
                     │                    │    │ + pgvector │
                     │                    │    └─────┬─────┘
                     │                    │          │
                     │                    │    ┌─────▼─────┐
                     │                    │    │   OLAP    │
                     │                    │    │  Atoti    │
                     │                    │    │  Cube +   │
                     │                    │    │  JupyterLab│
                     │                    │    └───────────┘
                     │                    │
                     ▼                    ▼
              📁 data/raw/         📁 data/processed/
```

---

## ⭐ Skema Data Warehouse (Star Schema)

```
                           ┌──────────────┐
                           │  dim_waktu   │
                           │──────────────│
                           │ waktu_id (PK)│
                           │ tanggal      │
                           │ hari         │
                           │ minggu       │
                           │ bulan        │
                           │ nama_bulan   │
                           │ kuartal      │
                           │ tahun        │
                           └──────┬───────┘
                                  │
    ┌──────────────┐    ┌─────────▼──────────┐    ┌──────────────┐
    │ dim_kategori │    │   fact_artikel      │    │ dim_penulis  │
    │──────────────│    │────────────────────│    │──────────────│
    │ kategori_id  │◄───│ artikel_id (PK)    │───►│ penulis_id   │
    │ nama_kategori│    │ url                │    │ nama_penulis │
    └──────────────┘    │ judul              │    └──────────────┘
                        │ konten             │
    ┌──────────────┐    │ waktu_id (FK)      │    ┌──────────────┐
    │ dim_sentimen │    │ kategori_id (FK)   │    │ dim_entitas  │
    │──────────────│    │ penulis_id (FK)    │    │──────────────│
    │ sentimen_id  │◄───│ sentimen_id (FK)   │    │ entitas_id   │
    │ label        │    │ sentimen_score     │    │ nama_entitas │
    │ deskripsi    │    │ embedding (vec384) │    │ tipe_entitas │
    └──────────────┘    │ jumlah_kata        │    └──────┬───────┘
                        │ tags[]             │           │
                        │ tanggal_publikasi  │    ┌──────▼───────┐
                        └────────────────────┘    │   bridge_    │
                                                  │artikel_entitas│
                        ┌────────────────────┐    │──────────────│
                        │  fact_trending     │    │ artikel_id   │
                        │────────────────────│    │ entitas_id   │
                        │ trending_id (PK)   │    │ frekuensi    │
                        │ waktu_id (FK)      │    └──────────────┘
                        │ keyword            │
                        │ frekuensi          │
                        │ skor_trending      │
                        └────────────────────┘
```

### Fitur Database Utama

| Fitur | Detail |
|-------|--------|
| **Partitioning** | `fact_artikel` dipartisi per bulan (`PARTITION BY RANGE`) untuk query performa tinggi |
| **pgvector** | Ekstensi PostgreSQL untuk menyimpan dan mencocokkan vector embedding 384-dimensi |
| **pg_trgm** | Trigram index pada kolom `judul` untuk fuzzy text search |
| **Materialized Views** | 3 MV untuk pre-aggregasi: artikel per kategori/bulan, sentimen harian, top entitas |

---

## 📁 Struktur Folder

```
📦 kompas-news-data-warehouse/
├── 📄 README.md                    # Dokumentasi proyek
├── 📄 requirements.txt             # Dependensi Python
├── 📄 .env.example                 # Template konfigurasi environment
├── 📄 .gitignore                   # File yang dikecualikan dari Git
├── 📄 config.py                    # Konfigurasi global (path, model, DB)
├── 📄 setup_database.py            # Script inisialisasi skema database
│
├── 📄 run_pipeline.py              # ⚡ Pipeline utama (scrape → transform → load)
├── 📄 run_csv_pipeline.py          # ⚡ Pipeline dari file CSV historis
│
├── 🐳 docker-compose.yml           # Docker Compose untuk Airflow
├── 🐳 Dockerfile.airflow           # Dockerfile custom Airflow + dependencies
│
├── 📂 scraper/                     # 🔍 Modul Extract
│   ├── __init__.py
│   ├── sitemap_parser.py           # Parser sitemap XML & halaman indeks
│   ├── article_scraper.py          # Scraper konten artikel
│   └── historical_scraper.py       # Scraper data historis (2024-2026)
│
├── 📂 preprocessor/                # 🧠 Modul Transform (NLP)
│   ├── __init__.py
│   ├── text_cleaner.py             # Pembersihan teks (HTML, stopwords, Sastrawi)
│   ├── sentiment_analyzer.py       # Analisis sentimen (IndoBERT)
│   ├── embedding_generator.py      # Vector embedding (Multilingual MiniLM)
│   ├── ner_extractor.py            # Named Entity Recognition
│   └── trending_detector.py        # Deteksi topik trending
│
├── 📂 feeder/                      # 💾 Modul Load
│   ├── __init__.py
│   ├── schema.py                   # DDL skema (tabel, partisi, index, MV)
│   ├── loader.py                   # Upsert data ke Supabase (batch + cache)
│   └── benchmark.py                # Benchmark performa ingestion
│
├── 📂 dags/                        # ✈️ Airflow DAGs
│   └── kompas_etl_dag.py           # DAG harian ETL pipeline
│
├── 📂 atoti_analysis/              # 📊 OLAP Analysis
│   ├── __init__.py
│   └── olap_cube.py                # Atoti OLAP cube + semantic search
│
├── 📂 data/                        # 📁 Direktori data (Git-ignored)
│   ├── raw/                        # Data mentah hasil scraping
│   └── processed/                  # Data hasil transformasi NLP
│
└── 📂 docs/                        # 📚 Dokumentasi tambahan
    └── architecture.png            # Diagram arsitektur
```

---

## 🛠 Tech Stack

### Core Pipeline
| Komponen | Teknologi | Fungsi |
|----------|-----------|--------|
| **Web Scraping** | `requests`, `BeautifulSoup4`, `lxml` | Akuisisi data dari Kompas.com via sitemap XML |
| **Data Processing** | `pandas`, `numpy` | Manipulasi dan pembersihan dataframe |
| **Database** | `PostgreSQL` (Supabase), `psycopg2` | Penyimpanan data warehouse cloud |
| **Vector DB** | `pgvector` | Penyimpanan dan pencarian vector embedding |

### NLP & Machine Learning
| Model | Arsitektur | Fungsi |
|-------|------------|--------|
| **IndoBERT Sentiment** | `mdhugol/indonesia-bert-sentiment-classification` | Klasifikasi sentimen bahasa Indonesia (positif/netral/negatif) |
| **Multilingual MiniLM** | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Pembuatan vector embedding 384-dimensi untuk semantic search |
| **Sastrawi** | Rule-based stemmer | Stemming kata bahasa Indonesia |

### Orchestration & Visualization
| Teknologi | Fungsi |
|-----------|--------|
| **Apache Airflow** | Orkestrasi DAG harian (Docker-based) |
| **Atoti** | OLAP cube engine untuk analisis multidimensi |
| **JupyterLab** | Eksplorasi data interaktif |

---

## 🚀 Cara Instalasi

### Prasyarat

- Python 3.11+
- Git
- Docker & Docker Compose *(opsional, untuk Airflow)*
- Akun [Supabase](https://supabase.com) *(free tier cukup)*

### 1. Clone Repository

```bash
git clone https://github.com/<username>/kompas-news-data-warehouse.git
cd kompas-news-data-warehouse
```

### 2. Buat Virtual Environment

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment

```bash
# Salin template
cp .env.example .env

# Edit dengan kredensial Supabase Anda
# Ambil dari: Supabase Dashboard → Settings → Database
```

Isi file `.env` dengan:
```env
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_KEY=<service-role-key>
SUPABASE_DB_HOST=<db-host>.supabase.com
SUPABASE_DB_PORT=6543
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres.<project-id>
SUPABASE_DB_PASSWORD=<password>
```

### 5. Inisialisasi Database

```bash
python setup_database.py
```

Perintah ini akan membuat seluruh tabel dimensi, tabel fakta (terpartisi per bulan), bridge table, index, dan materialized views di Supabase.

> ⚠️ Pastikan ekstensi `vector` dan `pg_trgm` sudah diaktifkan di Supabase Dashboard → Database → Extensions.

---

## ▶️ Cara Menjalankan

### Opsi A: Pipeline Penuh (Scrape + Transform + Load)

```bash
# Default: 2 tahun terakhir hingga hari ini
python run_pipeline.py

# Custom date range
python run_pipeline.py --start-date 2024-01-01 --end-date 2026-05-12

# Hanya kumpulkan URL (tanpa scraping/processing)
python run_pipeline.py --collect-urls-only

# Proses ulang data yang sudah di-scrape
python run_pipeline.py --process-only
```

### Opsi B: Load dari File CSV Historis

```bash
# Pastikan file CSV ada di data/raw/kompas_news_2yr.csv
python run_csv_pipeline.py
```

### Opsi C: Scraper Data Historis (Sitemap-based)

```bash
python scraper/historical_scraper.py
```

### Opsi D: Jalankan OLAP Cube

```bash
python atoti_analysis/olap_cube.py
```

Akses dashboard Atoti melalui URL yang ditampilkan di terminal (biasanya `http://localhost:xxxxx`).

---

## 🧠 Pipeline NLP

Setiap artikel yang masuk melalui pipeline akan diproses melalui **5 tahap transformasi**:

```
Artikel Mentah
     │
     ▼
┌────────────────────────────────────────┐
│ 1. TEXT CLEANING                       │
│    • Hapus tag HTML                    │
│    • Hapus stopwords bahasa Indonesia  │
│    • Stemming via Sastrawi             │
│    • Normalisasi whitespace            │
└────────────────┬───────────────────────┘
                 ▼
┌────────────────────────────────────────┐
│ 2. SENTIMENT ANALYSIS (IndoBERT)       │
│    • Model: indonesia-bert-sentiment   │
│    • Output: label (pos/neu/neg)       │
│    • Output: confidence score (0–1)    │
└────────────────┬───────────────────────┘
                 ▼
┌────────────────────────────────────────┐
│ 3. VECTOR EMBEDDING (MiniLM)           │
│    • Model: paraphrase-multilingual    │
│    • Output: 384-dim float vector      │
│    • Disimpan di pgvector (cosine sim) │
└────────────────┬───────────────────────┘
                 ▼
┌────────────────────────────────────────┐
│ 4. NAMED ENTITY RECOGNITION            │
│    • Ekstrak: PERSON, ORGANIZATION,    │
│      LOCATION dari judul + konten      │
│    • Disimpan di bridge table M:N      │
└────────────────┬───────────────────────┘
                 ▼
┌────────────────────────────────────────┐
│ 5. TRENDING DETECTION                  │
│    • Rolling window 7 hari             │
│    • Threshold: 2x rata-rata frekuensi │
│    • Output: keyword + skor trending   │
└────────────────────────────────────────┘
```

---

## 📊 OLAP & Analisis Multidimensi

Modul `atoti_analysis/olap_cube.py` membangun OLAP cube dengan konfigurasi:

### Hierarchies (Dimensi Drill-Down)
| Hierarchy | Levels |
|-----------|--------|
| **Waktu** | Tahun → Kuartal → Bulan → Tanggal |
| **Kategori** | Nama Kategori |
| **Sentimen** | Label (positive/neutral/negative) |
| **Penulis** | Nama Penulis |

### Measures (Metrik)
| Measure | Deskripsi |
|---------|-----------|
| `Jumlah Artikel` | Count artikel per sel cube |
| `Rata-rata Sentimen` | Mean sentiment score |
| `Rata-rata Kata` | Mean jumlah kata per artikel |
| `Persen Positif` | Rasio artikel positif |
| `Persen Negatif` | Rasio artikel negatif |

### Contoh CUBE Query

```python
# Distribusi artikel per kategori
cube.query(m["Jumlah Artikel"], levels=[h["Kategori"]["Nama Kategori"]])

# Sentimen per bulan
cube.query(m["Rata-rata Sentimen"], m["Jumlah Artikel"],
           levels=[h["Waktu"]["Bulan"]])

# Cross-tab: Kategori × Sentimen
cube.query(m["Jumlah Artikel"],
           levels=[h["Kategori"]["Nama Kategori"], h["Sentimen"]["Label"]])
```

### Semantic Search (Vector Similarity)

```python
from atoti_analysis.olap_cube import semantic_search

# Cari artikel yang mirip dengan query
results = semantic_search("kebijakan ekonomi digital Indonesia", top_k=5)
```

---

## ✈️ Orchestration dengan Airflow

Pipeline ETL diorkestrasi menggunakan Apache Airflow melalui Docker.

### Menjalankan Airflow

```bash
# Build dan jalankan
docker-compose up -d

# Akses Airflow UI
# http://localhost:8080
# Username: airflow | Password: airflow
```

### DAG: `kompas_etl_pipeline`

```
collect_urls → scrape_articles → clean_text → analyze_sentiment
    → generate_embeddings → extract_entities → detect_trending → load_to_db
```

| Parameter | Nilai |
|-----------|-------|
| Schedule | `@daily` |
| Start Date | 2024-05-01 |
| Catchup | Enabled |
| Retries | 2 (delay 5 menit) |

---

## 📜 Materialized Views

Pipeline secara otomatis me-refresh 3 materialized views setelah setiap batch:

| View | Deskripsi | Penggunaan |
|------|-----------|------------|
| `mv_artikel_per_kategori_bulan` | Agregasi jumlah artikel & sentimen per kategori per bulan | Dashboard tren bulanan |
| `mv_sentimen_harian` | Distribusi sentimen harian (positif/netral/negatif) | Time-series sentimen |
| `mv_top_entitas` | Ranking entitas berdasarkan frekuensi kemunculan | Analisis tokoh/organisasi |

---

## 👥 Kontributor

| Nama | NIM | Peran |
|------|-----|-------|
| *(Isi nama Anda)* | *(NIM)* | Pengembang Pipeline & Data Warehouse |

---

## 📄 Lisensi

Proyek ini dibuat untuk keperluan **Ujian Akhir Semester (UAS)** mata kuliah Data Warehouse, Semester 4.

Data yang di-scraping dari Kompas.com digunakan **hanya untuk keperluan akademis** dan bukan untuk tujuan komersial.

---

<p align="center">
  <sub>Built with ❤️ menggunakan Python, PostgreSQL, IndoBERT, dan Atoti</sub>
</p>
