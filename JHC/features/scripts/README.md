# Simple Benchmark Feature Extraction

## Usage

Get features for a single benchmark by filename. Check: `./test.py`. Change the path to the database. 

## What You Get

A simple Python dictionary with everything:

```python
{
    'benchmark_id': 123,
    'benchmark_name': 'calc2_sec2_bmc25.smt2',
    'logic': 'QF_NIA',
    'query_id': 456,
    'status': 'sat',
    'inferredStatus': 'sat',
    
    # Symbol counts (operators, quantifiers, etc.)
    'symbol_counts': {
        'and': 42,
        'or': 15,
        '+': 30,
        '*': 12,
        '<=': 8,
        ...
    },
    
    # Command counts from the SMT-LIB file
    'commands': {
        'assert': 10,
        'declare-fun': 3,
        'declare-const': 2,
        'declare-sort': 1,
        'define-fun': 2,
        'define-fun-rec': 1,
        'define-funs-rec': 0,
        'define-sort': 0,
        'declare-datatype': 2,
        'declare-datatypes': 0,
        'constantFunCount': 1,
    },
    
    # Additional metadata
    'metadata': {
        'maxTermDepth': 5,
        'normalizedSize': 1500
    }
}
```

## Command Line Usage

```bash
# Get features and print summary
python get_benchmark_features.py smtlib2025.sqlite calc2_sec2_bmc25.smt2

# Output includes:
# - Basic info (logic, status)
# - Command counts
# - Top symbol counts
# - Full JSON at the end
```

## Important Notes

### 1:1 Mapping (Non-Incremental Only)
Since we filter `isIncremental = 0`, each benchmark has exactly **one query**. This means:
- One benchmark → One query → One feature dict
- Does not handle multiple queries per benchmark

### Returns None If:
- Benchmark name not found in database
- Benchmark is incremental (`isIncremental = 1`)

## Integration Example

```python
from get_benchmark_features import get_benchmark_features
import json

def benchmark_to_json(db_path: str, benchmark_name: str) -> str:
    """Convert benchmark features to JSON."""
    features = get_benchmark_features(db_path, benchmark_name)
    if features is None:
        return json.dumps({'error': 'Benchmark not found or incremental'})
    return json.dumps(features, indent=2)
```

## Performance
- **Database**: Executes 2 SQL queries (benchmark info + symbol counts)

To improve performance:
1. Ensure database has indexes (run `add_indexes.sh`)
2. Reuse the database connection for multiple queries
3. Cache results if querying same benchmarks repeatedly