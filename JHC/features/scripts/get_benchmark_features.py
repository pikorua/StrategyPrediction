#!/usr/bin/env python3
"""
Simple feature extraction for individual SMT-LIB benchmarks.

Given a benchmark filename, returns symbol counts and command features.
"""

import sqlite3
from typing import Dict, Any, Optional

"""
Get features for a single non-incremental benchmark by name.
    
Args:
    db_path: Path to SQLite database
    benchmark_name: Benchmark filename (e.g., "calc2_sec2_bmc25.smt2")

Returns:
    Dictionary with:
    {
        'benchmark_id': int,
        'benchmark_name': str,
        'logic': str,
        'query_id': int,
        'status': str,
        'symbol_counts': {symbol_name: count, ...},
        'commands': {
            'assert': count,
            'declare-fun': count,
            'declare-const': count,
            'declare-sort': count,
            'define-fun': count,
            'define-fun-rec': count,
            'define-funs-rec': count,
            'define-sort': count,
            'declare-datatype': count,
            'declare-datatypes': count
        },
        'metadata': {
            'maxTermDepth': int,
            'normalizedSize': int,
        }
    }
    
    Returns None if benchmark not found or is incremental.

Example:
    >>> features = get_benchmark_features('smtlib2025.sqlite', 'calc2_sec2_bmc25.smt2')
    >>> print(features['logic'])
    'QF_NIA'
    >>> print(features['symbol_counts']['and'])
    42
    >>> print(features['commands']['assert'])
    10
"""

def get_benchmark_features(
    db_path: str,
    benchmark_name: str
) -> Optional[Dict[str, Any]]:
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get benchmark and query info (1:1 mapping for non-incremental)
    query = """
    SELECT 
        b.id as benchmark_id,
        b.name as benchmark_name,
        b.logic,
        q.id as query_id,
        q.status,
        q.inferredStatus,
        q.assertsCount,
        q.maxTermDepth,
        q.normalizedSize,
        q.declareFunCount,
        q.declareConstCount,
        q.declareSortCount,
        q.defineFunCount,
        q.defineFunRecCount,
        q.constantFunCount,
        q.defineSortCount,
        q.declareDatatypeCount
    FROM Benchmarks b
    JOIN Queries q ON q.benchmark = b.id
    WHERE b.name = ? AND b.isIncremental = 0
    LIMIT 1
    """
    
    cursor.execute(query, (benchmark_name,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return None
    
    # Unpack results
    (benchmark_id, benchmark_name, logic, query_id, status, inferred_status,
     asserts_count, max_term_depth, normalized_size,
     declare_fun_count, declare_const_count, declare_sort_count,
     define_fun_count, define_fun_rec_count, constant_fun_count,
     define_sort_count, declare_datatype_count) = result
    
    # Get symbol counts
    symbol_query = """
    SELECT s.name, sc.count
    FROM SymbolCounts sc
    JOIN Symbols s ON sc.symbol = s.id
    WHERE sc.query = ?
    """
    
    cursor.execute(symbol_query, (query_id,))
    symbol_counts = {name: count for name, count in cursor.fetchall()}
    
    conn.close()
    
    # Build command features dictionary
    # Map from Queries table columns to command names
    commands = {
        'assert': asserts_count or 0,
        'declare-fun': declare_fun_count or 0,
        'declare-const': declare_const_count or 0,
        'declare-sort': declare_sort_count or 0,
        'define-fun': define_fun_count or 0,
        'define-fun-rec': define_fun_rec_count or 0,  # Includes define-funs-rec
        'constant-fun': constant_fun_count or 0,  # 0-ary define-fun (constants)
        'define-sort': define_sort_count or 0,
        'declare-datatype': declare_datatype_count or 0,  # Includes declare-datatypes
    }
    
    # Build metadata dictionary (only non-redundant fields)
    metadata = {
        'maxTermDepth': max_term_depth or 0,
        'normalizedSize': normalized_size or 0,
    }
    
    # Return complete feature dictionary
    return {
        'benchmark_id': benchmark_id,
        'benchmark_name': benchmark_name,
        'logic': logic,
        'query_id': query_id,
        'status': status or 'unknown',
        'inferredStatus': inferred_status or 'unknown',
        'symbol_counts': symbol_counts,
        'commands': commands,
        'metadata': metadata,
    }

def main():
    """Example usage."""
    import sys
    import json
    
    if len(sys.argv) < 3:
        print("Usage: python get_benchmark_features.py <db_path> <benchmark_name>")
        print("\nExample:")
        print("  python get_benchmark_features.py smtlib2025.sqlite calc2_sec2_bmc25.smt2")
        return 1
    
    db_path = sys.argv[1]
    benchmark_name = sys.argv[2]
    
    features = get_benchmark_features(db_path, benchmark_name)
    
    if features is None:
        print(f"ERROR: Benchmark '{benchmark_name}' not found or is incremental")
        return 1
    
    # Print features in a nice format
    print(f"Benchmark: {features['benchmark_name']}")
    print(f"Logic: {features['logic']}")
    print(f"Status: {features['status']}")
    print(f"\n=== Commands ===")
    for cmd, count in sorted(features['commands'].items()):
        if count > 0:
            print(f"  {cmd:20s}: {count:6,}")
    
    print(f"\n=== Top Symbol Counts ===")
    top_symbols = sorted(features['symbol_counts'].items(), 
                        key=lambda x: x[1], reverse=True)[:10]
    for symbol, count in top_symbols:
        print(f"  {symbol:20s}: {count:6,}")
    
    print(f"\n=== Metadata ===")
    for key, value in sorted(features['metadata'].items()):
        print(f"  {key:20s}: {value:6,}")
    
    print(f"\n=== Full JSON Output ===")
    print(json.dumps(features, indent=2, default=str))
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())