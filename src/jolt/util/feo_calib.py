# -*- coding: utf-8 -*-
'''
Module to calibrate the offset of the Jolt front-end board.

Created on 12 March 2025
@author: Tim Moerkerken
Copyright © 2025 Tim Moerkerken, Delmic

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
version 2 as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, see http://www.gnu.org/licenses/.
'''

from jolt.util.measurement import (
                                    repeated_get,
                                    await_set,
                                    await_set_stabilized,
                                  )

from jolt.driver.joltcb import Channel, JOLTComputerBoard
from jolt.util.array import arange
from typing import List, Tuple, Optional
import logging
import statistics
from datetime import datetime, timedelta
import csv
import time
from appdirs import AppDirs
from pathlib import Path
from threading import Event
from typing import Union

logging.basicConfig(format='%(asctime)s %(module)s %(levelname)s %(message)s', level=logging.DEBUG)

CHANNELS = [Channel.RED, Channel.BLUE, Channel.GREEN, Channel.PANCHROMATIC]
TARGET_OP_TEMPS = [25]
FE_OFFSET_RANGE = (0, 1023)

OFFSET_LOOKBACK_VALUE = 3
STOP_EVENT_STRING = "ABORT"


def find_zero_offset_binary(dev, input_range: Tuple, stop_event: Event = None) -> Union[int, str]:
    """
    Optimization function to find the minimum offset that results in a 0 V output voltage.

    :param dev: the computer board driver class.
    :param input_range: the offset search space, (min, max), unitless.
    :param stop_event: a handle to stop the calibration process during a run.
    :return: the optimal offset within provided input range. Returns the string 'aborted' when cancelled during run.
    """
    min_offset = input_range[0]
    max_offset = input_range[1]

    while True:
        if stop_event is not None and stop_event.is_set():
            return STOP_EVENT_STRING

        if min_offset == max_offset:
            logging.warning("Was not able to normally converge within range")
            return max_offset

        input_offset_value = int(statistics.mean([min_offset, max_offset]))

        # Since our method looks back to confirm the found offset is correct, we have to abort when the offset would
        # become negative.
        if input_offset_value <= OFFSET_LOOKBACK_VALUE:
            return

        await_set_stabilized(dev.set_frontend_offset, dev.get_frontend_offset, input_offset_value, tolerance=0.1)
        # Wait a little, since the output voltage takes time to settle
        time.sleep(0.2)
        v_output_array = repeated_get(dev.get_frontend_output_voltage, repeats=5, interval=0.03)
        v_output = statistics.median(v_output_array)
        if v_output == 0:
            # We measure no significant voltage, so we are somewhere higher than the optimal offset

            # Output (V)
            #    |
            # Vm |
            #    |
            #    |⟍     →            ←
            #    |  ⟍   →            ←
            #    |    ⟍ →            ←
            #    |_____ ⟍____________
            #    0                  1023
            #    Offset

            # Check if we are close enough to the optimal value by looking back a little
            # Not too little, for a bit of robustness against noise.
            input_offset_value_convergence_check = input_offset_value - OFFSET_LOOKBACK_VALUE
            await_set_stabilized(
                dev.set_frontend_offset, dev.get_frontend_offset, input_offset_value_convergence_check, tolerance=0.1)
            # Add some settle time
            time.sleep(0.2)
            v_convergence_array = repeated_get(dev.get_frontend_output_voltage, repeats=5, interval=0.03)
            # Check if more significant signal than not is measured
            if statistics.median(v_convergence_array) > 0:
                # We are now here, which is where we can stop

                # Output (V)
                #    |
                # Vm |
                #    |
                #    |⟍
                #    |  ⟍    |
                #    |    ⟍  |
                #    |_____ ⟍↓__________
                #    0                  1023
                #    Offset
                min_offset = input_offset_value  # For following operating voltages
                return  input_offset_value
            elif v_output < 0:
                logging.error(f"Negative output voltage detected. \nPlease check the hardware for defects.")
                raise ValueError(f"Negative output voltage detected ({v_output} V)")
            else:
                # Apparently we are still somewhere higher than the optimum

                # Output (V)
                #    |
                # Vm |
                #    |
                #    |⟍
                #    |  ⟍            |
                #    |    ⟍          |
                #    |_____ ⟍________↓___
                #    0                  1023
                #    Offset
                # Set the max offset to the current value
                max_offset = input_offset_value
        elif v_output > 0:
            # We are now somewhere here, so we need to go higher

            # Output (V)
            #    |
            # Vm |
            #    |
            #    |⟍   |
            #    |  ⟍ ↓
            #    |    ⟍
            #    |_____ ⟍__________
            #    0                  1023
            #    Offset
            min_offset = input_offset_value
        elif v_output < 0:
            logging.error(f"Negative output voltage detected. \nPlease check the hardware for defects.")
            raise ValueError(f"Negative output voltage detected ({v_output} V)")


def find_initial_fe_offset(dev, stop_event: Event = None):
    """
    Optimization method to find the minimum offset that results in a 0 V output voltage.

    :param dev: the computer board driver class.
    :param stop_event: a handle to stop the calibration process during a run.
    :return: the optimal initial offset. Returns the string 'aborted' when cancelled during run.
    """
    fe_offset = None
    # Finding the initial point is critical, so keep attempting until found.
    # The starting operating voltage is the least noisy, so ideally there is only
    # one attempt needed.
    attempts = 0
    while not fe_offset:
        if attempts >= 5:
            logging.error("Was not able to find initial offset. "
                        "Skipping entire channel. \n"
                        "Please check the hardware for defects.")
            break
        logging.debug(f"Attempt {attempts + 1} to find initial offset")
        attempts += 1
        fe_offset = find_zero_offset_binary(dev, FE_OFFSET_RANGE, stop_event)
        if fe_offset == STOP_EVENT_STRING:
            return fe_offset

    return fe_offset


def find_subsequent_fe_offset(dev, fe_offset_initial, previous_op_voltage_offset_gap, stop_event: Event = None):
    """
    Method to find subsequent front-end offset that results in a 0 V output voltage in an optimized manner.
    The optimizations use the following assumptions:
    - The minimum offset that minimizes the output voltage always increases with increasing operating voltage.
        As an example: if we find an offset of 500 for the first operating voltage, the next one should be 500 or more.
    - The difference between offsets is increasing for increasing operating voltage
        As an example: if an offset of 500 is found at 35 V, and an offset of 550 at 36 V, we expect an offset of at
        least +50 at 37 V. This method will now use the previous offset plus a delta based on the previously measured
        offset difference.

    NOTE: The binary method can also work for these voltages, but it was found to be a bit more affected
    by noise (sometimes not converging) and therefore slower.

    :param dev: the computer board driver class.
    :param fe_offset_initial: the initial front-end offset value to start the search with.
    :param previous_op_voltage_offset_gap: the offset difference between found front-end offset values for
        previously measured operating voltages.
    :param stop_event: a handle to stop the calibration process during a run.
    :return: the optimal initial offset. Returns the string 'aborted' when cancelled during run.
    """
    # When there is an offset difference known from the previous operating voltages, use it to start looking a bit
    # further for the offset. When this difference is small, ignore it, since noise can dominate at this stage, and we
    # might miss the optimal offset. We only go as far as 70% of the previous difference, again, to not overshoot due
    # to earlier measured noise.
    initial_shift = 0 if previous_op_voltage_offset_gap < 10 else int(previous_op_voltage_offset_gap * 0.7)
    offset_candidate = fe_offset_initial + initial_shift
    # From this initial candidate, the voltage will incrementally be increased until no significant voltage is found.
    while True:
        if stop_event is not None and stop_event.is_set():
            return STOP_EVENT_STRING
        if offset_candidate >= FE_OFFSET_RANGE[1]:
            logging.warning(f"Was not able to converge within range")
            return FE_OFFSET_RANGE[1]
        await_set_stabilized(
            dev.set_frontend_offset, dev.get_frontend_offset, offset_candidate, tolerance=0.1)
        # Settle
        time.sleep(0.2)
        v_output_array = repeated_get(dev.get_frontend_output_voltage, repeats=5, interval=0.03)
        # When no significant voltage is found, assume optimal offset is reached
        v_output_median = statistics.median(v_output_array)
        if v_output_median == 0:
            return offset_candidate
        elif v_output_median < 0:
            logging.error(f"Negative output voltage detected. \nPlease check the hardware for defects.")
            raise ValueError(f"Negative output voltage detected ({v_output_median} V)")

        # The was no convergence yet, so keep going further

        # Output (V)
        #    |
        # Vm |
        #    |
        #    |⟍   | →
        #    |  ⟍ ↓ →
        #    |    ⟍
        #    |_____ ⟍__________
        #    0                  1023
        #    Offset

        # Since the offset difference seems somewhat exponential, and since the signal becomes more
        # noisy for larger operating voltages, keeping a small step size would be pointless (and slow).
        # Therefore make the step size dependent on the offset difference.
        step_size = max(1, int(previous_op_voltage_offset_gap ** 0.5))
        offset_candidate += step_size


def save_results(dev, calibration_file, target_op_temp, channel_name, target_op_voltage, fe_offset):
    """
    Saves the calibration results to a file.

    :param dev: the computer board driver class.
    :param calibration_file: The path to the file where the calibration data will be saved.
    :param target_op_temp: The target operating temperature in degrees Celsius.
    :param channel_name: The name of the channel being calibrated.
    :param target_op_voltage: The target operating voltage in volts.
    :param fe_offset: The front-end offset value used during calibration.
    :return: None
    :sideeffects: Appends a new row of calibration data to the specified file.
    """
    temp_measured = dev.get_cold_plate_temp()
    voltage_measured = dev.get_voltage()
    # Saving the data
    with open(calibration_file, "a", newline="") as file:
        writer = csv.writer(file, delimiter='\t')
        writer.writerow([
            f"{target_op_temp:.2f}",
            f"{temp_measured:.2f}",
            channel_name,
            f"{target_op_voltage:.2f}",
            f"{voltage_measured:.2f}",
            f"{fe_offset:d}",
        ])


def run(
        dev: JOLTComputerBoard,
        temperatures: List[float] = TARGET_OP_TEMPS,
        channels: List[Channel] = CHANNELS,
        voltage_range: Tuple[float] = None,
        stop_event: Optional[Event] = None,
        calibration_file: Optional[Path] = None,
    ):
    """
    Calibration runner for front-end offset vs. front-end output voltage optimization.

    :param dev: the computer board driver class.
    :param temperatures: a list of operating temperatures, in C.
    :param channels: a list of channel colors.
    :param voltage_range: the operating voltage search space, (min, max, step), in V.
    :param stop_event: a handle to stop the calibration process during a run.
    :param calibration_file: path to output file (extension: feo.tsv). If None, will use a AppDir as a folder, and naming scheme
        based on the front-end board serial number and the datetime. During runtime, this filename will prefixed with _.
        After completion the _ is removed. In this manner, one can differentiate between a passed, a running,
        or an interrupted or failed run.
    :sideeffect: a file on disk (see calibration_file).
    """
    if calibration_file is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

        jolt_sn = dev.get_fe_sn()
        dirs = AppDirs("Jolt", "Delmic")
        data_dir = Path(dirs.user_data_dir)
        data_dir.mkdir(exist_ok=True)
        calibration_file = data_dir / f"jolt-calibration-{jolt_sn}-{timestamp}.feo.tsv"

    calibration_file_tmp = calibration_file.with_name(f"_{calibration_file.name}")

    # Set max gain and zero offset, which is the ideal setting for imaging
    await_set_stabilized(dev.set_gain, dev.get_gain, target=100, tolerance=2)
    await_set_stabilized(dev.set_offset, dev.get_offset, target=0, tolerance=1)

    assert voltage_range is not None
    target_op_voltages = [*arange(*voltage_range), voltage_range[1]]

    with open(calibration_file_tmp, "w", newline="") as file:
        writer = csv.writer(file, delimiter='\t')
        writer.writerow(["temperature_target", "temperature", "channel", "voltage_target", "voltage", "fe_offset"])

    total_combinations = len(temperatures) * len(channels) * len(target_op_voltages)
    current_combination_idx = 0
    total_runtime = 0

    for target_op_temp in temperatures:
        logging.info(f"Switching temperature to: {target_op_temp}")
        await_set_stabilized(dev.set_target_mppc_temp, dev.get_cold_plate_temp, target_op_temp, tolerance=0.1)

        for channel in channels:
            logging.info(f"Switching channel to: {channel}")
            await_set(dev.set_channel, dev.get_channel, channel)

            # Per channel, keep track of the offset difference between operating voltages
            previous_op_voltage_offset_gap = 0
            for i, target_op_voltage in enumerate(target_op_voltages):
                start_time = time.time()
                logging.info(f"Switching operating voltage to: {target_op_voltage}")
                await_set_stabilized(dev.adjust_voltage, dev.get_voltage, target_op_voltage, tolerance=0.1)

                # For the first operating voltage, we want to do an exhaustive search
                if i == 0:
                    fe_offset = find_initial_fe_offset(dev, stop_event)

                    # If user canceled, or if no initial value was found, stop the algorithm.
                    if fe_offset in [STOP_EVENT_STRING, None]:
                        return

                # For the subsequent operating voltages, an optimized approach is used.
                elif i > 0:
                    previous_fe_offset = fe_offset
                    fe_offset = find_subsequent_fe_offset(dev, previous_fe_offset, previous_op_voltage_offset_gap, stop_event)

                    if fe_offset == STOP_EVENT_STRING:
                        return

                    previous_op_voltage_offset_gap = fe_offset - previous_fe_offset

                logging.info(f"Converged: {fe_offset} offset")
                # Saving results to tsv file on disk
                save_results(dev, calibration_file_tmp, target_op_temp, channel.name, target_op_voltage, fe_offset)

                # Time estimation logging
                runtime = time.time() - start_time
                current_combination_idx += 1
                total_runtime += runtime
                seconds_left = total_runtime * (total_combinations / current_combination_idx - 1)
                hours, minutes, seconds = str(timedelta(seconds=total_runtime)).split(":")
                logging.info(f"Total runtime: {hours}h {minutes}m {int(float(seconds))}s")
                hours, minutes, seconds = str(timedelta(seconds=seconds_left)).split(":")
                logging.info(f"Estimated time left: {hours}h {minutes}m {int(float(seconds))}s")

    # Remove the _ prefix after completion
    calibration_file_tmp.rename(calibration_file)
