import sys
import time
from pathlib import Path

# Add the project root to the sys.path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from feeder.loader import get_connection
from preprocessor.nel_linker import link_entity

def backfill_nel():
    print("Starting NEL Backfill Process...")
    conn = get_connection()
    cur = conn.cursor()

    try:
        # Get all entities that don't have a wikipedia_url, nel_matched is false, or nel_score is 0.0
        cur.execute("""
            SELECT entitas_id, nama_entitas, tipe_entitas 
            FROM dim_entitas 
            WHERE nel_matched = FALSE 
               OR nel_matched IS NULL 
               OR wikipedia_url IS NULL
               OR nel_score = 0.0
        """)
        
        entities = cur.fetchall()
        
        if not entities:
            print("No missing NEL entities found in the database. Everything is up to date!")
            return

        print(f"Found {len(entities)} entities missing links. Starting update...")

        updated_count = 0

        for row in entities:
            entitas_id, nama_entitas, tipe_entitas = row
            
            # Use our updated link_entity function (which now has Kompas Tag fallback)
            nel_result = link_entity(nama_entitas, tipe_entitas)
            
            if nel_result:
                cur.execute("""
                    UPDATE dim_entitas
                    SET wikidata_id = %s,
                        wikipedia_url = %s,
                        deskripsi = %s,
                        nel_score = %s,
                        nel_similarity = %s,
                        nel_matched = TRUE
                    WHERE entitas_id = %s
                """, (
                    nel_result.get("wikidata_id"),
                    nel_result.get("wikipedia_url"),
                    nel_result.get("deskripsi"),
                    nel_result.get("nel_score", 0.0),
                    nel_result.get("nel_similarity", 0.0),
                    entitas_id
                ))
                updated_count += 1
                
                # Commit every 50 to save progress
                if updated_count % 50 == 0:
                    conn.commit()
                    print(f"  Progress: Updated {updated_count}/{len(entities)} entities...")
                    
        conn.commit()
        print(f"\nSuccessfully backfilled {updated_count} entities with NEL links/descriptions!")

    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()
        print("NEL Backfill process completed.")

if __name__ == "__main__":
    backfill_nel()
