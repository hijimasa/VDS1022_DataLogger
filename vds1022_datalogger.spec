# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for VDS1022I DataLogger
# Usage: pyinstaller vds1022_datalogger.spec

import sys
import os
from pathlib import Path
import libusb_package

block_cipher = None

# libusb DLLのパスを取得
libusb_dir = Path(libusb_package.__file__).parent
libusb_dll = libusb_dir / 'libusb-1.0.dll'

# vds1022 パッケージのパスを取得（ファームウェア含む）
import vds1022
vds1022_dir = Path(vds1022.__file__).parent

a = Analysis(
    ['main_gui.py'],
    pathex=[],
    binaries=[
        # libusb DLLを実行ファイルと同じ場所に配置
        (str(libusb_dll), '.'),
    ],
    datas=[
        # libusb_package のデータリソース（DLLをパッケージとしても参照可能にする）
        (str(libusb_dir), 'libusb_package'),
        # vds1022 パッケージ全体（ファームウェア fwr/ を含む）
        (str(vds1022_dir), 'vds1022'),
    ],
    hiddenimports=[
        # vds1022
        'vds1022',
        'vds1022.vds1022',
        'vds1022.decoder',
        'vds1022.generator',
        'vds1022.plotter',
        # USB関連
        'usb',
        'usb.core',
        'usb.util',
        'usb.backend',
        'usb.backend.libusb1',
        'libusb_package',
        # pyqtgraph（自動検出されないサブモジュール）
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.graphicsItems.ViewBox',
        'pyqtgraph.graphicsItems.ViewBox.axisCtrlTemplate_pyqt6',
        'pyqtgraph.graphicsItems.ViewBox.viewBoxTemplate_pyqt6',
        'pyqtgraph.graphicsItems.PlotItem',
        'pyqtgraph.graphicsItems.PlotItem.plotConfigTemplate_pyqt6',
        'pyqtgraph.widgets.ColorMapWidget',
        'pyqtgraph.widgets.ScatterPlotWidget',
        'pyqtgraph.widgets.CheckTable',
        'pyqtgraph.widgets.DataFilterWidget',
        'pyqtgraph.canvas',
        'pyqtgraph.console',
        'pyqtgraph.parametertree',
        # numpy
        'numpy',
        'numpy.core',
        'numpy.core._multiarray_umath',
        # PyQt6
        'PyQt6',
        'PyQt6.QtOpenGL',
        'PyQt6.QtOpenGLWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'IPython',
        'jupyter',
        'pyqtgraph.opengl',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngine',
        'PyQt6.QtMultimedia',
        'PyQt6.QtBluetooth',
        'PyQt6.QtLocation',
        'PyQt6.QtPositioning',
        'PyQt6.QtSensors',
        'scipy',
        'pandas',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VDS1022_DataLogger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # コンソールウィンドウを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',    # アイコンファイルがあれば指定
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VDS1022_DataLogger',
)
