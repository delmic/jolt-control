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
import time
import unittest
from unittest.case import skip
from jolt.driver.joltcb import JOLTComputerBoard, JOLTSimulator
from jolt.gui.jolt_app import JoltApp

logging.getLogger().setLevel(logging.DEBUG)

# TODO: testcases not working yet

class TestSimulator(JOLTSimulator):
    """
    Removes randomness from simulator for testing purposes
    """
    def _modify_pressure(self):
        pass
    
    def _modify_temperature(self):
        pass

class TestDriver(JOLTComputerBoard):
    """
    Uses TestSimulator
    """
    def _find_device(self, baudrate=115200, simulated=True):
        return TestSimulator(1)
 
# @skip("skip")
class JoltAppTest(unittest.TestCase):
    """
    Tests the Jolt application
    """
 
    @classmethod
    def setUpClass(cls):
         
        cls.app = JoltApp(simulated=True)
        time.sleep(1)
 
    @classmethod
    def tearDownClass(cls):
        #cls.app.MainLoop()
        cls.app.Destroy()
 
    def test_widget_enabling(self):
        setting_ctrls = {self.app.channel_ctrl, self.app.spinctrl_gain, self.app.spinctrl_offset,
                         self.app.slider_gain, self.app.slider_offset}
        # Use different simulator without randomness 
        self.app.dev = TestDriver()
        self.app.refresh()
        # Everything disabled on start, except power button
        self.assertTrue(self.app.ctl_power.IsEnabled())
        self.assertFalse(self.app.ctl_hv.IsEnabled())
        for c in setting_ctrls:
            self.assertFalse(c.IsEnabled())

        # Power button disabled if pressure or hot plate temperature too high
        self.app.dev._serial.vacuum_pressure = 1000
        time.sleep(1)
        self.assertFalse(self.app.ctl_power.IsEnabled())

        # Debug mode: all enabled, even if pressure too high
        self.app.debug_mode = True
        time.sleep(1)
        self.assertFalse(self.app.ctl_power.IsEnabled())
         
        # Back to normal mode: allow turning off power (button not disabled if power is on)
        self.app.debug_mode = False
        self.assertTrue(self.app.ctl_power.IsEnabled())
    
        # disable power button after power is turned off (pressure is still too high)
        self.app.ctl_power = False
        self.assertFalse(self.app.ctl_power.IsEnabled())

        # Set pressure back to normal --> power button should be enabled again
        self.dev._serial.vacuum_pressure = 5
        self.assertFalse(self.app.ctl_power.IsEnabled())
 
    def test_power_off(self):
        # if pressure is too high --> power off (if persistent for set time)

        # same if temperature is not at target temperature
        pass
 
    def test_config_loading(self):
        # check if the configuration is saved to the ini file and read back correctly
        pass
     
    def test_power(self):
        # Test if temperature actually changes
        pass

    def test_voltage_ctrl(self):
        # When voltage button off --> display previous value, but greyed out (instead of 0)

        # When voltage is on --> display actual value, *not* greyed out
        pass
