# -*- coding: utf-8 -*-
'''
Created on 30 September 2019
@author: Anders Muskens
Copyright © 2019 Anders Muskens, Delmic
'''

import wx
from wx import xrc
import xmlh
import logging
import driver
import threading
import time
import configparser
from appdirs import AppDirs
import os
import log
from util import *
import taskbar


logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.DEBUG)

# Get app config directories
VERSION = "0.1"
dirs = AppDirs("Jolt", "Delmic", version=VERSION)
if os.path.isdir(dirs.user_data_dir):
    CONFIG_FILE = os.path.join(dirs.user_data_dir,'jolt.ini')
else:
    logging.error("User data directory for application does not exist. Searching config in local directory")
    CONFIG_FILE = 'jolt.ini'

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

        # Load config from file
        self.config = configparser.ConfigParser()
        logging.debug("Reading config %s", CONFIG_FILE)
        self.config.read(CONFIG_FILE)

        try:
            self._voltage = float(self.config['DEFAULT']['voltage'])
            self._gain = float(self.config['DEFAULT']['gain'])
            self._offset = float(self.config['DEFAULT']['offset'])
        except LookupError:
            logging.error("Invalid or missing configuration file.")
            self._voltage = 0.0
            self._gain = 0.0
            self._offset = 0.0

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
        self.bmp_off = wx.Bitmap("img/icons8-toggle-off-32.png")
        self.bmp_on = wx.Bitmap("img/icons8-toggle-on-32.png")
        self.bmp_icon = wx.Bitmap("img/jolt-icon.png")

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
        self.res = xrc.XmlResource('xrc/main.xrc')
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
        self.toh_R = xrc.XRCCTRL(self.dialog, 'tog_R')
        self.toh_G = xrc.XRCCTRL(self.dialog, 'tog_G')
        self.toh_B = xrc.XRCCTRL(self.dialog, 'tog_B')
        self.toh_Pan = xrc.XRCCTRL(self.dialog, 'tog_Pan')
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
        self.disable_power_controls()

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
        """
        if range[0] <= val <= range[1]:
            textctrl.SetForegroundColour(wx.BLACK)
            if name in self.warnings:
                # clear the warning if the error goes away
                self.warnings.remove(name)
        else:
            textctrl.SetForegroundColour(wx.RED)
            if not name in self.warnings:
                self.warnings.add(name)
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="%s is outside of the safe range of operation." % (name,), parent=self.dialog,
                                    flags=wx.ICON_WARNING)

                msg.Show()

            logging.warning("%s (%f) is outside of the safe range of operation (%f -> %f).", name, val, range[0], range[1])
            # this way, the warning message is only displayed when the warning first occurs


    def disable_gain_offset_controls(self):
        self.slider_gain.Disable()
        self.slider_offset.Disable()
        self.spinctrl_gain.Disable()
        self.spinctrl_offset.Disable()

    def enable_gain_offset_controls(self):
        self.slider_gain.Enable()
        self.slider_offset.Enable()
        self.spinctrl_gain.Enable()
        self.spinctrl_offset.Enable()

    def enable_power_controls(self):
        self.btn_auto_bc.Enable()
        self.enable_gain_offset_controls()
        self.toh_R.Enable()
        self.toh_G.Enable()
        self.toh_B.Enable()
        self.toh_Pan.Enable()

    def disable_power_controls(self):
        self.btn_auto_bc.Disable()
        self.disable_gain_offset_controls()
        self.toh_R.Disable()
        self.toh_G.Disable()
        self.toh_B.Disable()
        self.toh_Pan.Disable()

    def OnClose(self, event):
        """
        Event on window close
        """
        # Check if the user should power down
        if self._power:
            dlg = wx.MessageDialog(None, "Power down the Jolt hardware before closing the application?", 'Notice', wx.YES_NO | wx.ICON_WARNING)
            result = dlg.ShowModal()

            if result == wx.ID_YES:
                logging.info("Powering down Jolt...")
                self.dev.set_power(False)

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
            self.disable_power_controls()
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
            self.dev.set_voltage(self._voltage)
        else:
            self.dev.set_voltage(0)

    def OnAutoBC(self, event):
        # Call Auto BC
        logging.info("Calling auto BC")
        self.dev.call_auto_bc()
        self._call_auto_bc.set()
        self.disable_gain_offset_controls()

    def OnVoltage(self, event):
        self._voltage = event.GetValue()
        logging.info("Voltage setting: %f V", self._voltage)
        if self._hv:
            self.dev.set_voltage(self._voltage)

    def OnChanR(self, event):
        logging.info("Set channel R")
        self.dev.set_channel(driver.CHANNEL_R)
        self.toh_G.SetValue(False)
        self.toh_B.SetValue(False)
        self.toh_Pan.SetValue(False)

    def OnChanG(self, event):
        logging.info("Set channel G")
        self.dev.set_channel(driver.CHANNEL_G)
        self.toh_R.SetValue(False)
        self.toh_B.SetValue(False)
        self.toh_Pan.SetValue(False)

    def OnChanB(self, event):
        logging.info("Set channel B")
        self.dev.set_channel(driver.CHANNEL_B)
        self.toh_G.SetValue(False)
        self.toh_R.SetValue(False)
        self.toh_Pan.SetValue(False)

    def OnChanPan(self, event):
        logging.info("Set channel Pan")
        self.dev.set_channel(driver.CHANNEL_PAN)
        self.toh_G.SetValue(False)
        self.toh_B.SetValue(False)
        self.toh_R.SetValue(False)

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
        mpcc_current = self.dev.get_mppc_current()
        self.txtbox_current.SetValue("%.2f" % mpcc_current)
        self.check_saferange(self.txtbox_current, mpcc_current, driver.SAFERANGE_MPCC_CURRENT, "MPCC Current")

        mpcc_temp = self.dev.get_mppc_temp()
        self.txtbox_MPPCTemp.SetValue("%.1f" %  mpcc_temp)
        self.check_saferange(self.txtbox_MPPCTemp, mpcc_temp, driver.SAFERANGE_MPCC_TEMP, "MPCC Temperature")

        heat_sink_temp = self.dev.get_heat_sink_temp()
        self.txtbox_sinkTemp.SetValue("%.1f" % heat_sink_temp)
        self.check_saferange(self.txtbox_sinkTemp, heat_sink_temp, driver.SAFERANGE_HEATSINK_TEMP, "Heat Sink Temperature")

        vacuum_pressure = self.dev.get_vacuum_pressure()
        self.txtbox_vacuumPressure.SetValue("%.1f" %  vacuum_pressure)
        self.check_saferange(self.txtbox_vacuumPressure, vacuum_pressure, driver.SAFERANGE_VACUUM_PRESSURE,
                             "Vacuum Pressure")

        # check the error status
        err = self.dev.get_error_status()
        if err != 0:
            # Report error
            logging.error("Error code: %d", err)

            if not err in self.error_codes:
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="Jolt reports error code %d" % (err,),
                                                 parent=self.dialog,flags=wx.ICON_ERROR)

                msg.Show()

            # this way, the warning message is only displayed when the warning first occurs
            self.error_codes.add(err)

        else:
            # errors cleared
            self.error_codes.clear()

    def _do_poll(self):
        """
        This function is run in a thread and handles the polling of the device on a time interval
        """
        while not self.should_close.is_set():
            self.refresh()  # get new values and display them in the GUI

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
                self._set_gui_from_val()
                self._call_auto_bc.clear()
                self.enable_gain_offset_controls()

            # Wait till the next polling period
            time.sleep(POLL_INTERVAL)

        # ending the thread....
        logging.debug("Exiting polling thread...")

def main():
    app = JoltApp()
    app.MainLoop()

if __name__ == "__main__":
    main()