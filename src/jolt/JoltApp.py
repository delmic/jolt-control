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

TEST_NOHW = (os.environ.get("TEST_NOHW", 0) != 0)  # Default to Hw testing

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.DEBUG)

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Get app config directories
SAVE_CONFIG = True  # whether or not to save the last values to .ini
dirs = AppDirs("Jolt", "Delmic")
if os.path.isdir(dirs.user_data_dir):
    CONFIG_FILE = os.path.join(dirs.user_data_dir, 'jolt.ini')
else:
    # Create directory if it doesn't exist
    try:
        os.makedirs(dirs.user_data_dir)
        copyfile(resource_path('jolt.ini'), os.path.join(dirs.user_data_dir, 'jolt.ini'))
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
        LOG_FILE = resource_path('jolt.log')

POLL_INTERVAL = 2.0 # seconds


class JoltApp(wx.App):
    """
    The Jolt Control Window App

    Requries files
    xrc/main.xrc
    CONFIG_FILE: an ini file for settings

    Creates files:
    jolt.log: Log file

    """

    def __init__(self, simulated=TEST_NOHW):
        """
        Constructor
        :param simulated: True if the Jolt driver should be a simulator
        """
        try:
            self.dev = driver.JOLT(simulated)
            self._startup_error = False
        except IOError as ex:
            self._startup_error = True
            super().__init__(self)
            dlg = wx.MessageBox("Connection to Jolt failed. Make sure the hardware is connected and turned on.",
                          'Info', wx.OK)
            logging.error("Jolt failed to start: %s", ex)
            result = dlg.ShowModal()
            if result == wx.ID_OK:
                sys.exit()
        except Exception as ex:
            logging.error("Jolt failed to start: %s", ex)

        self._simulated = simulated
        self.should_close = threading.Event()

        # Load config
        self._voltage, self._gain, self._offset = self.load_config()
        self.voltage = 0.0
        self.mppc_temp = 0.0
        self.heat_sink_temp = 0.0
        self.vacuum_pressure = 0.0
        self.error = 8  # 8 means no error

        # settings
        self._power = False
        self._hv = False
        self._call_auto_bc = threading.Event()
        self._debug_mode = False

        # set of warnings currently active
        self.warnings = set()
        self.error_codes = set()

        # Initialize wx components
        super().__init__(self)

        # Get information from hardware for the log
        logging.info("Software version: %s", jolt.__version__)
        logging.info("Backend firmware: %s" % self.dev.get_be_fw_version())
        logging.info("Backend hardware: %s" % self.dev.get_be_hw_version())
        logging.info("Backend serial number: %s" % self.dev.get_be_sn())
        logging.info("Frontend firmware: %s" % self.dev.get_fe_fw_version())
        logging.info("Frontend hardware: %s" % self.dev.get_fe_hw_version())
        logging.info("Frontend serial number: %s" % self.dev.get_fe_sn())

        # Output single-ended, not differential
        self.dev.set_signal_type(single_ended=True)

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
        if self._startup_error:
            return True

        # open the main control window dialog
        self._init_dialog()

        # load bitmaps
        self.bmp_off = wx.Bitmap(resource_path("gui/img/icons8-toggle-off-32.png"))
        self.bmp_on = wx.Bitmap(resource_path("gui/img/icons8-toggle-on-32.png"))
        self.bmp_icon = wx.Bitmap(resource_path("gui/img/jolt-icon.png"))

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
        self.res = xrc.XmlResource(resource_path('gui/main.xrc'))
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

        # tooltip power
        self.ctl_power.ToolTip = wx.ToolTip("Cooling can only be turned on if pressure is OK")

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
        #self.txtbox_current.Enable(False)
        self.txtbox_MPPCTemp = xrc.XRCCTRL(self.dialog, 'txtbox_MPPCTemp')
        self.txtbox_sinkTemp = xrc.XRCCTRL(self.dialog, 'txtbox_sinkTemp')
        self.txtbox_vacuumPressure = xrc.XRCCTRL(self.dialog, 'txtbox_vacuumPressure')

        # log display
        self.btn_viewLog = xrc.XRCCTRL(self.dialog, 'btn_viewLog', wx.CollapsiblePane)
        self.dialog.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.OnCollapseLog, id=xrc.XRCID('btn_viewLog'))

        # catch the closing event
        self.dialog.Bind(wx.EVT_CLOSE, self.OnClose)
        
        # Debugging: allow shortcut to enable all controls
        f5_id = wx.NewId()
        self.dialog.Bind(wx.EVT_MENU, self._on_key, id=f5_id)
        accel_tbl = wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_F5, f5_id)])
        self.dialog.SetAcceleratorTable(accel_tbl)

        self.power_label = xrc.XRCCTRL(self.dialog, 'm_staticText16')

        if self._simulated:
            self.dialog.SetTitle("Delmic Jolt Simulator")

        self.refresh()

    @call_in_wx_main
    def _on_key(self, event):
        if self._debug_mode:
            self._debug_mode = False
        else:
            passwd = wx.PasswordEntryDialog(None, "Enter Debug Mode", 'Password','',
                                            style=wx.TextEntryDialogStyle)
            ans = passwd.ShowModal()
            if ans == wx.ID_OK:
                entered_password = passwd.GetValue()
                if entered_password == "delmic":
                    self._debug_mode = True
            passwd.Destroy()
        self.refresh()
        
    @call_in_wx_main
    def _set_gui_from_val(self):
        # Set the values from the currently loaded values
        self.spinctrl_voltage.SetValue(self._voltage)
        self.slider_gain.SetValue(self._gain)
        self.slider_offset.SetValue(self._offset)
        self.spinctrl_gain.SetValue(self._gain)
        self.spinctrl_offset.SetValue(self._offset)

    def check_saferange(self, textctrl, val, srange, name):
        """
        Turn a TextCtrl text red if the val is not in the range
        Display an error message if the value is out of the range.
        :param textctrl: wx TextCtrl
        :param val: (float) a value
        :param srange: (float tuple) safe range
        :param name: (str) the name of the parameter used in the error message
        """
        if srange[0] <= val <= srange[1]:
            textctrl.SetForegroundColour(wx.BLACK)
            if name in self.warnings:
                self.warnings.remove(name)  # clear the warning if the error goes away
        else:
            textctrl.SetForegroundColour(wx.RED)
            # this way, the warning message is only displayed when the warning first occurs
            if name not in self.warnings:
                self.warnings.add(name)
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="%s is outside of the safe range of operation." % (name,), parent=self.dialog,
                                                 flags=wx.ICON_WARNING)
                msg.Show()
            logging.warning("%s (%f) is outside of the safe range of operation (%f -> %f).",
                            name, val, srange[0], srange[1])

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
            logging.info("Changed power state to: %s", self._power)
            if self._power:
                if self._debug_mode:
                    self.dev.set_target_mppc_temp(10)
                else:
                    self.dev.set_target_mppc_temp(-10)
            else:
                self.dev.set_target_mppc_temp(24)
        # Turn voltage off
        if not self._power:
            self._hv = False
            logging.info("Changed voltage state to: %s", self._hv)
            self.dev.set_voltage(0)
        if self._power:
            # write parameters to device
            self.dev.set_voltage(self._voltage)
            self.dev.set_gain(self._gain)
            self.dev.set_offset(self._offset)
        self.refresh()

    def OnHV(self, event):
        # Toggle the HV value
        self._hv = not self._hv
        logging.info("Changed voltage state to: %s", self._hv)

        if self._hv:
            # write parameters to device
            self.dev.set_voltage(self._voltage)
            self.dev.set_gain(self._gain)
            self.dev.set_offset(self._offset)
        else:
            self.dev.set_voltage(0)
        self.refresh()

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
            logging.debug("Changed voltage to %s", self._voltage)
            self.dev.set_voltage(self._voltage)

    def OnRadioBox(self, event):
        channels = {"R": driver.CHANNEL_R, "G": driver.CHANNEL_G, "B": driver.CHANNEL_B, "Pan": driver.CHANNEL_PAN}
        self.dev.set_channel(channels[event.GetEventObject().GetStringSelection()])
        logging.debug("Changed channel to %s", event.GetEventObject().GetStringSelection())

    def OnGainSlider(self, event):
        self._gain = event.GetPosition()
        self.spinctrl_gain.SetValue(self._gain)
        self.dev.set_gain(self._gain)
        logging.debug("Changed gain to %s", self._gain)

    def OnOffsetSlider(self, event):
        self._offset = event.GetPosition()
        self.spinctrl_offset.SetValue(self._offset)
        self.dev.set_offset(self._offset)
        logging.debug("Changed offset to %s", self._offset)

    def OnGainSpin(self, event):
        self._gain = event.GetValue()
        self.slider_gain.SetValue(int(self._gain))
        self.dev.set_gain(self._gain)
        logging.debug("Changed gain to %s", self._gain)

    def OnOffsetSpin(self, event):
        self._offset = event.GetValue()
        self.slider_offset.SetValue(int(self._offset))
        self.dev.set_offset(self._offset)
        logging.debug("Changed offset to %s", self._offset)

    def OnRefreshGUI(self, event):
        self.refresh()

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

        pressure_ok = driver.SAFERANGE_VACUUM_PRESSURE[0] <= self.vacuum_pressure <= driver.SAFERANGE_VACUUM_PRESSURE[1]
        if self._debug_mode or self._power:
            # enable all
            self.ctl_power.Enable(True)
            self.ctl_hv.Enable(True)
            self.ctl_power.SetBitmap(self.bmp_on if self._power else self.bmp_off)
            self.ctl_hv.SetBitmap(self.bmp_on if self._hv else self.bmp_off)
            self.channel_ctrl.Enable(True)
            self.spinctrl_voltage.Enable(True)
            self.slider_gain.Enable(True)
            self.slider_offset.Enable(True)
            self.spinctrl_gain.Enable(True)
            self.spinctrl_offset.Enable(True)
        elif pressure_ok:
            # enable power, disable rest
            self.ctl_power.Enable(True)
            self.ctl_hv.Enable(False)
            self.ctl_power.SetBitmap(self.bmp_on if self._power else self.bmp_off)
            self.ctl_hv.SetBitmap(disable_bmp(self.bmp_on) if self._hv else disable_bmp(self.bmp_off))
            self.channel_ctrl.Enable(False)
            self.spinctrl_voltage.Enable(False)
            self.slider_gain.Enable(False)
            self.slider_offset.Enable(False)
            self.spinctrl_gain.Enable(False)
            self.spinctrl_offset.Enable(False)
        else:
            # disable all
            self.ctl_power.Enable(False)
            self.ctl_hv.Enable(False)
            self.ctl_power.SetBitmap(disable_bmp(self.bmp_on) if self._power else disable_bmp(self.bmp_off))
            self.ctl_hv.SetBitmap(disable_bmp(self.bmp_on) if self._hv else disable_bmp(self.bmp_off))
            self.channel_ctrl.Enable(False)
            self.spinctrl_voltage.Enable(False)
            self.slider_gain.Enable(False)
            self.slider_offset.Enable(False)
            self.spinctrl_gain.Enable(False)
            self.spinctrl_offset.Enable(False)

        # Auto BC not implemented yet
        self.btn_auto_bc.Enable(False)

        # Show we are in debug mode
        if self._debug_mode:
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
        # Show settings for temperature, pressure etc
        self.txtbox_current.SetValue("%.2f" % self.output)
        self.txtbox_MPPCTemp.SetValue("%.1f" %  self.mppc_temp)
        self.txtbox_sinkTemp.SetValue("%.1f" % self.heat_sink_temp)
        self.txtbox_vacuumPressure.SetValue("%.1f" %  self.vacuum_pressure)

        # Check ranges, create notification if necessary
        if self._power:  # mppc temperature will always be out of range if power is off
            self.check_saferange(self.txtbox_MPPCTemp, self.mppc_temp, driver.SAFERANGE_MPCC_TEMP, "MPCC Temperature")
        self.check_saferange(self.txtbox_sinkTemp, self.heat_sink_temp, driver.SAFERANGE_HEATSINK_TEMP, "Heat Sink Temperature")
        self.check_saferange(self.txtbox_vacuumPressure, self.vacuum_pressure, driver.SAFERANGE_VACUUM_PRESSURE,"Vacuum Pressure")

        # Check the error status
        if self.error != 8:
            if not self.error in self.error_codes:
                msg = wx.adv.NotificationMessage("DELMIC JOLT", message="Jolt reports error code %d" % (self.error,),
                                                 parent=self.dialog,flags=wx.ICON_ERROR)
                msg.Show()

            # this way, the warning message is only displayed when the warning first occurs
            self.error_codes.add(self.error)
        else:
            # errors cleared
            self.error_codes.clear()

        # Update controls
        self.update_controls()

    def _do_poll(self):
        """
        This function is run in a thread and handles the polling of the device on a time interval
        """
        try:
            while not self.should_close.is_set():
                # Get new values from the device
                self.output = self.dev.get_output_single_ended()
                self.mppc_temp = self.dev.get_cold_plate_temp()
                self.heat_sink_temp = self.dev.get_hot_plate_temp()
                self.vacuum_pressure = self.dev.get_vacuum_pressure()
                self.error = self.dev.get_error_status()
                gain = self.dev.get_gain()
                offset = self.dev.get_offset()
                self.voltage = self.dev.get_voltage()
                channel_list = {driver.CHANNEL_R: "R", driver.CHANNEL_G: "G", driver.CHANNEL_B: "B",
                                driver.CHANNEL_PAN: "PAN"}
                channel = channel_list[self.dev.get_channel()]
       
                # Logging
                logging.info("Gain: %.2f, offset: %.2f, channel: %s, temperature: %.2f, sink temperature: %.2f, " +
                             "pressure: %.2f, voltage: %.2f, output: %.2f, error state: %d", gain, offset, channel,
                             self.mppc_temp, self.heat_sink_temp, self.vacuum_pressure, self.voltage, self.output,
                             self.error)

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