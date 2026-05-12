import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Path Configuration
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Create directories if they don't exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Supabase / PostgreSQL Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

DB_CONFIG = {
    "host": os.getenv("SUPABASE_DB_HOST", ""),
    "port": int(os.getenv("SUPABASE_DB_PORT", "5432")),
    "dbname": os.getenv("SUPABASE_DB_NAME", "postgres"),
    "user": os.getenv("SUPABASE_DB_USER", "postgres"),
    "password": os.getenv("SUPABASE_DB_PASSWORD", ""),
    "sslmode": "require",
}

# Scraping Configuration
SITEMAP_INDEX_URL = "https://www.kompas.com/sitemap.xml"
INDEKS_BASE_URL = "https://indeks.kompas.com/"

# HTTP request settings
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}
REQUEST_TIMEOUT = 30  # seconds
REQUEST_DELAY = 1.5   # seconds between requests (be polite)

# Date range for scraping (2 years back from today)
from datetime import date, timedelta
SCRAPE_END_DATE = date.today()
SCRAPE_START_DATE = SCRAPE_END_DATE - timedelta(days=730)  # ~2 years

# NLP Model Configuration
SENTIMENT_MODEL = "mdhugol/indonesia-bert-sentiment-classification"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384  # Output dimension of the embedding model

# Sentiment label mapping
SENTIMENT_LABELS = {
    "LABEL_0": "positive",
    "LABEL_1": "neutral",
    "LABEL_2": "negative",
}

# Processing Configuration
BATCH_SIZE = 32           # Batch size for NLP inference
MAX_TOKEN_LENGTH = 512    # Max tokens for transformer models
TRENDING_WINDOW_DAYS = 7  # Rolling window for trending detection
TRENDING_THRESHOLD = 2.0  # Multiplier above average to flag as trending

# Kompas.com Category Mapping (from URL subdomain/path)
CATEGORY_MAP = {
    "nasional": "Nasional",
    "megapolitan": "Megapolitan",
    "sains": "Sains",
    "tekno": "Teknologi",
    "ekonomi": "Ekonomi",
    "internasional": "Internasional",
    "bola": "Sepak Bola",
    "sport": "Olahraga",
    "entertainment": "Hiburan",
    "lifestyle": "Gaya Hidup",
    "health": "Kesehatan",
    "edukasi": "Edukasi",
    "money": "Finansial",
    "properti": "Properti",
    "otomotif": "Otomotif",
    "travel": "Travel",
    "food": "Kuliner",
    "tren": "Tren",
    "hype": "Hype",
    "global": "Global",
    "homey": "Homey",
    "regional": "Regional",
    "jeo": "Jeo",
    "skola": "Skola",
    "stori": "Stori",
    "wiken": "Wiken",
    "cekfakta": "Cek Fakta",
}
