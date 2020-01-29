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
import sys
import warnings
import traceback
from shutil import copyfile


logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.DEBUG)

# Get app config directories
SAVE_CONFIG = True  # whether or not to save the last values to .ini
dirs = AppDirs("Jolt", "Delmic")
if os.path.isdir(dirs.user_data_dir):
    CONFIG_FILE = os.path.join(dirs.user_data_dir, 'jolt.ini')
else:
    # Create directory if it doesn't exist
    try:
        os.makedirs(dirs.user_data_dir)
        copyfile('jolt.ini', os.path.join(dirs.user_data_dir, 'jolt.ini'))
        CONFIG_FILE = os.path.join(dirs.user_data_dir, 'jolt.ini')
    except:
        logging.error("Failed to create user data directory, using default .ini file.")
        CONFIG_FILE = 'jolt.ini'
        SAVE_CONFIG = False

if os.path.isdir(dirs.user_log_dir):
    LOG_FILE = os.path.join(dirs.user_log_dir, 'jolt.log')
else:
    # Create directory if it doesn't exist
    try:
        os.makedirs(dirs.user_log_dir)
        LOG_FILE = os.path.join(dirs.user_log_dir, 'jolt.log')
    except:
        logging.error("Failed to create user log directory, using default .ini file.")
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

        self._debug_mode = False

        # set of warnings currently active
        self.warnings = set()
        self.error_codes = set()

        # Initialize wx components
        super().__init__(self)

        # settings
        self._power = False
        self._hv = False
        self._call_auto_bc = threading.Event()

        # Get information from hardware for the log
        logging.info("Backend firmware: %s" % self.dev.get_be_fw_version())
        logging.info("Backend hardware: %s" % self.dev.get_be_hw_version())
        logging.info("Backend serial number: %s" % self.dev.get_be_sn())
        logging.info("Frontend firmware: %s" % self.dev.get_fe_fw_version())
        logging.info("Frontend hardware: %s" % self.dev.get_fe_hw_version())
        logging.info("Frontend serial number: %s" % self.dev.get_fe_sn())

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
            logging.error("Invalid or missing configuration file, falling back to default values.")
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
        if not SAVE_CONFIG:
            logging.warning("Not saving jolt state.")
            return
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
        self.channel_ctrl = xrc.XRCCTRL(self.dialog, 'radio_channel')
        self.dialog.Bind(wx.EVT_RADIOBOX, self.OnRadioBox, id=xrc.XRCID('radio_channel'))

        # Live displays
        self.txtbox_current = xrc.XRCCTRL(self.dialog, 'txtbox_current')
        self.txtbox_current.Enable(False)
        self.txtbox_MPPCTemp = xrc.XRCCTRL(self.dialog, 'txtbox_MPPCTemp')
        self.txtbox_sinkTemp = xrc.XRCCTRL(self.dialog, 'txtbox_sinkTemp')
        self.txtbox_vacuumPressure = xrc.XRCCTRL(self.dialog, 'txtbox_vacuumPressure')

        # log display
        self.btn_viewLog = xrc.XRCCTRL(self.dialog, 'btn_viewLog', wx.CollapsiblePane)
        self.dialog.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.OnCollapseLog, id=xrc.XRCID('btn_viewLog'))

        # catch the closing event
        self.dialog.Bind(wx.EVT_CLOSE, self.OnClose)

        # disable the controls until powered on
        self.ctl_power.Enable(False)
        self.enable_power_controls(False)
        
        # Debugging: allow shortcut to enable all controls
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    @call_in_wx_main
    def _on_key(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_F5:
            if self._debug_mode:
                self._debug_mode = False
            else:
                self._debug_mode = True
        
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
        self.btn_auto_bc.Enable(False)  # not implemented yet
        self.enable_gain_offset_controls(val)
        self.channel_ctrl.Enable(val)

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
                self.dev.set_target_mppc_temp(24)
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
        if self.ctl_power.IsEnabled():
            self._power = not self._power
            logging.info("Power: %s", self._power)
            if self._power:
                self.dev.set_target_mppc_temp(-10)
            else:
                self.dev.set_target_mppc_temp(24)
            self.ctl_power.SetBitmap(self.bmp_on if self._power else self.bmp_off)
            if self._power:
                self.enable_power_controls(True)
            else:
                self.enable_power_controls(False)

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
        raise NotImplementedError()
#         logging.info("Calling auto BC")
#         self.dev.call_auto_bc()
#         self._call_auto_bc.set()
#         self.enable_gain_offset_controls(False)

    def OnVoltage(self, event):
        self._voltage = event.GetValue()
        if self._hv:
            self.dev.set_voltage(self._voltage)
            logging.info("Voltage setting: %f V", self.dev.get_voltage())

    def OnRadioBox(self, event):
        channels = {"R": driver.CHANNEL_R, "G": driver.CHANNEL_G, "B": driver.CHANNEL_B, "Pan": driver.CHANNEL_PAN}
        logging.error(channels[event.GetEventObject().GetStringSelection()])
        self.dev.set_channel(channels[event.GetEventObject().GetStringSelection()])
        ret = self.dev.get_channel()
        logging.info("Channel: %s", ret)

    def OnGainSlider(self, event):
        self._gain = event.GetPosition()
        self.spinctrl_gain.SetValue(self._gain)
        self.dev.set_gain(self._gain)
        logging.info("Gain: %f %%", self.dev.get_gain())

    def OnOffsetSlider(self, event):
        self._offset = event.GetPosition()
        self.spinctrl_offset.SetValue(self._offset)
        self.dev.set_offset(self._offset)
        logging.info("Offset: %f %%", self.dev.get_offset())

    def OnGainSpin(self, event):
        self._gain = event.GetValue()
        self.slider_gain.SetValue(int(self._gain))
        self.dev.set_gain(self._gain)
        time.sleep(0.2)
        logging.info("Gain: %f %%", self.dev.get_gain())

    def OnOffsetSpin(self, event):
        self._offset = event.GetValue()
        self.slider_offset.SetValue(int(self._offset))
        self.dev.set_offset(self._offset)
        logging.info("Offset: %f %%", self.dev.get_offset())

    def OnRefreshGUI(self, event):
        self.refresh()

    @call_in_wx_main
    def refresh(self):
        """
        Refreshes the GUI display values
        """
        self.txtbox_current.SetValue("N/A")
        #self.txtbox_current.SetValue("%.2f" % self.mpcc_current)
        #self.check_saferange(self.txtbox_current, self.mpcc_current, driver.SAFERANGE_MPCC_CURRENT, "MPCC Current")

        self.txtbox_MPPCTemp.SetValue("%.1f" %  self.mpcc_temp)
        self.check_saferange(self.txtbox_MPPCTemp, self.mpcc_temp, driver.SAFERANGE_MPCC_TEMP, "MPCC Temperature")

        self.txtbox_sinkTemp.SetValue("%.1f" % self.heat_sink_temp)
        self.check_saferange(self.txtbox_sinkTemp, self.heat_sink_temp, driver.SAFERANGE_HEATSINK_TEMP, "Heat Sink Temperature")

        self.txtbox_vacuumPressure.SetValue("%.1f" %  self.vacuum_pressure)
        self.check_saferange(self.txtbox_vacuumPressure, self.vacuum_pressure, driver.SAFERANGE_VACUUM_PRESSURE,"Vacuum Pressure")
        if (not driver.SAFERANGE_VACUUM_PRESSURE[0] <= self.vacuum_pressure <= driver.SAFERANGE_VACUUM_PRESSURE[1]
            and not self._power):  # don't allow to turn it on, but turning it off should still work
            self.ctl_power.Enable(False)
        else:
            self.ctl_power.Enable(True)
            
        if self._debug_mode:
            self.ctl_power.Enable(True)
            self.enable_power_controls(True)
        elif not self._debug_mode and not self._power:
            self.enable_power_controls(False)

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
                self.mpcc_temp = self.dev.get_cold_plate_temp()
                self.heat_sink_temp = self.dev.get_hot_plate_temp()
                self.vacuum_pressure = self.dev.get_vacuum_pressure()
                #self.err = self.dev.get_error_status()
                # refresh gui with these values
                self.refresh()

                logging.info("Gain: %s, offset: %s, channel: %s, voltage: %s",
                             self.dev.get_gain(), self.dev.get_offset(), self.dev.get_channel(),
                             self.dev.get_voltage())

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
                time.sleep(POLL_INTERVAL)
                #self.should_close.wait(POLL_INTERVAL)

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