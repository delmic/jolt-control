#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on 5 Mar 2025

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


import logging
import os
import tempfile
import unittest
import threading
import csv
import time
from pathlib import Path
from jolt.driver.joltcb import JOLTComputerBoard, Channel
from jolt.util import feo_calib

logging.getLogger().setLevel(logging.DEBUG)
TEST_NOHW = (os.environ.get("TEST_NOHW", "0") != "0")  # Default to Hw testing


class TestCalibration(unittest.TestCase):
    """
    Tests the Jolt computer board driver.
    """

    @classmethod
    def setUpClass(cls):
        cls.jolt = JOLTComputerBoard(simulated=TEST_NOHW)

    @classmethod
    def setUp(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.jolt.terminate()

    @classmethod
    def tearDown(cls):
        cls.tmpdir.cleanup()

    def test_calibration_abort(self):
        stop_event = threading.Event()
        with self.tmpdir as tmpdir:
            tmp_file = Path(tmpdir) / "calibration.feo.tsv"
            self.calibration_thread = threading.Thread(
                target=feo_calib.run,
                kwargs=dict(
                    dev=self.jolt,
                    calibration_file=tmp_file,
                    stop_event=stop_event,
                    voltage_range=(30, 37, 1),
                )
            )
            self.calibration_thread.start()
            # Stop the running calibration preemptively.
            # Assert the creation of the calibration file. Running calibration files are prefixed with _.
            time.sleep(2)
            stop_event.set()
            self.calibration_thread.join()
            # The final file should not be present
            self.assertFalse(tmp_file.exists())
            # Check if the uncompleted file is present
            tmp_file_running = tmp_file.with_name(f"_{tmp_file.name}")
            self.assertTrue(tmp_file_running.exists())

    def test_calibration_run(self):
        completed_event = threading.Event()
        with self.tmpdir as tmpdir:
            tmp_file = Path(tmpdir) / "calibration.feo.tsv"

            def _calibrate():
                feo_calib.run(
                    dev=self.jolt,
                    temperatures=[25],
                    channels=[Channel.GREEN],
                    voltage_range=(30, 37, 1),
                    calibration_file=tmp_file,
                )
                completed_event.set()

            self.calibration_thread = threading.Thread(target=_calibrate)
            self.calibration_thread.start()

            # Poll for completion
            while not completed_event.is_set():
                time.sleep(1)
            # Check if the completed calibration file exists
            self.assertTrue(tmp_file.exists())

            # Now check qualitatively
            calibration = []
            with open(tmp_file, "r") as fp:
                reader = csv.DictReader(fp, delimiter="\t")
                for row in reader:
                    calibration.append(row)

            def _ideal_offset(voltage):
                # Must be in sync with driver simulator function (simulate_frontend_output_voltage)
                return (-0.002653 * voltage - 0.029203) / -0.0001640

            for i, calibration_entry in enumerate(calibration):
                # Voltages are increasing since calibration was sorted
                voltage_target = float(calibration_entry["voltage_target"])
                fe_offset = int(calibration_entry["fe_offset"])
                self.assertAlmostEqual(fe_offset, _ideal_offset(voltage_target), delta=5)

if __name__ == "__main__":
    unittest.main()
