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
ID_STATUS = b"\x53"  # packet identifier status
ID_ASCII = b"\x4D"  # packet identifier ascii message
ID_BIN = b"\x04"  # packet identifier binary message
JOLT_V1_HW_IDENTIFIER = "rev. a"
JOLT_V2_HW_IDENTIFIER = "rev. b"


# Error codes, as defined in FrontEndBoard/SystemMediator.h:FaultState
class FrontEndErrorCodes(enum.Enum):
    P5OutOfRange = 0
    M5OutOfRange = 1
    VBiasOutOfRange = 2
    HotPlateTemperatureOutOfRange = 3
    ColdPlateTemperatureOutOfRange = 4
    PGACalibrationFailed = 5
    PressureOutOfRange = 6
    TPressureOutOfRange =7
    NoFault = 8  # means everything OK

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
CMD_GET_FRONTEND_OUTPUT_VOLTAGE = 0x8a  # Read output signal output voltage of frontend board
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
CMD_GET_ERROR = 0x9e  # FrontEnd fault state
CMD_GET_SYSTEM_STATE = 0xd0
CMD_GET_FAULT_STATE = 0xd1  # ComputerBoard fault state
CMD_GET_TEMP_ERROR = 0xd3
CMD_GET_TEMP_INTEGRAL = 0xd2


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
        # Let's see if it actually raises
        self._serial = self._find_device(simulated=simulated)
        self.counter = 0

        # Version handling
        be_hw_version = self.get_be_hw_version().lower()
        if JOLT_V1_HW_IDENTIFIER in be_hw_version:
            logging.info("JOLT V1 detected")
            self.version = 1
        elif JOLT_V2_HW_IDENTIFIER in be_hw_version:
            logging.info("JOLT V2 detected")
            self.version = 2
        else:
            self.version = -1
            logging.warning(f"Could not detect JOLT version for be_hw_version: {be_hw_version}")

        # If JOLT V1 or unknown (probably also a V1)
        if self.version <= 1:
            self.voltage_range = (52, 70)
        else:
            # Set lower voltages for the JOLT V2.
            self.voltage_range = (30, 37)  # Min useful / Max

        self.adjust_voltage_thread = None
        self.stop_adjust_voltage_event = threading.Event()

    def sanitize(func):
        """
        Wrapper to sanitize strings obtained over serial connection. Most serial number and version getters seem to have
        unwanted characters at the end. This is consistent per method, but the characters might differ between methods.
        """
        def wrapper(self, *args, **kwargs):
            return func(self, *args, **kwargs).rstrip("\x00\x03")
        return wrapper

    @sanitize
    def get_fe_sn(self):
        """
        :returns: (str) frontend serial number
        """
        b = self._send_query(CMD_GET_FRONTEND_SERIAL_NUM)  # 40 bytes
        return b.decode('latin1')

    @sanitize
    def get_fe_fw_version(self):
        """
        :returns: (str) frontend firmware version
        """
        b = self._send_query(CMD_GET_FRONTEND_FW_VER)  # 40 bytes
        return b.decode('latin1')

    @sanitize
    def get_fe_hw_version(self):
        """
        :returns: (str) frontend hardware version
        """
        b = self._send_query(CMD_GET_FRONTEND_VER)  # 40 bytes
        return b.decode('latin1')

    @sanitize
    def get_be_sn(self):
        """
        :returns: (str) backend serial number
        """
        b = self._send_query(CMD_GET_SERIAL_NUM)  # 40 bytes
        return b.decode('latin1')

    @sanitize
    def get_be_fw_version(self):
        """
        :returns: (str) backend (computer board) firmware version
        """
        b = self._send_query(CMD_GET_FIRMWARE_VER)  # 40 bytes
        return b.decode('latin1')

    @sanitize
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

    def set_voltage(self, val: float) -> None:
        """
        :param val: (lower_bound <= float <= upper_bound): vbias in V
        :returns: (None)
        """
        if not 0 <= val <= self.voltage_range[1]:
            logging.warning(f"Voltage {val:.6f} out of range 0 <= vol <= {self.voltage_range[1]}")
        # Voltage is in fact negative, but this might be confusing in the GUI?
        # Value needs to be between -upper and 0.
        val = -val
        b = int(val * 1e6).to_bytes(4, 'little', signed=True)
        self._send_cmd(CMD_SET_VOLTAGE, b)

    def adjust_voltage(self, target: float, timeout: float = 5) -> None:
        """
        Asynchronously adjusts the voltage to the target value within the specified timeout.

        This function starts a new thread to adjust the voltage to the target value. If a previous adjustment
        is still running, it will be stopped before starting a new one. The adjustment process will repeatedly
        set the voltage and measure it until the target value is reached within a specified tolerance or the
        timeout is exceeded.

        :param target: The target voltage value to be reached (0 <= float <= max_voltage).
        :param timeout: The maximum time in seconds to attempt adjusting the voltage.
        :returns: None
        :sideeffects: Starts a new thread to adjust the voltage.
        """
        def run():
            voltage = target
            voltage_delta = 1000  # Something large
            start_time = time.time()
            while abs(voltage_delta) > 0.01 and not self.stop_adjust_voltage_event.is_set():
                self.set_voltage(voltage)
                self.stop_adjust_voltage_event.wait(0.2)  # Wait to settle
                measured_voltage = self.get_voltage()
                logging.debug(f"Setting voltage (forced). Target: {target}, adjusted target: {voltage}, measured voltage: {measured_voltage}")
                voltage_delta = target - measured_voltage
                voltage += voltage_delta
                if time.time() - start_time > timeout:
                    logging.warning(f"Failed adjusting voltage to reach {target} V (currently {measured_voltage} V) within timeout ({timeout} s)")
                    break

        # Stop any existing thread
        if self.adjust_voltage_thread and self.adjust_voltage_thread.is_alive():
            self.stop_adjust_voltage_event.set()
            self.adjust_voltage_thread.join(2)  # Wait for termination or timeout after 2 seconds

        # Clear the stop event and start a new thread
        self.stop_adjust_voltage_event.clear()
        self.adjust_voltage_thread = threading.Thread(target=run)
        self.adjust_voltage_thread.start()

    def get_gain(self):
        """
        :returns: (0 <= float <= 100): PGA gain percentage
        """
        b = self._send_query(CMD_GET_GAIN)  # 4 bytes, 5e5 - 64e6
        gain = int.from_bytes(b, 'little', signed=True) * 1e-6
        gain = (gain - 0.5) / 63.5 * 100
        return gain

    def set_gain(self, val):
        """
        :param val: (0 <= float <= 100): PGA gain percentage to be set
        :returns: (None)
        """
        # Map percentage to a value between 0.5 and 64 V
        val = (val / 100 * 63.5) + 0.5
        if not 0.5 <= val <= 64:
            # TODO: raise error instead of just logging
            logging.error(f"Gain {val:.6f} out of range 0.5 <= gain <= 64.")
            # Clip for now
            val = 0.5 if val < 0.5 else 64
            logging.error(f"Clipped gain to {val:.6f}")
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
        if not 0 <= val <= 4095:
            # TODO: raise error instead of just logging
            logging.error(f"Offset {val:.6f} out of range 0 <= offset <= 4095")
            # Clip for now
            val = 0 if val < 0 else 4095
            logging.error(f"Clipped offset to {val:.6f}")
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

    def get_frontend_output_voltage(self):
        """
        :returns: Signal output voltage on frontend board
        """
        # The command returns a int32
        b = self._send_query(CMD_GET_FRONTEND_OUTPUT_VOLTAGE)
        return int.from_bytes(b, 'little', signed=True) * 1e-6

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

    def get_output_differential(self):
        """
        :returns: (-100 <= float <= 100): differential output
        #TODO: investigate range, since it is not clear what this value represents
        """
        b = self._send_query(CMD_GET_DIFFERENTIAL_PLUS_READING)
        plus = int.from_bytes(b, 'little', signed=True)
        b = self._send_query(CMD_GET_DIFFERENTIAL_MINUS_READING)
        minus = int.from_bytes(b, 'little', signed=True)

        return (plus - minus) / 4095 * 100

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

    def get_temp_error(self):
        """
        :returns (int): error status
        """
        b = self._send_query(CMD_GET_TEMP_ERROR)  # 1 byte
        return int.from_bytes(b, 'little', signed=True)

    def get_temp_integral(self):
        """
        :returns (int): error status
        """
        b = self._send_query(CMD_GET_TEMP_INTEGRAL)  # 1 byte
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
                logging.info("Test compatibility of device %s", n)
                serial = self._openSerialPort(n, baudrate)
                logging.info("Opened connection to device %s", n)
                self._serial = serial
                logging.info("Attempt to retrieve hw info from device %s", n)
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
                char = self._serial.read(1)
                if not char:
                    raise IOError("Timeout after receiving %s" % stat)
                stat += char
            #logging.debug("Received status %s" % stat)
            # TODO: validate status is ACK

            # Read response
            # SOH + packet type + length + US + message + EOT
            resp = b''
            resp += self._serial.read(2)  # SOH, message type
            message_type = resp[1:2]
            if message_type == ID_ASCII:  # String message
                char = b""
                # Check if last character is EOT and then stop
                while resp[-1:] != EOT:
                    resp += self._serial.read()
                ret = resp[3:-1]

            # TODO: explicitly check for the type, and raise an error (but still try to read up to EOT)
            # elif message_type == ID_BIN:  # Binary data
            else:
                l = self._serial.read(1)  # argument length
                resp += l
                l = int.from_bytes(l, 'little', signed=True)
                resp += self._serial.read(1)  # US
                # TODO: validate this is "US"
                resp += self._serial.read(l)  # message
                resp += self._serial.read(1)  # EOT
                # TODO: validate this is EOT
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
        self.hot_plate_temp = int(30e6)  # µC
        self.output = int(800)  # µV
        self.vacuum_pressure = int(3e3)  # µBar
        self.channel = Channel.RED
        self.itec = int(10e6)
        self.fe_offset = int(513)
        self.fe_output_voltage = int(1e6)  # µV

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
            self._sendAnswer(b'SIMULATED_HARDWARE_rev. b' + 22 * b'x')
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
            voltage = self.voltage + random.randint(-1e4, 1e4)
            self._sendAnswer(voltage.to_bytes(4, 'little', signed=True))
        elif com == CMD_SET_VOLTAGE:
            self._sendStatus(ACK)
            voltage = int.from_bytes(arg, 'little', signed=True)
            # Try to replicate a deviation as observed in real life
            deviation = int((-4e-6 * (voltage * 1e-6) ** 3) * 1e6)
            self.voltage = voltage + deviation
            self._update_frontend_output_voltage()
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
            self._update_frontend_output_voltage()
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
            self._modify_cold_plate_temp()
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
            error = FrontEndErrorCodes.NoFault.value
            self._sendAnswer(error.to_bytes(1, 'little', signed=False))
        elif com == CMD_CALL_AUTO_BC:
            self._sendStatus(ACK)
            # do nothing
        elif com == CMD_GET_CHANNEL_LIST:
            logging.error("not implemented")
        elif com == CMD_GET_FRONTEND_OUTPUT_VOLTAGE:
            self._sendStatus(ACK)
            self._update_frontend_output_voltage()
            self._sendAnswer(self.fe_output_voltage.to_bytes(4, 'little', signed=True))
        else:
            # TODO: error code
            logging.error("Unknown command %s" % com)
            self._sendStatus(NAK)

    @staticmethod
    def simulate_frontend_output_voltage(fe_offset, voltage):
        # Estimate operating voltage influence on output voltage intercept with linear model parameters:
        # (0.002653871656383483, 0.02920275957021566)
        # With constant slope: -0.000164
        # Note that the linear model is a simplification, in practice it is more exponential.
        estimation = 1e6 * (-0.0001640 * fe_offset + (-0.002653 * voltage * 1e-6  + 0.029203))
        # NOTE: noise is not simulated here
        # NOTE: this was derived at min gain, and the output significantly deviates for different gain
        # NOTE: the signal cannot go bellow zero
        return int(max(0, estimation))

    def _update_frontend_output_voltage(self):
        self.fe_output_voltage = self.simulate_frontend_output_voltage(self.fe_offset, self.voltage)

    def _modify_cold_plate_temp(self):
        self.cold_plate_temp = int(self.mppc_temp + random.randint(-2e4, 2e4))

    def _modify_pressure(self):
        self.vacuum_pressure += random.randint(-0.1e3, 0.1e3)
        self.vacuum_pressure = max(self.vacuum_pressure, 0)

    def _modify_hp_temperature(self):
        self.hot_plate_temp += random.randint(-1e6, 1e6)

    def _change_temp(self):
        self._stop_thread = False
        delta = self.mppc_temp - self.cold_plate_temp

        # Values in uC
        while not self._stop_thread and abs(delta) > 0.1 * 1e6:
            delta = self.mppc_temp - self.cold_plate_temp
            self.cold_plate_temp += int(delta // 1.5)
            time.sleep(1)
