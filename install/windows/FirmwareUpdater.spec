# -*- mode: python ; coding: utf-8 -*-
import jolt
import platform

block_cipher = None


a = Analysis(['..\\..\\src\\jolt\\fwupd\\jolt_fwupd.py'],
             pathex=['../../src/jolt', 'C:\\development\\jolt-engineering\\install\\windows'],
             binaries=[],
             datas=[('../../src/jolt/fwupd/fw_updater.xrc', 'jolt/fwupd')],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
		  a.binaries,
          a.zipfiles,
          a.datas,
          name='JoltFirmwareUpdater-v%s-win%s' % (jolt.__version__, platform.release()),
          debug=False,
          strip=False,
          upx=True,
          console=False)
