#!/usr/bin/env python3
from NXPISP.ISPProgrammer import LPC80x, LPC84x, LPC175_6x
import click

INSTALLED_FAMILIES = (
    LPC80x, 
    LPC84x,
    LPC175_6x
)
BAUDRATES = (
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    460800
)
DEFAULT_BAUD = BAUDRATES[3]# breaks with 115200

CHIPS = []
for family in INSTALLED_FAMILIES:
    CHIPS.extend(family.Family)

def SetupChip(chipname, device="/dev/ttyUSB0"):
    chip = None
    for ChipFamily in INSTALLED_FAMILIES:
        if chipname in ChipFamily.Family:
            chip = ChipFamily(device, baudrate = ChipFamily.MAXBAUDRATE) 
            break
    
    if(chip is None):
        raise UserWarning("Chip %s unknown"%chipname)

    chip.InitConnection()
    print("Initiated %s"%chipname)
    chip.ChangeBaudRate(chip.MAXBAUDRATE)
    print("Setup chip Baudrate set to:", chip.MAXBAUDRATE)

    return chip

