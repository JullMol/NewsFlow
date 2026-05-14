from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "kompas-dw",
    "depends_on_past": True,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "max_active_runs": 1,
}

def task_collect_urls(**context):
    from scraper.sitemap_parser import collect_urls_from_indeks
    exec_date = context["ds"]
    from datetime import date as d
    dt = d.fromisoformat(exec_date)
    articles = collect_urls_from_indeks(dt)
    context["ti"].xcom_push(key="articles_info", value=articles)
    return len(articles)


def task_scrape_articles(**context):
    from scraper.article_scraper import scrape_batch
    exec_date = context["ds"]
    articles_info = context["ti"].xcom_pull(key="articles_info", task_ids="collect_urls")
    if not articles_info:
        print(f"No URLs for {exec_date}")
        return 0
    articles = scrape_batch(articles_info, exec_date)
    return len(articles)


def task_clean_text(**context):
    from scraper.article_scraper import load_batch
    from preprocessor.text_cleaner import clean_batch
    import json
    from config import RAW_DIR, PROCESSED_DIR

    exec_date = context["ds"]
    articles = load_batch(exec_date)
    articles = clean_batch(articles)

    out = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_analyze_sentiment(**context):
    from preprocessor.sentiment_analyzer import analyze_articles, get_analyzer
    import json
    from config import PROCESSED_DIR

    exec_date = context["ds"]
    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    analyzer = get_analyzer()
    articles = analyze_articles(articles, analyzer)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_generate_embeddings(**context):
    from preprocessor.embedding_generator import generate_article_embeddings, get_generator
    import json
    from config import PROCESSED_DIR

    exec_date = context["ds"]
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


def task_extract_entities(**context):
    from preprocessor.ner_extractor import extract_article_entities
    import json
    from config import PROCESSED_DIR

    exec_date = context["ds"]
    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    articles = extract_article_entities(articles)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_link_entities(**context):
    from preprocessor.nel_linker import link_article_entities
    import json
    from config import PROCESSED_DIR

    exec_date = context["ds"]
    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    articles = link_article_entities(articles)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False)
    return len(articles)


def task_detect_trending(**context):
    from preprocessor.trending_detector import process_trending
    import json
    from config import PROCESSED_DIR

    exec_date = context["ds"]
    path = PROCESSED_DIR / f"clean_{exec_date}.json"
    with open(path, "r", encoding="utf-8") as f:
        articles = json.load(f)

    trending = process_trending(articles, exec_date)

    trend_path = PROCESSED_DIR / f"trending_{exec_date}.json"
    with open(trend_path, "w", encoding="utf-8") as f:
        json.dump(trending, f, ensure_ascii=False)

    return len(trending)


def task_load_to_db(**context):
    from feeder.loader import load_batch, refresh_materialized_views
    import json
    from config import PROCESSED_DIR

    exec_date = context["ds"]

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
    dag_id="kompas_etl_pipeline",
    default_args=default_args,
    description="Daily ETL pipeline for Kompas.com news articles",
    schedule_interval="@daily",
    start_date=datetime(2026, 5, 13),
    catchup=False,
    tags=["kompas", "etl", "data-warehouse"],
) as dag:

    t1 = PythonOperator(task_id="collect_urls", python_callable=task_collect_urls)
    t2 = PythonOperator(task_id="scrape_articles", python_callable=task_scrape_articles)
    t3 = PythonOperator(task_id="clean_text", python_callable=task_clean_text)
    t4 = PythonOperator(task_id="analyze_sentiment", python_callable=task_analyze_sentiment)
    t5 = PythonOperator(task_id="generate_embeddings", python_callable=task_generate_embeddings)
    t6 = PythonOperator(task_id="extract_entities", python_callable=task_extract_entities)
    t6_5 = PythonOperator(task_id="link_entities", python_callable=task_link_entities)
    t7 = PythonOperator(task_id="detect_trending", python_callable=task_detect_trending)
    t8 = PythonOperator(task_id="load_to_db", python_callable=task_load_to_db)

    t1 >> t2 >> t3 >> t4 >> t5 >> t6 >> t6_5 >> t7 >> t8