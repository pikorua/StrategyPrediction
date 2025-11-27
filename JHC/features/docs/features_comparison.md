# SMT Feature Database Comparison

## Overview

**SMTLIB Catalog**: ~204 operator features + 11 command-level features + some metadata (file size, maxTermDepth)
**MachSMT Parser**: ~175 features (includes ~30 SMT-LIB2 commands)

**Verdict**: SMTLIB Catalog is more comprehensive overall, covering both theory operators and key command-level statistics.

---

## Coverage Summary

| Theory/Category | SMTLIB Catalog | MachSMT Parser | Winner |
|----------------|------------|------------|--------|
| Core Logic | ✓ | ✓ | Tie |
| Bit-vectors | ✓✓ (extended) | ✓ | DB1 |
| Integers/Reals | ✓✓ (extended) | ✓ | DB1 |
| Arrays | ✓✓ (extended) | ✓ | DB1 |
| Floating-point | ✓✓ (extended) | ✓ | DB1 |
| Strings/RegEx | ✓✓ (extended) | ✓ | DB1 |
| Sequences | ✓ | ✗ | DB1 |
| **Command-level Features** | ✓ (10 tracked) | ✓ (33 tracked) | DB2 (more granular) |
| **Structural Features** | ✓ (depth, size) | ✗ | DB1 |

---

## Features in SMTLIB Catalog but NOT in MachSMT Parser

### Bit-vectors (Extended Operations)
- `bvempty` - empty bit-vector
- `reduce_and`, `reduce_or`, `reduce_xor` - reduction operations
- `bvite` - bit-vector if-then-else
- `bv1ult` - specialized comparison
- `bitOf` - bit extraction
- **Overflow detection**: `bvuaddo`, `bvsaddo`, `bvumulo`, `bvsmulo`, `bvusubo`, `bvssubo`, `bvsdivo`
- `bvultbv`, `bvsltbv` - bit-vector comparisons returning bit-vectors
- `bvredand`, `bvredor` - alternative reduction operations
- `int2bv`, `bv2nat` - conversion operations
- `bvsize` - size query

### Arithmetic (Extended Operations)
- **Total functions**: `div_total`, `mod_total`, `/_total`
- `divisible` - divisibility predicate
- `iand` - integer bitwise AND
- `int.pow2` - power of 2
- `^` - exponentiation
- **Transcendental functions**:
  - `real.pi` - pi constant
  - `exp` - exponential
  - Trigonometric: `sin`, `cos`, `tan`, `csc`, `sec`, `cot`
  - Inverse trig: `arcsin`, `arccos`, `arctan`, `arccsc`, `arcsec`, `arccot`
  - `sqrt` - square root

### Arrays (Extended Operations)
- `store_all` - constant array constructor
- `eqrange` - equality over range

### Floating-point (Extended Operations)
- `fp.to_ubv_total`, `fp.to_sbv_total` - total conversion functions
- `to_fp_bv` - bit-vector to floating-point conversion

### Strings (Extended Operations)
- `Char` - character type
- `str.rev` - string reverse
- `str.unit` - unit string constructor
- `str.update` - string update
- `str.to_lower`, `str.to_upper` - case conversion
- `str.indexof_re` - index of regex match
- `re.empty` - empty language
- `re.loop` - regex loop/repetition

### Sequences
- `seq.empty` - empty sequence
- `seq.unit` - unit sequence
- `seq.nth` - nth element
- `seq.len` - sequence length

### Command-level and Structural Features

SMTLIB Catalog tracks these at the query/benchmark level (counts and metrics):

**Declaration Commands** (tracked as counts):
- `declare-fun` - function declarations (with arguments)
- `declare-const` - constant declarations (includes 0-ary `declare-fun`)
- `declare-sort` - sort declarations
- `define-fun` - function definitions (with arguments)
- `define-fun-rec` / `define-funs-rec` - recursive function definitions
- `constantFun` - constant definitions (0-ary `define-fun`)
- `define-sort` - sort definitions
- `declare-datatype` / `declare-datatypes` - datatype declarations
- `assertsCount` - number of assertions

**Structural Metrics**:
- `maxTermDepth` - maximum nesting depth of terms
- `normalizedSize` - query size in bytes
- `compressedSize` - compressed query size

**Note**: SMTLIB Catalog tracks these as *aggregate statistics* rather than individual feature occurrences.

### Core
- `const` - constant constructor (for arrays/values)

---

## Features in MachSMT Parser but NOT in SMTLIB Catalog

### SMT-LIB2 Commands and Keywords

MachSMT Parser tracks these as individual feature occurrences, while SMTLIB Catalog tracks some as aggregate counts (see overlap below).

**Commands also tracked by SMTLIB Catalog** (as counts):
- `assert`
- `declare-const`, `declare-datatype`, `declare-datatypes`
- `declare-fun`, `declare-sort`
- `define-fun`, `define-fun-rec`, `define-funs-rec`, `define-sort`

**Commands unique to MachSMT Parser**:

*Assertions and Queries*:
- `check-sat`, `check-sat-assuming`

*Stack Management*:
- `push`, `pop`, `reset`, `reset-assertions`

*Configuration*:
- `set-info`, `set-logic`, `set-option`
- `get-info`, `get-option`

*Results and Debugging*:
- `get-model`, `get-value`, `get-proof`
- `get-unsat-core`, `get-unsat-assumptions`, `get-assignment`
- `get-assertions`

*Other*:
- `as` - type casting/annotation
- `echo` - output
- `exit` - termination

### Floating-point Type Shortcuts
- `Float16`, `Float32`, `Float64`, `Float128` - specific floating-point formats

### Rounding Mode Abbreviations
- `RNE` (roundNearestTiesToEven)
- `RNA` (roundNearestTiesToAway)
- `RTP` (roundTowardPositive)
- `RTN` (roundTowardNegative)
- `RTZ` (roundTowardZero)

### Strings/RegEx
- `re.^` - (if different from `re.loop` in SMTLIB Catalog)

---

## Recommendations

### Use SMTLIB Catalog if:
- You need comprehensive operator/function coverage
- You're extracting features from SMT formulas/constraints
- You want extended theory operations (transcendentals, sequences, overflow detection)
- **You need structural metrics** (term depth, query size, compression ratios)
- **You want aggregate command statistics** (counts of declarations, definitions, assertions)

### Use MachSMT Parser if:
- You need to track individual occurrences of each command
- You require fine-grained command-level analysis (e.g., tracking each `check-sat`)
- You want to analyze solver interaction commands (`get-model`, `push`, `pop`)
- You need query/configuration commands (`set-logic`, `get-info`, etc.)

### Use Both if:
- You need complete SMT-LIB2 file analysis
- You want both operator-level features AND command-level tracking
- You're building a comprehensive SMT analysis tool
- You need structural metrics (DB1) plus fine-grained command tracking (DB2)

---

## Statistics

| Metric | SMTLIB Catalog | MachSMT Parser |
|--------|------------|------------|
| **Total Features** | **~214** | **~175** |
| Theory Operators | ~204 | ~142 |
| Command-level | 10 (as counts) | 33 (as occurrences) |
| Structural Metrics | 4 | 0 |
| Unique Operators | ~62 | 0 |
| Unique Commands | 0 | ~24 |

### Key Differences in Approach

**SMTLIB Catalog**: 
- Focuses on comprehensive operator coverage
- Tracks commands as aggregate counts per query
- Includes structural analysis (depth, size)
- Better for formula feature extraction

**MachSMT Parser**: 
- Tracks individual command occurrences
- Includes solver interaction commands
- Better for analyzing solver usage patterns
- More granular command-level tracking

---

## Conclusion

**SMTLIB Catalog is more comprehensive overall** for SMT instance analysis:
- **Superior operator coverage**: ~62 additional theory operators including transcendentals, sequences, and overflow detection
- **Structural metrics**: Unique capabilities for analyzing query complexity (term depth, size metrics)
- **Command tracking**: Aggregate statistics for declarations and definitions

**MachSMT Parser's advantages**:
- **Granular command tracking**: Tracks individual occurrences of 33 commands
- **Solver interaction**: Includes commands for solver control (`push`, `pop`, `check-sat`, `get-model`)

### Best Choice by Use Case

| Use Case | Recommended Database |
|----------|---------------------|
| Formula feature extraction | **SMTLIB Catalog** |
| Theory operator analysis | **SMTLIB Catalog** |
| Structural complexity analysis | **SMTLIB Catalog** |
| Solver interaction patterns | **MachSMT Parser** |
| Fine-grained command tracking | **MachSMT Parser** |
| Comprehensive analysis | **Both (complementary)** |

For most SMT instance feature extraction tasks, **SMTLIB Catalog provides superior coverage** with 214 total features versus MachSMT Parser's 175.