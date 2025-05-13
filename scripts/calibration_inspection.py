"""
Script to inspect the voltage vs. optimal offset characteristic of a calibration run.

Created on 12 March 2025
@author: Tim Moerkerken
Copyright © 2025 Tim Moerkerken, Delmic
"""

# %%
import matplotlib.pyplot as plt
from pathlib import Path
import pandas as pd
from appdirs import AppDirs
plt.style.use('default')  # Or 'dark_background'

# %%

dirs = AppDirs("Jolt", "Delmic")
data_dir = Path(dirs.user_data_dir)

calibration_files = sorted(list(data_dir.glob("jolt-calibration-000000000268513344944902274611242003*.tsv")))
calibration_file = calibration_files[-1]
measurement = pd.read_csv(calibration_file, delimiter='\t')
# %%

for temp in measurement["temperature_target"].unique():
    plt.figure(figsize=(8, 8))
    for channel in ["RED", "GREEN", "BLUE", "PANCHROMATIC"]:
        color = channel.lower() if "PAN" not in channel else "black"
        cond1 = measurement["channel"] == channel
        cond2 = measurement["temperature_target"] == temp
        m = measurement[cond1 & cond2]
        plt.scatter(m["voltage"].values, m["fe_offset"].values, color=color, label=channel)
        plt.xlabel("Operating voltage (V)")
        plt.ylabel("Optimal offset")
        plt.legend(title="Channel")
        plt.title(f"{temp} C")
plt.show()

# %%
