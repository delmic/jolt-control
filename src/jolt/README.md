# jolt
It contains the gui and the firmware updater.

## Add threshold and target values
You can modify or extend the configuration file (jolt.ini) and add threshold ('saferange') and 'target' values, as presented in the following example.
The code takes care of updating the target and saferange values based on the user input. In case the configuration file is not extended
or invalid inputs are inserted, the code updates the variables with the default values. An example of an extended configuration file follows.

   [DEFAULT]
   voltage = 0.0
   gain = 0.0
   offset = 0.0
   channel = R

   [TARGET]
   mppc_temp = -10

   [SAFERANGE]
   mppc_temp_rel = (-1, 1)
   heatsink_temp = (-20, 40)
   mppc_current = (-5000, 5000)
   vacuum_pressure = (0, 50)

Note that the SAFERANGE variables are tuples of integers and they represent the lower and upper threshold value of the corresponding feature.
The mppc_temp_rel is added to the target mppc temperature to result in the threshold values of the mppc temperature. 
Note that an integer value should be given for the TARGET mppc temperature.


