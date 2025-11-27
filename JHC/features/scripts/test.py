from get_benchmark_features import get_benchmark_features

# Get features for a specific benchmark
features = get_benchmark_features('SMT-LIB-Catalog-2025/database/smtlib2025.sqlite', 'calc2_sec2_bmc25.smt2')

# Access the data
print(features['logic'])                      
print(features['symbol_counts'])       
print(features['commands'])         
print(features['metadata'])   

