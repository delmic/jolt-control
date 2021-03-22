# -*- mode: python ; coding: utf-8 -*-
block_cipher = None


a = Analysis(['..\\..\\src\\jolt\\gui\\jolt_app.py'],
             pathex=['../../src/jolt', 'C:\\development\\jolt-control\\install\\windows'],
             binaries=[],
             datas=[('../../src/jolt/gui/jolt_app.xrc', 'jolt/gui'), ('../../src/jolt/gui/img/*', 'jolt/gui/img'), ('dll/api-ms-win-crt-runtime-l1-1-0.dll', '.')],
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
          name='Jolt',
          debug=False,
          strip=False,
          upx=True,
          console=False,
          icon='jolt_icon.ico')
