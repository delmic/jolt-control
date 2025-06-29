#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on 30 September 2019
@author: Anders Muskens, Philip Winkler
Copyright © 2019-2021 Anders Muskens, Philip Winkler, Delmic

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

from appdirs import AppDirs
import configparser
from jolt import driver
import jolt
from jolt.gui import xmlh
from jolt.util import log, call_in_wx_main, feo_calib
from jolt.util.math import argmin, linear_regression
import logging
from logging.handlers import RotatingFileHandler
import os
from packaging.version import Version
from pathlib import Path
import sys
import threading
import time
import traceback
import warnings
from wx import xrc
import wx
import wx.adv
from pkg_resources import resource_filename, resource_stream
import csv

# Start simulator if environment variable is set
TEST_NOHW = (os.environ.get("TEST_NOHW", "0") != "0")  # Default to Hw testing

# Set up logging
logging.basicConfig(format='%(asctime)s %(module)s %(levelname)s %(message)s', level=logging.DEBUG)

POLL_INTERVAL = 1.0  # seconds
SAVE_CONFIG = True  # save configuration before closing
STR2CHANNEL = {
    "R": driver.Channel.RED,
    "G": driver.Channel.GREEN,
    "B": driver.Channel.BLUE,
    "Pan": driver.Channel.PANCHROMATIC,
    "OFF": driver.Channel.NONE,
}
CHANNEL2STR = {
    driver.Channel.RED: "R",
    driver.Channel.GREEN: "G",
    driver.Channel.BLUE: "B",
    driver.Channel.PANCHROMATIC: "Pan",
    driver.Channel.NONE: "OFF",
}

MPPC_TEMP_POWER_OFF = 24  # degrees in °C
MPPC_TEMP_DEBUG = 25   # degrees in °C
MPPC_TEMP_POWER_ON = 0  # degrees in °C
MPPC_TEMP_REL = (-1, 1)  # temperature range, relative to the target temperature, in °C


class JoltApp(wx.App):
    """
    The Jolt Control Window Application
    """

    def __init__(self, simulated=TEST_NOHW):
        """
        Constructor
        :param simulated: True if the Jolt driver should be a simulator
        """
        self.simulated = simulated
        self.debug_mode = False
        self.should_stop_polling = threading.Event()  # stop polling thread if set
        self.should_stop_calibration = threading.Event()  # stop calibration thread if set
        self.warnings = set()
        self.error_codes = set()
        self.attrs_to_watch = {}  # empty dict

        # Load configuration and logging files, create directories if they don't exist
        self.dirs = AppDirs("Jolt", "Delmic")
        if not os.path.isdir(self.dirs.user_log_dir):
            os.makedirs(self.dirs.user_log_dir)
        log_file = os.path.join(self.dirs.user_log_dir, 'jolt.log')  # C:\Users\<name>\AppData\Local\Delmic\Jolt\Logs
        self.init_file_logger(log_file, logging.DEBUG)

        logging.info("Software version: %s", jolt.__version__)
        logging.info("Python version: %d.%d", sys.version_info[0], sys.version_info[1])

        self.config_file = os.path.join(self.dirs.user_data_dir, 'jolt.ini')
        if not os.path.isdir(self.dirs.user_data_dir):
            os.makedirs(self.dirs.user_data_dir)

        # Start driver
        try:
            self.dev = driver.JOLTComputerBoard(simulated)
            self.startup_error = False
        except IOError as ex:
            self.startup_error = True
            super().__init__(self)

            dlg = wx.MessageDialog(
                None,
                "Connection to Jolt failed. Make sure the hardware is connected and turned on and restart the application",
                'Info', wx.OK | wx.ICON_INFORMATION
            )

            if dlg.ShowModal() == wx.ID_OK:
                dlg.Destroy()
                self.dialog.Close()
                # The compiled Windows app has troubles nicely shutting down, therefore explicitly force it to stop.
                sys.exit(0)
                return
        except Exception as ex:
            logging.error("Jolt failed to start: %s", ex)
            sys.exit(0)
            return

        self.config = None
        # Initialize values
        self.voltage, self.gain, self.offset, self.channel, fe_offset, self.ambient = self.load_config(section='DEFAULT')
        # ambient == True means that the device should only be cooling down
        # to 15°C and the pressure is left unchecked.
        self.mppc_temp, self.heat_sink_temp, self.vacuum_pressure, self.output = (0, 0, 0, 0)
        # Get the target mppc temperature from the configuration file if provided,
        # otherwise use the default one.
        self.target_mppc_temp = self.load_config(section='TARGET')
        # Get the threshold values from the configuration file if provided, otherwise use the default ones.
        # TODO: saferange_mppc_current is unused => use it too... but comparing with which reading?
        self.mppc_temp_rel, self.saferange_sink_temp, self.saferange_mppc_current, self.saferange_vacuum_pressure = \
            self.load_config(section='SAFERANGE')
        self.differential, self.rgb_filter = self.load_config(section='SIGNAL')

        self.calibration_compatible = self.dev.version >= Version("2.0")
        self.calibration_file, self.calibration_temps, self.calibration_voltage_range = self.load_config(section='CALIBRATION')
        if not self.rgb_filter:
            # Force the channel to panchromatic. The channel selection will be hidden.
            self.channel = "Pan"
        self.error = 8  # 8 means no error
        self.target_temp = 24
        self.voltage_gui = 0  # Initialize on zero for now
        self.fe_output = 0
        self.power = False
        self.hv = False
        self.calibrating = False

        # Initialize wx components
        super().__init__(redirect=False)
        self.init_dialog()

        # Get information from hardware for the log
        logging.info("Backend firmware: %s", self.dev.get_be_fw_version())
        logging.info("Backend hardware: %s", self.dev.get_be_hw_version())
        logging.info("Backend serial number: %s", self.dev.get_be_sn())
        logging.info("Frontend firmware: %s", self.dev.get_fe_fw_version())
        logging.info("Frontend hardware: %s", self.dev.get_fe_hw_version())
        logging.info("Frontend serial number: %s", self.dev.get_fe_sn())

        # Check frontend board connection
        if "Unknown" in self.dev.get_fe_fw_version():
            dlg = wx.MessageBox("Problem connecting to the frontend board. Verify that the control box is connected " +
                                "properly and cycle the power. It this warning persists, please contact Delmic support.",
                                'Info', wx.OK)
            sys.exit(0)
            return

        # Set hw output to either single-ended or differential
        self.dev.set_signal_type(not self.differential)
        # Write gain, offset, channel parameters to device
        self.dev.set_gain(self.gain)
        self.dev.set_offset(self.offset)
        self.dev.set_channel(STR2CHANNEL[self.channel])
        if fe_offset is not None:
            old_fe_offset = self.dev.get_frontend_offset()
            logging.debug("Changing front-end offset from %s to %s", old_fe_offset, fe_offset)
            self.dev.set_frontend_offset(fe_offset)

        # Override XRC default values, since they are static and do not work for different JOLT versions
        self.spinctrl_voltage.SetMin(0)  # For now, now differentiation for the lower bound
        self.spinctrl_voltage.SetMax(self.dev.voltage_range[1])
        self.voltage_gui = min(self.voltage, self.dev.voltage_range[1])
        self.spinctrl_voltage.SetValue(self.voltage_gui)

        # Start the thread for polling
        self.polling_thread = threading.Thread(target=self.do_poll)
        self.polling_thread.start()

        # Initialize calibration thread
        self.calibration_thread = threading.Thread(target=self.calibrate)

        # Calibration is only available for JOLT V2 and up
        if self.calibration_compatible:
            self.load_calibration_file()  # Populates self.valid_calibration and self.calibration_table
            if not self.valid_calibration:
                no_calibration_dialog_text = "No (valid) calibration file available. The data will be unreliable, contact Delmic support (support@delmic.com) to obtain the calibration file. Use the JOLT anyway?"
                dlg = wx.MessageDialog(None, no_calibration_dialog_text, 'Warning', wx.OK | wx.CANCEL | wx.ICON_WARNING)
                dlg.SetOKCancelLabels("Continue", "Quit")
                result = dlg.ShowModal()
                if result == wx.ID_CANCEL:
                    self.dialog.Close()
            else:
                logging.info(f"Matching calibration file found: {self.calibration_file}")

        # Don't write voltage to device yet, but show value in the gui
        self.spinctrl_voltage.SetForegroundColour((211, 211, 211))
        # Set fe offset controls to visible first and then immediately toggle off,
        # so it calculates the sizes correctly.
        self.fe_offset_visible = True
        self.on_fe_offset_toggle(None)
        self.refresh()

    def load_calibration_file(self):
        """
        Attempts to load calibration file. If successful, the file is loaded and stored as a table.
        If file is not present or incomplete, it is not a valid calibration.

        :sideeffect self.calibration_table: List[dict] or None, rows of the calibration table containing a dict with
            structure <measurement>: <value>. For example: [{"temperature_target": "20", ...}, ...].
        :sideeffect self.valid_calibration: Bool, whether the calibration is successfully loaded and whether it is
            complete and compatible with the current settings.
        """
        # If no manually selected calibration was found, pick the latest one available on the system
        if (self.calibration_file and not Path(self.calibration_file).exists()):
            logging.error(f"Provided calibration file: {self.calibration_file}, but it does not exist")
        else:
            calibration_files = sorted(Path(self.dirs.user_data_dir).glob(
                f"jolt-calibration-{self.dev.get_fe_sn()}*feo.tsv"))
            if len(calibration_files):
                self.calibration_file = calibration_files[-1]

        self.calibration_table = None
        self.valid_calibration = False
        if self.calibration_file:
            try:
                dtype_lookup = {
                    "temperature_target": float,
                    "temperature": float,
                    "voltage_target": float,
                    "voltage": float,
                    "fe_offset": int,
                    "channel": lambda c: driver.Channel[c]
                }
                with open(self.calibration_file, "r") as file:
                    reader = csv.DictReader(file, delimiter="\t")
                    # In csv everything is a string, so convert to the appropriate dtypes.
                    self.calibration_table = [{k: dtype_lookup[k](v) for k, v in row.items()} for row in reader]
                    # Furthermore, go over the list one more time to filter for mppc temperature
                    self.calibration_table = list(filter(
                        lambda x : x["temperature_target"] == self.target_mppc_temp,
                        self.calibration_table
                    ))

            except Exception as ex:
                logging.error(f"Loading {self.calibration_file} failed: {ex}")
        if self.calibration_table:
            expected_channel_count = 4 if self.rgb_filter else 1
            channels_in_calibration_file = set([r["channel"] for r in self.calibration_table])
            self.valid_calibration = len(channels_in_calibration_file) == expected_channel_count

            if not self.valid_calibration:
                logging.error(f"Calibration file found: {self.calibration_file}, but does not contain data for all the channels")

    def load_config(self, section):
        """
        Reads configuration file
        section (str): the part of the configuration file to read
        :returns:
        if section is "DEFAULT":
            (float, float, float, str, int | None, bool): voltage, gain, offset,
                channel, font-end offset, ambient
        if section 'TARGET':
            (float): mppc_temp
        if section 'SAFERANGE':
            (tuple, tuple, tuple, tuple): mppc_temp_rel, heatsink_temp, mppc_current, vacuum_pressure
        if section is 'SIGNAL':
           (bool, bool): differential, rgb_filter
        if section is 'CALIBRATION':
           (str, tuple, tuple): calibration_file, calibration_temps, calibration_voltage_range
        """
        if self.config is None:
            self.config = configparser.ConfigParser(converters={'tuple': self.get_tuple})
            logging.debug("Reading configuration file %s", self.config_file)
            self.config.read(self.config_file)
        if section == 'DEFAULT':
            try:
                voltage = self.config.getfloat('DEFAULT', 'voltage', fallback=0.0)
                gain = self.config.getfloat('DEFAULT', 'gain', fallback=0.0)
                offset = self.config.getfloat('DEFAULT', 'offset', fallback=0.0)
                channel = self.config.get('DEFAULT', 'channel', fallback="R")
                fe_offset = self.config.getint('DEFAULT', 'front_offset', fallback=None)
                # TODO: ambient is not really needed, as it could be replicated by
                # setting the target temperature to 15 and the pressure range to a very wide range.
                ambient = self.config.get('DEFAULT', 'ambient', fallback=False)
            except Exception as ex:
                logging.error("Invalid given values, falling back to default values, ex: %s", ex)
                voltage, gain, offset, channel, ambient = (0.0, 0.0, 0.0, "R", False)
            if channel not in ["R", "G", "B", "Pan"]:
                channel = "R"
            return voltage, gain, offset, channel, fe_offset, ambient
        elif section == 'TARGET':
            try:
                mppc_temp = self.config.getint('TARGET', 'mppc_temp', fallback=MPPC_TEMP_POWER_ON)
            except Exception as ex:
                logging.error("Invalid TARGET mppc temperature, an integer expected, "
                              "falling back to default values, ex: %s", ex)
                mppc_temp = MPPC_TEMP_POWER_ON
            return mppc_temp
        elif section == 'SAFERANGE':
            try:
                mppc_temp_rel = self.config.gettuple('SAFERANGE', 'mppc_temp_rel', fallback=MPPC_TEMP_REL)
                heatsink_temp = self.config.gettuple('SAFERANGE', 'heatsink_temp',
                                                     fallback=driver.SAFERANGE_HEATSINK_TEMP)
                mppc_current = self.config.gettuple('SAFERANGE', 'mppc_current',
                                                    fallback=driver.SAFERANGE_MPCC_CURRENT)
                vacuum_pressure = self.config.gettuple('SAFERANGE', 'vacuum_pressure',
                                                       fallback=driver.SAFERANGE_VACUUM_PRESSURE)
            except Exception as ex:
                logging.error("Invalid SAFERANGE values, tuples of integers expected, "
                              "falling back to default values, ex: %s", ex)
                mppc_temp_rel = MPPC_TEMP_REL
                heatsink_temp = driver.SAFERANGE_HEATSINK_TEMP
                mppc_current = driver.SAFERANGE_MPCC_CURRENT
                vacuum_pressure = driver.SAFERANGE_VACUUM_PRESSURE
            return mppc_temp_rel, heatsink_temp, mppc_current, vacuum_pressure
        elif section == 'SIGNAL':
            try:
                differential = self.config.getboolean('SIGNAL', 'differential', fallback=False)
                rgb_filter = self.config.getboolean('SIGNAL', 'rgb_filter', fallback=True)
            except Exception as ex:
                logging.error("Invalid SIGNAL value, falling back to default values, ex: %s", ex)
                differential = False
                rgb_filter = True
            return differential, rgb_filter
        elif section == 'CALIBRATION':
            calibration_voltage_range_fallback = (*self.dev.voltage_range, 1)
            try:
                calibration_file = self.config.get('CALIBRATION', 'calibration_file', fallback=None)
                calibration_temps = self.config.gettuple('CALIBRATION', 'calibration_temps', fallback=None)
                calibration_voltage_range = self.config.gettuple('CALIBRATION', 'calibration_voltage_range', fallback=None)

                mppc_temp = self.config.getint('TARGET', 'mppc_temp', fallback=MPPC_TEMP_POWER_ON)
                calibration_temps_fallback = (mppc_temp, )
                if calibration_temps is None:
                    logging.warning("No calibration temperatures provided, will use 20 C now")
                    calibration_temps = calibration_temps_fallback

                if calibration_voltage_range is None and self.calibration_compatible:
                    logging.warning(f"No calibration voltage range provided, will use {calibration_voltage_range_fallback}")
                    calibration_voltage_range = calibration_voltage_range_fallback
            except Exception as ex:
                logging.error("Invalid CALIBRATION value, falling back to default values, ex: %s", ex)
                calibration_file = None
                calibration_temps = calibration_temps_fallback
                calibration_voltage_range = calibration_voltage_range_fallback

            return calibration_file, calibration_temps, calibration_voltage_range
        else:
            raise ValueError("No available section with name %s in the config file", section)

    def get_tuple(self, option):
        return tuple(int(k.strip()) for k in option[1:-1].split(','))

    def save_config(self):
        """
        Save the configuration to an INI file. This is usually called when the window is closed.
        Note that the 'TARGET' and 'SAFERANGE' sections are not saved on purpose. They should not appear in the
        config file if the user hasn’t explicitly written them. The ini file will contain these 2 sections only
        if they are read from the previous config.read().
        """
        if not SAVE_CONFIG:
            logging.warning("Not saving jolt state.")
            return
        cfgfile = open(self.config_file, 'w')
        self.config.set('DEFAULT', 'voltage', str(self.voltage_gui))
        self.config.set('DEFAULT', 'gain', str(self.gain))
        self.config.set('DEFAULT', 'offset', str(self.offset))
        self.config.set('DEFAULT', 'channel', str(self.channel))
        self.config.write(cfgfile)
        cfgfile.close()

    def init_file_logger(self, log_file, level=logging.DEBUG):
        """
        Initializes the file logger to some nice defaults.
        To be called only once, at the initialisation.
        log_file (str): full path to the log file
        """
        logging.debug("Opening log file %s", log_file)
        # Max 5 log files of 100Mb
        self.fileHandler = RotatingFileHandler(log_file, maxBytes=100 * (2 ** 20), backupCount=5)
        self.fileHandler.setLevel(level)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        self.fileHandler.setFormatter(formatter)

        logging.getLogger().addHandler(self.fileHandler)

    def init_dialog(self):
        """
        Load the XRC GUI and connect all of the GUI controls to their event handlers
        """
        # XRC Loading
        self.res = xrc.XmlResource(resource_filename('jolt.gui', 'jolt_app.xrc'))
        # custom xml handler for wxSpinCtrlDouble, which is not supported officially yet
        self.res.InsertHandler(xmlh.SpinCtrlDoubleXmlHandler())
        self.dialog = self.res.LoadDialog(None, 'ControlWindow')

        # attach the logging to the log text control as a handler
        self.txtbox_log = xrc.XRCCTRL(self.dialog, 'txtbox_log')
        self.textHandler = log.TextFieldHandler()
        self.textHandler.setTextField(self.txtbox_log)
        self.textHandler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        self.textHandler.setFormatter(formatter)

        # attach to the global logger
        logging.getLogger().addHandler(self.textHandler)

        # controls and events:
        # Initialize all of the GUI controls and connect them to events
        self.ctl_power =  xrc.XRCCTRL(self.dialog, 'ctl_power')
        self.ctl_power.Bind(wx.EVT_LEFT_DOWN, self.on_power)
        self.ctl_hv = xrc.XRCCTRL(self.dialog, 'ctl_hv')
        self.ctl_hv.Bind(wx.EVT_LEFT_DOWN, self.on_voltage_button)

        self.btn_auto_bc = xrc.XRCCTRL(self.dialog, 'btn_AutoBC')
        self.dialog.Bind(wx.EVT_BUTTON, self.on_auto_bc, id=xrc.XRCID('btn_AutoBC'))

        # tooltip power
        self.ctl_power.ToolTip = wx.ToolTip("Cooling can only be turned on if pressure is OK")

        # voltage
        self.spinctrl_voltage = xrc.XRCCTRL(self.dialog, 'spn_voltage')

        self.text_voltage = xrc.XRCCTRL(self.dialog, 'text_voltage')
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_voltage_value, id=xrc.XRCID('spn_voltage'))
        self.dialog.Bind(wx.EVT_TEXT_ENTER, self.on_voltage_value, id=xrc.XRCID('spn_voltage'))

        # gain and offsets
        self.text_fe_offset = xrc.XRCCTRL(self.dialog, 'text_fe_offset')
        self.unit_fe_offset = xrc.XRCCTRL(self.dialog, 'unit_fe_offset')
        self.slider_gain = xrc.XRCCTRL(self.dialog, 'slider_gain')
        self.slider_offset = xrc.XRCCTRL(self.dialog, 'slider_offset')
        self.slider_fe_offset = xrc.XRCCTRL(self.dialog, 'slider_fe_offset')
        self.spinctrl_gain = xrc.XRCCTRL(self.dialog, 'spin_gain')
        self.spinctrl_offset = xrc.XRCCTRL(self.dialog, 'spin_offset')
        self.spinctrl_fe_offset = xrc.XRCCTRL(self.dialog, 'spin_fe_offset')
        self.dialog.Bind(wx.EVT_SCROLL, self.on_gain_slider, id=xrc.XRCID('slider_gain'))
        self.dialog.Bind(wx.EVT_SCROLL, self.on_offset_slider, id=xrc.XRCID('slider_offset'))
        self.dialog.Bind(wx.EVT_SCROLL, self.on_fe_offset_slider, id=xrc.XRCID('slider_fe_offset'))
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_gain_spin, id=xrc.XRCID('spin_gain'))
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_offset_spin, id=xrc.XRCID('spin_offset'))
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_fe_offset_spin, id=xrc.XRCID('spin_fe_offset'))
        self.dialog.Bind(wx.EVT_TEXT_ENTER, self.on_gain_spin, id=xrc.XRCID('spin_gain'))
        self.dialog.Bind(wx.EVT_TEXT_ENTER, self.on_offset_spin, id=xrc.XRCID('spin_offset'))
        self.dialog.Bind(wx.EVT_TEXT_ENTER, self.on_fe_offset_spin, id=xrc.XRCID('spin_fe_offset'))

        # channel selection
        self.channel_ctrl = xrc.XRCCTRL(self.dialog, 'radio_channel')
        self.channel_ctrl.SetSelection(0)
        self.dialog.Bind(wx.EVT_RADIOBOX, self.on_radiobox, id=xrc.XRCID('radio_channel'))

        # Hide if panchromatic
        if not self.rgb_filter:
            channel_label = xrc.XRCCTRL(self.dialog, 'm_staticText7')
            self.channel_ctrl.Hide()
            channel_label.Hide()

        # live displays
        self.txtbox_output = xrc.XRCCTRL(self.dialog, 'txtbox_current')
        self.txtbox_MPPCTemp = xrc.XRCCTRL(self.dialog, 'txtbox_MPPCTemp')
        self.txtbox_sinkTemp = xrc.XRCCTRL(self.dialog, 'txtbox_sinkTemp')
        self.txtbox_vacuumPressure = xrc.XRCCTRL(self.dialog, 'txtbox_vacuumPressure')
        self.text_fe_output = xrc.XRCCTRL(self.dialog, 'text_fe_output')
        self.txtbox_fe_output = xrc.XRCCTRL(self.dialog, 'txtbox_fe_output')
        self.unit_fe_output = xrc.XRCCTRL(self.dialog, 'unit_fe_output')

        # log display
        # FIXME: at init, the CollapsiblePane is collapsed but still takes space
        self.btn_viewLog = xrc.XRCCTRL(self.dialog, 'btn_viewLog', wx.CollapsiblePane)
        self.dialog.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.on_collapse_log, id=xrc.XRCID('btn_viewLog'))

        # catch the closing event
        self.dialog.Bind(wx.EVT_CLOSE, self.on_close)

        # Debug mode: allow F5 + "delmic" password to enable all controls
        # Inspection window: Ctrl+I (in debug mode) to show GUI controls
        f5_id = 1
        inspect_id = 2
        calibration_id = 3
        fe_offset_toggle_id = 4
        self.dialog.Bind(wx.EVT_MENU, self.on_f5, id=f5_id)
        self.dialog.Bind(wx.EVT_MENU, self.on_inspect, id=inspect_id)
        self.dialog.Bind(wx.EVT_MENU, self.on_fe_offset_toggle, id=fe_offset_toggle_id)

        accelerators = [
            (wx.ACCEL_NORMAL, wx.WXK_F5, f5_id),
            (wx.ACCEL_CTRL, ord('I'), inspect_id),
            (wx.ACCEL_CTRL, ord('O'), fe_offset_toggle_id),
        ]

        if self.calibration_compatible:
            self.dialog.Bind(wx.EVT_MENU, self.on_calibration, id=calibration_id)
            accelerators.append((wx.ACCEL_CTRL, ord('K'), calibration_id))

        accel_tbl = wx.AcceleratorTable(accelerators)
        self.dialog.SetAcceleratorTable(accel_tbl)
        self.power_label = xrc.XRCCTRL(self.dialog, 'm_staticText16')  # will be updated in debug mode
        self.txtbox_output.SetFocus()  # if focus is None, the f5 event is not captured, so set focus to a textbox

        # Put the version number in the title, and add "Simulator" when it's not connected to the real hardware
        title = "Delmic Jolt%s v%s" % (" Simulator" if self.simulated else "", jolt.__version__)
        self.dialog.SetTitle(title)

        # Load bitmaps
        self.bmp_off = wx.Bitmap(wx.Image(resource_stream('jolt.gui', "img/icon_toggle_off.png")))
        self.bmp_on = wx.Bitmap(wx.Image(resource_stream('jolt.gui', "img/icon_toggle_on.png")))
        self.bmp_icon = wx.Bitmap(wx.Image(resource_stream('jolt.gui', "img/icon_jolt.png")))

        # set icon
        icon = wx.Icon(self.bmp_icon)
        self.dialog.SetIcon(icon)

        self.dialog.Show()

    @call_in_wx_main
    def on_f5(self, event):
        if self.debug_mode:
            self.debug_mode = False
        else:
            passwd = wx.PasswordEntryDialog(None, "Enter Debug Mode", 'Password','',
                                            style=wx.TextEntryDialogStyle)
            ans = passwd.ShowModal()
            if ans == wx.ID_OK:
                entered_password = passwd.GetValue()
                if entered_password == "delmic":
                    self.debug_mode = True
            passwd.Destroy()
        self.refresh()
        event.Skip()

        # Change maximum voltage in debug mode (too high voltage can hurt the system if it's not covered)
        if self.debug_mode:
            self.spinctrl_voltage.SetMax(self.dev.voltage_range[0])  # just enough to get signal
        else:
            self.spinctrl_voltage.SetMax(self.dev.voltage_range[1])  # as usual

    def check_saferange(self, textctrl, val, srange, name, t=None):
        """
        Checks if a value is in the defined safe range and displays it in the corresponding colour
        (green if it's ok, red if it isn't, black if it's still adjusting). If the value is outside
        the range, a system warning will be displayed and the device will be powered off.
        If the current time is specified in the t parameter, there will be a buffer of 1 minute for
        the value to adjust. During this time period, the value will be displayed in black.
        :param textctrl: wx TextCtrl
        :param val: (float) a value
        :param srange: (float tuple) safe range
        :param name: (str) the name of the parameter used in the error message
        :param t (float or None) current time. If specified, the function will only give an error
        if the value persists to be out of range after one minute.
        """
        textctrl.SetForegroundColour(wx.BLACK)
        if srange[0] <= val <= srange[1]:
            textctrl.SetForegroundColour((50, 210, 50))  # somewhat less bright than wx.GREEN
            if name in self.warnings:
                self.warnings.remove(name)  # clear the warning if the error goes away
            if name in self.attrs_to_watch:
                del self.attrs_to_watch[name]
        else:
            if not t:
                textctrl.SetForegroundColour(wx.RED)
                # this way, the warning message is only displayed when the warning first occurs
                if name not in self.warnings and not self.error_codes:  # don't show warning in case of error code, so it doesn't hide it
                    self.warnings.add(name)
                    msg = wx.adv.NotificationMessage("DELMIC JOLT", message="%s is outside of the safe range of operation." % (name,), parent=self.dialog,
                                                     flags=wx.ICON_WARNING)
                    msg.Show()
                # Power off
                if self.power and not self.debug_mode:
                    self.toggle_power()
                logging.warning("%s (%f) is outside of the safe range of operation (%f -> %f).",
                                name, val, srange[0], srange[1])
            elif name not in self.attrs_to_watch:
                # don't complain yet, but take notice
                self.attrs_to_watch[name] = t
            elif time.time() >= self.attrs_to_watch[name] + 60:
                textctrl.SetForegroundColour(wx.RED)
                # this way, the warning message is only displayed when the warning first occurs
                if name not in self.warnings and not self.error_codes: # don't show warning in case of error code, so it doesn't hide it
                    self.warnings.add(name)
                    msg = wx.adv.NotificationMessage("DELMIC JOLT", message="%s is outside of the safe range of operation." % (name,), parent=self.dialog,
                                                     flags=wx.ICON_WARNING)
                    msg.Show()
                # Power off
                if self.power and not self.debug_mode:
                    self.toggle_power()
                logging.warning("%s (%f) is outside of the safe range of operation (%f -> %f).",
                                name, val, srange[0], srange[1])
                del self.attrs_to_watch[name]

    def on_close(self, event):
        if self.calibrating:
            dlg = wx.MessageDialog(None, "Calibration still in progress. Closing aborts the running calibration. Go ahead?", 'Warning', wx.OK | wx.CANCEL | wx.ICON_WARNING)
            dlg.SetOKCancelLabels("Close app", "Continue calibration")
            result = dlg.ShowModal()
            if result == wx.ID_CANCEL:
                return

        # If device is powered on, ask use to power it off first
        if self.power:
            dlg = wx.MessageDialog(None, "Power down the Jolt hardware before closing the application?", 'Notice', wx.OK | wx.CANCEL | wx.ICON_WARNING)
            dlg.SetOKCancelLabels("Power down", "Cancel closing")
            result = dlg.ShowModal()

            if result == wx.ID_OK:
                logging.info("Powering down Jolt...")
                try:
                    self.dev.set_target_mppc_temp(24)
                except:
                    # connection lost, device already turned off
                    dlg = wx.MessageDialog(None, "Failed to power down device, connection lost.", 'Notice',
                                     wx.OK | wx.ICON_WARNING)
                    dlg.ShowModal()
            else:
                return  # Cancel closing

        self.should_stop_polling.set()  # Stop the polling thread
        self.should_stop_calibration.set()  # Stop the polling thread
        if self.polling_thread and self.polling_thread.is_alive():
            self.polling_thread.join()
        if self.calibration_thread and self.calibration_thread.is_alive():
            self.calibration_thread.join()
        self.save_config()  # Save config to INI
        self.dialog.Destroy()
        event.Skip()

    def on_collapse_log(self, event):
        self.dialog.Fit()

    def on_power(self, event):
        self.toggle_power()

    def on_inspect(self, event):
        if self.debug_mode:
            from wx.lib.inspection import InspectionTool
            InspectionTool().Show()

    def calibrate(self):
        logging.info("Calibration started.")
        self.calibrating = True
        feo_calib.run(
            self.dev,
            temperatures=self.calibration_temps,
            voltage_range=self.calibration_voltage_range,
            stop_event=self.should_stop_calibration,
            channels = feo_calib.CHANNELS if self.rgb_filter else [driver.Channel.PANCHROMATIC],
        )
        self.calibrating = False
        logging.info("Calibration ended.")

    @call_in_wx_main
    def on_fe_offset_toggle(self, event):
        elements = [
            # Offset
            self.text_fe_offset,
            self.slider_fe_offset,
            self.spinctrl_fe_offset,
            self.unit_fe_offset,
            # Output
            self.text_fe_output,
            self.txtbox_fe_output,
            self.unit_fe_output,
        ]

        self.fe_offset_visible = not self.fe_offset_visible
        for element in elements:
            element.Show(self.fe_offset_visible)
        self.dialog.Layout()
        self.dialog.Fit()

    def open_log(self):
        if hasattr(self.btn_viewLog, "Collapse"):
            self.btn_viewLog.Collapse(False)
        # On Windows, this element is a button that sadly does not have the Collapse() method.
        # We can still toggle it by simulating a click on the button element in the control element.
        # We only click it when it is not yet open. We use a height heuristic for this.
        elif self.btn_viewLog.GetSize()[1] < 100:
            ui_sim = wx.UIActionSimulator()
            original_pos = wx.GetMousePosition()
            # This is the top left coordinate. The button happens to be right there. The element
            # itself is the entire log, so obtaining the size is not the size of the button, but the log element.
            log_pos = self.btn_viewLog.ScreenPosition
            # Offset the top left coordinate so we end up in the area of the button.
            log_pos = (log_pos[0] + 5, log_pos[1] + 5)
            ui_sim.MouseMove(*log_pos)
            ui_sim.MouseClick()
            # Move back to original position, so we don't really notice this hack during use
            ui_sim.MouseMove(*original_pos)

    @call_in_wx_main
    def on_calibration(self, event):
        if self.debug_mode:
            if not self.calibration_thread.is_alive():
                dlg = wx.MessageDialog(
                    None,
                    "Do you want to calibrate the front-end offset?",
                    'Calibration',
                    wx.YES_NO | wx.ICON_QUESTION
                )
                result = dlg.ShowModal()
                dlg.Destroy()
                if result == wx.ID_YES:
                    self.should_stop_polling.set()
                    self.should_stop_calibration.clear()
                    self.calibration_thread = threading.Thread(target=self.calibrate)
                    self.calibration_thread.start()
                    self.open_log()
                else:
                    logging.info("Calibration canceled.")
            else:
                dlg = wx.MessageDialog(
                    None,
                    "Calibration in progress. Abort?",
                    "Cancel calibration",
                    wx.YES_NO | wx.ICON_QUESTION
                )
                result = dlg.ShowModal()
                dlg.Destroy()
                if result == wx.ID_YES:
                    self.should_stop_calibration.set()
                    self.calibration_thread.join()
                    self.should_stop_polling.clear()
                    self.polling_thread = threading.Thread(target=self.do_poll)
                    self.polling_thread.start()
                    logging.info("Calibration canceled.")
                else:
                    logging.info("Calibration continuing.")

    def toggle_power(self):
        if self.ctl_power.IsEnabled():
            self.power = not self.power
            logging.info("Changed power state to: %s", self.power)
            if self.power:
                if self.debug_mode or self.ambient:
                    self.target_temp = MPPC_TEMP_DEBUG
                else:
                    self.target_temp = self.target_mppc_temp
            else:
                self.target_temp = MPPC_TEMP_POWER_OFF
            self.dev.set_target_mppc_temp(self.target_temp)

        # Turn voltage off if device is not powered on
        if not self.power:
            self.hv = False
            logging.info("Changed voltage state to: %s", self.hv)
            self.dev.set_voltage(0)
            self.spinctrl_voltage.SetForegroundColour((211, 211, 211))
            self.spinctrl_voltage.SetValue(self.voltage_gui)

        self.refresh()

    def on_voltage_button(self, event):
        """
        Enable/disable voltage changes. If disabled, set voltage to 0.
        """
        # Toggle the HV value
        if self.ctl_hv.IsEnabled():
            self.hv = not self.hv
            logging.info("Changed voltage state to: %s", self.hv)

            if self.hv:
                # write parameters to device
                self.dev.adjust_voltage(self.voltage_gui)
                if self.valid_calibration:
                    self.set_matching_calibrated_offset()
                self.spinctrl_voltage.SetForegroundColour(wx.Colour(wx.BLACK))
            else:
                self.dev.set_voltage(0)
                # light grey to show it's not actually set
                self.spinctrl_voltage.SetForegroundColour((211, 211, 211))
        self.refresh()

    def on_auto_bc(self, event):
        raise NotImplementedError()
        # disable gain/offset controls

    def set_matching_calibrated_offset(self):
        # Ignore temperature inaccuracies for now and just use the target to simplify things.
        voltage_dists = {i: abs(r["voltage"] - self.voltage_gui) for i, r in enumerate(self.calibration_table)
            if r["channel"] == STR2CHANNEL[self.channel]}

        # Obtain the two closest calibration points for interpolation
        idx_within_channel_low = argmin(voltage_dists.values())[0]
        idx_within_channel_high = argmin(voltage_dists.values())[1]

        match_idx_low = list(voltage_dists.keys())[idx_within_channel_low]
        match_idx_high = list(voltage_dists.keys())[idx_within_channel_high]

        matching_voltage_low = self.calibration_table[match_idx_low]["voltage_target"]
        matching_voltage_high = self.calibration_table[match_idx_high]["voltage_target"]

        matching_offset_low = self.calibration_table[match_idx_low]["fe_offset"]
        matching_offset_high = self.calibration_table[match_idx_high]["fe_offset"]

        # Interpolate to obtain the matching offset
        slope, intercept = linear_regression([
            (matching_voltage_low, matching_offset_low),
            (matching_voltage_high, matching_offset_high),
        ])

        matching_offset = int(slope * self.voltage_gui + intercept)

        # Clip
        matching_offset = max(0, min(matching_offset, 1023))

        self.dev.set_frontend_offset(matching_offset)
        logging.info(f"Front-end offset is set to {matching_offset} at {self.voltage_gui} V, based on calibration data")
        self.slider_fe_offset.SetValue(matching_offset)
        self.spinctrl_fe_offset.SetValue(matching_offset)

    def on_voltage_value(self, event):
        """
        Set voltage if voltage change enabled, otherwise ignore.
        """
        voltage = float(event.GetString())
        # Safeguard for safe voltage range
        voltage = max(min(voltage, self.dev.voltage_range[1]), 0)
        self.voltage_gui = voltage
        # This makes sure that formatting rules apply and focus is regained.
        # For example: 20 becomes 20.00 if precision is 2 for instance.
        self.spinctrl_voltage.SetValue(voltage)
        if self.hv:
            logging.debug("Changed voltage to %s", self.voltage_gui)
            self.dev.adjust_voltage(self.voltage_gui)
            if self.valid_calibration:
                self.set_matching_calibrated_offset()
        event.Skip()

    def on_radiobox(self, event):
        self.channel = event.GetEventObject().GetStringSelection()
        self.dev.set_channel(STR2CHANNEL[event.GetEventObject().GetStringSelection()])
        logging.debug("Changed channel to %s", event.GetEventObject().GetStringSelection())
        if self.valid_calibration:
            self.set_matching_calibrated_offset()

    def on_gain_slider(self, event):
        gain = event.GetPosition()
        self.spinctrl_gain.SetValue(gain)
        self.dev.set_gain(gain)
        logging.debug("Changed gain to %s", gain)

    def on_offset_slider(self, event):
        offset = event.GetPosition()
        self.spinctrl_offset.SetValue(offset)
        self.dev.set_offset(offset)
        logging.debug("Changed offset to %s", offset)

    def on_fe_offset_slider(self, event):
        offset = event.GetPosition()
        self.spinctrl_fe_offset.SetValue(offset)
        self.dev.set_frontend_offset(offset)
        logging.debug("Changed front-end offset to %s", offset)

    def on_gain_spin(self, event):
        gain = int(float(event.GetString()))
        self.slider_gain.SetValue(gain)
        self.spinctrl_gain.SetValue(gain)
        self.dev.set_gain(gain)
        logging.debug("Changed gain to %s", gain)
        event.Skip()

    def on_offset_spin(self, event):
        offset = round(int(float(event.GetString())))
        self.slider_offset.SetValue(offset)
        self.spinctrl_offset.SetValue(offset)
        self.dev.set_offset(offset)
        logging.debug("Changed offset to %s", offset)
        event.Skip()

    def on_fe_offset_spin(self, event):
        offset = int(float(event.GetString()))
        self.slider_fe_offset.SetValue(offset)
        self.spinctrl_fe_offset.SetValue(offset)
        self.dev.set_frontend_offset(offset)
        logging.debug("Changed front-end offset to %s", offset)
        event.Skip()

    @call_in_wx_main
    def update_controls(self):
        """
        Enable/disable the right controls, set bitmap controls and let the user know if we are in debug mode.
        """
        def disable_bmp(bmp):
            # The bitmap control should be greyed out. On linux, disabling the StaticBitmap does this
            # automatically, however, on windows, this requires a bit more work. wx.Bitmap has a function
            # .ConvertToDisabled(), but the resulting bitmap is almost transparent and can hardly be seen.
            # Therefore we have to go the long way around and first convert the bitmap to an image, which
            # can be converted to greyscale and then convert it back to a bitmap.
            return bmp.ConvertToImage().ConvertToGreyscale().ConvertToDisabled().ConvertToBitmap()

        pressure_ok = self.saferange_vacuum_pressure[0] <= self.vacuum_pressure <= self.saferange_vacuum_pressure[1]
        heatsink_ok = self.saferange_sink_temp[0] <= self.heat_sink_temp <= self.saferange_sink_temp[1]
        if (self.debug_mode or self.power) and not self.error_codes:
            # enable all
            self.ctl_power.Enable(True)
            self.ctl_hv.Enable(True)
            self.ctl_power.SetBitmap(self.bmp_on if self.power else self.bmp_off)
            self.ctl_hv.SetBitmap(self.bmp_on if self.hv else self.bmp_off)
            self.channel_ctrl.Enable(True)
            self.spinctrl_voltage.Enable(True)
            self.slider_gain.Enable(True)
            self.slider_offset.Enable(True)
            self.slider_fe_offset.Enable(True)
            self.spinctrl_gain.Enable(True)
            self.spinctrl_offset.Enable(True)
            self.spinctrl_fe_offset.Enable(True)
        elif (pressure_ok or self.ambient) and heatsink_ok and not self.error_codes:
            # enable power, disable rest
            # don't care about pressure in ambient mode
            self.ctl_power.Enable(True)
            self.ctl_hv.Enable(False)
            self.ctl_power.SetBitmap(self.bmp_on if self.power else self.bmp_off)
            self.ctl_hv.SetBitmap(disable_bmp(self.bmp_on) if self.hv else disable_bmp(self.bmp_off))
            self.channel_ctrl.Enable(False)
            self.spinctrl_voltage.Enable(False)
            self.slider_fe_offset.Enable(False)
            self.slider_gain.Enable(False)
            self.slider_offset.Enable(False)
            self.spinctrl_gain.Enable(False)
            self.spinctrl_offset.Enable(False)
            self.spinctrl_fe_offset.Enable(False)
        else:
            # disable all
            self.ctl_power.Enable(False)
            self.ctl_hv.Enable(False)
            self.ctl_power.SetBitmap(disable_bmp(self.bmp_on) if self.power else disable_bmp(self.bmp_off))
            self.ctl_hv.SetBitmap(disable_bmp(self.bmp_on) if self.hv else disable_bmp(self.bmp_off))
            self.channel_ctrl.Enable(False)
            self.spinctrl_voltage.Enable(False)
            self.slider_gain.Enable(False)
            self.slider_offset.Enable(False)
            self.spinctrl_gain.Enable(False)
            self.spinctrl_offset.Enable(False)

        # Show we are in debug mode
        if self.debug_mode:
            self.power_label.SetLabel("Power\tDEBUG MODE")
            self.power_label.SetForegroundColour(wx.Colour(wx.RED))
        else:
            self.power_label.SetLabel("Power")
            self.power_label.SetForegroundColour(wx.Colour(wx.BLACK))

    @call_in_wx_main
    def refresh(self):
        """
        Refreshes the GUI display values
        """
        # Check the error status
        if self.error != driver.FrontEndErrorCodes.NoFault.value:
            if not self.error in self.error_codes:
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="Jolt reports error code %d." % (self.error,) +
                                                 " Verify that the control box is connected " +
                                                 "properly and cycle the power",
                                                 parent=self.dialog, flags=wx.ICON_ERROR)
                if self.power:  # and not self.debug_mode:
                    self.toggle_power()
                msg.Show()
            # this way, the warning message is only displayed when the warning first occurs
            self.error_codes.add(self.error)
        else:
            # errors cleared
            self.error_codes.clear()

        # Show settings for temperature, pressure etc
        self.txtbox_output.SetValue("%.2f" % self.output)
        self.txtbox_MPPCTemp.SetValue("%.1f" % self.mppc_temp)
        self.txtbox_sinkTemp.SetValue("%.1f" % self.heat_sink_temp)
        self.txtbox_fe_output.SetValue("%.3f" % self.fe_output)
        pressure_ok = self.saferange_vacuum_pressure[0] <= self.vacuum_pressure <= self.saferange_vacuum_pressure[1]
        if pressure_ok:
            self.txtbox_vacuumPressure.SetValue("vacuum")
        else:
            self.txtbox_vacuumPressure.SetValue("vented")

        # Check ranges, create notification if necessary
        self.check_saferange(self.txtbox_MPPCTemp, self.mppc_temp, [self.target_temp + self.mppc_temp_rel[0], self.target_temp + self.mppc_temp_rel[1]], "MPCC Temperature", time.time())
        self.check_saferange(self.txtbox_sinkTemp, self.heat_sink_temp, self.saferange_sink_temp, "Heat Sink Temperature")
        if not self.ambient:
            # don't care about pressure in ambient mode
            self.check_saferange(self.txtbox_vacuumPressure, self.vacuum_pressure, self.saferange_vacuum_pressure, "Vacuum Pressure")

        # Modify controls to show hardware values
        ch2sel = {"R": 0, "G": 1, "B": 2, "Pan": 3}
        try:
            self.channel_ctrl.SetSelection(ch2sel[self.channel])  # fails if it's Channel.NONE
        except:
            pass
        self.slider_gain.SetValue(int(round(self.gain)))
        self.slider_offset.SetValue(int(round(self.offset)))
        # Don't refresh text controls that can be changed, it's annoying if you're trying to write
        # Also don't update voltage control when voltage is off, we want to be able to easily turn the
        # voltage on without readjusting the value.
        # After entering a value, the focus will be automatically set to the output textbox, so there
        # is a good chance that the textbox is going to be updated when we're not actively writing in it
        # (this last point is implemented in the event callback functions).
        focus = self.dialog.FindFocus()
        # All controls will be disabled except the one that's in focus. However, on Windows,
        # the FindFocus() returns a textcontrol object for the spincontrols, so it's not possible
        # to compare them directly (bug in wxpython?). It turns out that the name of this textcontrol
        # inside the spincontrol is always 'text', so we can test for that instead. The result is not
        # perfect, we're now also not updating other spincontrols while typing in one, but
        # this should not be a big issue for now.
        try:
            focus_name = focus.GetName()
        except:
            focus_name = ""
        for ctrl, val in [(self.spinctrl_gain, self.gain), (self.spinctrl_offset, self.offset)]:
            if focus != ctrl and focus_name != 'text':
                ctrl.SetValue(round(float(val), 1))
        voltage_numeric = round(float(self.voltage), 2)
        voltage_string = f"({voltage_numeric} V)"
        self.text_voltage.SetLabel(voltage_string)
        self.text_voltage.SetToolTip("Measured voltage")

        # Grey out value in voltage control if voltage button is off.
        # In this case, the actual voltage will be 0, but we still want the previous
        # voltage to be shown, so it's easy to turn it back on again.
        if self.hv:
            self.spinctrl_voltage.SetForegroundColour(wx.BLACK)
        elif not self.hv and focus != self.spinctrl_voltage and focus_name != 'text':
            self.spinctrl_voltage.SetForegroundColour((211, 211, 211))  # light grey

        # Update controls
        self.update_controls()

    def do_poll(self):
        """
        This function is run in a thread and handles the polling of the device on a time interval
        """
        try:
            while not self.should_stop_polling.is_set():
                # Get new values from the device
                if not self.differential:
                    self.output = self.dev.get_output_single_ended()
                else:
                    self.output = self.dev.get_output_differential()
                self.gain = self.dev.get_gain()
                self.offset = self.dev.get_offset()
                self.voltage = self.dev.get_voltage()
                self.channel = CHANNEL2STR[self.dev.get_channel()]
                self.mppc_temp = self.dev.get_cold_plate_temp()
                self.heat_sink_temp = self.dev.get_hot_plate_temp()
                self.vacuum_pressure = self.dev.get_vacuum_pressure()
                self.error = self.dev.get_error_status()
                self.itec = self.dev.get_itec()
                # Properties purely for logging
                target_temp = self.dev.get_mppc_temp()
                fe_offset = self.dev.get_frontend_offset()
                self.fe_output = self.dev.get_frontend_output_voltage()
                # Convert error code 8 (no error) to more user friendly string
                error_log = self.error if self.error != driver.FrontEndErrorCodes.NoFault.value else "no errors"

                logging.info("Gain: %.2f, offset: %.2f, channel: %s, target temperature: %.2f, temperature: %.2f, sink temperature: %.2f, " +
                             "pressure: %.2f, voltage: %.2f, output: %.2f, fe offset: %d, fe output: %.3e, error state: %s, Tec current: %s", self.gain, self.offset,
                             self.channel, target_temp, self.mppc_temp, self.heat_sink_temp, self.vacuum_pressure, self.voltage, self.output, fe_offset, self.fe_output,
                             error_log, self.itec)

                # Refresh gui with these values
                self.refresh()

                # Wait till the next polling period
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            logging.exception(e)

        finally:
            # ending the thread....
            logging.debug("Exiting polling thread...")

    def excepthook(self, etype, value, trace):
        """ Method to intercept unexpected errors that are not caught
        anywhere else and redirects them to the logger.
        Note that exceptions caught and logged will appear in the text pane,
        but not cause it to pop-up (as this method will not be called).
        """
        # in case of error here, don't call again, it'd create infinite recursion
        if sys and traceback:
            sys.excepthook = sys.__excepthook__

            try:
                exc = traceback.format_exception(etype, value, trace)
                try:
                    remote_tb = value._pyroTraceback
                    rmt_exc = "Remote exception %s" % ("".join(remote_tb),)
                except AttributeError:
                    rmt_exc = ""
                logging.error("".join(exc) + rmt_exc)

            finally:
                # put us back
                sys.excepthook = self.excepthook
        # python is ending... can't rely on anything
        else:
            print("%s: %s\n%s" % (etype, value, trace))

    def showwarning(self, message, category, filename, lineno, file=None, line=None):
        """
        Called when a warning is generated.
        The default behaviour is to write it on stderr, which would lead to it
        being shown as an error.
        """
        warn = warnings.formatwarning(message, category, filename, lineno, line)
        logging.warning(warn)


def installThreadExcepthook():
    """ Workaround for sys.excepthook thread bug
    http://spyced.blogspot.com/2007/06/workaround-for-sysexcepthook-bug.html

    Call once from ``__main__`` before creating any threads.
    """
    init_old = threading.Thread.__init__

    def init(self, *args, **kwargs):
        init_old(self, *args, **kwargs)
        run_old = self.run

        def run_with_except_hook(*args, **kw):
            try:
                run_old(*args, **kw)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                sys.excepthook(*sys.exc_info())

        self.run = run_with_except_hook
    threading.Thread.__init__ = init


def main():
    app = JoltApp()
    # Change exception hook so unexpected exception get caught by the logger,
    # and warnings are shown as warnings in the log.
    backup_excepthook, sys.excepthook = sys.excepthook, app.excepthook
    warnings.showwarning = app.showwarning

    app.MainLoop()
    app.Destroy()
    sys.excepthook = backup_excepthook

if __name__ == "__main__":
    installThreadExcepthook()
    main()
