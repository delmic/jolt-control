# -*- coding: utf-8 -*-
'''
Created on 8 October 2019
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