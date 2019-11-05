# -*- coding: utf-8 -*-
'''
Created on 8 October 2019
@author: Anders Muskens
Copyright © 2019 Anders Muskens, Delmic

This module contains initialization of the TaskBar icon
'''

import wx.adv


class JoltTaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        self.frame = frame
        super(JoltTaskBarIcon, self).__init__()
        self.bmp_icon = wx.Bitmap("../img/jolt-icon.png")
        self.icon = wx.Icon()
        self.icon.CopyFromBitmap(self.bmp_icon)
        self.SetIcon(self.icon)
        #self.Bind(wx.EVT_TASKBAR_LEFT_DOWN, self.OnLeftDown)

    def OnLeftDown(self, event):
        event.Skip()