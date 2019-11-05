# -*- coding: utf-8 -*-
'''
Created on 8 October 2019
@author: Anders Muskens
Copyright © 2019 Anders Muskens, Delmic
'''

import wx
import logging
import collections
import threading
from jolt.gui import wxlimit_invocation

# Foreground (i.e text) colours
FG_COLOUR_MAIN = "#GGGGGG"       # Default foreground colour
FG_COLOUR_DIS = "#777777"        # Disabled foreground colour
FG_COLOUR_WARNING = "#FFA300"    # Warning text colour (TODO: "#C87000" is better?)
FG_COLOUR_ERROR = "#DD3939"      # Error text colour

LOG_LINES = 500

class TextFieldHandler(logging.Handler):
    """ Custom log handler, used to output log entries to a text field. """
    TEXT_STYLES = (
        wx.TextAttr(FG_COLOUR_ERROR, None),
        wx.TextAttr(FG_COLOUR_WARNING, None),
        wx.TextAttr(FG_COLOUR_MAIN, None),
        wx.TextAttr(FG_COLOUR_DIS, None),
    )

    def __init__(self):
        """ Call the parent constructor and initialize the handler """
        logging.Handler.__init__(self)
        self.textfield = None

        # queue of tuple (str, TextAttr) = text, style
        self._to_print = collections.deque(maxlen=LOG_LINES)
        self._print_lock = threading.Lock()

    def setTextField(self, textfield):
        self.textfield = textfield
        self.textfield.Clear()

    def emit(self, record):
        """ Write a record, in colour, to a text field. """
        if self.textfield is not None:
            if record.levelno >= logging.ERROR:
                text_style = self.TEXT_STYLES[0]
            elif record.levelno == logging.WARNING:
                text_style = self.TEXT_STYLES[1]
            elif record.levelno == logging.INFO:
                text_style = self.TEXT_STYLES[2]
            else:
                text_style = self.TEXT_STYLES[3]

            # Do the actual writing in a rate-limited thread, so logging won't
            # interfere with the GUI drawing process.
            self._to_print.append((record, text_style))
            self.write_to_field()

    @wxlimit_invocation(0.2)
    def write_to_field(self):

        with self._print_lock:

            # Process the latest messages
            try:
                prev_style = None
                while True:
                    record, text_style = self._to_print.popleft()
                    if prev_style != text_style:
                        self.textfield.SetDefaultStyle(text_style)
                        prev_style = text_style
                    self.textfield.AppendText(self.format(record) + "\n")
            except IndexError:
                pass  # end of the queue

            # Removes the characters from position 0 up to and including the Nth line break
            nb_lines = self.textfield.GetNumberOfLines()
            nb_old = nb_lines - LOG_LINES
            if nb_old > 0:
                first_new = 0
                txt = self.textfield.Value
                for i in range(nb_old):
                    first_new = txt.find('\n', first_new) + 1

                self.textfield.Remove(0, first_new)

        self.textfield.Refresh()