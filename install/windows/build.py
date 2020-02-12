import os
import subprocess
import sys
import traceback
from builtins import input
import jolt

jolt_cmd = ["pyinstaller", "--clean", "-y", "--onefile", "JoltApp.spec"]
fwupd_cmd = ["pyinstaller", "--clean", "-y", "--onefile", "FirmwareUpdater.spec"]

def run_command(cmd, flavor=None):
    if flavor is not None:
        os.environ['FLAVOR'] = str(flavor)
    try:
        subprocess.check_call(cmd)
    except Exception as ex:
        # Don't close terminal after raising Exception
        traceback.print_exc(ex)
        input("Press any key to exit.")
        sys.exit(-1)
	
os.chdir(os.path.dirname(__file__) or '.')
while True:
    i = input("""
    [1] Jolt
    [2] FirmwareUpdater
    [3] Both
    [4] Exit
    """)

    try:
        i = int(i)
    except:
        break

    if i == 1:
        run_command(jolt_cmd)
    elif i == 2:
        run_command(fwupd_cmd)
    elif i == 3:
        run_command(jolt_cmd)
        run_command(fwupd_cmd)
    else:
        break
    print("\n\nBuild Done.")
input("Press any key to exit.")