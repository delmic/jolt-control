#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on 10 Mar 2020

Copyright © 2020 Philip Winkler, Delmic

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
import unittest
from unittest.case import skip
from jolt.driver.joltcb import JOLTComputerBoard

logging.getLogger().setLevel(logging.DEBUG)
TEST_NOHW = 1#(os.environ.get("TEST_NOHW", 0) != 0)  # Default to Hw testing


# @skip("skip")
class TestDriver(unittest.TestCase):
    """
    Tests the Jolt computer board driver.
    """

    @classmethod
    def setUpClass(cls):
        cls.jolt = JOLTComputerBoard(simulated=TEST_NOHW)

    @classmethod
    def tearDownClass(cls):
        cls.jolt.terminate()

    def test_settings(self):
        # Voltage
        self.jolt.set_voltage(20)
        vol = self.jolt.get_voltage()
        self.assertEqual(vol, 20)

        # Gain
        self.jolt.set_gain(50)
        gain = self.jolt.get_gain()
        self.assertEqual(gain, 50)

        # Offset
        self.jolt.set_offset(99)
        offset = self.jolt.get_offset()
        self.assertAlmostEqual(offset, 99, places=1)

        # Frontend offset
        self.jolt.set_frontend_offset(4000)
        offset = self.jolt.get_frontend_offset()
        self.assertEqual(offset, 4000)


if __name__ == "__main__":
    unittest.main()
