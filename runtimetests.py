import pandas as pd
import subprocess
import os
import tempfile
import shutil

# === STEP 1: Compute best strategy from CSV =====================

df = pd.read_csv("input.csv")

# Kopieren & abs() anwenden
df_sum = df.copy()
df_sum.loc[:, df_sum.columns[1:]] = df_sum.loc[:, df_sum.columns[1:]].abs()

# <-- Diese Zeile war wahrscheinlich vergessen
df_sum["total_runtime"] = df_sum.drop(columns=["strat"]).sum(axis=1)

# Jetzt Zugriff möglich
best_strategy = df_sum.loc[df_sum["total_runtime"].idxmin(), "strat"]
total_time = df_sum["total_runtime"].min()

print(f"Best strategy: {best_strategy} (Total runtime: {total_time})")
# === STEP 2: Test .smt2 files in a directory =====================

best_strategy = "(then (using-params nla2bv :nla2bv_max_bv_size 16) simplify smt)"

folder = "/home/paul/PycharmProjects/StrategyPrediction/data/ijcai24/benchmarks/QF_NIA/train1"  # Folder containing .smt2 files
timeout = 20  # Time limit

results = []
solved_count = 0  # Count sat/unsat only

for filename in os.listdir(folder):
    if filename.endswith(".smt2"):
        original_path = os.path.join(folder, filename)

        # Create temp SMT2 file with modified check-sat
        with tempfile.NamedTemporaryFile(delete=False, suffix=".smt2", mode="w") as tmp_file:
            temp_path = tmp_file.name

            with open(original_path, "r") as f:
                content = f.read()

            # Replace 'check-sat' with strategy
            new_content = content.replace(
                "(check-sat)", f"(check-sat-using {best_strategy})"
            )

            tmp_file.write(new_content)

        # Run solver
        command = ["z3", temp_path, f"-t:{timeout}"]

        try:
            process = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout
            )
            output = process.stdout.strip()
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            output = "timeout"
            exit_code = -1

        # Categorize result
        if output in ["sat", "unsat"]:
            result_type = "solved"
            solved_count += 1
        elif output == "unknown":
            result_type = "unknown"
        else:
            result_type = "timeout"

        results.append({
            "filename": filename,
            "strategy": best_strategy,
            "result": output,
            "result_type": result_type,
            "exit_code": exit_code
        })

        print(f"Tested {filename} → {output}")

        os.unlink(temp_path)  # Clean up temp file

# Save results
pd.DataFrame(results).to_csv("test_results.csv", index=False)

print(f"\nTesting complete using strategy: {best_strategy}")
print(f"Solved (sat/unsat): {solved_count} out of {len(results)} files")
print("Results saved to test_results.csv")
