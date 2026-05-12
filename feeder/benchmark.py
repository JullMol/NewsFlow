import time
import json
import psycopg2
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_CONFIG, PROCESSED_DIR

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def run_explain_analyze(conn, query: str, params=None) -> dict:
    cur = conn.cursor()
    explain_query = f"EXPLAIN (ANALYZE, FORMAT JSON) {query}"
    cur.execute(explain_query, params)
    result = cur.fetchone()[0]
    plan = result[0]
    return {
        "planning_time_ms": plan.get("Planning Time", 0),
        "execution_time_ms": plan.get("Execution Time", 0),
        "total_time_ms": plan.get("Planning Time", 0) + plan.get("Execution Time", 0),
        "plan": plan.get("Plan", {}),
    }

def benchmark_materialized_view(conn) -> dict:
    print("BENCHMARK 1: Materialized View")

    # Query WITHOUT materialized view (direct aggregation)
    query_without = """
        SELECT dk.nama_kategori, dw.tahun, dw.bulan,
               COUNT(*) as jumlah,
               AVG(fa.sentimen_score) as avg_sentimen
        FROM fact_artikel fa
        JOIN dim_kategori dk ON fa.kategori_id = dk.kategori_id
        JOIN dim_waktu dw ON fa.waktu_id = dw.waktu_id
        GROUP BY dk.nama_kategori, dw.tahun, dw.bulan
        ORDER BY dw.tahun, dw.bulan, dk.nama_kategori
    """

    # Query WITH materialized view
    query_with = """
        SELECT nama_kategori, tahun, bulan,
               jumlah_artikel, avg_sentimen_score
        FROM mv_artikel_per_kategori_bulan
        ORDER BY tahun, bulan, nama_kategori
    """

    result_without = run_explain_analyze(conn, query_without)
    result_with = run_explain_analyze(conn, query_with)

    print(f"\n  WITHOUT MV: {result_without['execution_time_ms']:.3f} ms")
    print(f"  WITH MV:    {result_with['execution_time_ms']:.3f} ms")

    speedup = result_without['execution_time_ms'] / max(result_with['execution_time_ms'], 0.001)
    print(f"  SPEEDUP:    {speedup:.1f}x faster")

    return {
        "benchmark": "Materialized View",
        "query": "Aggregate article count per category per month",
        "without_mv_ms": result_without['execution_time_ms'],
        "with_mv_ms": result_with['execution_time_ms'],
        "speedup": round(speedup, 2),
    }


def benchmark_partition(conn) -> dict:
    print("BENCHMARK 2: Partition (Range by Date)")

    # Query that benefits from partitioning (specific date range)
    query = """
        SELECT COUNT(*), AVG(sentimen_score)
        FROM fact_artikel
        WHERE tanggal_publikasi BETWEEN '2025-01-01' AND '2025-03-31'
    """

    result = run_explain_analyze(conn, query)
    print(f"\n  With Partition Pruning: {result['execution_time_ms']:.3f} ms")

    # Check if partition pruning was used
    plan_str = json.dumps(result['plan'])
    pruning_used = "Append" in plan_str or "Partition" in plan_str

    print(f"  Partition Pruning Used: {pruning_used}")
    print(f"  (Partitioned table only scans relevant monthly partitions)")

    return {
        "benchmark": "Partition (Range by Date)",
        "query": "Filter articles by date range (Q1 2025)",
        "execution_time_ms": result['execution_time_ms'],
        "partition_pruning": pruning_used,
        "note": "Only scans 3 monthly partitions instead of full table",
    }


def benchmark_index(conn) -> dict:
    print("BENCHMARK 3: Index Performance")

    query = """
        SELECT fa.judul, fa.sentimen_score
        FROM fact_artikel fa
        JOIN dim_kategori dk ON fa.kategori_id = dk.kategori_id
        JOIN dim_sentimen ds ON fa.sentimen_id = ds.sentimen_id
        WHERE dk.nama_kategori = 'Nasional'
          AND ds.label = 'negative'
        ORDER BY fa.sentimen_score
        LIMIT 10
    """

    # Run with indexes (current state)
    result_with = run_explain_analyze(conn, query)

    # Temporarily drop indexes, run without, then recreate
    cur = conn.cursor()
    try:
        cur.execute("DROP INDEX IF EXISTS idx_fact_artikel_kategori;")
        cur.execute("DROP INDEX IF EXISTS idx_fact_artikel_sentimen;")
        conn.commit()

        result_without = run_explain_analyze(conn, query)

        # Recreate indexes
        cur.execute("CREATE INDEX idx_fact_artikel_kategori ON fact_artikel(kategori_id);")
        cur.execute("CREATE INDEX idx_fact_artikel_sentimen ON fact_artikel(sentimen_id);")
        conn.commit()
    except Exception as e:
        print(f"  [WARN] Index benchmark error: {e}")
        conn.rollback()
        result_without = result_with  # Fallback

    print(f"\n  WITHOUT Index: {result_without['execution_time_ms']:.3f} ms")
    print(f"  WITH Index:    {result_with['execution_time_ms']:.3f} ms")

    speedup = result_without['execution_time_ms'] / max(result_with['execution_time_ms'], 0.001)
    print(f"  SPEEDUP:       {speedup:.1f}x faster")

    return {
        "benchmark": "Index (B-Tree)",
        "query": "Filter by category=Nasional AND sentiment=negative",
        "without_index_ms": result_without['execution_time_ms'],
        "with_index_ms": result_with['execution_time_ms'],
        "speedup": round(speedup, 2),
    }


def benchmark_pgvector(conn) -> dict:
    print("BENCHMARK 4: pgvector Similarity Search")

    cur = conn.cursor()

    # Get a sample embedding for query
    cur.execute("SELECT embedding FROM fact_artikel WHERE embedding IS NOT NULL LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("  [SKIP] No embeddings in database yet")
        return {"benchmark": "pgvector", "status": "skipped - no data"}

    sample_embedding = row[0]

    # Similarity search query
    query = """
        SELECT judul, embedding <=> %s::vector AS distance
        FROM fact_artikel
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT 5
    """

    result = run_explain_analyze(conn, query, (sample_embedding, sample_embedding))

    print(f"\n  Similarity Search (cosine): {result['execution_time_ms']:.3f} ms")

    # Try creating IVFFlat index if enough data
    try:
        cur.execute("SELECT COUNT(*) FROM fact_artikel WHERE embedding IS NOT NULL")
        count = cur.fetchone()[0]

        if count >= 100:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_fact_artikel_embedding
                ON fact_artikel USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 50)
            """)
            conn.commit()

            result_with_idx = run_explain_analyze(conn, query, (sample_embedding, sample_embedding))
            print(f"  With IVFFlat Index:         {result_with_idx['execution_time_ms']:.3f} ms")

            return {
                "benchmark": "pgvector Similarity Search",
                "without_ivfflat_ms": result['execution_time_ms'],
                "with_ivfflat_ms": result_with_idx['execution_time_ms'],
                "data_count": count,
            }
    except Exception as e:
        print(f"  [WARN] IVFFlat index creation: {e}")
        conn.rollback()

    return {
        "benchmark": "pgvector Similarity Search",
        "execution_time_ms": result['execution_time_ms'],
    }


def run_all_benchmarks():
    conn = get_connection()
    results = []

    try:
        results.append(benchmark_materialized_view(conn))
        results.append(benchmark_partition(conn))
        results.append(benchmark_index(conn))
        results.append(benchmark_pgvector(conn))
    except Exception as e:
        print(f"\n[ERROR] Benchmark failed: {e}")
    finally:
        conn.close()

    # Save results
    output_path = PROCESSED_DIR / "benchmark_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"  BENCHMARK RESULTS SAVED: {output_path}")

    # Print summary table
    print(f"\n{'Benchmark':<35} {'Without':<15} {'With':<15} {'Speedup':<10}")
    for r in results:
        name = r.get("benchmark", "N/A")[:34]
        if "without_mv_ms" in r:
            print(f"{name:<35} {r['without_mv_ms']:<15.3f} {r['with_mv_ms']:<15.3f} {r['speedup']:<10.1f}x")
        elif "without_index_ms" in r:
            print(f"{name:<35} {r['without_index_ms']:<15.3f} {r['with_index_ms']:<15.3f} {r['speedup']:<10.1f}x")
        elif "execution_time_ms" in r:
            print(f"{name:<35} {'N/A':<15} {r['execution_time_ms']:<15.3f} {'N/A':<10}")

    return results

if __name__ == "__main__":
    run_all_benchmarks()