import sys
from pathlib import Path
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.standard.operators.python import ExternalPythonOperator

# Dynamic search for project root containing 'scraper' in global scope
PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
possible_global_paths = ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]
try:
    possible_global_paths.insert(0, str(Path(__file__).parent))
    possible_global_paths.insert(1, str(Path(__file__).parent.parent))
except Exception:
    pass

for p_str in possible_global_paths:
    if p_str and (Path(p_str) / "scraper").exists():
        PROJECT_ROOT = p_str
        break

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

default_args = {
    "owner": "kompas-dw",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "max_active_runs": 1,
}

def task_collect_urls(exec_date):
    import sys
    from pathlib import Path
    
    # Dynamic search for project root inside the venv subprocess
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from scraper.sitemap_parser import collect_urls_from_indeks
    import json
    from config import RAW_DIR
    from datetime import date as d
    
    dt = d.fromisoformat(exec_date)
    articles = collect_urls_from_indeks(dt)
    
    articles = articles[:50]
    
    out_path = RAW_DIR / f"urls_{exec_date}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
        
    return len(articles)


def task_scrape_articles(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from scraper.article_scraper import scrape_batch
    import json
    from config import RAW_DIR

    path = RAW_DIR / f"urls_{exec_date}.json"
    if not path.exists():
        print(f"No URLs file found for {exec_date}")
        return 0
        
    with open(path, "r", encoding="utf-8") as f:
        articles_info = json.load(f)

    if not articles_info:
        print(f"No URLs in sitemap for {exec_date}")
        return 0

    articles = scrape_batch(articles_info, exec_date)
    return len(articles)


def task_clean_text(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from scraper.article_scraper import load_batch
    from preprocessor.text_cleaner import clean_batch
    import json
    from config import RAW_DIR, PROCESSED_DIR

    articles = load_batch(exec_date)
    articles = clean_batch(articles)

    out = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_analyze_sentiment(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from preprocessor.sentiment_analyzer import analyze_articles, get_analyzer
    import json
    from config import PROCESSED_DIR

    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    analyzer = get_analyzer()
    articles = analyze_articles(articles, analyzer)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_generate_embeddings(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from preprocessor.embedding_generator import generate_article_embeddings, get_generator
    import json
    from config import PROCESSED_DIR

    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    generator = get_generator()
    articles = generate_article_embeddings(articles, generator)

    embeddings = {a["url"]: a.get("embedding") for a in articles}
    emb_path = PROCESSED_DIR / f"emb_{exec_date}.json"
    with open(emb_path, "w") as f:
        json.dump(embeddings, f)

    return len(articles)


def task_extract_entities(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from preprocessor.ner_extractor import extract_article_entities
    import json
    from config import PROCESSED_DIR

    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    articles = extract_article_entities(articles)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_link_entities(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from preprocessor.nel_linker import link_article_entities
    import json
    from config import PROCESSED_DIR

    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    articles = link_article_entities(articles)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_detect_trending(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    from preprocessor.trending_detector import process_trending
    import json
    from config import PROCESSED_DIR

    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    trending = process_trending(articles, exec_date)

    trend_path = PROCESSED_DIR / f"trending_{exec_date}.json"
    with open(trend_path, "w", encoding="utf-8") as f:
        json.dump(trending, f, ensure_ascii=False)

    return len(trending)


def task_load_to_db(exec_date):
    import sys
    from pathlib import Path
    
    PROJECT_ROOT = "/opt/airflow/dags/inter24-dag"
    for p_str in ["/opt/airflow/dags/inter24-dag", "/opt/airflow/dags/inter24-dag/NewsFlow", "/home/inter24/NewsFlow", "/opt/airflow/NewsFlow"]:
        if (Path(p_str) / "scraper").exists():
            PROJECT_ROOT = p_str
            break
            
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    try:
        from feeder.loader import load_batch, refresh_materialized_views
    except (ImportError, Exception):
        from feeder.rest_loader import load_batch, refresh_materialized_views

    import json
    from config import PROCESSED_DIR

    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    emb_path = PROCESSED_DIR / f"emb_{exec_date}.json"
    if emb_path.exists():
        with open(emb_path, "r") as f:
            embeddings = json.load(f)
        for a in articles:
            if a["url"] in embeddings:
                a["embedding"] = embeddings[a["url"]]

    trending = []
    trend_path = PROCESSED_DIR / f"trending_{exec_date}.json"
    if trend_path.exists():
        with open(trend_path, "r", encoding="utf-8") as f:
            trending = json.load(f)

    loaded = load_batch(articles, trending)
    refresh_materialized_views()
    return loaded

with DAG(
    dag_id="kompas_etl_pipeline_v3",
    default_args=default_args,
    description="Daily ETL pipeline for Kompas.com news articles",
    schedule="@daily",
    start_date=datetime(2026, 5, 13),
    catchup=False,
    tags=["kompas", "etl", "data-warehouse"],
) as dag:

    t1 = ExternalPythonOperator(
        task_id="collect_urls",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_collect_urls,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t2 = ExternalPythonOperator(
        task_id="scrape_articles",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_scrape_articles,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t3 = ExternalPythonOperator(
        task_id="clean_text",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_clean_text,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t4 = ExternalPythonOperator(
        task_id="analyze_sentiment",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_analyze_sentiment,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t5 = ExternalPythonOperator(
        task_id="generate_embeddings",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_generate_embeddings,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t6 = ExternalPythonOperator(
        task_id="extract_entities",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_extract_entities,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t6_5 = ExternalPythonOperator(
        task_id="link_entities",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_link_entities,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t7 = ExternalPythonOperator(
        task_id="detect_trending",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_detect_trending,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )
    t8 = ExternalPythonOperator(
        task_id="load_to_db",
        python="/opt/airflow/.venv/bin/python",
        python_callable=task_load_to_db,
        op_kwargs={"exec_date": "{{ ds }}"},
        expect_airflow=False
    )

    t1 >> t2 >> t3 >> t4 >> t5 >> t6 >> t6_5 >> t7 >> t8