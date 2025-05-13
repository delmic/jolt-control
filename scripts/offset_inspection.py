"""Script to inspect data for offset vs. output characteristic for varying operating voltage

Created on 12 March 2025
@author: Tim Moerkerken
Copyright © 2025 Tim Moerkerken, Delmic
"""

# %%
import matplotlib.pyplot as plt
from pathlib import Path
import pandas as pd
plt.style.use('dark_background')
# %%

measurement_file = Path("offset_output_relation_red_max_gain_30_37_1.feo.tsv")

measurement = pd.read_csv(measurement_file, delimiter='\t')
for c in measurement["channel"].unique():
    plt.figure(figsize=(8 ,8), dpi=300)
    for v in measurement["voltage_target"].unique():
        v_match = measurement[measurement["voltage_target"] == v][measurement["channel"] == c]
        offset = v_match["offset"].values
        if "fe_output_avg" in v_match:
            output = v_match["fe_output_avg"].values
        else:
            output = v_match["fe_output"].values

        plt.plot(offset[1:], output[1:], label=v)
    plt.xlabel("Offset")
    plt.ylabel("FE Output (V)")
    plt.legend(title="Op. Voltage (V)")
    plt.title(f"Frontend offset vs. averaged output voltage at {measurement['temperature_target'].unique()[0]}°C\nChannel: {c.lower()}, max gain")
plt.show()
# %%
