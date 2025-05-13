"""
Script to acquire data for offset vs. output characteristic for varying operating voltage

Created on 12 March 2025
@author: Tim Moerkerken
Copyright © 2025 Tim Moerkerken, Delmic
"""

# %%
from jolt.driver import JOLTComputerBoard
from jolt.driver.joltcb import Channel
from jolt.util.measurement import await_set, await_set_stabilized, average_get
from jolt.util.array import arange
import csv
from datetime import datetime
import logging
import time
logger = logging.getLogger()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logging.basicConfig(level=logging.DEBUG, handlers=[console_handler])
dev = JOLTComputerBoard(simulated=False)
# dev = JoltMeasurementMock()
# %%
TARGET_OP_TEMPS = [25]
TARGET_OP_VOLTAGES = [30, 33.5, 37]
TARGET_OP_VOLTAGES = [*range(30, 37, 1), 37]

CHANNELS = [Channel.GREEN, Channel.RED, Channel.BLUE, Channel.PANCHROMATIC]

FE_OFFSET_RANGE = (0, 1024)
FE_OFFSET_STEP = 4
timestamp = datetime.now().strftime("%Y%m%d_%H%M")

with open(f"offset_output_relation_{timestamp}.feo.tsv", "w", newline="") as file:
    writer = csv.writer(file, delimiter='\t')
    writer.writerow(["temperature_target", "channel", "voltage_target", "temp", "voltage", "offset", "fe_output"])

dev.set_gain(64)
dev.set_offset(0)
time.sleep(0.5)
logger.info(f"Gain is {dev.get_gain()}, offset is {dev.get_offset()}")
for target_op_temp in TARGET_OP_TEMPS:
    # Verify this stays stable
    await_set_stabilized(dev.set_target_mppc_temp, dev.get_cold_plate_temp, target_op_temp, 0.2, 1)
    for channel in CHANNELS:
        await_set(dev.set_channel, dev.get_channel, channel)
        for target_op_voltage in TARGET_OP_VOLTAGES:
            voltage_stabilized = await_set_stabilized(dev.adjust_voltage, dev.get_voltage, target_op_voltage, 0.1, 0)
            for offset in range(*FE_OFFSET_RANGE, FE_OFFSET_STEP):
                await_set_stabilized(dev.set_frontend_offset, dev.get_frontend_offset, offset, 0.1, 1, 0.1)
                time.sleep(0.2)
                temp = dev.get_cold_plate_temp()
                voltage = dev.get_voltage()
                offset = dev.get_frontend_offset()
                fe_output = dev.get_frontend_output_voltage()
                measurement = [target_op_temp, channel.name, target_op_voltage, temp, voltage, offset, fe_output]
                logger.info(measurement)
                with open(f"offset_output_relation_{timestamp}.feo.tsv", "a", newline="") as file:
                    writer = csv.writer(file, delimiter='\t')
                    writer.writerows([measurement])

# %%
