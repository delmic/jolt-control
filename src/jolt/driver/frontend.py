#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Created on 1 Oct 2019

Copyright © 2017-2018 Anders Muskens, Philip Winkler, Delmic

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
import serial
import logging
import time
import threading
import math
import glob


SOH = b'\x01'  # chr(0x01)  # start of header
EOT = b'\x04'  # end of transmission
ACK = b'\x06'  # acknowledgement
NAK = b'\x15'
US = b'\x1F'  # unit separator
ETX = b'\x03'  # end of text
ID_CMD = b'\x43'  # packet identifier command
ID_STATUS = b'\x53'  # packet identifier command
ID_ASCII = b'\x4D'  # packet identifier ascii message
ID_BIN = b'\x04'  # packet identifier binary message
ERRORS = []  # error codes

CMD_SET_POWER = b'A'
CMD_GET_VOLTAGE = b'B'
CMD_SET_VOLTAGE = b'C'
CMD_GET_OFFSET = b'D'
CMD_SET_OFFSET = b'E'
CMD_GET_GAIN = b'F'
CMD_SET_GAIN = b'G'
CMD_GET_MPPC_TEMP = b'H'
CMD_SET_MPPC_TEMP = b'I'
CMD_GET_SINK_TEMP = b'J'
CMD_GET_MPPC_CURRENT = b'K'
CMD_GET_VACUUM_PRESSURE = b'L'
CMD_GET_CHANNEL = b'M'
CMD_SET_CHANNEL = b'N'
CMD_GET_ERROR = b'O'
CMD_CALL_AUTO_BC = b'P'
CMD_GET_CHANNEL_LIST = b'Q'
CMD_GET_ID = chr(0x13)
CMD_SERIAL_VERSION = chr(0x14)
CMD_ARG_SIZE = chr(0x15)
CMD_ENDIANNESS = chr(0x16)

CHANNEL_PAN = 0
CHANNEL_R = 1
CHANNEL_G = 2
CHANNEL_B = 3

SAFERANGE_MPCC_CURRENT = (0, 5)
SAFERANGE_MPCC_TEMP = (0, 50)
SAFERANGE_HEATSINK_TEMP = (0, 75)
SAFERANGE_VACUUM_PRESSURE = (0, 10)

class JOLTError(Exception):

    def __init__(self, code):
        # TODO: Map code to message
        super(JOLTError, self).__init__(code)
        self.code = code

    def __str__(self):
        return self.args[1]

class JOLT():
    
    def __init__(self, simulated=False):
        self._serial = self._find_device(simulated=simulated)
        self._ser_access = threading.Lock()

        self.counter = 0
        
    def get_id(self):
        """
        :param val: (bool) True for on, False for off
        """
        return self._send_query(CMD_GET_ID)
    
    def set_power(self, val):
        """
        :param val: (bool) True for on, False for off
        :returns: (None)
        """
        self._send_cmd(CMD_SET_POWER, format(val, "b"))
    
    def get_voltage(self):
        """
        :returns: (int)
        """
        return int(self._send_query(CMD_GET_VOLTAGE))
    
    def set_voltage(self, val):
        """
        :param val: (int)
        :returns: (None)
        """
        self._send_cmd(CMD_SET_VOLTAGE, b"%d" % val)  # format(val, "b"))
    
    def get_gain(self):
        """
        :returns: (int)
        """
        return int(self._send_query(CMD_GET_GAIN))
    
    def set_gain(self, val):
        """
        :param val: (int)
        :returns: (None)
        """
        self._send_cmd(CMD_SET_GAIN, format(val, "b"))
    
    def get_offset(self):
        """
        :param val: (int)
        :returns: (None)
        """
        return self._send_query(CMD_GET_OFFSET)
    
    def set_offset(self, val):
        """
        :param val: (int)
        :returns: (None)
        """
        self._send_cmd(CMD_SET_OFFSET, format(val, "b"))
    
    def get_mppc_temp(self):
        """
        :returns: (int)
        """
        return int(self._send_query(CMD_GET_MPPC_TEMP))
  
    def set_target_mppc_temp(self, val):
        """
        :param val: (int)
        :returns: (None)
        """
        # sets the target temperature
        self._send_cmd(CMD_SET_MPPC_TEMP, format(val, "b"))
    
    def get_heat_sink_temp(self):
        """
        :returns: (int)
        """
        return int(self._send_query(CMD_GET_SINK_TEMP))
    
    def get_mppc_current(self):
        """
        :returns: (int)
        """
        #return int(self._send_query(CMD_GET_MPPC_CURRENT))
        self.counter += 0.1
        return math.sin(self.counter) * 7
    
    def get_vacuum_pressure(self):
        """
        :returns: (int)
        """
        return int(self._send_query(CMD_GET_VACUUM_PRESSURE))
    
    def get_channel(self):
        """
        :returns: (int)
        """
        return int(self._send_query(CMD_GET_CHANNEL))

    def set_channel(self, val):
        """
        :param val: (int)
        :returns: (None)
        """
        self._send_cmd(CMD_SET_CHANNEL, format(val, "b"))
    
    def get_error_status(self):
        """
        :returns: (?)
        """
        return self._send_query(CMD_GET_ERROR)
    
    def call_auto_bc(self):
        """
        :returns: (int)
        """
        self._send_cmd(CMD_CALL_AUTO_BC)
    
    def get_channel_list(self):
        """
        :returns: ?
        """
        # TODO: what does this return
        return self._send_query(CMD_GET_CHANNEL_LIST)

    @staticmethod
    def _openSerialPort(port, baudrate):
        """
        Opens the given serial port the right way for a Power control device.
        port (string): the name of the serial port (e.g., /dev/ttyUSB0)
        baudrate (int)
        return (serial): the opened serial port
        """
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=2  # s
        )

        # Purge
        ser.flush()
        ser.flushInput()

        # Try to read until timeout to be extra safe that we properly flushed
        ser.timeout = 0
        while True:
            char = ser.read()
            if char == b'':
                break
        ser.timeout = 1

        return ser


    def _find_device(self, baudrate=9600, simulated=False):
        """
        Look for a compatible device
        :param baudrate: (0<int)
        :param simulated: (str) use simulator if True
        :returns: (serial) the opened serial port
        :raises: (IOError) if no device are found
        """
        # For debugging purposes
        if simulated:
            serial = JOLTSimulator(timeout=0.1)
            return serial

        if os.name == "nt":
            ports = glob.glob("COM*")
        else:
            ports = glob.glob("/dev/ttyUSB*")

        for n in ports:
            try:
                serial = self._openSerialPort(n, baudrate)
                try:
                    self.send_null_cmd()  # stop if it's not the right hardware before disturbing it
                    idn = self.get_id()
                    if not "jolt" in idn.lower():
                        raise IOError("Device doesn't seem to be a JOLT, identified as: %s" % (idn,))
                except JOLTError:
                    # Can happen if the device has received some weird characters
                    # => try again (now that it's flushed)
                    logging.info("Device answered by an error, will try again")
                    idn = self.GetVersion()
                return n, idn
            except (IOError, JOLTError):
                logging.info("Skipping device on port %s, which didn't seem to be compatible", n)
                # not possible to use this port? next one!
                continue
        else:
            raise IOError("Check that Jolt is running, and check the connection "
                          "to the PC. No JOLT found on ports %s" %
                          (ports,))
        return serial
     
    def _send_cmd(self, cmd, args):
        """
        Packages command, sends it to the firmware and parses response
        :param cmd: (str) command code
        :param arg: ? multiple args? binary format?
        :returns: (None) no response to command (unlike _send_query)
        :raises: (JOLTError) error containing status code and corresponding message
        """

        # Package command
        print(cmd, args)
        msg = SOH + ID_CMD + cmd + b"%d" % len(args) + args + EOT
        print(msg)
        #msg = msg.encode('ascii')

        # Send frame
        with self._ser_access:
            logging.debug("Sending command %s", msg.decode('latin1'))
            self._serial.write(msg)
        
        # Parse status
        # Status response looks like this:
        # SOH + packet type + status code + US + status code + EOT
        stat = char = b""
        while char != EOT:
            char = self._serial.read()
            if not char:
                raise IOError("Timeout after receiving %s" % stat.decode('ascii'))
            stat += char
        logging.debug("Received status message %s" % stat)
        
        if stat[0:1] != SOH or stat[1:2] != ID_STATUS or stat[3:4] != US or stat[5:6] != EOT or stat[2:3] != stat[4:5]:
            raise IOError("Status message %s has unexpected format." % stat)
        if stat[2:3] != ACK:
            raise JOLTError(stat[2])

    def _send_query(self, cmd, args=b""):
        """
        Packages query, sends it to the firmware and parses response
        :param cmd: (str) command code
        :returns: (str) firmware response
        :raises: (JOLTError) error containing status code and corresponding message
        """

        # Package command
        print(args, 'args')
        msg = SOH + ID_CMD + cmd + b"%d" % len(args) + args + EOT
        #msg = msg.encode('ascii')

        # Send frame
        with self._ser_access:
            logging.debug("Sending command %s", msg.decode('latin1'))
            self._serial.write(msg)
        
        # Parse status
        # Status response looks like this:
        # SOH + packet type + status code + US + status code + EOT
        stat = char = b""
        while char != EOT:
            char = self._serial.read()
            if not char:
                raise IOError("Timeout after receiving %s" % stat.decode('ascii'))
            stat += char
        logging.debug("Received status message %s" % stat)
        
        if stat[0:1] != SOH or stat[1:2] != ID_STATUS or stat[3:4] != US or stat[5:6] != EOT or stat[2:3] != stat[4:5]:
            raise IOError("Status message %s has unexpected format." % stat)
        if stat[2:3] != ACK:
            raise JOLTError(stat[2])

        # Parse response
        # Response looks like this:
        # SOH + packet type + message length + message type + US + message + ETX + EOT
        resp = char = b""
        while char != EOT:
            char = self._serial.read()
            if not char:
                raise IOError("Timeout after receiving %s" % resp.decode('ascii'))
            resp += char
        logging.debug("Received response message %s" % resp)

        soh = resp[0]  # SOH
        enc = resp[1]  # M or B
        mlen = resp[2]  # length
        mtype = resp[3]  # type
        sep = resp[4]  # US separator
        m = resp[5:5+mlen]  # message
        etx = resp[-2]  # end of text
        eot = resp[-1]  # end of transmission

        if (soh != SOH or (enc != ID_ASCII or enc != ID_BIN) or sep != US
            or etx != ETX or eot != EOT):
            raise IOError("Status message %s has unexpected format." % resp)     
        
        return m.decode('ascii') if enc == ID_ASCII else chr(int(m))
        
    def terminate(self):
        pass

class JOLTSimulator():
    
    def __init__(self, timeout):
        self.timeout = timeout
        self._output_buf = b""  # what the commands sends back to the "host computer"
        self._input_buf = b""  # what we receive from the "host computer"

        # TODO: use reasonable numbers
        self.power = False
        self.voltage = 12  # V
        self.offset = 5
        self.gain = 10
        self.mppc_temp = 30
        self.sink_temp = 35
        self.mppc_current = 50
        self.vacuum_pressure = 23
        self.channel = CHANNEL_R
        self.channels = str(CHANNEL_R) + str(CHANNEL_G) + str(CHANNEL_B)

    def write(self, data):
        self._input_buf += data
        self._parseMessage(self._input_buf)  # will update _output_buf

        self._input_buf = self._input_buf[-len(data):]

    def read(self, size=1):
        print(self._output_buf)
        ret = self._output_buf[:size]
        self._output_buf = self._output_buf[len(ret):]

        if len(ret) < size:
            # simulate timeout
            time.sleep(self.timeout)
        return ret
    
    def flush(self):
        pass

    def flushInput(self):
        self._output_buf = b""

    def close(self):
        # using read or write will fail after that
        del self._output_buf
        del self._input_buf

    def _sendStatus(self, status):
        logging.debug("Sending status message %s" % status.decode('ascii'))
        self._output_buf += SOH + ID_STATUS + status + US + status + EOT#.encode('ascii')

    def _sendAnswer(self, ans, ptype=ID_ASCII):
        # TODO: message type (byte 4)
        logging.debug("Sending response %s" % ans.decode('ascii'))
        mtype = b'T'
        self._output_buf += SOH + ptype + b"%d" % len(ans) + mtype + US + ans + ETX + EOT  #.encode('ascii')

    def _parseMessage(self, msg):
        """
        msg (str): the message to parse (without the \r)
        return None: self._output_buf is updated if necessary
        """

        logging.debug("SIM: parsing %s", msg)

        com = msg[2:3]  # indexing byte returns int
        arglen = int(msg[3:4])
        print(msg, arglen, 'msg', com)
        args = [msg[4+i] for i in range(arglen)]
        
        if msg[0] != SOH or msg[-1] != EOT:
            # TODO: error code
            pass

        # decode the command
        if com == CMD_SET_POWER:
            self._sendStatus(ACK)
            self.power = args[0]
        elif com == CMD_GET_VOLTAGE:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.voltage)
        elif com == CMD_SET_VOLTAGE:
            self._sendStatus(ACK)
            self.voltage = int(args[0])
        elif com == CMD_GET_OFFSET:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.offset)
        elif com == CMD_SET_OFFSET:
            self._sendStatus(ACK)
            self.offset = int(args[0])
        elif com == CMD_GET_GAIN:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.gain)
        elif com == CMD_SET_GAIN:
            self._sendStatus(ACK)
            self.gain = int(args[0])
        elif com == CMD_GET_MPPC_TEMP:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.mppc_temp)
        elif com == CMD_SET_MPPC_TEMP:
            self._sendStatus(ACK)
            self.mppc_temp = int(args[0])
        elif com == CMD_GET_SINK_TEMP:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.sink_temp)
        elif com == CMD_GET_MPPC_CURRENT:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.mppc_current)
        elif com == CMD_GET_VACUUM_PRESSURE:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.vacuum_pressure)
        elif com == CMD_GET_CHANNEL:
            self._sendStatus(ACK)
            self._sendAnswer(b"%d" % self.channel)
        elif com == CMD_SET_CHANNEL:
            self._sendStatus(ACK)
            self.channel = int(args[0])
        elif com == CMD_GET_ERROR:
            self._sendStatus(ACK)
            # TODO: send what?
            self._sendAnswer(b"errorerrorerror")
        elif com == CMD_CALL_AUTO_BC:
            self._sendStatus(ACK)
            # do nothing
        elif com == CMD_GET_CHANNEL_LIST:
            self._sendStatus(ACK)
            self._sendAnswer(self.channels.encode('ascii'))
        else:
            # TODO: error code
            self._sendStatus(NAK)
