import numpy as np
import pandas as pd

# CSV-Datei einlesen
df = pd.read_csv("qfnia_ln_res.csv")

# Ergebnisliste
results = []

# Alle Dateinamen-Spalten (alles außer 'strat')
files = df.columns[1:]

for file in files:
    times = df[file]

    if (times == -10).all():
        # Alle -10 → irgendeine Strategie nehmen, Runtime = 180
        fastest_strategy = df.loc[0, "strat"]
        runtime = 180
    else:
        # Nur gültige Zeiten betrachten
        valid_times = times.where(times != -10)
        runtime = np.abs(valid_times.min())
        fastest_strategy = df.loc[valid_times.idxmin(), "strat"]

    results.append({
        "filename": file,
        "fastest_strategy": fastest_strategy,
        "runtime": runtime
    })

# In DataFrame umwandeln und speichern
result_df = pd.DataFrame(results)
result_df.to_csv("output.csv", index=False)

print("CSV erfolgreich erstellt!")
