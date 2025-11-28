# Benchmark Feature Extraction

Extract features from SMT-LIB benchmarks - either single benchmarks or entire logic datasets.

## Quick Start

### Single Benchmark
```bash
python3 get_benchmark_features.py smtlib2025.sqlite benchmark.smt2
```

### Entire Logic → CSV
```bash
python3 extract_logic_features.py \
    --db smtlib2025.sqlite \
    --logic QF_NIA \
    --output QF_NIA_features.csv
```

## How It Works: Function Call Workflow

### `extract_logic_features.py` → CSV for entire logic

This is the **main extraction tool** for processing all benchmarks in a logic.

**Workflow:**
```
extract_logic_features.py
  ↓
  1. Query database for all non-incremental benchmarks in logic
  ↓
  2. For each benchmark, call:
     get_padded_feature_vector(db, benchmark_name, logic)
       ↓
       2a. Call: get_benchmark_features(db, benchmark_name, logic)
           → Queries database for raw features (symbols, commands, metadata)
       ↓
       2b. Extract logic from features: logic = features['logic']
       ↓
       2c. Call: get_relevant_features(logic)  [from logic_features.py]
           → Returns list of ALL features valid for this logic
           → Example: QF_NIA → [commands, arithmetic ops, core ops, metadata]
       ↓
       2d. Merge raw features: commands + symbols + metadata
       ↓
       2e. Pad missing features with 0
           → If feature in relevant_features but not in benchmark: value = 0
       ↓
       2f. Return: (feature_values, feature_names)
  ↓
  3. Write to CSV:
     - Header: path, feature1, feature2, ..., featureN
     - Rows: benchmark_path, value1, value2, ..., valueN
```

**Key Functions:**

| Function | Script | Purpose |
|----------|--------|---------|
| `extract_features_to_csv()` | extract_logic_features.py | Orchestrates extraction for all benchmarks |
| `get_padded_feature_vector()` | get_benchmark_features.py | Returns zero-padded feature vector |
| `get_benchmark_features()` | get_benchmark_features.py | Queries database for raw features |
| `get_relevant_features()` | logic_features.py | Returns feature list for a logic |


## Command Line Usage

### Single Benchmark
```bash
# Get features and print summary
python3 get_benchmark_features.py smtlib2025.sqlite calc2_sec2_bmc25.smt2

# Output includes:
# - Basic info (logic, status)
# - Command counts
# - Top symbol counts
# - Padded feature vector
# - Full JSON at the end
```

### Entire Logic → CSV
```bash
# Extract all benchmarks for a logic
python3 extract_logic_features.py \
    --db smtlib2025.sqlite \
    --logic QF_NIA \
    --output QF_NIA_features.csv

# Options:
# --db      : Path to database (required)
# --logic   : Logic to extract (required)
# --output  : Output CSV file (required)
# --quiet   : Suppress progress messages (optional)
```

## Important Notes

### 1:1 Mapping (Non-Incremental Only)
Since we filter `isIncremental = 0`, each benchmark has exactly **one query**. This means:
- One benchmark → One query → One feature dict
- Does not handle multiple queries per benchmark

### Returns None If:
- Benchmark name not found in database
- Benchmark is incremental (`isIncremental = 1`)

## Scripts Overview

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `logic_features.py` | Define features per logic | Logic name | List of feature names |
| `get_benchmark_features.py` | Extract single benchmark | Benchmark name, logic | Feature dict or padded vector |
| `extract_logic_features.py` | Extract entire logic | Logic name | CSV file |

**Typical workflow:**
1. Use `extract_logic_features.py` to generate CSV for your logic
3. Load CSV in Python/R for ML