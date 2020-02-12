# -*- coding: utf-8 -*-
'''
Created on 10 February 2020
@author: Philip Winkler
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
from jolt.util import resource_path
from jolt.gui import call_in_wx_main
import sys
import warnings
import traceback
from shutil import copyfile

from jolt.driver import JOLT

from jolt.gui.firmware import MyWizard1
from jolt.JoltApp import JoltApp
from NXPISP.bin import SetupChip
import serial
import glob

COMPUTER_BOARD = 0
FIRMWARE_BOARD = 1
UPDATE = 0
EMPTY_BOARD = 1

class FirmwareUpdater(wx.App):
    """
    The Jolt Control Window App

    Requires files
    xrc/main.xrc
    CONFIG_FILE: an ini file for settings

    Creates files:
    jolt.log: Log file

    """

    def __init__(self):
        """
        Constructor
        """
        self.file_cb = None
        self.file_fb = None
        self.driver = None
        self.compboard_isempty = False
        self.frontboard_isempty = False
        self._user_ok = False
        
        # Initialize wx components
        super().__init__(self)
        self.dialog.Show()

        # Check that JoltApp is not running
        try:
            self.driver = JOLT()
            self.portname = self.driver.portname
            self.serial = self.driver._serial
            print("Found jolt on port %s" % self.portname)
            print("Current firmware version computer board: %s\n\n" % self.driver.get_be_fw_version())
            fe_version = self.driver.get_fe_fw_version()
            if "unknown" in fe_version.lower():
                self.frontboard_isempty = True
            print("Current firmware version frontend board: %s" % fe_version)
        except:
            dlg = wx.MessageDialog(None, "Couldn't find JOLT! Please make sure the device is connected and turned on. If this is the first time the firmware is uploaded, select 'Upload to empty board'", 'Warning', wx.OK | wx.CANCEL | wx.ICON_WARNING)
            dlg.SetOKCancelLabels("Exit", "Upload to empty computer board")
            result = dlg.ShowModal()
            if result == wx.ID_OK:
                self.dialog.Destroy()
            else:
                print("No firmware found. Uploading to empty computer board.\n\n")
                self.compboard_isempty = True

    def OnInit(self, *args, **kwargs):
        # XRC Loading
        self.res = xrc.XmlResource(resource_path('gui/fw_updater.xrc'))
        self.dialog = self.res.LoadDialog(None, 'MyDialog1')
        
        self.upload_btn = xrc.XRCCTRL(self.dialog, 'upload_button')
        self.filePicker_cb = xrc.XRCCTRL(self.dialog, 'filePicker_cb')
        self.filePicker_fb = xrc.XRCCTRL(self.dialog, 'filePicker_fb')
        self.output_box = xrc.XRCCTRL(self.dialog, 'm_textCtrl5')
        self.finish_label = xrc.XRCCTRL(self.dialog, 'm_staticText27')
        self.slider = xrc.XRCCTRL(self.dialog, 'm_scrollBar4')
        
        self.dialog.Bind(wx.EVT_FILEPICKER_CHANGED, self.OnFileCb, id=xrc.XRCID('filePicker_cb'))
        self.dialog.Bind(wx.EVT_FILEPICKER_CHANGED, self.OnFileFb, id=xrc.XRCID('filePicker_fb'))
        self.dialog.Bind(wx.EVT_BUTTON, self.OnUploadBtn, id=xrc.XRCID('upload_button'))

        self.dialog.Bind(wx.EVT_CLOSE, self.OnClose)

        redir = RedirectText(self.output_box)
        sys.stdout = redir
        sys.stderr = redir
        
        self.upload_btn.Enable(False)
        self.finish_label.Hide()

        # Advanced drop down menu for resetting completely (deleting firmware)
        
        return True

    def OnFileCb(self, event):
        path = event.GetPath()
        if 'frontend' in path.lower() or 'front-end' in path.lower():
            dlg = wx.MessageDialog(None, "The name of the file includes the word 'frontend'. Are you sure it's a file for the computer board? If so, please rename it and try again.", 'Warning', wx.OK | wx.ICON_WARNING)
            dlg.ShowModal()
            self.filePicker_cb.SetPath("None")  # that's probably not the best way of doing it, but it works (with any text that's not a proper file, but not with "")
        else:
            self.file_cb = event.GetPath()
            self.upload_btn.Enable(True)
        
    def OnFileFb(self, event):
        path = event.GetPath()
        if 'frontend' not in path.lower():
            dlg = wx.MessageDialog(None, "The name of the file does not include the word 'frontend'. Are you sure it's a file for the frontend board? If so, please rename it and try again.", 'Warning', wx.OK | wx.ICON_WARNING)
            dlg.ShowModal()
            self.filePicker_fb.SetPath("None")  # that's probably not the best way of doing it, but it works (with any text that's not a proper file, but not with "")
        else:
            self.file_fb = event.GetPath()
            if not self.compboard_isempty:  # computer board firmware required
                self.upload_btn.Enable(True)

    def OnUploadBtn(self, event):
        if not self.file_cb and not self.file_fb:
            # error dialog
            raise ValueError('No file selected.')
        
        thread = threading.Thread(target=self.upload_firmware)
        thread.start()

    def upload_firmware(self):
        cb_success = True
        fb_success = True
        if self.compboard_isempty:
            while True:
                if os.name == "nt":
                    import serial.tools.list_ports
                    ports = list(serial.tools.list_ports.comports())
                    for p in ports:
                        print(p)
                else:
                    ports = glob.glob("/dev/ttyUSB*")
                    
                if len(ports) > 1:
                    # make sure we don't upload firmware to wrong device
                    self.display_msg_dialog("Multiple serial ports detected. Remove all other USB devices and try again.", 'Warning', wx.OK | wx.CANCEL | wx.ICON_WARNING)
                    continue
                else:
                    self.portname = ports[0]
                    self.serial = serial.Serial(ports[0], baudrate=9600, xonxoff=False)
                    break

        if self.file_cb:
            cb_success = False
            if not self.compboard_isempty:
                try:
                    print("Entering Computer Board ISP mode...")
                    self.driver.set_cb_isp_mode()
                except:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    traceback.print_exception(exc_type, exc_value, exc_tb)
                    return
                time.sleep(2)
            max_trials = 5

            for i in range(max_trials):
                print("\n\nNXPISP Upload: Trial %d" % i)
                print("Setting up chip...")
                try:
                    chip = SetupChip('LPC845', self.serial)
                    print('Writing image...')
                    chip.WriteImage(self.file_cb)
                    break
                except Exception as ex:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    traceback.print_exception(exc_type, exc_value, exc_tb)
                    self.serial.close()
                    self.serial = serial.Serial(self.portname, baudrate=9600, xonxoff=False)
            else:
                self.display_msg_dialog("Upload failed. Please contact Delmic (www.support.delmic.com) and attach the output from the console.", 'Error', wx.OK | wx.ICON_ERROR)
                return
 
            print("\nComputer Board Firmware uploaded successfully.\n\n")
            cb_success = True

        if self.file_cb and self.file_fb:
            ret = self.display_msg_dialog("Please power cycle the device, wait for the boot process to finish (status light stops blinking) and press OK to continue.", 'Action required', wx.OK)
            # TODO: wait for ok
            while not self._user_ok:
                time.sleep(0.1)
            print("Reconnecting to driver...")
            self.serial.close()
            self.driver = JOLT()

        if self.file_fb:
            fb_success = False
            try:
                print("Entering Frontend ISP mode...")
                if self.frontboard_isempty:
                    self.driver.set_passthrough_mode()
                else:
                    self.driver.set_fb_isp_mode()
            except:
                exc_type, exc_value, exc_tb = sys.exc_info()
                traceback.print_exception(exc_type, exc_value, exc_tb)
                return
            time.sleep(2)
            max_trials = 5
            for i in range(max_trials):
                print("\n\nNXPISP Upload: Trial %d" % i)
                print("Setting up chip...")
                try:
                    chip = SetupChip('LPC845', self.serial)
                    print('Writing image...')
                    chip.WriteImage(self.file_fb)
                    break
                except Exception as ex:
                    exc_type, exc_value, exc_tb = sys.exc_info()
                    traceback.print_exception(exc_type, exc_value, exc_tb)
                    self.serial.close()
                    self.serial = serial.Serial(self.portname, baudrate=9600, xonxoff=False)
            else:
                self.display_msg_dialog("Upload failed. Please contact Delmic (www.support.delmic.com) and attach the output from the console.", 'Error', wx.OK | wx.ICON_ERROR)
                return
            print("Frontend Board Firmware uploaded successfully.\n\n")
            fb_success = True
            
        if cb_success and fb_success:
            self.finish_label.Show()
        else:
            # TODO
            pass

    @call_in_wx_main
    def display_msg_dialog(self, text, title, mtype=wx.ICON_WARNING):
        dlg = wx.MessageDialog(None, text, title, wx.OK | mtype)
        ret = dlg.ShowModal()
        if ret == wx.ID_OK:
            self._user_ok = True
        return ret
        
    def OnClose(self, event):
        if self.driver:
            self.driver._serial.close()
        self.dialog.Destroy()
        event.Skip()

class RedirectText:
    def __init__(self, aWxTextCtrl):
        self.out = aWxTextCtrl
        
    @call_in_wx_main
    def write(self, string):
        self.out.WriteText(string)  
        
    def flush(self):
        # Timeout decorator in ISPChip class requires flush function
        pass

if __name__ == "__main__":
    app = FirmwareUpdater()
    app.MainLoop()
    app.Destroy()
