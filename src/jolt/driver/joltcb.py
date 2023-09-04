#!/usr/bin/env python3
'''
Created on 1 Oct 2019
@author: Philip Winkler
Copyright © 2019 Philip Winkler, Delmic

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

import enum
import os
import serial
import logging
import time
import threading
import random
from serial.tools.list_ports import comports

SOH = b"\x01"  # start of header
EOT = b"\x04"  # end of transmission
ACK = b"\x06"  # acknowledgement
NAK = b"\x15"
US = b"\x1F"  # unit separator
ETX = b"\x03"  # end of text
ID_CMD = b"\x43"  # packet identifier command
ID_STATUS = b"\x53"  # packet identifier command
ID_ASCII = b"\x4D"  # packet identifier ascii message
ID_BIN = b"\x04"  # packet identifier binary message

ERROR_CODE_OK = 8  # 8 means everything OK

CMD_GET_VERSION = 0x60
CMD_GET_FIRMWARE_VER = 0x61
CMD_GET_COMPILE_DATE = 0x62
CMD_GET_COMPILE_TIME = 0x63
CMD_GET_SERIAL_NUM = 0x64
CMD_GET_FRONTEND_VER = 0x70
CMD_GET_FRONTEND_FW_VER = 0x71
CMD_GET_FRONTEND_COMPILE_DATE = 0x72
CMD_GET_FRONTEND_COMPILE_TIME = 0x73
CMD_GET_FRONTEND_SERIAL_NUM = 0x74
CMD_GET_FRONTEND_VBIAS = 0x95
CMD_GET_COLD_PLATE_TEMP = 0x8c
CMD_GET_HOT_PLATE_TEMP = 0x8d
CMD_CALL_AUTO_BC = 0x00
CMD_GET_CHANNEL_LIST = 0x00
CMD_GET_MPPC_TEMP = 0xb1
CMD_GET_OUTPUT_SINGLE_ENDED = 0xbe
CMD_GET_DIFFERENTIAL_PLUS_READING = 0xbb
CMD_GET_DIFFERENTIAL_MINUS_READING = 0xbc
CMD_GET_HOT_PLATE_TEMP = 0x8d
CMD_GET_VACUUM_PRESSURE = 0x92
CMD_SET_GAIN = 0x89
CMD_SET_CHANNEL = 0x91
CMD_SET_VOLTAGE = 0xc9
CMD_SET_OFFSET = 0xbf
CMD_GET_GAIN = 0x88
CMD_GET_CHANNEL = 0x90
CMD_GET_VOLTAGE = 0xca
CMD_GET_OFFSET = 0xE0
CMD_GET_COLD_PLATE_TEMP = 0x8c
CMD_SET_MPPC_TEMP = 0xb0
CMD_GET_ITEC = 0xcd
CMD_SET_DIFFERENTIAL_OUTPUT = 0xba
CMD_SET_SINGLE_ENDED_OUTPUT = 0xbd
CMD_GET_VOS_ADJ_SETTING = 0x9a  # Offset voltage on frontend board
CMD_SET_VOS_ADJ_SETTING = 0x9b
CMD_GET_ERROR = 0x9e

CMD_CB_ISP = 0xfe
CMD_FW_ISP = 0xff
CMD_PASSTHROUGH_MODE = 0x65

SAFERANGE_MPCC_CURRENT = (-5000, 5000)
SAFERANGE_MPCC_TEMP = (-20, 20)  # °C
SAFERANGE_HEATSINK_TEMP = (-20, 40)  # °C
SAFERANGE_VACUUM_PRESSURE = (0, 5)  # mbar


class Channel(enum.Flag):
    NONE = 0
    RED = 1
    BLUE = 2
    GREEN = 4
    PANCHROMATIC = 7


class JOLTError(Exception):

    def __init__(self, code):
        # TODO: Map code to message
        super(JOLTError, self).__init__(code)
        self.code = code

    def __str__(self):
        return self.args[1]

class JOLTComputerBoard():
    
    def __init__(self, simulated=False):
        self._ser_access = threading.Lock()
        self._serial = self._find_device(simulated=simulated)
        self.counter = 0
        
    def get_fe_sn(self):
        """
        :returns: (str) frontend serial number
        """
        b = self._send_query(CMD_GET_FRONTEND_SERIAL_NUM)  # 40 bytes
        return b.decode('latin1')

    def get_fe_fw_version(self):
        """
        :returns: (str) frontend firmware version
        """
        b = self._send_query(CMD_GET_FRONTEND_FW_VER)  # 40 bytes
        return b.decode('latin1')

    def get_fe_hw_version(self):
        """
        :returns: (str) frontend hardware version
        """
        b = self._send_query(CMD_GET_FRONTEND_VER)  # 40 bytes
        return b.decode('latin1')

    def get_be_sn(self):
        """
        :returns: (str) backend serial number
        """
        b = self._send_query(CMD_GET_SERIAL_NUM)  # 40 bytes
        return b.decode('latin1')

    def get_be_fw_version(self):
        """
        :returns: (str) backend (computer board) firmware version
        """
        b = self._send_query(CMD_GET_FIRMWARE_VER)  # 40 bytes
        return b.decode('latin1')
    
    def get_be_hw_version(self):
        """
        :returns: (str) backend (computer board) hardware version
        """
        b = self._send_query(CMD_GET_VERSION)  # 40 bytes
        return b.decode('latin1')

    def set_signal_type(self, single_ended):
        """
        :arg single_ended: True for single ended, false for differential
        """
        if single_ended:
            self._send_cmd(CMD_SET_DIFFERENTIAL_OUTPUT, bytes([0x00]))
            self._send_cmd(CMD_SET_SINGLE_ENDED_OUTPUT, bytes([0xff]))
        else:
            self._send_cmd(CMD_SET_SINGLE_ENDED_OUTPUT, bytes([0x00]))
            self._send_cmd(CMD_SET_DIFFERENTIAL_OUTPUT, bytes([0xff]))

    def set_power(self, val):
        """
        :param val: (bool) True for on, False for off
        :returns: (None)
        """
        raise NotImplementedError()
    
    def get_voltage(self):
        """
        :returns: (0 <= float <= 80): vbias in V
        """
        b = self._send_query(CMD_GET_VOLTAGE)  # 4 bytes, -80e6 - 0
        return int.from_bytes(b, 'little', signed=True) * -1e-6
    
    def set_voltage(self, val):
        """
        :param val: (0 <= float <= 80): vbias in V
        :returns: (None)
        """
        if not 0 <= val <= 80:
            logging.error("Voltage %.6f out of range 0 <= vol <= 80." % val)
        # Voltage is in fact negative, but this might be confusing in the GUI?
        # Value needs to be between -80 and 0.
        val = -val
        b = int(val * 1e6).to_bytes(4, 'little', signed=True)
        self._send_cmd(CMD_SET_VOLTAGE, b)
    
    def get_gain(self):
        """
        :returns: (0.5 <= float <= 64): PGA gain
        """
        b = self._send_query(CMD_GET_GAIN)  # 4 bytes, 5e5 - 64e6
        gain = int.from_bytes(b, 'little', signed=True) * 1e-6
        gain = (gain - 0.5) / 63.5 * 100
        return gain
    
    def set_gain(self, val):
        """
        :param val: (0.5 <= float <= 64): PGA gain to be set
        :returns: (None)
        """
        # Gain must be between 0.5 and 64 V, scale from [0, 100]
        val = (val / 100 * 63.5) + 0.5
        if not 0.5 <= val <= 64:
            # TODO: raise error instead of just logging
            logging.error("Gain %.6f out of range 0.5 <= gain <= 64." % val)
        b = int(val * 1e6).to_bytes(4, 'little', signed=True)
        self._send_cmd(CMD_SET_GAIN, b)
    
    def get_offset(self):
        """
        :returns: (0 <= float <= 100) output offset
        """
        b = self._send_query(CMD_GET_OFFSET)  # 4 bytes
        offset = int.from_bytes(b, 'little', signed=True)
        offset = offset / 4095 * 100
        return offset

    def set_offset(self, val):
        """
        :param val: (0 <= float <= 100) output offset
        :returns: (None)
        """
        # Offset is between 0 and 4095 V, scale from [0, 100]
        val = val / 100 * 4095
        b = int(val).to_bytes(4, 'little', signed=True)
        self._send_cmd(CMD_SET_OFFSET, b)

    def get_frontend_offset(self):
        """
        :returns: (0 <= int <= 1023) Offset voltage on frontend board
        """
        # The command returns a uint32
        # Offset is between 0 and 1023 (10 bits)
        b = self._send_query(CMD_GET_VOS_ADJ_SETTING)  # 4 bytes
        offset = int.from_bytes(b, 'little', signed=False)
        return offset

    def set_frontend_offset(self, val):
        """
        :param val: (0 <= int <= 1023) Offset voltage on frontend board
        :returns: (None)
        """
        if not (0 <= val <= 1023):
            raise ValueError(f"Frontend offset voltage should be between 0 and 1023, got {val}")
        # The command takes a uint32
        # Offset is between 0 and 1023 (10 bits)
        b = int(val).to_bytes(4, 'little', signed=False)
        self._send_cmd(CMD_SET_VOS_ADJ_SETTING, b)

    def get_mppc_temp(self):
        """
        :returns: (-20 <= float <= 70): temperature in C
        """
        b = self._send_query(CMD_GET_MPPC_TEMP)
        return int.from_bytes(b, 'little', signed=True) * 1e-6
  
    def set_target_mppc_temp(self, val):
        """
        :param val: (-20 <= float <= 70): temperature in C
        :returns: (None)
        """
        if not -20 <= val <= 70:
            logging.error("Temperature %.6f out of range -20 <= temp <= 70." % val)
        b = int(val * 1e6).to_bytes(4, 'little', signed=True)
        self._send_cmd(CMD_SET_MPPC_TEMP, b)
    
    def get_cold_plate_temp(self):
        """
        :returns: (-20 <= float <= 70): temperature in C
        """
        b = self._send_query(CMD_GET_COLD_PLATE_TEMP)  # 4 bytes, -20e6 - 70e6
        return int.from_bytes(b, 'little', signed=True) * 1e-6
    
    def get_hot_plate_temp(self):
        """
        :returns: (-20 <= float <= 70): temperature in C
        """
        b = self._send_query(CMD_GET_HOT_PLATE_TEMP)  # 4 bytes, -20e6 - 70e6
        return int.from_bytes(b, 'little', signed=True) * 1e-6
    
    def get_output_single_ended(self):
        """
        :returns: (0 <= float <= 100): single-ended output
        """
        b = self._send_query(CMD_GET_OUTPUT_SINGLE_ENDED)  # 4 bytes, 0 - 4095
        return int.from_bytes(b, 'little', signed=True) / 4095 * 100

    def get_plus_reading_differential(self):
        """
        :returns: (0 <= float <= 100): differential output, plus side
        """
        b = self._send_query(CMD_GET_DIFFERENTIAL_PLUS_READING)  # 4 bytes, 0 - 4095
        return int.from_bytes(b, 'little', signed=True) / 4095 * 100

    def get_minus_reading_differential(self):
        """
        :returns: (0 <= float <= 100): differential output, minus side
        """
        b = self._send_query(CMD_GET_DIFFERENTIAL_MINUS_READING)  # 4 bytes, 0 - 4095
        return int.from_bytes(b, 'little', signed=True) / 4095 * 100

    def get_vacuum_pressure(self):
        """
        :returns: (10 <= float <= 1200) pressure in mBar
        """
        b = self._send_query(CMD_GET_VACUUM_PRESSURE)  # 4 bytes, 10e3 - 12e6
        return int.from_bytes(b, 'little', signed=True) * 1e-3
    
    def get_channel(self) -> Channel:
        """
        :returns: Channel: color channel
        """
        b = self._send_query(CMD_GET_CHANNEL)  # 1 byte
        value = int.from_bytes(b, 'little', signed=True)
        return Channel(value)

    def set_channel(self, channel: Channel) -> None:
        """
        :param channel: Channel: color channel
        :returns: (None)
        """
        if not isinstance(channel, Channel):
            logging.error("Unknown channel %s, needs to be of type Channel.", channel)
        b = channel.value.to_bytes(1, 'little', signed=True)
        self._send_cmd(CMD_SET_CHANNEL, b)

    def get_itec(self):
        """
        :returns (int): tec current
        """
        b = self._send_query(CMD_GET_ITEC)  # 1 byte
        return int.from_bytes(b, 'little', signed=True)

    def get_error_status(self):
        """
        :returns (int): error status
        """
        b = self._send_query(CMD_GET_ERROR)  # 1 byte
        return int.from_bytes(b, 'little', signed=True)

    def set_cb_isp_mode(self):
        """
        ISP mode for computer board
        """
        self._send_cmd(CMD_CB_ISP, (235).to_bytes(1, 'little', signed=False))
        
    def set_fb_isp_mode(self):
        """
        ISP mode for frontend (requires frontend firmware to be present)
        """
        self._send_cmd(CMD_FW_ISP, (235).to_bytes(1, 'little', signed=False))

    def set_passthrough_mode(self):
        """
        ISP mode for frontend if frontend doesn't contain firmware
        """
        self._send_cmd(CMD_PASSTHROUGH_MODE, (255).to_bytes(1, 'little', signed=False))

    def call_auto_bc(self):
        raise NotImplementedError()


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
        ser.timeout = 0.1

        return ser


    def _find_device(self, baudrate=115200, simulated=False):
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

        ports = [p.device for p in comports()]
 
        for n in ports:
            try:
                serial = self._openSerialPort(n, baudrate)
                self._serial = serial
                idn = self.get_be_hw_version()
                if not "jolt" in idn.lower():
                    raise IOError("Device doesn't seem to be a JOLT, identified as: %s" % (idn,))
                self.portname = n
                return serial
            except:
                logging.info("Skipping device on port %s, which didn't seem to be compatible", n)
                # not possible to use this port? next one!
                continue
        else:
            self.portname = None
            raise IOError("Check that Jolt is running, and check the connection "
                          "to the PC. No JOLT found on ports %s" %
                          (ports,))
        return serial
     
    def _send_cmd(self, cmd, arg=b''):
        """
        Frames command, sends it to the firmware and parses response
        :param cmd: (bytes) command code
        :param arg: (bytes) argument
        :returns: (None) no response to command (unlike _send_query)
        :raises: (JOLTError) error containing status code and corresponding message
        """
        # Frame command
        cmd = chr(cmd).encode('latin1')
        msg = SOH + ID_CMD + len(arg).to_bytes(1, 'little', signed=True) + cmd + arg + EOT

        # Send frame
        with self._ser_access:
            # logging.debug("Sending command %s", msg)
            self._serial.write(msg)
        
            # Parse status
            # Status response looks like this:
            # SOH + packet type + status code + US + status code + EOT
            stat = char = b""
            while char != EOT:
                char = self._serial.read()
                if not char:
                    raise IOError("Timeout after receiving %s" % stat)
                stat += char
            #logging.debug("Received status message %s" % stat)

    def _send_query(self, cmd, arg=b""):
        """
        Frames query, sends it to the firmware and parses response
        :param cmd: (bytes) command code
        :param arg: (bytes): argument
        :returns: (bytes) firmware response
        :raises: (JOLTError) error containing status code and corresponding message
        """
        # Frame command
        cmd = chr(cmd).encode('latin1')
        msg = SOH + ID_CMD + len(arg).to_bytes(1, 'little', signed=True) + cmd + arg + EOT

        # Send frame
        with self._ser_access:
            #logging.debug("Sending query %s", msg)
            self._serial.write(msg)

            # Parse status
            # Status response looks like this:
            # SOH + packet type + status code + US + status code + EOT
            stat = char = b""
            while char != EOT:
                char = self._serial.read()
                if not char:
                    raise IOError("Timeout after receiving %s" % stat)
                stat += char
            #logging.debug("Received status %s" % stat)

            # Read response
            resp = b''
            resp += self._serial.read(2)  # SOH, message type
            if resp[1] == ord(b'M'):  # message type
                char = b""
                while resp[-1] != ord(EOT):
                    resp += self._serial.read()
                ret = resp[3:-2]
            else:  # binary type
                l = self._serial.read()  # argument length
                resp += l
                l = int.from_bytes(l, 'little', signed=True)
                resp += self._serial.read(1)  # US
                resp += self._serial.read(l)  # message
                resp += self._serial.read(1)  # EOT
                ret = resp[4:-1]
            #logging.debug("Received response %s" % resp)
            return ret
        
    def terminate(self):
        pass

class JOLTSimulator():
    
    def __init__(self, timeout):
        self.timeout = timeout
        self._output_buf = b""  # what the commands sends back to the "host computer"
        self._input_buf = b""  # what we receive from the "host computer"

        # TODO: use reasonable numbers
        self.power = False
        self.voltage = int(-12e6)  # µV
        self.offset = int(5e6)  # µV
        self.gain = int(10e6)  # µV
        self.mppc_temp = int(30e6)  # µC
        self.cold_plate_temp = int(24e6)  # µC
        self.hot_plate_temp = int(35e6)  # µC
        self.output = int(800)  # µV
        self.vacuum_pressure = int(3e3)  # µBar
        self.channel = Channel.RED
        self.itec = int(10e6)
        self.fe_offset = int(513)

        self._temp_thread = None
        self._stop_thread = False  # temperature thread

    def write(self, data):
        self._input_buf += data
        self._parseMessage(self._input_buf)  # will update _output_buf

        self._input_buf = b''

    def read(self, size=1):
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
        #logging.debug("Sending status message %s" % status)
        self._output_buf += SOH + ID_STATUS + status + US + status + EOT

    def _sendAnswer(self, ans, ptype=ID_ASCII):
        # TODO: message type (byte 4)
        #logging.debug("Sending response %s" % ans)
        mtype = 'B'.encode('latin1')
        self._output_buf += SOH + mtype + len(ans).to_bytes(1, 'little', signed=True) + US + ans + EOT

    def _parseMessage(self, msg):
        """
        msg (str): the message to parse (without the \r)
        return None: self._output_buf is updated if necessary
        """

        #logging.debug("SIM: parsing %s", msg)

        com = msg[3]
        arglen = msg[2]
        arg = msg[4:4+arglen]
        
        if msg[0] != SOH or msg[-1] != EOT:
            # TODO: error code
            pass

        # decode the command
        if com == CMD_GET_FIRMWARE_VER:
            self._sendStatus(ACK)
            self._sendAnswer(b'SIMULATED_FIRMWARE' + 22 * b'x')
        elif com == CMD_GET_VERSION:
            self._sendStatus(ACK)
            self._sendAnswer(b'SIMULATED_HARDWARE' + 22 * b'x')
        elif com == CMD_GET_FRONTEND_FW_VER:
            self._sendStatus(ACK)
            self._sendAnswer(b'SIMULATED_FIRMWARE' + 22 * b'x')
        elif com == CMD_GET_FRONTEND_VER:
            self._sendStatus(ACK)
            self._sendAnswer(b'SIMULATED_HARDWARE' + 22 * b'x')
        elif com == CMD_GET_SERIAL_NUM:
            self._sendStatus(ACK)
            self._sendAnswer(b'SIMULATED_00000000' + 22 * b'x')
        elif com == CMD_GET_FRONTEND_SERIAL_NUM:
            self._sendStatus(ACK)
            self._sendAnswer(b'SIMULATED_00000000' + 22 * b'x')
        elif com == CMD_GET_VOLTAGE:
            self._sendStatus(ACK)
            self._sendAnswer(self.voltage.to_bytes(4, 'little', signed=True))
        elif com == CMD_SET_VOLTAGE:
            self._sendStatus(ACK)
            self.voltage = int.from_bytes(arg, 'little', signed=True)
        elif com == CMD_GET_OFFSET:
            self._sendStatus(ACK)
            self._sendAnswer(self.offset.to_bytes(4, 'little', signed=True))
        elif com == CMD_SET_OFFSET:
            self._sendStatus(ACK)
            self.offset = int.from_bytes(arg, 'little', signed=True)
        elif com == CMD_GET_VOS_ADJ_SETTING:
            self._sendStatus(ACK)
            self._sendAnswer(self.fe_offset.to_bytes(4, 'little', signed=False))
        elif com == CMD_SET_VOS_ADJ_SETTING:
            self._sendStatus(ACK)
            self.fe_offset = int.from_bytes(arg, 'little', signed=False)
        elif com == CMD_GET_GAIN:
            self._sendStatus(ACK)
            self._sendAnswer(self.gain.to_bytes(4, 'little', signed=True))
        elif com == CMD_SET_GAIN:
            self._sendStatus(ACK)
            self.gain = int.from_bytes(arg, 'little', signed=True)
        elif com == CMD_GET_MPPC_TEMP:
            self._sendStatus(ACK)
            self._sendAnswer(self.mppc_temp.to_bytes(4, 'little', signed=True))
        elif com == CMD_SET_MPPC_TEMP:
            self._sendStatus(ACK)
            if self._temp_thread:  # if it's already changing temperature, stop it
                self._stop_thread = True
                self._temp_thread.join()
            self.mppc_temp = int.from_bytes(arg, 'little', signed=True)
            self._temp_thread = threading.Thread(target=self._change_temp).start()
        elif com == CMD_GET_HOT_PLATE_TEMP:
            self._modify_hp_temperature()
            self._sendStatus(ACK)
            self._sendAnswer(self.hot_plate_temp.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_COLD_PLATE_TEMP:
            self._sendStatus(ACK)
            self._sendAnswer(self.cold_plate_temp.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_OUTPUT_SINGLE_ENDED:
            self._sendStatus(ACK)
            self._sendAnswer(self.output.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_DIFFERENTIAL_PLUS_READING:
            self._sendStatus(ACK)
            self._sendAnswer(self.output.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_DIFFERENTIAL_MINUS_READING:
            self._sendStatus(ACK)
            self._sendAnswer(self.output.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_VACUUM_PRESSURE:
            self._sendStatus(ACK)
            self._modify_pressure()
            self._sendAnswer(self.vacuum_pressure.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_CHANNEL:
            self._sendStatus(ACK)
            self._sendAnswer(self.channel.value.to_bytes(1, 'little', signed=True))
        elif com == CMD_SET_CHANNEL:
            self._sendStatus(ACK)
            self.channel = Channel(int.from_bytes(arg, 'little', signed=True))
        elif com == CMD_SET_DIFFERENTIAL_OUTPUT:
            self._sendStatus(ACK)
            # do nothing
        elif com == CMD_SET_SINGLE_ENDED_OUTPUT:
            self._sendStatus(ACK)
            # do nothing
        elif com == CMD_GET_ITEC:
            self._sendStatus(ACK)
            self._sendAnswer(self.itec.to_bytes(4, 'little', signed=True))
        elif com == CMD_GET_ERROR:
            self._sendStatus(ACK)
            self._sendAnswer(ERROR_CODE_OK.to_bytes(1, 'little', signed=False))
        elif com == CMD_CALL_AUTO_BC:
            self._sendStatus(ACK)
            # do nothing
        elif com == CMD_GET_CHANNEL_LIST:
            logging.error("not implemented")
        else:
            # TODO: error code
            logging.error("Unknown command %s" % com)
            self._sendStatus(NAK)

    def _modify_pressure(self):
        self.vacuum_pressure += random.randint(-0.1e3, 0.1e3)
        self.vacuum_pressure = max(self.vacuum_pressure, 0)

    def _modify_hp_temperature(self):
        self.hot_plate_temp += random.randint(-2e6, 2e6)

    def _change_temp(self):
        self._stop_thread = False
        if self.cold_plate_temp > self.mppc_temp:
            while not self._stop_thread and self.cold_plate_temp - self.mppc_temp > 0:
                self.cold_plate_temp -= 5000000
                time.sleep(2)
        else:
            while not self._stop_thread and self.cold_plate_temp - self.mppc_temp < 0:
                self.cold_plate_temp += 5000000
                time.sleep(2)
