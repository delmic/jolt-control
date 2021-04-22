![Delmic](./src/jolt/gui/img/delmic_logo.png  "Delmic")
# Jolt Control
This repository contains the control software for Delmic's Jolt system.

## Getting Started
Customers of Delmic will receive executables for Windows 7 and 10.
If you want to run the software from source, follow the instructions below.

### Prerequisites
Install Python 3 on your computer and install the dependencies. This can be done with:

        pip3 install -r requirements.txt

### Running from Source
You can run the software from source on both Linux and Windows.
Add the `src/` folder to your PYTHONPATH (in Linux, this is done with `export PYTHONPATH="src/"`), and run the main program:

`python3 src/jolt/gui/jolt_app.py` to start the main GUI

`python3 src/jolt/fwupd/jolt_fwupd.py` to start the firmware updater GUI

### Configuration file
You can modify or extend the configuration file and add threshold ('saferange') and 'target' values, as presented in the following example.
The configuration file, named `jolt.ini`, is stored in the `C:\Users\<username>\AppData\Local\Delmic\Jolt\`.

The code takes care of updating the target and safe-range values based on the user input. In case the configuration file is not extended
or invalid inputs are inserted, the code updates the variables with some default values. An example of an extended configuration file follows.

```
   [DEFAULT]
   voltage = 0.0
   gain = 0.0
   offset = 0.0
   channel = R
   ambient = False

   [TARGET]
   mppc_temp = 10

   [SAFERANGE]
   mppc_temp_rel = (-1, 1)
   heatsink_temp = (-20, 40)
   mppc_current = (-5000, 5000)
   vacuum_pressure = (0, 50)
```

Note that the SAFERANGE variables are tuples of integers and they represent the lower and upper threshold value of the corresponding feature.
The mppc_temp_rel corresponds to the MPPC temperature range, relative to the target temperature, in °C.
Note that an integer value should be given for the TARGET MPPC temperature.

If ambient is set to `True`, then the target mppc_temp is 15°C and no check is done on the pressure.

## Developer Information
More information for Delmic software developers can be found in the `doc/` folder.
For compiling the PDF install texlive, navigate to the folder in a terminal and type `pdflatex developer-doc.tex`.

## Links
#### NXPISP Repository
We use a modified version of the NXPISP repository from ElectroOptical Innovations for programming the NXP Cortex-M Chips:
https://github.com/snhobbs/NXPISP.

#### Delmic Website
For more information on the Jolt system, please visit https://www.delmic.com/sparc-jolt-detection.


