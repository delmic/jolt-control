# -*- coding: utf-8 -*-
'''
Created on 30 September 2019
@author: Anders Muskens
Copyright © 2019 Anders Muskens, Delmic

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

import os
import time
import wx
import wx.adv
from wx import xrc
import logging
import threading
import configparser
from appdirs import AppDirs
import jolt
from jolt.util import log
from jolt.gui import xmlh
from jolt import driver
from jolt.util import *
from jolt.gui import call_in_wx_main


logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.DEBUG)

# Get app config directories
dirs = AppDirs("Jolt", "Delmic", version=jolt.__version__)
if os.path.isdir(dirs.user_data_dir):
    CONFIG_FILE = os.path.join(dirs.user_data_dir,'jolt.ini')
else:
    logging.error("User data directory for application does not exist. Searching config in local directory")
    CONFIG_FILE = 'jolt.ini'
    # TODO: put right path
if os.path.isdir(dirs.user_log_dir):
    LOG_FILE = os.path.join(dirs.user_log_dir, 'jolt.log')
else:
    logging.error("User data directory for application does not exist. Putting log in local directory")
    LOG_FILE = 'jolt.log'

POLL_INTERVAL = 1.0 # seconds

class JoltApp(wx.App):
    """
    The Jolt Control Window App

    Requries files
    xrc/main.xrc
    CONFIG_FILE: an ini file for settings

    Creates files:
    jolt.log: Log file

    """

    def __init__(self, simulated=True):
        """
        Constructor
        :param simulated: True if the Jolt driver should be a simulator
        """
        self.dev = driver.JOLT(simulated)
        self.should_close = threading.Event()

        # Load config
        self._voltage, self._gain, self._offset = self.load_config()
        self.mpcc_current = 0.0
        self.mpcc_temp = 0.0
        self.heat_sink_temp = 0.0
        self.vacuum_pressure = 0.0
        self.err = 0

        # set of warnings currently active
        self.warnings = set()
        self.error_codes = set()

        # Initialize wx components
        super().__init__(self)

        # settings
        self._power = False
        self._hv = False
        self._call_auto_bc = threading.Event()

        # start the thread for polling
        self.polling_thread = threading.Thread(target=self._do_poll)
        self.polling_thread.start()

    def load_config(self):
        # Load config from file
        self.config = configparser.ConfigParser()
        logging.debug("Reading config %s", CONFIG_FILE)
        self.config.read(CONFIG_FILE)

        try:
            voltage = self.config.getfloat('DEFAULT', 'voltage')
            gain = self.config.getfloat('DEFAULT', 'gain')
            offset = self.config.getfloat('DEFAULT', 'offset')
        except (LookupError, KeyError, configparser.NoOptionError):
            logging.error("Invalid or missing configuration file.")
            voltage = 0.0
            gain = 0.0
            offset = 0.0

        return voltage, gain, offset

    def save_config(self):
        """
        Save the configuration in the window to an INI file.
        This is usually called when the window is closed.
        :return:
        """
        cfgfile = open(CONFIG_FILE, 'w')
        self.config.set('DEFAULT', 'voltage', str(self._voltage))
        self.config.set('DEFAULT', 'gain', str(self._gain))
        self.config.set('DEFAULT', 'offset', str(self._offset))
        self.config.write(cfgfile)
        cfgfile.close()

    def OnInit(self):
        """
        Function called when the wxWindow is initialized.
        """
        # open the main control window dialog
        self._init_dialog()

        # load bitmaps
        self.bmp_off = wx.Bitmap("gui/img/icons8-toggle-off-32.png")
        self.bmp_on = wx.Bitmap("gui/img/icons8-toggle-on-32.png")
        self.bmp_icon = wx.Bitmap("gui/img/jolt-icon.png")

        # set icon
        icon = wx.Icon()
        icon.CopyFromBitmap(self.bmp_icon)
        self.dialog.SetIcon(icon)
        self.dialog.Show()

        # Refresh the live values
        self._set_gui_from_val()
        self.refresh()

        #self.taskbar = taskbar.JoltTaskBarIcon(self.dialog)
        return True

    def _init_dialog(self):
        """
        Load the XRC GUI and connect all of the GUI controls to their event handlers
        """

        # XRC Loading
        self.res = xrc.XmlResource('gui/main.xrc')
        # custom xml handler for wxSpinCtrlDouble, which is not supported officially yet
        self.res.InsertHandler(xmlh.SpinCtrlDoubleXmlHandler())
        self.dialog = self.res.LoadDialog(None, 'ControlWindow')

        # Initialize logging and connect it to the log text box
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

        # attach the logging to the log text control as a handler
        self.txtbox_log = xrc.XRCCTRL(self.dialog, 'txtbox_log')
        self.textHandler = log.TextFieldHandler()
        self.textHandler.setTextField(self.txtbox_log)
        self.textHandler.setLevel(logging.INFO)
        self.textHandler.setFormatter(formatter)

        # add a file logger handler
        logging.debug("Opening log file %s", LOG_FILE)
        self.fileHandler = logging.FileHandler(LOG_FILE)
        self.fileHandler.setLevel(logging.DEBUG)
        self.fileHandler.setFormatter(formatter)

        # attach to the global logger
        self.logger = logging.getLogger('')  # use the global logger
        self.logger.addHandler(self.textHandler)
        self.logger.addHandler(self.fileHandler)

        # controls and events:
        # Initialize all of the GUI controls and connect them to events
        self.ctl_power =  xrc.XRCCTRL(self.dialog, 'ctl_power')
        self.ctl_power.Bind(wx.EVT_LEFT_DOWN, self.OnPower)
        self.ctl_hv = xrc.XRCCTRL(self.dialog, 'ctl_hv')
        self.ctl_hv.Bind(wx.EVT_LEFT_DOWN, self.OnHV)

        self.btn_auto_bc = xrc.XRCCTRL(self.dialog, 'btn_AutoBC')
        self.dialog.Bind(wx.EVT_BUTTON, self.OnAutoBC, id=xrc.XRCID('btn_AutoBC'))

        # voltage
        self.spinctrl_voltage = xrc.XRCCTRL(self.dialog, 'spn_voltage')
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.OnVoltage, id=xrc.XRCID('spn_voltage'))

        # gain and offset
        self.slider_gain = xrc.XRCCTRL(self.dialog, 'slider_gain')
        self.slider_offset = xrc.XRCCTRL(self.dialog, 'slider_offset')
        self.spinctrl_gain = xrc.XRCCTRL(self.dialog, 'spin_gain')
        self.spinctrl_offset = xrc.XRCCTRL(self.dialog, 'spin_offset')
        self.dialog.Bind(wx.EVT_SCROLL, self.OnGainSlider, id=xrc.XRCID('slider_gain'))
        self.dialog.Bind(wx.EVT_SCROLL, self.OnOffsetSlider, id=xrc.XRCID('slider_offset'))
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.OnGainSpin, id=xrc.XRCID('spin_gain'))
        self.dialog.Bind(wx.EVT_SPINCTRLDOUBLE, self.OnOffsetSpin, id=xrc.XRCID('spin_offset'))

        # Channel select
        self.tog_R = xrc.XRCCTRL(self.dialog, 'tog_R')
        self.tog_G = xrc.XRCCTRL(self.dialog, 'tog_G')
        self.tog_B = xrc.XRCCTRL(self.dialog, 'tog_B')
        self.tog_Pan = xrc.XRCCTRL(self.dialog, 'tog_Pan')
        self.dialog.Bind(wx.EVT_TOGGLEBUTTON, self.OnChanR, id=xrc.XRCID('tog_R'))
        self.dialog.Bind(wx.EVT_TOGGLEBUTTON, self.OnChanG, id=xrc.XRCID('tog_G'))
        self.dialog.Bind(wx.EVT_TOGGLEBUTTON, self.OnChanB, id=xrc.XRCID('tog_B'))
        self.dialog.Bind(wx.EVT_TOGGLEBUTTON, self.OnChanPan, id=xrc.XRCID('tog_Pan'))

        # Live displays
        self.txtbox_current = xrc.XRCCTRL(self.dialog, 'txtbox_current')
        self.txtbox_MPPCTemp = xrc.XRCCTRL(self.dialog, 'txtbox_MPPCTemp')
        self.txtbox_sinkTemp = xrc.XRCCTRL(self.dialog, 'txtbox_sinkTemp')
        self.txtbox_vacuumPressure = xrc.XRCCTRL(self.dialog, 'txtbox_vacuumPressure')

        # log display
        self.btn_viewLog = xrc.XRCCTRL(self.dialog, 'btn_viewLog', wx.CollapsiblePane)
        self.dialog.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.OnCollapseLog, id=xrc.XRCID('btn_viewLog'))

        # catch the closing event
        self.dialog.Bind(wx.EVT_CLOSE, self.OnClose)

        # disable the controls until powered on
        self.enable_power_controls(False)

    @call_in_wx_main
    def _set_gui_from_val(self):
        # Set the values from the currently loaded values
        self.spinctrl_voltage.SetValue(self._voltage)
        self.slider_gain.SetValue(self._gain)
        self.slider_offset.SetValue(self._offset)
        self.spinctrl_gain.SetValue(self._gain)
        self.spinctrl_offset.SetValue(self._offset)

    def check_saferange(self, textctrl, val, range, name):
        """
        Turn a TextCtrl text red if the val is not in the range
        Display an error message if the value is out of the range.
        :param textctrl: wx TextCtrl
        :param val: (float) a value
        :param range: (float tuple) safe range
        :param name: (str) the name of the parameter used in the error message
        """
        if range[0] <= val <= range[1]:
            textctrl.SetForegroundColour(wx.BLACK)
            if name in self.warnings:
                # clear the warning if the error goes away
                self.warnings.remove(name)
        else:
            textctrl.SetForegroundColour(wx.RED)
            # this way, the warning message is only displayed when the warning first occurs
            if name not in self.warnings:
                self.warnings.add(name)
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="%s is outside of the safe range of operation." % (name,), parent=self.dialog,
                                    flags=wx.ICON_WARNING)

                msg.Show()

            logging.warning("%s (%f) is outside of the safe range of operation (%f -> %f).", name, val, range[0], range[1])

    def enable_gain_offset_controls(self, val=True):
        """
        Enable (or disable if val=False) the gain and offset controls
        :param val: (bool) default is true, but if set to false, the controls will be disabled.
        """
        self.slider_gain.Enable(val)
        self.slider_offset.Enable(val)
        self.spinctrl_gain.Enable(val)
        self.spinctrl_offset.Enable(val)

    def enable_power_controls(self, val=True):
        """
        Enable (or disable if val=False) power controls
        :param val: (bool) default is true, but if set to false, the controls will be disabled.
        """
        self.btn_auto_bc.Enable(val)
        self.enable_gain_offset_controls(val)
        self.tog_R.Enable(val)
        self.tog_G.Enable(val)
        self.tog_B.Enable(val)
        self.tog_Pan.Enable(val)

    def OnClose(self, event):
        """
        Event on window close
        """
        # Check if the user should power down
        if self._power:
            dlg = wx.MessageDialog(None, "Power down the Jolt hardware before closing the application?", 'Notice', wx.OK | wx.CANCEL | wx.ICON_WARNING)
            dlg.SetOKCancelLabels("Power down", "Cancel closing")
            result = dlg.ShowModal()

            if result == wx.ID_OK:
                logging.info("Powering down Jolt...")
                self.dev.set_power(False)
            else:
                # Cancel closing
                return

        # end the polling thread
        self.should_close.set()

        self.save_config() # Save config to INI
        self.dialog.Destroy()

    def OnCollapseLog(self, event):
        self.dialog.Fit()

    def OnPower(self, event):
        # Toggle the power value
        self._power = not self._power
        logging.info("Power: %s", self._power)
        self.dev.set_power(self._power)
        self.ctl_power.SetBitmap(self.bmp_on if self._power else self.bmp_off)

        # disable HV if power is off
        if not self._power:
            self._hv = False
            self.ctl_hv.SetBitmap(self.bmp_on if self._hv else self.bmp_off)
            self.enable_power_controls(False)
        else:
            self.enable_power_controls()

    def OnHV(self, event):
        # Toggle the HV value
        if not self._power:
            return

        self._hv = not self._hv
        logging.info("HV: %s", self._hv)

        self.ctl_hv.SetBitmap(self.bmp_on if self._hv else self.bmp_off)

        if self._hv:
            # write parameters to device
            self.dev.set_voltage(self._voltage)
            self.dev.set_gain(self._gain)
            self.dev.set_offset(self._offset)
        else:
            self.dev.set_voltage(0)

    def OnAutoBC(self, event):
        # Call Auto BC
        logging.info("Calling auto BC")
        self.dev.call_auto_bc()
        self._call_auto_bc.set()
        self.enable_gain_offset_controls(False)

    def OnVoltage(self, event):
        self._voltage = event.GetValue()
        logging.info("Voltage setting: %f V", self._voltage)
        if self._hv:
            self.dev.set_voltage(self._voltage)

    def SetToggleRGBP(self, channel):
        """
        Sets to false all toggle buttons except the selected one (passed in channel)
        :param channel: (wx.ToggleButton) Reference to toggle button that should be
        """
        toggles = [self.tog_R, self.tog_G, self.tog_B, self.tog_Pan]
        toggles.remove(channel)
        for tog in toggles:
            tog.SetValue(False)

    def OnChanR(self, event):
        logging.info("Set channel R")
        self.dev.set_channel(driver.CHANNEL_R)
        self.SetToggleRGBP(self.tog_R)

    def OnChanG(self, event):
        logging.info("Set channel G")
        self.dev.set_channel(driver.CHANNEL_G)
        self.SetToggleRGBP(self.tog_G)

    def OnChanB(self, event):
        logging.info("Set channel B")
        self.dev.set_channel(driver.CHANNEL_B)
        self.SetToggleRGBP(self.tog_B)

    def OnChanPan(self, event):
        logging.info("Set channel Pan")
        self.dev.set_channel(driver.CHANNEL_PAN)
        self.SetToggleRGBP(self.tog_Pan)

    def OnGainSlider(self, event):
        self._gain = event.GetPosition()
        logging.info("Gain: %f %%", self._gain)
        self.spinctrl_gain.SetValue(self._gain)
        self.dev.set_gain(self._gain)

    def OnOffsetSlider(self, event):
        self._offset = event.GetPosition()
        logging.info("Offset: %f %%", self._offset)
        self.spinctrl_offset.SetValue(self._offset)
        self.dev.set_offset(self._offset)

    def OnGainSpin(self, event):
        self._gain = event.GetValue()
        logging.info("Gain: %f %%", self._gain)
        self.slider_gain.SetValue(int(self._gain))
        self.dev.set_gain(self._gain)

    def OnOffsetSpin(self, event):
        self._offset = event.GetValue()
        logging.info("Offset: %f %%", self._offset)
        self.slider_offset.SetValue(int(self._offset))
        self.dev.set_offset(self._offset)

    def OnRefreshGUI(self, event):
        self.refresh()

    @call_in_wx_main
    def refresh(self):
        """
        Refreshes the GUI display values
        """
        self.txtbox_current.SetValue("%.2f" % self.mpcc_current)
        self.check_saferange(self.txtbox_current, self.mpcc_current, driver.SAFERANGE_MPCC_CURRENT, "MPCC Current")

        self.txtbox_MPPCTemp.SetValue("%.1f" %  self.mpcc_temp)
        self.check_saferange(self.txtbox_MPPCTemp, self.mpcc_temp, driver.SAFERANGE_MPCC_TEMP, "MPCC Temperature")

        self.txtbox_sinkTemp.SetValue("%.1f" % self.heat_sink_temp)
        self.check_saferange(self.txtbox_sinkTemp, self.heat_sink_temp, driver.SAFERANGE_HEATSINK_TEMP, "Heat Sink Temperature")

        self.txtbox_vacuumPressure.SetValue("%.1f" %  self.vacuum_pressure)
        self.check_saferange(self.txtbox_vacuumPressure, self.vacuum_pressure, driver.SAFERANGE_VACUUM_PRESSURE,"Vacuum Pressure")

        # check the error status
        if self.err != 0:
            # Report error
            logging.error("Error code: %d", self.err)

            if not self.err in self.error_codes:
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="Jolt reports error code %d" % (self.err,),
                                                 parent=self.dialog,flags=wx.ICON_ERROR)

                msg.Show()

            # this way, the warning message is only displayed when the warning first occurs
            self.error_codes.add(self.err)

        else:
            # errors cleared
            self.error_codes.clear()

    def _do_poll(self):
        """
        This function is run in a thread and handles the polling of the device on a time interval
        """
        try:
            while not self.should_close.is_set():
                # get new values from the device
                self.mpcc_current = self.dev.get_mppc_current()
                self.mpcc_temp = self.dev.get_mppc_temp()
                self.heat_sink_temp = self.dev.get_heat_sink_temp()
                self.vacuum_pressure = self.dev.get_vacuum_pressure()
                self.err = self.dev.get_error_status()
                # refresh gui with these values
                self.refresh()

                # refresh gain & offset if auto BC was called
                if self._call_auto_bc.is_set():
                    # Since we don't know how long the auto BC takes, add more time
                    time.sleep(POLL_INTERVAL)

                    logging.debug("update gain and offset values after AUTO BC")
                    # get gain & offset updates
                    self._gain = self.dev.get_gain()
                    self._offset = self.dev.get_offset()
                    logging.info("Gain: %f %%", self._gain)
                    logging.info("Offset: %f %%", self._offset)
                    wx.CallAfter(self._set_gui_from_val)
                    self._call_auto_bc.clear()
                    wx.CallAfter(self.enable_gain_offset_controls)

                # Wait till the next polling period
                self.should_close.wait(POLL_INTERVAL)

        except Exception as e:
            logging.exception(e)

        finally:
            # ending the thread....
            logging.debug("Exiting polling thread...")


def main():
    app = JoltApp()
    app.MainLoop()

if __name__ == "__main__":
    main()