import pandas as pd


def rewrite():
# CSV einlesen
    df = pd.read_csv("input.csv")

    # Ergebnisliste
    results = []

    # Alle Dateinamen (alles außer 'strat')
    files = df.columns[1:]

    for file in files:
        for _, row in df.iterrows():
            strategy = row["strat"]
            runtime = row[file]

            # Nur erfolgreiche Lösungen übernehmen
            if runtime != -10:
                results.append({
                    "filename": file,
                    "strategy": strategy,
                    "runtime": abs(runtime)
                })

    # In DataFrame umwandeln
    result_df = pd.DataFrame(results)

    # Sortieren optional: Erst nach filename, dann nach runtime
    result_df = result_df.sort_values(by=["filename", "runtime"])

    # Speichern
    result_df.to_csv("output.csv", index=False)

    print("Fertig! output.csv erstellt.")

if __name__ == "__main__":
    rewrite()
