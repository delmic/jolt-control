# -*- coding: utf-8 -*-
'''
Created on 3 Oct 2019
@author: Anders Muskens
Copyright © 2019 Anders Muskens, Delmic
'''

import wx
import wx.xrc as xrc
import wx.adv

DEFAULT_VALUE = "0.0"
DEFAULT_MIN = 0.0
DEFAULT_MAX = 100.0
DEFAULT_STEP = 1.0
DEFAULT_INITIAL = 0.0

class SpinCtrlDoubleXmlHandler (xrc.XmlResourceHandler):
    """
    Class to implement loading the wx SpinCtrlDouble class from XRC
    """
    def __init__(self):
        xrc.XmlResourceHandler.__init__(self)
        # Specify the styles recognized by objects of this type
        self.AddStyle("wxSP_HORIZONTAL", wx.SP_HORIZONTAL)
        self.AddStyle("wxSP_VERTICAL", wx.SP_VERTICAL)
        self.AddStyle("wxSP_ARROW_KEYS", wx.SP_ARROW_KEYS)
        self.AddStyle("wxSP_WRAP", wx.SP_WRAP)
        self.AddStyle("wxALIGN_LEFT", wx.ALIGN_LEFT)
        self.AddStyle("wxALIGN_CENTER", wx.ALIGN_CENTER)
        self.AddStyle("wxALIGN_RIGHT", wx.ALIGN_RIGHT)
        self.AddStyle("wxTE_PROCESS_ENTER", wx.TE_PROCESS_ENTER)
        self.AddWindowStyles()

    def CanHandle(self, node):
        return self.IsOfClass(node, 'wxSpinCtrlDouble')

    def DoCreateResource(self):
        assert self.GetInstance() is None

        parent_window = self.GetParentAsWindow()
        # Now create the object
        spinctrl = wx.SpinCtrlDouble(
            parent_window,
            self.GetID(),
            self.GetText("value"),
            self.GetPosition(),
            self.GetSize(),
            self.GetStyle("style", wx.SP_ARROW_KEYS | wx.ALIGN_RIGHT),
            self.GetFloat("min", DEFAULT_MIN),
            self.GetFloat("max", DEFAULT_MAX),
            self.GetFloat("initial", DEFAULT_INITIAL),
            self.GetFloat("inc", DEFAULT_STEP),
            self.GetName(),
        )

        # These two things should be done in either case:
        # Set standard window attributes
        self.SetupWindow(spinctrl)

        return spinctrl
