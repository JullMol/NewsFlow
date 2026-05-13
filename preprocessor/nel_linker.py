"""
Named Entity Linking (NEL) Module
=================================
Links NER-extracted entities to Wikipedia / Wikidata knowledge base.

For each entity, the linker:
  1. Searches Indonesian Wikipedia for the best matching article.
  2. Extracts the Wikidata QID (e.g. Q3588) from the Wikipedia page.
  3. Returns a dictionary with wikipedia_url, wikidata_id, and description.

Uses an in-memory cache so repeated entities across articles in the
same batch are only looked up once.
"""

import re
import time
import requests
from typing import Optional
from difflib import SequenceMatcher

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Configuration ──────────────────────────────────────────────
WIKIPEDIA_API = "https://id.wikipedia.org/w/api.php"
WIKIDATA_API  = "https://www.wikidata.org/w/api.php"

# Rate limiting: be polite
DELAY_BETWEEN_CALLS = 0.2  # seconds
MAX_RETRIES = 2

# Wikipedia/Wikidata requires a User-Agent header
HEADERS = {
    "User-Agent": "NewsFlowBot/1.0 (https://github.com/JullMol/NewsFlow; jullmol@example.com)"
}

# In-memory cache: entity_name -> NEL result dict
_nel_cache: dict[str, dict | None] = {}

def _get_similarity(a: str, b: str) -> float:
    """
    Improved similarity score with multiple strategies:
    1. Sequence matching (whole string)
    2. Word-level matching (handles reordered words)
    3. Prefix/suffix matching (handles abbreviations)
    """
    a_clean = re.sub(r'[^\w\s]', '', a.lower()).strip()
    b_clean = re.sub(r'[^\w\s]', '', b.lower()).strip()
    
    if not a_clean or not b_clean: 
        return 0.0
    
    # Strategy 1: Exact substring match (highest confidence)
    if a_clean == b_clean:
        return 1.0
    if a_clean in b_clean or b_clean in a_clean:
        return 0.95
    
    # Strategy 2: Sequence matcher on whole strings
    seq_ratio = SequenceMatcher(None, a_clean, b_clean).ratio()
    
    # Strategy 3: Word-level matching
    a_words = set(re.findall(r'\w+', a_clean))
    b_words = set(re.findall(r'\w+', b_clean))
    
    if a_words and b_words:
        # Jaccard similarity
        intersection = a_words.intersection(b_words)
        union = a_words.union(b_words)
        word_ratio = len(intersection) / len(union) if union else 0.0
    else:
        word_ratio = 0.0
    
    # Strategy 4: Check if all query words are in title (partial match bonus)
    min_words = min(len(a_words), len(b_words))
    if min_words > 0:
        if a_words.issubset(b_words) or b_words.issubset(a_words):
            partial_ratio = 0.85
        else:
            partial_ratio = 0.0
    else:
        partial_ratio = 0.0
    
    # Combine strategies: seq_ratio is most reliable
    final_score = max(seq_ratio * 0.4 + word_ratio * 0.35 + partial_ratio * 0.25, seq_ratio)
    
    return final_score

def _search_web_fallback(query: str) -> Optional[dict]:
    """
    Search DuckDuckGo Instant Answer API as a fallback.
    Useful for entities not yet in Wikipedia.
    """
    params = {
        "q": query,
        "format": "json",
        "no_html": 1,
        "skip_disambig": 1
    }
    try:
        resp = requests.get("https://api.duckduckgo.com/", params=params, headers=HEADERS, timeout=5)
        data = resp.json()
        
        # Priority 1: AbstractURL (usually Wikipedia or Official Site)
        if data.get("AbstractURL"):
            return {
                "wikipedia_url": data["AbstractURL"],
                "wikidata_id":   None,
                "deskripsi":     data.get("AbstractText", ""),
                "matched_title": data.get("Heading", query),
                "source":        "DuckDuckGo (Abstract)"
            }
        
        # Priority 2: Results (if it's a direct link)
        results = data.get("Results", [])
        if results:
            return {
                "wikipedia_url": results[0].get("FirstURL"),
                "wikidata_id":   None,
                "deskripsi":     results[0].get("Text", ""),
                "matched_title": query,
                "source":        "DuckDuckGo (Result)"
            }
            
        return None
    except:
        return None

def _search_wikipedia(query: str, lang: str = "id") -> Optional[dict]:
    """Search Wikipedia (default: Indonesian)."""
    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action":   "query",
        "list":     "search",
        "srsearch": query,
        "srlimit":  3,
        "format":   "json",
        "utf8":     1,
    }
    try:
        resp = requests.get(api_url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        return results[0] if results else None
    except:
        return None

def _get_wikidata_info(qid: str) -> Optional[dict]:
    """Get description and official website from Wikidata."""
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "descriptions|sitelinks|claims",
        "languages": "id|en",
        "format": "json"
    }
    try:
        resp = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        entity = data.get("entities", {}).get(qid, {})
        
        # 1. Get Description
        desc_data = entity.get("descriptions", {})
        desc = desc_data.get("id", {}).get("value") or desc_data.get("en", {}).get("value", "")
        
        # 2. Get Wikipedia URL
        sitelinks = entity.get("sitelinks", {})
        wiki_url = sitelinks.get("idwiki", {}).get("url") or sitelinks.get("enwiki", {}).get("url", "")
        
        # 3. Get Official Website (P856)
        official_url = None
        claims = entity.get("claims", {})
        if "P856" in claims:
            # Take the first main value
            try:
                official_url = claims["P856"][0]["mainsnak"]["datavalue"]["value"]
            except:
                pass

        return {
            "wikidata_id": qid, 
            "deskripsi": desc, 
            "wikipedia_url": wiki_url,
            "official_url": official_url
        }
    except:
        return None

def _search_wikidata_directly(query: str) -> Optional[dict]:
    """Fallback search using Wikidata's search API."""
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "id",
        "format": "json",
        "limit": 1
    }
    try:
        resp = requests.get(WIKIDATA_API, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        results = data.get("search", [])
        if results:
            res = results[0]
            return {
                "wikidata_id": res.get("id"),
                "matched_title": res.get("label"),
                "deskripsi": res.get("description", ""),
                "wikipedia_url": f"https://www.wikidata.org/wiki/{res.get('id')}"
            }
        return None
    except:
        return None

def _get_page_info(title: str, lang: str = "id") -> Optional[dict]:
    """Get full page info including Wikidata ID."""
    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action":  "query",
        "titles":  title,
        "prop":    "pageprops|extracts|info",
        "exintro": True,
        "explaintext": True,
        "exsentences": 3,
        "inprop":  "url",
        "format":  "json",
        "utf8":    1,
    }
    try:
        resp = requests.get(api_url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1": continue
            return {
                "title":         page_data.get("title", ""),
                "wikidata_id":   page_data.get("pageprops", {}).get("wikibase_item"),
                "wikipedia_url": page_data.get("fullurl", ""),
                "extract":       page_data.get("extract", ""),
            }
    except:
        return None
    return None

def _clean_query(query: str) -> str:
    """
    Remove clear noisy suffixes but preserve important info.
    Priority: Keep entity name intact, only remove obvious news noise.
    """
    # Remove 'cq' and anything after it (specific news formatting)
    query = re.split(r'\s+cq(?:\s|$)', query, flags=re.IGNORECASE)[0]
    
    # Remove date patterns like 'per 23 April 2026' but preserve numbers in names
    query = re.sub(r'\s+per\s+\d+\s+(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|\w+)\s+\d{4}', '', query, flags=re.IGNORECASE)
    query = re.sub(r'\s+per\s+\d+\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', '', query, flags=re.IGNORECASE)
    
    # Remove common news attribution suffixes only at very end
    query = re.sub(r'\s+(akan|menegaskan|menyatakan|mengimbau|memastikan|mengatakan|ungkap|jelaskan)\s+.*$', '', query, flags=re.IGNORECASE)
    
    # Remove trailing punctuation and extra spaces
    query = re.sub(r'[,;:\.]*\s*$', '', query)
    query = query.strip()
    
    return query

def link_entity(name: str, entity_type: str) -> Optional[dict]:
    """
    Links an entity to the best available reference.
    Priority: Official Web > Wikipedia (ID) > Wikipedia (EN) > Web Search.
    
    Improved with:
    - Multiple query variations for better matching
    - Lowered thresholds for better recall
    - Better disambiguation using entity type and context
    """
    cache_key = f"{name}|{entity_type}"
    if cache_key in _nel_cache:
        return _nel_cache[cache_key]

    if len(name) < 3: 
        return None

    # Clean the name (remove news fluff)
    cleaned_name = _clean_query(name)
    
    candidates = []

    # Generate query variations: try multiple strategies
    queries = []
    
    # 1. Cleaned query (prioritized)
    if cleaned_name and cleaned_name != name:
        queries.append(cleaned_name)
    
    # 2. Original name
    queries.append(name)
    
    # 3. For multi-word entities, try first N words (handles truncation)
    words = name.split()
    if len(words) > 2:
        queries.append(' '.join(words[:3]))  # First 3 words
        queries.append(' '.join(words[:2]))  # First 2 words
    
    # 4. For PERSON type, try reverse words (last name first)
    if entity_type == "PERSON" and len(words) == 2:
        queries.append(f"{words[1]} {words[0]}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for q in queries:
        q_normalized = q.lower().strip()
        if q_normalized not in seen and len(q_normalized) >= 2:
            seen.add(q_normalized)
            unique_queries.append(q)
    
    for q in unique_queries:
        # --- Step 1: Search Wikipedia (ID) - LOWER THRESHOLD ---
        res_id = _search_wikipedia(q, "id")
        if res_id and _get_similarity(q, res_id["title"]) > 0.35:  # Lowered from 0.4
            info = _get_page_info(res_id["title"], "id")
            if info:
                wikidata_info = _get_wikidata_info(info["wikidata_id"]) if info["wikidata_id"] else None
                
                # Compute score based on similarity
                sim_score = _get_similarity(q, res_id["title"])
                base_score = 1.0 if sim_score > 0.85 else (0.9 if sim_score > 0.75 else 0.8)
                
                candidates.append({
                    "wikipedia_url": info["wikipedia_url"],
                    "official_url":  wikidata_info.get("official_url") if wikidata_info else None,
                    "wikidata_id":   info["wikidata_id"],
                    "deskripsi":     info["extract"] or res_id.get("snippet", ""),
                    "matched_title": info["title"],
                    "score":         base_score,
                    "similarity":    sim_score,
                    "language":      "id"
                })

        # --- Step 2: Search Wikipedia (EN) - LOWER THRESHOLD ---
        res_en = _search_wikipedia(q, "en")
        if res_en and _get_similarity(q, res_en["title"]) > 0.5:  # Lowered from 0.6
            info = _get_page_info(res_en["title"], "en")
            if info:
                wikidata_info = _get_wikidata_info(info["wikidata_id"]) if info["wikidata_id"] else None
                
                sim_score = _get_similarity(q, res_en["title"])
                base_score = 0.75 if sim_score > 0.8 else 0.65
                
                candidates.append({
                    "wikipedia_url": info["wikipedia_url"],
                    "official_url":  wikidata_info.get("official_url") if wikidata_info else None,
                    "wikidata_id":   info["wikidata_id"],
                    "deskripsi":     info["extract"] or res_en.get("snippet", ""),
                    "matched_title": info["title"],
                    "score":         base_score,
                    "similarity":    sim_score,
                    "language":      "en"
                })
        
        if candidates: 
            break  # Found something good, stop searching variations

    # --- Step 3: Search Wikidata directly - LOWER THRESHOLD ---
    if not candidates:
        res_wd = _search_wikidata_directly(name)
        if res_wd and _get_similarity(name, res_wd["matched_title"]) > 0.5:  # Lowered from 0.6
            wikidata_info = _get_wikidata_info(res_wd["wikidata_id"])
            candidates.append({
                "wikipedia_url": res_wd["wikipedia_url"],
                "official_url":  wikidata_info.get("official_url") if wikidata_info else None,
                "wikidata_id":   res_wd["wikidata_id"],
                "deskripsi":     res_wd["deskripsi"],
                "matched_title": res_wd["matched_title"],
                "score":         0.65,
                "similarity":    _get_similarity(name, res_wd["matched_title"]),
                "language":      "wikidata"
            })

    # --- Step 4: Fallback to Web Search (DuckDuckGo) ---
    if not candidates:
        res_web = _search_web_fallback(name)
        if res_web:
            candidates.append({
                "wikipedia_url": res_web["wikipedia_url"],
                "official_url":  None,
                "wikidata_id":   None,
                "deskripsi":     res_web["deskripsi"],
                "matched_title": res_web["matched_title"],
                "score":         0.4,
                "similarity":    0.4,
                "language":      "web"
            })

    if not candidates:
        _nel_cache[cache_key] = None
        return None

    # Sort by score and pick the best
    candidates.sort(key=lambda x: (-x["score"], -x["similarity"]))
    best = candidates[0]

    # --- Step 5: Relevance Check (Official Website) ---
    # For Organizations, if we have an official website with high score, prefer it
    final_link = best["wikipedia_url"]
    if entity_type == "ORGANIZATION" and best.get("official_url") and best["score"] >= 0.9:
        final_link = best["official_url"]

    result = {
        "wikipedia_url": final_link,
        "wikidata_id":   best["wikidata_id"],
        "deskripsi":     best["deskripsi"],
        "matched_title": best["matched_title"],
        "nel_score":     best["score"],  # Include score for verification
        "nel_similarity": best["similarity"],  # Include similarity for verification
        "nel_language":  best["language"]  # Track which source found it
    }
    
    _nel_cache[cache_key] = result
    time.sleep(DELAY_BETWEEN_CALLS)  # Be polite to APIs
    return result


def link_article_entities(articles: list[dict]) -> list[dict]:
    """
    Run NEL on all entities in a batch of articles.
    Each entity dict in article["entities"] gets enriched with:
      - wikipedia_url
      - wikidata_id
      - deskripsi
      - nel_matched (bool)
      - nel_score (confidence score 0-1)
      - nel_similarity (similarity match score)
      - nel_language (which source found it)
    """
    # Count total entities for progress
    total = sum(len(a.get("entities", [])) for a in articles)
    linked = 0
    not_found = 0
    low_confidence = 0

    print(f"[NEL] Linking {total} entities from {len(articles)} articles to Wikipedia/Wikidata")

    for article in articles:
        entities = article.get("entities", [])
        for entity in entities:
            nel_result = link_entity(entity["name"], entity["type"])

            if nel_result:
                entity["wikipedia_url"] = nel_result["wikipedia_url"]
                entity["wikidata_id"]   = nel_result["wikidata_id"]
                entity["deskripsi"]     = nel_result["deskripsi"]
                entity["nel_matched"]   = True
                entity["nel_score"]     = nel_result.get("nel_score", 0.5)
                entity["nel_similarity"] = nel_result.get("nel_similarity", 0.0)
                entity["nel_language"]  = nel_result.get("nel_language", "unknown")
                
                if nel_result.get("nel_score", 0.5) < 0.65:
                    low_confidence += 1
                linked += 1
            else:
                entity["wikipedia_url"] = None
                entity["wikidata_id"]   = None
                entity["deskripsi"]     = None
                entity["nel_matched"]   = False
                entity["nel_score"]     = 0.0
                entity["nel_similarity"] = 0.0
                entity["nel_language"]  = None
                not_found += 1

    print(f"  [NEL] Done: {linked} linked, {not_found} not found, "
          f"{low_confidence} low-confidence ({(linked/total*100):.1f}%), "
          f"{len(_nel_cache)} cached")

    return articles


def get_cache_stats() -> dict:
    """Return stats about the NEL cache."""
    total = len(_nel_cache)
    matched = sum(1 for v in _nel_cache.values() if v is not None)
    return {
        "total_cached": total,
        "matched":      matched,
        "not_found":    total - matched,
    }


# ── CLI test ───────────────────────────────────────────────────
if __name__ == "__main__":
    test_entities = [
        ("Joko Widodo", "PERSON"),
        ("DPR", "ORGANIZATION"),
        ("Jakarta", "LOCATION"),
        ("Prabowo Subianto", "PERSON"),
        ("Bank Indonesia", "ORGANIZATION"),
        ("Surabaya", "LOCATION"),
    ]

    print("NEL Test — Linking entities to Wikipedia/Wikidata\n")
    for name, etype in test_entities:
        result = link_entity(name, etype)
        if result:
            print(f"  [{etype}] {name}")
            print(f"    -> {result['matched_title']}")
            print(f"    -> Wikidata: {result['wikidata_id']}")
            print(f"    -> URL: {result['wikipedia_url']}")
            print(f"    -> {result['deskripsi'][:100]}...")
        else:
            print(f"  [{etype}] {name} -> NOT FOUND")
        print()

    stats = get_cache_stats()
    print(f"Cache: {stats}")
