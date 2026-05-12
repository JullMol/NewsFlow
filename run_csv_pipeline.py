import pandas as pd
from tqdm import tqdm
from datetime import datetime
import sys
from pathlib import Path

# Import pipeline modules
from preprocessor import text_cleaner, sentiment_analyzer, ner_extractor, embedding_generator
from feeder import loader

def main():
    print("KOMPAS DATA WAREHOUSE - CSV HISTORICAL LOADER")

    csv_path = Path("data/raw/kompas_news_2yr.csv")
    if not csv_path.exists():
        print(f"[ERROR] File not found: {csv_path}")
        return

    print(f"\n1. Loading data from {csv_path}")
    df = pd.read_csv(csv_path)
    
    # Filter valid articles
    if 'is_valid' in df.columns:
        df = df[df['is_valid'] == True].copy()
    
    # Fill NaN with empty string
    df = df.fillna("")
    
    articles = df.to_dict('records')
    print(f"Total articles to process: {len(articles)} rows\n")
    
    # Pre-formatting data to match pipeline
    print("Adjusting data format")
    for art in tqdm(articles, desc="Formatting"):
        # Extract pub_date
        if 'published_at' in art and str(art['published_at']).strip():
            art['pub_date'] = str(art['published_at']).split(' ')[0]
        else:
            art['pub_date'] = datetime.now().strftime("%Y-%m-%d")
        
        # Format tags as list
        if isinstance(art.get('tags'), str):
            art['tags'] = [t.strip() for t in art['tags'].split(',') if t.strip()]
        else:
            art['tags'] = []
            
        if 'scraped_at' not in art or not str(art['scraped_at']).strip():
            art['scraped_at'] = datetime.now().isoformat()
            
    print("\n2. Initializing NLP Models (IndoBERT and Sentence Transformers)")
    sentiment_analyzer_inst = sentiment_analyzer.get_analyzer()
    embedding_generator_inst = embedding_generator.get_generator()
    
    print("\n3. Starting Batch Processing")
    # Process in batches of 100 to avoid high memory usage
    batch_size = 100
    total_batches = (len(articles) - 1) // batch_size + 1
    
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        print(f"\nProcessing Batch {i//batch_size + 1} of {total_batches} ({len(batch)} articles)")
        
        # Transform 1: Clean Text
        batch = text_cleaner.clean_batch(batch)
            
        # Transform 2: Sentiment (IndoBERT)
        batch = sentiment_analyzer.analyze_articles(batch, sentiment_analyzer_inst)
        
        # Transform 3: NER (Person, Org, Loc)
        for art in batch:
            text_to_extract = f"{art.get('title', '')} {art.get('content', '')}"
            art['entities'] = ner_extractor.extract_entities(text_to_extract)
            
        # Transform 4: Vector Embeddings
        batch = embedding_generator.generate_article_embeddings(batch, embedding_generator_inst)
        
        # Load: Upsert to Supabase
        loader.load_batch(batch)
        print(f"Batch {i//batch_size + 1} successfully saved to database")
        
    print("\n4. Refreshing Materialized Views in Database")
    loader.refresh_materialized_views()
    print("\nFINISHED! All historical articles processed and loaded to Supabase Data Warehouse")

if __name__ == "__main__":
    main()
