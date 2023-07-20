![Delmic](./src/jolt/gui/img/delmic_logo.png  "Delmic")
# Jolt Control
This repository contains the control software for Delmic's Jolt system.

## Getting Started
Customers of Delmic will receive executables for Windows 7 and 10.
If you want to run the software from source, follow the instructions below.

### Prerequisites
Install Python 3 on your computer and install the dependencies.

On Ubuntu, Python is already installed, so all that is needed is:

        pip3 install -r requirements.txt

On Windows, get the miniconda installer from there: https://docs.conda.io/en/latest/miniconda.html .
Then install miniconda, and run an anaconda terminal, go to the folder containing these sources. Then type:

        conda create -y --name jolt python==3.6.13
        conda activate jolt
        pip install -r requirements.txt

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
   vacuum_pressure = (0, 5)

   [SIGNAL]
   differential = False
   rgb_filter = True
```

The SAFERANGE variables represent the lower and upper threshold value of the
corresponding feature. They are written between parenthesis and separated by a comma.
The mppc_temp_rel corresponds to the MPPC temperature range, relative to the target
temperature, in °C. The vaccum pressure is in mbar. Note that the TARGET and
SAFERANGE settings only accept *integer* values.

If DEFAULT/ambient is set to `True`, then the target mppc_temp is automatically set to
15°C and no check is done on the pressure.
The DEFAULT section also accepts a front_offset option, which, if set, changes the
front-end offset voltage. It accepts values between 0 and 4095. The default value
is automatically calibrated at initialization, and is in most cases correct.

When SIGNAL/differential is set to `True`, the analog output of the JOLT,
going to the SEM input, is configured to be represented as a differential voltage.
When SIGNAL/rgb_filter is set to `False`, the channel is restricted to panchromatic.

## Configuration for the SNEL

The SNEL doesn't require cooling and has no temperature sensor. So the ini file has to be adjusted after the first run (which creates the file) with these parameters:
```
   [DEFAULT]
   ambient = True

   [SAFERANGE]
   mppc_temp_rel = (-100, -100)
   heatsink_temp = (-100, 100)
```


## Developer Information
More information for Delmic software developers can be found in the `doc/` folder.
For compiling the PDF install texlive, navigate to the folder in a terminal and type `pdflatex developer-doc.tex`.

In the GUI the following shortcuts provide access to extra tools:
 * Debug mode: F5 + "delmic" password to enable all controls
 * Inspection window: Ctrl+I (in debug mode) to show GUI controls


## Links
#### NXPISP Repository
We use a modified version of the NXPISP repository from ElectroOptical Innovations for programming the NXP Cortex-M Chips:
https://github.com/snhobbs/NXPISP.

#### Delmic Website
For more information on the Jolt system, please visit https://www.delmic.com/sparc-jolt-detection.


