#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on 1 Oct 2019

Copyright © 2017-2018 Anders Muskens, Philip Winkler, Delmic

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
import time
import unittest
from unittest.case import skip
from jolt.driver.frontend import JOLT

logging.getLogger().setLevel(logging.DEBUG)
TEST_NOHW = 1#(os.environ.get("TEST_NOHW", 0) != 0)  # Default to Hw testing


# @skip("skip")
class TestSEM(unittest.TestCase):
    """
    Tests which can share one SEM device
    """

    @classmethod
    def setUpClass(cls):
        cls.jolt = JOLT(simulated=TEST_NOHW)

    @classmethod
    def tearDownClass(cls):
        cls.jolt.terminate()

    def test_voltage(self):
        self.jolt.set_voltage(20)
        vol = self.jolt.get_voltage()
        self.assertEqual(20, vol)


if __name__ == "__main__":
    unittest.main()
