"""
VDS1022I データロガー メインGUIアプリケーション
PyQt6 + pyqtgraph を使用した高性能波形表示
"""

import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QTabWidget, QFileDialog, QListWidget, QListWidgetItem,
    QSplitter, QStatusBar, QMessageBox, QSlider, QFrame, QGridLayout,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QPalette

import pyqtgraph as pg
import numpy as np

from oscilloscope import VDS1022Controller, WaveformData, TriggerMode, TriggerEdge, Coupling
from data_logger import DataLogger
from signal_decoder import UARTDecoder, UARTFrame, I2CDecoder, I2CFrame


# pyqtgraph設定
pg.setConfigOptions(antialias=False, background='k', foreground='w', useOpenGL=True)


class AcquisitionThread(QThread):
    """データ取得用スレッド"""
    waveform_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, controller: VDS1022Controller):
        super().__init__()
        self.controller = controller
        self.running = False
        self.interval = 0.05  # 50ms

    def run(self):
        self.running = True
        while self.running:
            try:
                waveform = self.controller.acquire()
                if waveform:
                    self.waveform_ready.emit(waveform)
            except Exception as e:
                self.error_occurred.emit(str(e))
            time.sleep(self.interval)

    def stop(self):
        self.running = False
        self.wait()


class WaveformPlotWidget(pg.PlotWidget):
    """波形表示ウィジェット"""

    # setClipToView+setDownsampling(auto)使用のため手動の上限は不要
    # ただし1回のsetDataに渡す点数が多すぎると重いので上限を設ける
    MAX_DISPLAY_POINTS = 10000

    def __init__(self, title: str = ""):
        super().__init__(title=title)

        self.setLabel('left', '電圧', 'V')
        self.setLabel('bottom', '時間', 's')
        self.showGrid(x=True, y=True, alpha=0.3)
        self.addLegend()

        # チャネル用プロットアイテム（ClipToView+自動ダウンサンプリングで高速描画）
        self.ch1_curve = self.plot(pen=pg.mkPen('y', width=1), name='CH1')
        self.ch2_curve = self.plot(pen=pg.mkPen('c', width=1), name='CH2')
        for curve in (self.ch1_curve, self.ch2_curve):
            curve.setDownsampling(auto=True, method='peak')
            curve.setClipToView(True)

        # 履歴表示用（薄い色）
        self.history_curves: List[pg.PlotDataItem] = []

        # 保存波形表示用
        self.saved_curves: List[pg.PlotDataItem] = []

        # 読み込んだ波形データを保持
        self._loaded_waveform: Optional[WaveformData] = None
        self._time_base = 1e-3   # s/div
        self._v_div = 1.0        # V/div (CH1基準)
        self._y_center = 0.0     # Y軸中心位置（ホイールスクロール用）
        self._view_offset = 0.0  # X軸表示開始位置（秒）
        self._updating = False   # 再帰防止フラグ

        # カーソル
        self.cursor_v = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen('g', width=1))
        self.cursor_h = pg.InfiniteLine(angle=0, movable=True, pen=pg.mkPen('g', width=1))
        self.addItem(self.cursor_v)
        self.addItem(self.cursor_h)
        self.cursor_v.hide()
        self.cursor_h.hide()

        # デコードオーバーレイアイテム
        self._decode_items: List = []

        # X軸はドラッグでパン、Y軸はドラッグ無効
        self.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.setMouseEnabled(x=True, y=False)

        # パン後のデータ更新用デバウンスタイマー（50ms）
        self._pan_timer = QTimer()
        self._pan_timer.setSingleShot(True)
        self._pan_timer.setInterval(50)
        self._pan_timer.timeout.connect(self._update_view)

        # X軸範囲変更を監視（パン操作検出）
        self.getViewBox().sigXRangeChanged.connect(self._on_x_range_changed)

    def wheelEvent(self, ev):
        """マウスホイール: Y軸をスクロール（V/divに基づく刻み）"""
        delta = ev.angleDelta().y()
        if delta == 0:
            return
        # 1ノッチ = V/divの半分だけスクロール
        scroll_step = self._v_div * 0.5 * (-1 if delta > 0 else 1)
        self._y_center += scroll_step
        self._apply_y_range()
        ev.accept()

    def _apply_y_range(self):
        """V/divと_y_centerからY軸範囲を設定（8div分表示）"""
        half = self._v_div * 4  # 上下各4div
        self.setYRange(self._y_center - half, self._y_center + half, padding=0)

    def set_voltage_range(self, v_div: float):
        """V/divを設定してY軸スケールを更新"""
        self._v_div = v_div
        self._apply_y_range()

    def update_waveform(self, waveform: WaveformData):
        """リアルタイム波形を更新"""
        self.clear_loaded_waveform()  # ビューアモードを解除してライブ表示に戻す
        if waveform.ch1_data is not None:
            self.ch1_curve.setData(waveform.time_array, waveform.ch1_data)
            self.ch1_curve.show()
        else:
            self.ch1_curve.hide()

        if waveform.ch2_data is not None:
            self.ch2_curve.setData(waveform.time_array, waveform.ch2_data)
            self.ch2_curve.show()
        else:
            self.ch2_curve.hide()

    def show_history(self, waveforms: List[WaveformData], channel: int = 1):
        """履歴波形を表示"""
        for curve in self.history_curves:
            self.removeItem(curve)
        self.history_curves.clear()

        for i, wf in enumerate(waveforms):
            alpha = int(50 + (150 * i / len(waveforms)))
            if channel == 1 and wf.ch1_data is not None:
                pen = pg.mkPen(QColor(255, 255, 0, alpha), width=1)
                curve = self.plot(wf.time_array, wf.ch1_data, pen=pen)
            elif channel == 2 and wf.ch2_data is not None:
                pen = pg.mkPen(QColor(0, 255, 255, alpha), width=1)
                curve = self.plot(wf.time_array, wf.ch2_data, pen=pen)
            else:
                continue
            self.history_curves.append(curve)

    def clear_history(self):
        """履歴表示をクリア"""
        for curve in self.history_curves:
            self.removeItem(curve)
        self.history_curves.clear()

    def add_saved_waveform(self, waveform: WaveformData, color: str = 'm', label: str = ""):
        """保存波形を追加表示"""
        if waveform.ch1_data is not None:
            curve = self.plot(waveform.time_array, waveform.ch1_data,
                              pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
                              name=label or "保存波形")
            self.saved_curves.append(curve)

    def set_time_base(self, time_base: float):
        """タイムベースを設定（s/div）- 表示中央を基準に変更"""
        if self._loaded_waveform is not None:
            current_center = self._view_offset + self._time_base * 5
            self._time_base = time_base
            self._view_offset = current_center - time_base * 5
        else:
            self._time_base = time_base

        if self._loaded_waveform is not None:
            self._update_view()

    def load_waveform_data(self, waveform: WaveformData):
        """波形データを読み込み、タイムベースに基づいて表示"""
        self._loaded_waveform = waveform
        self._view_offset = waveform.time_array[0]
        self._y_center = 0.0
        self._update_view()

    def _update_view(self):
        """タイムベース・オフセットに基づいて表示を更新"""
        if self._loaded_waveform is None or self._updating:
            return

        waveform = self._loaded_waveform
        data_t_min = waveform.time_array[0]
        data_t_max = waveform.time_array[-1]

        # 表示範囲（10div）をデータ範囲内に収める
        view_duration = self._time_base * 10
        t_start = self._view_offset
        t_end = t_start + view_duration

        if t_start < data_t_min:
            t_start = data_t_min
            t_end = min(data_t_max, t_start + view_duration)
        if t_end > data_t_max:
            t_end = data_t_max
            t_start = max(data_t_min, t_end - view_duration)

        self._view_offset = t_start

        # searchsortedで範囲インデックスをO(log n)で取得
        i_start = np.searchsorted(waveform.time_array, t_start)
        i_end = np.searchsorted(waveform.time_array, t_end, side='right')
        n_in_view = i_end - i_start

        if n_in_view == 0:
            return

        # スライスで間引き（インデックス配列を作らない）
        step = max(1, n_in_view // self.MAX_DISPLAY_POINTS)

        time_display = waveform.time_array[i_start:i_end:step]

        if waveform.ch1_data is not None:
            self.ch1_curve.setData(time_display, waveform.ch1_data[i_start:i_end:step])
            self.ch1_curve.show()
        else:
            self.ch1_curve.hide()

        if waveform.ch2_data is not None:
            self.ch2_curve.setData(time_display, waveform.ch2_data[i_start:i_end:step])
            self.ch2_curve.show()
        else:
            self.ch2_curve.hide()

        # X軸を固定（再帰防止）
        self._updating = True
        self.setXRange(t_start, t_end, padding=0)
        self._updating = False

        # Y軸はV/divに基づいて設定
        self._apply_y_range()

    def _on_x_range_changed(self, viewbox, range_):
        """パン操作によるX軸変更: オフセットを記録してタイマーをリスタート"""
        if self._loaded_waveform is None or self._updating:
            return
        self._view_offset = range_[0]
        # ドラッグ中は毎回_update_viewせず、止まってから100ms後に更新
        self._pan_timer.start()

    def fit_to_data(self, waveform: WaveformData):
        """波形データ全体がちょうど10divに収まるよう自動フィットしてビューアモードへ切替"""
        duration = float(waveform.time_array[-1] - waveform.time_array[0])
        self._time_base = max(duration / 10.0, 1e-9)  # 10divに収まるtimebase
        self._y_center = 0.0
        self.load_waveform_data(waveform)

    def clear_loaded_waveform(self):
        """読み込んだ波形データをクリア"""
        self._loaded_waveform = None
        self._view_offset = 0.0

    def clear_saved_waveforms(self):
        """保存波形表示をクリア"""
        for curve in self.saved_curves:
            self.removeItem(curve)
        self.saved_curves.clear()

    def toggle_cursors(self, show: bool):
        """カーソル表示切替"""
        if show:
            self.cursor_v.show()
            self.cursor_h.show()
        else:
            self.cursor_v.hide()
            self.cursor_h.hide()

    def show_decode_overlay(self, frames: List):
        """デコード結果をオーバーレイ表示（波形上に色付き領域とラベル）

        UART/I2C など共通インターフェース: frame.status / frame.overlay_label を使用。
        """
        self.clear_decode_overlay()

        if not frames:
            return

        y_top = self._y_center + self._v_div * 3.5

        for frame in frames:
            status = frame.status
            # ステータスに応じた色設定
            if status == 'OK':
                region_color = (60, 200, 100, 60)    # 緑: 正常
                text_color = (100, 255, 150)
            elif status == 'START/STOP':
                region_color = (60, 150, 255, 60)    # 青: START/STOP条件
                text_color = (100, 200, 255)
            elif 'NACK' in status:
                region_color = (200, 150, 0, 60)     # 黄: NACK / パリティエラー
                text_color = (255, 200, 0)
            else:
                region_color = (200, 60, 60, 60)     # 赤: フレームエラー
                text_color = (255, 100, 100)

            # 時間領域をハイライト
            region = pg.LinearRegionItem(
                values=[frame.start_time, frame.end_time],
                movable=False,
                brush=pg.mkBrush(*region_color),
                pen=pg.mkPen(region_color[:3], width=1),
            )
            region.setZValue(-5)
            self.addItem(region)
            self._decode_items.append(region)

            # ラベル（frame.overlay_label を使用）
            center_time = (frame.start_time + frame.end_time) / 2.0
            text_item = pg.TextItem(
                frame.overlay_label,
                color=pg.mkColor(*text_color),
                anchor=(0.5, 1.0),
                fill=pg.mkBrush(0, 0, 0, 160),
            )
            text_item.setPos(center_time, y_top)
            self.addItem(text_item)
            self._decode_items.append(text_item)

    def clear_decode_overlay(self):
        """デコードオーバーレイをクリア"""
        for item in self._decode_items:
            self.removeItem(item)
        self._decode_items.clear()


class SettingsPanel(QWidget):
    """設定パネル"""
    settings_changed = pyqtSignal()

    def __init__(self, controller: VDS1022Controller):
        super().__init__()
        self.controller = controller
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # チャネル設定
        ch_group = QGroupBox("チャネル設定")
        ch_layout = QGridLayout()

        # CH1
        self.ch1_enabled = QCheckBox("CH1 有効")
        self.ch1_enabled.setChecked(True)
        self.ch1_enabled.toggled.connect(self._on_ch1_enabled)
        ch_layout.addWidget(self.ch1_enabled, 0, 0)

        ch_layout.addWidget(QLabel("電圧レンジ:"), 0, 1)
        self.ch1_range = QComboBox()
        for v in VDS1022Controller.VOLTAGE_RANGES:
            self.ch1_range.addItem(f"{v} V/div", v)
        self.ch1_range.setCurrentIndex(7)  # 1.0 V/div
        self.ch1_range.currentIndexChanged.connect(self._on_ch1_range)
        ch_layout.addWidget(self.ch1_range, 0, 2)

        ch_layout.addWidget(QLabel("カップリング:"), 0, 3)
        self.ch1_coupling = QComboBox()
        self.ch1_coupling.addItems(["DC", "AC", "GND"])
        ch_layout.addWidget(self.ch1_coupling, 0, 4)

        # CH2
        self.ch2_enabled = QCheckBox("CH2 有効")
        self.ch2_enabled.setChecked(False)
        self.ch2_enabled.toggled.connect(self._on_ch2_enabled)
        ch_layout.addWidget(self.ch2_enabled, 1, 0)

        ch_layout.addWidget(QLabel("電圧レンジ:"), 1, 1)
        self.ch2_range = QComboBox()
        for v in VDS1022Controller.VOLTAGE_RANGES:
            self.ch2_range.addItem(f"{v} V/div", v)
        self.ch2_range.setCurrentIndex(7)
        self.ch2_range.currentIndexChanged.connect(self._on_ch2_range)
        ch_layout.addWidget(self.ch2_range, 1, 2)

        ch_layout.addWidget(QLabel("カップリング:"), 1, 3)
        self.ch2_coupling = QComboBox()
        self.ch2_coupling.addItems(["DC", "AC", "GND"])
        ch_layout.addWidget(self.ch2_coupling, 1, 4)

        ch_group.setLayout(ch_layout)
        layout.addWidget(ch_group)

        # タイムベース設定
        time_group = QGroupBox("タイムベース")
        time_layout = QHBoxLayout()

        time_layout.addWidget(QLabel("Time/div:"))
        self.time_base = QComboBox()
        for t in VDS1022Controller.TIME_BASES:
            if t >= 1:
                self.time_base.addItem(f"{t} s/div", t)
            elif t >= 1e-3:
                self.time_base.addItem(f"{t*1000:.1f} ms/div", t)
            elif t >= 1e-6:
                self.time_base.addItem(f"{t*1e6:.1f} µs/div", t)
            else:
                self.time_base.addItem(f"{t*1e9:.1f} ns/div", t)
        self.time_base.setCurrentIndex(16)  # 1ms
        self.time_base.currentIndexChanged.connect(self._on_time_base)
        time_layout.addWidget(self.time_base)

        time_group.setLayout(time_layout)
        layout.addWidget(time_group)

        # トリガー設定
        trig_group = QGroupBox("トリガー")
        trig_layout = QGridLayout()

        trig_layout.addWidget(QLabel("モード:"), 0, 0)
        self.trigger_mode = QComboBox()
        self.trigger_mode.addItems(["Auto", "Normal", "Single"])
        self.trigger_mode.currentIndexChanged.connect(self._on_trigger_mode)
        trig_layout.addWidget(self.trigger_mode, 0, 1)

        trig_layout.addWidget(QLabel("ソース:"), 0, 2)
        self.trigger_source = QComboBox()
        self.trigger_source.addItems(["CH1", "CH2"])
        trig_layout.addWidget(self.trigger_source, 0, 3)

        trig_layout.addWidget(QLabel("エッジ:"), 1, 0)
        self.trigger_edge = QComboBox()
        self.trigger_edge.addItems(["立ち上がり", "立ち下がり"])
        trig_layout.addWidget(self.trigger_edge, 1, 1)

        trig_layout.addWidget(QLabel("レベル:"), 1, 2)
        self.trigger_level = QDoubleSpinBox()
        self.trigger_level.setRange(-100, 100)
        self.trigger_level.setSingleStep(0.1)
        self.trigger_level.setSuffix(" V")
        trig_layout.addWidget(self.trigger_level, 1, 3)

        trig_group.setLayout(trig_layout)
        layout.addWidget(trig_group)

        # シミュレーション設定
        sim_group = QGroupBox("シミュレーション設定")
        sim_layout = QGridLayout()

        sim_layout.addWidget(QLabel("周波数:"), 0, 0)
        self.sim_freq = QDoubleSpinBox()
        self.sim_freq.setRange(1, 100000)
        self.sim_freq.setValue(1000)
        self.sim_freq.setSuffix(" Hz")
        self.sim_freq.valueChanged.connect(self._on_sim_changed)
        sim_layout.addWidget(self.sim_freq, 0, 1)

        sim_layout.addWidget(QLabel("振幅:"), 0, 2)
        self.sim_amp = QDoubleSpinBox()
        self.sim_amp.setRange(0.01, 50)
        self.sim_amp.setValue(2.0)
        self.sim_amp.setSuffix(" V")
        self.sim_amp.valueChanged.connect(self._on_sim_changed)
        sim_layout.addWidget(self.sim_amp, 0, 3)

        sim_layout.addWidget(QLabel("波形:"), 1, 0)
        self.sim_waveform = QComboBox()
        self.sim_waveform.addItems(["sine", "square", "triangle", "sawtooth", "uart", "i2c"])
        self.sim_waveform.currentTextChanged.connect(self._on_sim_changed)
        self.sim_waveform.currentTextChanged.connect(self._on_waveform_type_changed)
        sim_layout.addWidget(self.sim_waveform, 1, 1)

        sim_layout.addWidget(QLabel("ノイズ:"), 1, 2)
        self.sim_noise = QDoubleSpinBox()
        self.sim_noise.setRange(0, 1)
        self.sim_noise.setValue(0.05)
        self.sim_noise.setSingleStep(0.01)
        self.sim_noise.valueChanged.connect(self._on_sim_changed)
        sim_layout.addWidget(self.sim_noise, 1, 3)

        sim_group.setLayout(sim_layout)
        layout.addWidget(sim_group)

        # UARTシミュレーション設定（uart波形選択時のみ表示）
        self.uart_sim_group = QGroupBox("UARTシミュレーション設定")
        uart_layout = QGridLayout()

        uart_layout.addWidget(QLabel("ボーレート:"), 0, 0)
        self.sim_uart_baudrate = QComboBox()
        for br in [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]:
            self.sim_uart_baudrate.addItem(str(br), br)
        self.sim_uart_baudrate.setCurrentText("9600")
        self.sim_uart_baudrate.currentIndexChanged.connect(self._on_sim_changed)
        uart_layout.addWidget(self.sim_uart_baudrate, 0, 1)

        uart_layout.addWidget(QLabel("メッセージ:"), 1, 0)
        self.sim_uart_message = QLineEdit("Hello\\r\\n")
        self.sim_uart_message.setPlaceholderText("送信テキスト (\\r\\nも使用可)")
        self.sim_uart_message.textChanged.connect(self._on_sim_changed)
        uart_layout.addWidget(self.sim_uart_message, 1, 1)

        self.uart_sim_group.setLayout(uart_layout)
        self.uart_sim_group.setVisible(False)
        layout.addWidget(self.uart_sim_group)

        # I2Cシミュレーション設定（i2c波形選択時のみ表示）
        self.i2c_sim_group = QGroupBox("I2Cシミュレーション設定")
        i2c_sim_layout = QGridLayout()

        i2c_sim_layout.addWidget(QLabel("スレーブアドレス(7bit):"), 0, 0)
        self.sim_i2c_address = QSpinBox()
        self.sim_i2c_address.setRange(0, 127)
        self.sim_i2c_address.setValue(0x68)  # MPU-6050
        self.sim_i2c_address.setDisplayIntegerBase(16)
        self.sim_i2c_address.setPrefix("0x")
        self.sim_i2c_address.valueChanged.connect(self._on_sim_changed)
        i2c_sim_layout.addWidget(self.sim_i2c_address, 0, 1)

        i2c_sim_layout.addWidget(QLabel("クロック:"), 0, 2)
        self.sim_i2c_freq = QComboBox()
        for freq, lbl in [(100000, "100kHz (Standard)"),
                          (400000, "400kHz (Fast)"),
                          (1000000, "1MHz (Fast+)")]:
            self.sim_i2c_freq.addItem(lbl, freq)
        self.sim_i2c_freq.currentIndexChanged.connect(self._on_sim_changed)
        i2c_sim_layout.addWidget(self.sim_i2c_freq, 0, 3)

        i2c_sim_layout.addWidget(QLabel("データ(HEX):"), 1, 0)
        self.sim_i2c_data = QLineEdit("00 01 02")
        self.sim_i2c_data.setPlaceholderText("スペース区切り HEX (例: 00 01 02)")
        self.sim_i2c_data.textChanged.connect(self._on_sim_changed)
        i2c_sim_layout.addWidget(self.sim_i2c_data, 1, 1, 1, 3)

        self.i2c_sim_group.setLayout(i2c_sim_layout)
        self.i2c_sim_group.setVisible(False)
        layout.addWidget(self.i2c_sim_group)

        layout.addStretch()

    def _on_ch1_enabled(self, enabled):
        self.controller.set_channel_enabled(1, enabled)
        self.settings_changed.emit()

    def _on_ch2_enabled(self, enabled):
        self.controller.set_channel_enabled(2, enabled)
        self.settings_changed.emit()

    def _on_ch1_range(self, index):
        voltage = self.ch1_range.itemData(index)
        self.controller.set_voltage_range(1, voltage)
        self.settings_changed.emit()

    def _on_ch2_range(self, index):
        voltage = self.ch2_range.itemData(index)
        self.controller.set_voltage_range(2, voltage)
        self.settings_changed.emit()

    def _on_time_base(self, index):
        time_base = self.time_base.itemData(index)
        self.controller.set_time_base(time_base)
        self.settings_changed.emit()

    def _on_trigger_mode(self, index):
        modes = [TriggerMode.AUTO, TriggerMode.NORMAL, TriggerMode.SINGLE]
        self.controller.set_trigger(mode=modes[index])

    def _on_waveform_type_changed(self, waveform_type: str):
        """波形タイプ変更時のUI切替"""
        self.uart_sim_group.setVisible(waveform_type == "uart")
        self.i2c_sim_group.setVisible(waveform_type == "i2c")

    def _on_sim_changed(self):
        # UARTメッセージのエスケープシーケンスを解釈
        raw_msg = self.sim_uart_message.text()
        uart_msg = raw_msg.replace("\\r\\n", "\r\n").replace("\\r", "\r").replace("\\n", "\n")

        # I2Cデータ（スペース区切りHEX文字列をbytesに変換）
        try:
            i2c_data = bytes(int(x, 16) for x in self.sim_i2c_data.text().split() if x)
        except ValueError:
            i2c_data = b'\x00'

        self.controller.set_simulation_params(
            frequency=self.sim_freq.value(),
            amplitude=self.sim_amp.value(),
            waveform=self.sim_waveform.currentText(),
            noise_level=self.sim_noise.value(),
            uart_baudrate=self.sim_uart_baudrate.currentData(),
            uart_message=uart_msg.encode('utf-8', errors='replace'),
            i2c_address=self.sim_i2c_address.value(),
            i2c_data=i2c_data,
            i2c_freq=self.sim_i2c_freq.currentData(),
        )


class MeasurementPanel(QWidget):
    """測定値表示パネル"""

    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # CH1測定値
        ch1_group = QGroupBox("CH1 測定値")
        ch1_layout = QGridLayout()

        self.ch1_vpp = QLabel("---")
        self.ch1_vrms = QLabel("---")
        self.ch1_vmax = QLabel("---")
        self.ch1_vmin = QLabel("---")
        self.ch1_freq = QLabel("---")

        ch1_layout.addWidget(QLabel("Vpp:"), 0, 0)
        ch1_layout.addWidget(self.ch1_vpp, 0, 1)
        ch1_layout.addWidget(QLabel("Vrms:"), 0, 2)
        ch1_layout.addWidget(self.ch1_vrms, 0, 3)
        ch1_layout.addWidget(QLabel("Vmax:"), 1, 0)
        ch1_layout.addWidget(self.ch1_vmax, 1, 1)
        ch1_layout.addWidget(QLabel("Vmin:"), 1, 2)
        ch1_layout.addWidget(self.ch1_vmin, 1, 3)
        ch1_layout.addWidget(QLabel("Freq:"), 2, 0)
        ch1_layout.addWidget(self.ch1_freq, 2, 1)

        ch1_group.setLayout(ch1_layout)
        layout.addWidget(ch1_group)

        # CH2測定値
        ch2_group = QGroupBox("CH2 測定値")
        ch2_layout = QGridLayout()

        self.ch2_vpp = QLabel("---")
        self.ch2_vrms = QLabel("---")
        self.ch2_vmax = QLabel("---")
        self.ch2_vmin = QLabel("---")
        self.ch2_freq = QLabel("---")

        ch2_layout.addWidget(QLabel("Vpp:"), 0, 0)
        ch2_layout.addWidget(self.ch2_vpp, 0, 1)
        ch2_layout.addWidget(QLabel("Vrms:"), 0, 2)
        ch2_layout.addWidget(self.ch2_vrms, 0, 3)
        ch2_layout.addWidget(QLabel("Vmax:"), 1, 0)
        ch2_layout.addWidget(self.ch2_vmax, 1, 1)
        ch2_layout.addWidget(QLabel("Vmin:"), 1, 2)
        ch2_layout.addWidget(self.ch2_vmin, 1, 3)
        ch2_layout.addWidget(QLabel("Freq:"), 2, 0)
        ch2_layout.addWidget(self.ch2_freq, 2, 1)

        ch2_group.setLayout(ch2_layout)
        layout.addWidget(ch2_group)

        layout.addStretch()

    def update_measurements(self, waveform: WaveformData):
        """測定値を更新"""
        if waveform.ch1_data is not None:
            meas = waveform.get_measurements(1)
            self.ch1_vpp.setText(f"{meas['vpp']:.3f} V")
            self.ch1_vrms.setText(f"{meas['vrms']:.3f} V")
            self.ch1_vmax.setText(f"{meas['vmax']:.3f} V")
            self.ch1_vmin.setText(f"{meas['vmin']:.3f} V")
            self.ch1_freq.setText(f"{meas['frequency']:.1f} Hz")
        else:
            for label in [self.ch1_vpp, self.ch1_vrms, self.ch1_vmax, self.ch1_vmin, self.ch1_freq]:
                label.setText("---")

        if waveform.ch2_data is not None:
            meas = waveform.get_measurements(2)
            self.ch2_vpp.setText(f"{meas['vpp']:.3f} V")
            self.ch2_vrms.setText(f"{meas['vrms']:.3f} V")
            self.ch2_vmax.setText(f"{meas['vmax']:.3f} V")
            self.ch2_vmin.setText(f"{meas['vmin']:.3f} V")
            self.ch2_freq.setText(f"{meas['frequency']:.1f} Hz")
        else:
            for label in [self.ch2_vpp, self.ch2_vrms, self.ch2_vmax, self.ch2_vmin, self.ch2_freq]:
                label.setText("---")


class HistoryPanel(QWidget):
    """履歴・保存波形パネル"""
    load_waveform = pyqtSignal(object)

    def __init__(self, data_logger: DataLogger):
        super().__init__()
        self.data_logger = data_logger
        self._loaded_files = {}  # filepath -> waveform のマッピング
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 履歴表示設定
        history_group = QGroupBox("波形履歴")
        history_layout = QVBoxLayout()

        h_ctrl = QHBoxLayout()
        self.show_history = QCheckBox("履歴を表示")
        h_ctrl.addWidget(self.show_history)

        h_ctrl.addWidget(QLabel("表示数:"))
        self.history_count = QSpinBox()
        self.history_count.setRange(1, 50)
        self.history_count.setValue(10)
        h_ctrl.addWidget(self.history_count)

        history_layout.addLayout(h_ctrl)

        self.history_slider = QSlider(Qt.Orientation.Horizontal)
        self.history_slider.setRange(0, 100)
        history_layout.addWidget(self.history_slider)

        history_group.setLayout(history_layout)
        layout.addWidget(history_group)

        # 保存波形
        saved_group = QGroupBox("保存波形 (NPZ)")
        saved_layout = QVBoxLayout()

        self.saved_list = QListWidget()
        self.saved_list.itemClicked.connect(self._on_select_waveform)
        self.saved_list.itemDoubleClicked.connect(self._on_load_waveform)
        saved_layout.addWidget(self.saved_list)

        # 波形情報表示
        self.waveform_info = QLabel("ファイルを選択してください")
        self.waveform_info.setWordWrap(True)
        self.waveform_info.setStyleSheet("color: #aaa; font-size: 11px;")
        saved_layout.addWidget(self.waveform_info)

        btn_layout = QHBoxLayout()
        self.btn_load = QPushButton("NPZ読込")
        self.btn_load.clicked.connect(self._on_browse_waveform)
        btn_layout.addWidget(self.btn_load)

        self.btn_export_csv = QPushButton("CSV変換")
        self.btn_export_csv.clicked.connect(self._on_export_csv)
        self.btn_export_csv.setEnabled(False)
        btn_layout.addWidget(self.btn_export_csv)

        self.btn_clear_saved = QPushButton("クリア")
        self.btn_clear_saved.clicked.connect(self._on_clear_saved)
        btn_layout.addWidget(self.btn_clear_saved)

        saved_layout.addLayout(btn_layout)
        saved_group.setLayout(saved_layout)
        layout.addWidget(saved_group)

        # ログファイル
        log_group = QGroupBox("ログファイル")
        log_layout = QVBoxLayout()

        self.log_list = QListWidget()
        log_layout.addWidget(self.log_list)

        self.btn_refresh_logs = QPushButton("更新")
        self.btn_refresh_logs.clicked.connect(self._refresh_logs)
        log_layout.addWidget(self.btn_refresh_logs)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        self._refresh_logs()

    def _refresh_logs(self):
        """ログファイル一覧を更新"""
        self.log_list.clear()
        for log_file in self.data_logger.get_log_files():
            self.log_list.addItem(log_file.name)

    def _on_browse_waveform(self):
        """波形ファイルを参照"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "波形ファイルを開く", str(self.data_logger.log_dir),
            "NPZ Files (*.npz);;All Files (*)"
        )
        if filepath:
            waveform = DataLogger.load_waveform(filepath)
            if waveform:
                filename = Path(filepath).name
                self._loaded_files[filename] = filepath
                self.saved_list.addItem(filename)
                self.load_waveform.emit(waveform)
                self._update_waveform_info(filepath)
                self.btn_export_csv.setEnabled(True)

    def _on_select_waveform(self, item):
        """波形ファイルを選択"""
        filename = item.text()
        if filename in self._loaded_files:
            filepath = self._loaded_files[filename]
            self._update_waveform_info(filepath)
            self.btn_export_csv.setEnabled(True)

    def _on_load_waveform(self, item):
        """保存波形を読み込み（ダブルクリック）"""
        filename = item.text()
        if filename in self._loaded_files:
            filepath = self._loaded_files[filename]
            waveform = DataLogger.load_waveform(filepath)
            if waveform:
                self.load_waveform.emit(waveform)

    def _update_waveform_info(self, filepath: str):
        """波形情報を更新"""
        info = DataLogger.get_npz_info(filepath)
        if info:
            ch_info = []
            if info['has_ch1']:
                ch_info.append("CH1")
            if info['has_ch2']:
                ch_info.append("CH2")

            text = (
                f"サンプル数: {info['samples']:,}\n"
                f"サンプリング: {info['sample_rate']/1000:.1f} kHz\n"
                f"記録時間: {info['duration']:.3f} 秒\n"
                f"チャネル: {', '.join(ch_info)}"
            )
            self.waveform_info.setText(text)
        else:
            self.waveform_info.setText("情報を取得できません")

    def _on_export_csv(self):
        """選択中のNPZをCSVに変換"""
        item = self.saved_list.currentItem()
        if not item:
            QMessageBox.warning(self, "警告", "波形ファイルを選択してください")
            return

        filename = item.text()
        if filename not in self._loaded_files:
            return

        npz_filepath = self._loaded_files[filename]
        info = DataLogger.get_npz_info(npz_filepath)

        if not info:
            return

        # 間引き率を計算（100万行を超えないように）
        samples = info['samples']
        suggested_downsample = 1
        if samples > 1000000:
            suggested_downsample = (samples // 1000000) + 1

        # ダイアログで間引き率を確認
        downsample, ok = self._ask_downsample(samples, suggested_downsample)
        if not ok:
            return

        # 保存先を選択
        default_name = Path(filename).stem + ".csv"
        csv_filepath, _ = QFileDialog.getSaveFileName(
            self, "CSVファイルを保存",
            str(self.data_logger.log_dir / default_name),
            "CSV Files (*.csv)"
        )

        if csv_filepath:
            result_rows = samples // downsample
            self.waveform_info.setText(f"CSV変換中... ({result_rows:,}行)")
            QApplication.processEvents()

            success = DataLogger.convert_npz_to_csv(
                npz_filepath, csv_filepath,
                downsample=downsample,
                max_rows=1048576  # Excelの上限
            )

            if success:
                QMessageBox.information(
                    self, "変換完了",
                    f"CSVファイルを保存しました:\n{csv_filepath}\n\n"
                    f"出力行数: 約{result_rows:,}行"
                )
                self._update_waveform_info(npz_filepath)
            else:
                QMessageBox.warning(self, "エラー", "CSV変換に失敗しました")

    def _ask_downsample(self, samples: int, suggested: int) -> tuple:
        """間引き率を確認するダイアログ"""
        from PyQt6.QtWidgets import QInputDialog

        result_rows = samples // suggested
        text = (
            f"元データ: {samples:,} サンプル\n"
            f"間引き率 {suggested} → 約 {result_rows:,} 行\n\n"
            f"間引き率を入力 (1=全データ, 10=1/10):"
        )

        value, ok = QInputDialog.getInt(
            self, "CSV変換オプション", text,
            suggested, 1, 10000, 1
        )
        return value, ok

    def _on_clear_saved(self):
        """保存波形リストをクリア"""
        self.saved_list.clear()
        self._loaded_files.clear()
        self.waveform_info.setText("ファイルを選択してください")
        self.btn_export_csv.setEnabled(False)


class LoggingPanel(QWidget):
    """ロギングコントロールパネル"""
    continuous_recording_finished = pyqtSignal(object, str)  # waveform, filepath
    _continuous_progress = pyqtSignal(str)  # 進捗メッセージ用シグナル
    _continuous_complete = pyqtSignal(object, str)  # 完了用シグナル

    def __init__(self, data_logger: DataLogger):
        super().__init__()
        self.data_logger = data_logger
        self._init_ui()

        # シグナル接続（スレッドセーフなGUI更新用）
        self._continuous_progress.connect(self._update_continuous_status)
        self._continuous_complete.connect(self._handle_continuous_complete)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # === 連続記録（高速記録） ===
        continuous_group = QGroupBox("連続記録（高速）")
        continuous_layout = QVBoxLayout()

        # 記録時間設定
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("記録時間:"))
        self.continuous_duration = QDoubleSpinBox()
        self.continuous_duration.setRange(0.1, 60.0)
        self.continuous_duration.setValue(1.0)
        self.continuous_duration.setSingleStep(0.5)
        self.continuous_duration.setSuffix(" 秒")
        duration_layout.addWidget(self.continuous_duration)
        continuous_layout.addLayout(duration_layout)

        # 予想サンプル数表示
        self.sample_estimate_label = QLabel("予想: 約250,000サンプル")
        continuous_layout.addWidget(self.sample_estimate_label)
        self.continuous_duration.valueChanged.connect(self._update_sample_estimate)

        # 連続記録ボタン
        self.btn_continuous = QPushButton("連続記録開始")
        self.btn_continuous.clicked.connect(self._on_start_continuous)
        continuous_layout.addWidget(self.btn_continuous)

        # 進捗表示
        self.continuous_status = QLabel("状態: 待機中")
        continuous_layout.addWidget(self.continuous_status)

        continuous_group.setLayout(continuous_layout)
        layout.addWidget(continuous_group)

        # === 間欠記録（従来のロギング） ===
        ctrl_group = QGroupBox("間欠記録（測定値ログ）")
        ctrl_layout = QVBoxLayout()

        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("記録間隔:"))
        self.log_interval = QDoubleSpinBox()
        self.log_interval.setRange(0.1, 60)
        self.log_interval.setValue(1.0)
        self.log_interval.setSuffix(" 秒")
        interval_layout.addWidget(self.log_interval)
        ctrl_layout.addLayout(interval_layout)

        self.save_waveforms = QCheckBox("波形データを保存")
        self.save_waveforms.setChecked(True)
        ctrl_layout.addWidget(self.save_waveforms)

        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("記録開始")
        self.btn_start.clicked.connect(self._on_start_logging)
        btn_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("記録停止")
        self.btn_stop.clicked.connect(self._on_stop_logging)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)

        ctrl_layout.addLayout(btn_layout)

        self.status_label = QLabel("状態: 停止中")
        ctrl_layout.addWidget(self.status_label)

        self.file_label = QLabel("ファイル: ---")
        ctrl_layout.addWidget(self.file_label)

        self.count_label = QLabel("記録数: 0")
        ctrl_layout.addWidget(self.count_label)

        ctrl_group.setLayout(ctrl_layout)
        layout.addWidget(ctrl_group)

        # エクスポート
        export_group = QGroupBox("エクスポート")
        export_layout = QVBoxLayout()

        self.btn_export = QPushButton("CSVエクスポート")
        self.btn_export.clicked.connect(self._on_export)
        export_layout.addWidget(self.btn_export)

        export_group.setLayout(export_layout)
        layout.addWidget(export_group)

        layout.addStretch()

        # 更新タイマー
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_status)
        self.update_timer.start(1000)

    def _update_sample_estimate(self):
        """予想サンプル数を更新"""
        duration = self.continuous_duration.value()
        samples = int(250000 * duration)  # 250kHz想定
        self.sample_estimate_label.setText(f"予想: 約{samples:,}サンプル")

    def _on_start_continuous(self):
        """連続記録開始"""
        if self.data_logger.is_continuous_recording:
            return

        duration = self.continuous_duration.value()
        self.btn_continuous.setEnabled(False)
        self.continuous_status.setText(f"記録中... ({duration}秒)")

        # 連続記録を開始
        self.data_logger.start_continuous_recording(
            duration=duration,
            callback=self._on_continuous_progress,
            completion_callback=self._on_continuous_complete
        )

    def _on_continuous_progress(self, progress: float, message: str):
        """連続記録の進捗更新（別スレッドから呼ばれる）"""
        # pyqtSignalでGUIスレッドに送信
        self._continuous_progress.emit(message)

    def _on_continuous_complete(self, waveform, filepath: str):
        """連続記録完了（別スレッドから呼ばれる）"""
        # pyqtSignalでGUIスレッドに送信
        self._continuous_complete.emit(waveform, filepath if filepath else "")

    def _update_continuous_status(self, message: str):
        """進捗ステータス更新（GUIスレッドで実行）"""
        self.continuous_status.setText(message)

    def _handle_continuous_complete(self, waveform, filepath: str):
        """連続記録完了処理（GUIスレッドで実行）"""
        self.btn_continuous.setEnabled(True)
        if waveform and filepath:
            samples = len(waveform.time_array)
            self.continuous_status.setText(f"完了: {samples:,}サンプル保存")
            self.continuous_recording_finished.emit(waveform, filepath)
        else:
            self.continuous_status.setText("エラー: 記録失敗")

    def _on_start_logging(self):
        """ロギング開始"""
        self.data_logger.start_logging(
            interval=self.log_interval.value(),
            save_waveforms=self.save_waveforms.isChecked()
        )
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("状態: 記録中...")

    def _on_stop_logging(self):
        """ロギング停止"""
        self.data_logger.stop_logging()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("状態: 停止中")

    def _update_status(self):
        """ステータス更新"""
        if self.data_logger.is_logging:
            if self.data_logger.current_log_file:
                self.file_label.setText(f"ファイル: {self.data_logger.current_log_file.name}")
            self.count_label.setText(f"記録数: {len(self.data_logger.log_entries)}")

    def _on_export(self):
        """CSVエクスポート"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "CSVエクスポート", "", "CSV Files (*.csv)"
        )
        if filepath:
            self.data_logger.export_to_csv(filepath)
            QMessageBox.information(self, "エクスポート完了",
                                    f"CSVファイルを保存しました:\n{filepath}")


class DecodePanel(QWidget):
    """信号デコードパネル（UART / I2C プロトコルデコード）"""
    decode_completed = pyqtSignal(list)    # List[UARTFrame or I2CFrame]
    fit_waveform = pyqtSignal(object)      # デコード後に波形全体を自動フィット

    def __init__(self):
        super().__init__()
        self._current_waveform: Optional[WaveformData] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ---- プロトコル選択 ----
        proto_layout = QHBoxLayout()
        proto_layout.addWidget(QLabel("プロトコル:"))
        self.protocol = QComboBox()
        self.protocol.addItems(["UART", "I2C"])
        self.protocol.currentTextChanged.connect(self._on_protocol_changed)
        proto_layout.addWidget(self.protocol)
        proto_layout.addStretch()
        layout.addLayout(proto_layout)

        # ---- UART 設定グループ ----
        self.uart_cfg_group = QGroupBox("UART設定")
        uart_layout = QGridLayout()

        row = 0
        uart_layout.addWidget(QLabel("チャネル:"), row, 0)
        self.channel = QComboBox()
        self.channel.addItems(["CH1", "CH2"])
        uart_layout.addWidget(self.channel, row, 1)

        uart_layout.addWidget(QLabel("ボーレート:"), row, 2)
        self.baudrate = QComboBox()
        for br in UARTDecoder.STANDARD_BAUDRATES:
            self.baudrate.addItem(str(br), br)
        self.baudrate.setCurrentText("9600")
        uart_layout.addWidget(self.baudrate, row, 3)

        row += 1
        uart_layout.addWidget(QLabel("データビット:"), row, 0)
        self.data_bits = QComboBox()
        for db in [5, 6, 7, 8, 9]:
            self.data_bits.addItem(str(db), db)
        self.data_bits.setCurrentIndex(3)  # 8
        uart_layout.addWidget(self.data_bits, row, 1)

        uart_layout.addWidget(QLabel("パリティ:"), row, 2)
        self.parity = QComboBox()
        self.parity.addItems(["なし", "偶数", "奇数"])
        uart_layout.addWidget(self.parity, row, 3)

        row += 1
        uart_layout.addWidget(QLabel("ストップビット:"), row, 0)
        self.stop_bits = QComboBox()
        self.stop_bits.addItems(["1", "1.5", "2"])
        uart_layout.addWidget(self.stop_bits, row, 1)

        uart_layout.addWidget(QLabel("スレッショルド:"), row, 2)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(-50.0, 50.0)
        self.threshold.setValue(1.65)
        self.threshold.setSingleStep(0.05)
        self.threshold.setSuffix(" V")
        uart_layout.addWidget(self.threshold, row, 3)

        row += 1
        self.btn_auto_thresh = QPushButton("スレッショルド自動")
        self.btn_auto_thresh.setToolTip("選択チャネルの (Vmax+Vmin)/2 を自動設定")
        self.btn_auto_thresh.clicked.connect(self._auto_threshold)
        uart_layout.addWidget(self.btn_auto_thresh, row, 0, 1, 4)

        self.uart_cfg_group.setLayout(uart_layout)
        layout.addWidget(self.uart_cfg_group)

        # ---- I2C 設定グループ ----
        self.i2c_cfg_group = QGroupBox("I2C設定")
        i2c_layout = QGridLayout()

        row = 0
        i2c_layout.addWidget(QLabel("SDA チャネル:"), row, 0)
        self.i2c_sda_ch = QComboBox()
        self.i2c_sda_ch.addItems(["CH1", "CH2"])
        i2c_layout.addWidget(self.i2c_sda_ch, row, 1)

        i2c_layout.addWidget(QLabel("SCL チャネル:"), row, 2)
        self.i2c_scl_ch = QComboBox()
        self.i2c_scl_ch.addItems(["CH2", "CH1"])
        i2c_layout.addWidget(self.i2c_scl_ch, row, 3)

        row += 1
        i2c_layout.addWidget(QLabel("SDA スレッショルド:"), row, 0)
        self.i2c_sda_threshold = QDoubleSpinBox()
        self.i2c_sda_threshold.setRange(-50.0, 50.0)
        self.i2c_sda_threshold.setValue(1.65)
        self.i2c_sda_threshold.setSingleStep(0.05)
        self.i2c_sda_threshold.setSuffix(" V")
        i2c_layout.addWidget(self.i2c_sda_threshold, row, 1)

        self.btn_auto_sda = QPushButton("自動")
        self.btn_auto_sda.setToolTip("SDAチャネルの (Vmax+Vmin)/2 を自動設定")
        self.btn_auto_sda.clicked.connect(self._auto_sda_threshold)
        i2c_layout.addWidget(self.btn_auto_sda, row, 2)

        row += 1
        i2c_layout.addWidget(QLabel("SCL スレッショルド:"), row, 0)
        self.i2c_scl_threshold = QDoubleSpinBox()
        self.i2c_scl_threshold.setRange(-50.0, 50.0)
        self.i2c_scl_threshold.setValue(1.65)
        self.i2c_scl_threshold.setSingleStep(0.05)
        self.i2c_scl_threshold.setSuffix(" V")
        i2c_layout.addWidget(self.i2c_scl_threshold, row, 1)

        self.btn_auto_scl = QPushButton("自動")
        self.btn_auto_scl.setToolTip("SCLチャネルの (Vmax+Vmin)/2 を自動設定")
        self.btn_auto_scl.clicked.connect(self._auto_scl_threshold)
        i2c_layout.addWidget(self.btn_auto_scl, row, 2)

        row += 1
        i2c_layout.addWidget(QLabel("アドレスフィルタ:"), row, 0)
        self.i2c_addr_filter = QLineEdit()
        self.i2c_addr_filter.setPlaceholderText("空欄=全表示 / 例: 0x68")
        i2c_layout.addWidget(self.i2c_addr_filter, row, 1, 1, 3)

        self.i2c_cfg_group.setLayout(i2c_layout)
        self.i2c_cfg_group.setVisible(False)
        layout.addWidget(self.i2c_cfg_group)

        # ---- デコードボタン ----
        self.btn_decode = QPushButton("デコード実行")
        self.btn_decode.setEnabled(False)
        self.btn_decode.clicked.connect(self._on_decode)
        layout.addWidget(self.btn_decode)

        # ---- 結果テーブル ----
        res_group = QGroupBox("デコード結果")
        res_layout = QVBoxLayout()

        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(["#", "時刻(s)", "HEX", "ASCII", "状態"])
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        res_layout.addWidget(self.result_table)

        res_group.setLayout(res_layout)
        layout.addWidget(res_group, stretch=1)

        # ---- ステータス ----
        self.status_label = QLabel("波形を取得後にデコードしてください")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------------
    # プロトコル切替
    # ------------------------------------------------------------------

    def _on_protocol_changed(self, protocol: str):
        """プロトコル変更時: 設定グループとテーブル列を切替"""
        is_uart = protocol == "UART"
        self.uart_cfg_group.setVisible(is_uart)
        self.i2c_cfg_group.setVisible(not is_uart)
        self._setup_table_columns(protocol)

    def _setup_table_columns(self, protocol: str):
        """テーブル列をプロトコルに合わせて再設定"""
        self.result_table.clearContents()
        self.result_table.setRowCount(0)
        if protocol == "UART":
            self.result_table.setColumnCount(5)
            self.result_table.setHorizontalHeaderLabels(["#", "時刻(s)", "HEX", "ASCII", "状態"])
            self.result_table.horizontalHeader().setSectionResizeMode(
                4, QHeaderView.ResizeMode.Stretch)
        elif protocol == "I2C":
            self.result_table.setColumnCount(6)
            self.result_table.setHorizontalHeaderLabels(
                ["#", "種別", "時刻(s)", "アドレス/データ", "R/W", "ACK"])
            self.result_table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.Stretch)

    # ------------------------------------------------------------------
    # 公開メソッド
    # ------------------------------------------------------------------

    def set_waveform(self, waveform: Optional[WaveformData]):
        """デコード対象の波形を設定"""
        self._current_waveform = waveform
        self.btn_decode.setEnabled(waveform is not None)

    # ------------------------------------------------------------------
    # スレッショルド自動設定
    # ------------------------------------------------------------------

    def _auto_threshold(self):
        """UART: 選択チャネルの中間電圧を自動設定"""
        if self._current_waveform is None:
            return
        ch = 1 if self.channel.currentText() == "CH1" else 2
        data = self._current_waveform.ch1_data if ch == 1 else self._current_waveform.ch2_data
        if data is None:
            self.status_label.setText("選択チャネルにデータがありません")
            return
        mid = (float(np.max(data)) + float(np.min(data))) / 2.0
        self.threshold.setValue(round(mid, 3))

    def _auto_sda_threshold(self):
        """I2C SDA: 選択チャネルの中間電圧を自動設定"""
        if self._current_waveform is None:
            return
        ch = 1 if self.i2c_sda_ch.currentText() == "CH1" else 2
        data = self._current_waveform.ch1_data if ch == 1 else self._current_waveform.ch2_data
        if data is None:
            self.status_label.setText("SDAチャネルにデータがありません")
            return
        mid = (float(np.max(data)) + float(np.min(data))) / 2.0
        self.i2c_sda_threshold.setValue(round(mid, 3))

    def _auto_scl_threshold(self):
        """I2C SCL: 選択チャネルの中間電圧を自動設定"""
        if self._current_waveform is None:
            return
        ch = 1 if self.i2c_scl_ch.currentText() == "CH1" else 2
        data = self._current_waveform.ch1_data if ch == 1 else self._current_waveform.ch2_data
        if data is None:
            self.status_label.setText("SCLチャネルにデータがありません")
            return
        mid = (float(np.max(data)) + float(np.min(data))) / 2.0
        self.i2c_scl_threshold.setValue(round(mid, 3))

    # ------------------------------------------------------------------
    # デコード実行
    # ------------------------------------------------------------------

    def _on_decode(self):
        """プロトコルに応じてデコードを実行"""
        if self._current_waveform is None:
            return
        protocol = self.protocol.currentText()
        if protocol == "UART":
            self._decode_uart()
        elif protocol == "I2C":
            self._decode_i2c()

    def _decode_uart(self):
        """UARTデコード実行"""
        wf = self._current_waveform
        ch = 1 if self.channel.currentText() == "CH1" else 2
        data = wf.ch1_data if ch == 1 else wf.ch2_data

        if data is None:
            self.status_label.setText("選択チャネルにデータがありません")
            return

        parity_map = {"なし": "none", "偶数": "even", "奇数": "odd"}
        stop_map = {"1": 1.0, "1.5": 1.5, "2": 2.0}

        decoder = UARTDecoder(
            baudrate=self.baudrate.currentData(),
            data_bits=self.data_bits.currentData(),
            parity=parity_map[self.parity.currentText()],
            stop_bits=stop_map[self.stop_bits.currentText()],
        )

        try:
            frames = decoder.decode(wf.time_array, data, threshold=self.threshold.value())
        except ValueError as e:
            self.status_label.setText(f"エラー: {e}")
            return

        # テーブル更新
        self._setup_table_columns("UART")
        self.result_table.setRowCount(len(frames))
        for row_idx, frame in enumerate(frames):
            vals = [str(row_idx), f"{frame.start_time:.6f}",
                    frame.hex_str, frame.ascii_str, frame.status]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                if not frame.frame_ok or not frame.parity_ok:
                    item.setForeground(QColor(255, 100, 100))
                self.result_table.setItem(row_idx, col, item)

        n = len(frames)
        err = sum(1 for f in frames if not f.frame_ok or not f.parity_ok)
        ok_bytes = bytes(f.data for f in frames if f.frame_ok)
        preview = "".join(
            chr(b) if 0x20 <= b <= 0x7E else ("↵" if b in (0x0A, 0x0D) else "·")
            for b in ok_bytes[:60]
        )
        self.status_label.setText(
            f"{n} フレーム検出  エラー: {err}"
            + (f"\nASCII: {preview}" if preview else "")
        )
        self.decode_completed.emit(frames)
        self.fit_waveform.emit(wf)

    def _decode_i2c(self):
        """I2Cデコード実行"""
        wf = self._current_waveform
        sda_ch = 1 if self.i2c_sda_ch.currentText() == "CH1" else 2
        scl_ch = 1 if self.i2c_scl_ch.currentText() == "CH1" else 2

        sda_data = wf.ch1_data if sda_ch == 1 else wf.ch2_data
        scl_data = wf.ch1_data if scl_ch == 1 else wf.ch2_data

        if sda_data is None:
            self.status_label.setText(
                f"SDA (CH{sda_ch}) にデータがありません。CH2を有効にしてください。")
            return
        if scl_data is None:
            self.status_label.setText(
                f"SCL (CH{scl_ch}) にデータがありません。CH2を有効にしてください。")
            return
        if sda_ch == scl_ch:
            self.status_label.setText("SDAとSCLに異なるチャネルを選択してください")
            return

        decoder = I2CDecoder()
        try:
            frames = decoder.decode(
                wf.time_array, sda_data, scl_data,
                sda_threshold=self.i2c_sda_threshold.value(),
                scl_threshold=self.i2c_scl_threshold.value(),
            )
        except ValueError as e:
            self.status_label.setText(f"エラー: {e}")
            return

        # アドレスフィルタ
        addr_filter_text = self.i2c_addr_filter.text().strip()
        addr_filter = None
        if addr_filter_text:
            try:
                addr_filter = int(addr_filter_text, 0)  # 0x68 や 104 など
            except ValueError:
                pass

        # テーブル更新
        self._setup_table_columns("I2C")
        display_frames = []
        for frame in frames:
            if addr_filter is not None and frame.frame_type == 'address':
                if frame.data != addr_filter:
                    continue
            display_frames.append(frame)

        self.result_table.setRowCount(len(display_frames))
        for row_idx, frame in enumerate(display_frames):
            rw_str = 'R' if frame.is_read else 'W'
            ack_str = 'ACK' if frame.ack else 'NAK'

            if frame.frame_type in ('start', 'restart'):
                vals = [str(row_idx), 'START' if frame.frame_type == 'start' else 'RS',
                        f"{frame.start_time:.6f}", '', '', '']
            elif frame.frame_type == 'stop':
                vals = [str(row_idx), 'STOP', f"{frame.start_time:.6f}", '', '', '']
            elif frame.frame_type == 'address':
                vals = [str(row_idx), 'ADDR', f"{frame.start_time:.6f}",
                        f"0x{frame.data:02X}", rw_str, ack_str]
            else:  # data
                vals = [str(row_idx), 'DATA', f"{frame.start_time:.6f}",
                        f"{frame.hex_str}  {frame.ascii_str}", '', ack_str]

            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                status = frame.status
                if 'NACK' in status:
                    item.setForeground(QColor(255, 200, 0))
                elif status not in ('OK', 'START/STOP'):
                    item.setForeground(QColor(255, 100, 100))
                self.result_table.setItem(row_idx, col, item)

        # サマリ
        addr_frames = [f for f in frames if f.frame_type == 'address']
        data_frames = [f for f in frames if f.frame_type == 'data']
        nacks = sum(1 for f in frames if f.frame_type in ('address', 'data') and not f.ack)
        self.status_label.setText(
            f"{len(frames)} フレーム  "
            f"ADDR:{len(addr_frames)}  DATA:{len(data_frames)}  NACK:{nacks}"
        )
        self.decode_completed.emit(frames)
        self.fit_waveform.emit(wf)


class MainWindow(QMainWindow):
    """メインウィンドウ"""

    def __init__(self, simulation_mode: bool = None):
        super().__init__()
        self.setWindowTitle("VDS1022I データロガー")
        self.setGeometry(100, 100, 1400, 900)

        # 実機接続を試みる（simulation_mode=Noneの場合は自動検出）
        if simulation_mode is None:
            # 実機接続を試みる
            try:
                # libusb_packageのバックエンドを設定
                try:
                    import libusb_package
                    import usb.backend.libusb1
                    backend = libusb_package.get_libusb1_backend()
                    if backend:
                        usb.backend.libusb1.get_backend = lambda *a, **k: backend
                except ImportError:
                    pass

                from vds1022 import VDS1022
                test_device = VDS1022()
                test_device.dispose()
                simulation_mode = False
                print("VDS1022I 実機を検出しました")
            except Exception as e:
                simulation_mode = True
                print(f"実機が見つかりません。シミュレーションモードで起動します: {e}")

        # コントローラーとロガーを初期化
        self.controller = VDS1022Controller(simulation_mode=simulation_mode)
        self.data_logger = DataLogger(self.controller)

        # 現在の波形
        self.current_waveform: Optional[WaveformData] = None

        self._init_ui()
        self._init_connections()

        # 接続
        self._connect_device()

    def _init_ui(self):
        """UIを初期化"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)

        # 左側: 波形表示
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # コントロールボタン
        ctrl_layout = QHBoxLayout()

        self.btn_run = QPushButton("▶ 実行")
        self.btn_run.setCheckable(True)
        ctrl_layout.addWidget(self.btn_run)

        self.btn_single = QPushButton("単発")
        ctrl_layout.addWidget(self.btn_single)

        self.btn_save = QPushButton("波形保存")
        ctrl_layout.addWidget(self.btn_save)

        self.btn_cursor = QPushButton("カーソル")
        self.btn_cursor.setCheckable(True)
        ctrl_layout.addWidget(self.btn_cursor)

        ctrl_layout.addStretch()

        self.connection_label = QLabel("● 未接続")
        self.connection_label.setStyleSheet("color: red;")
        ctrl_layout.addWidget(self.connection_label)

        left_layout.addLayout(ctrl_layout)

        # 波形プロット
        self.plot_widget = WaveformPlotWidget()
        left_layout.addWidget(self.plot_widget)

        # 測定値パネル
        self.measurement_panel = MeasurementPanel()

        main_layout.addWidget(left_panel, stretch=3)

        # 右側: タブパネル
        right_panel = QTabWidget()

        # 設定タブ
        self.settings_panel = SettingsPanel(self.controller)
        right_panel.addTab(self.settings_panel, "設定")

        # 測定タブ
        right_panel.addTab(self.measurement_panel, "測定")

        # 履歴タブ
        self.history_panel = HistoryPanel(self.data_logger)
        right_panel.addTab(self.history_panel, "履歴")

        # ロギングタブ
        self.logging_panel = LoggingPanel(self.data_logger)
        right_panel.addTab(self.logging_panel, "ロギング")

        # デコードタブ
        self.decode_panel = DecodePanel()
        right_panel.addTab(self.decode_panel, "デコード")

        main_layout.addWidget(right_panel, stretch=1)

        # ステータスバー
        self.statusBar().showMessage("準備完了")

        # 取得スレッド
        self.acq_thread = AcquisitionThread(self.controller)

    def _init_connections(self):
        """シグナル接続"""
        self.btn_run.toggled.connect(self._on_run_toggled)
        self.btn_single.clicked.connect(self._on_single)
        self.btn_save.clicked.connect(self._on_save_waveform)
        self.btn_cursor.toggled.connect(self.plot_widget.toggle_cursors)

        self.acq_thread.waveform_ready.connect(self._on_waveform_ready)
        self.acq_thread.error_occurred.connect(self._on_error)

        self.history_panel.show_history.toggled.connect(self._on_history_toggled)
        self.history_panel.load_waveform.connect(self._on_load_saved_waveform)

        # デコード結果をオーバーレイ表示し、波形全体を自動フィット
        self.decode_panel.decode_completed.connect(self.plot_widget.show_decode_overlay)
        self.decode_panel.fit_waveform.connect(self.plot_widget.fit_to_data)

        # タイムベース・V/div変更時にプロットを更新
        self.settings_panel.time_base.currentIndexChanged.connect(self._on_time_base_changed)
        self.settings_panel.ch1_range.currentIndexChanged.connect(self._on_voltage_range_changed)
        self.settings_panel.ch2_range.currentIndexChanged.connect(self._on_voltage_range_changed)

    def _connect_device(self):
        """デバイスに接続"""
        if self.controller.connect():
            self.connection_label.setText("● 接続済み (シミュレーション)" if self.controller.simulation_mode else "● 接続済み")
            self.connection_label.setStyleSheet("color: green;")
            self.statusBar().showMessage("デバイスに接続しました")
        else:
            self.connection_label.setText("● 接続エラー")
            self.connection_label.setStyleSheet("color: red;")

    def _on_run_toggled(self, checked):
        """実行/停止"""
        if checked:
            self.acq_thread.start()
            self.btn_run.setText("⏹ 停止")
            self.statusBar().showMessage("取得中...")
        else:
            self.acq_thread.stop()
            self.btn_run.setText("▶ 実行")
            self.statusBar().showMessage("停止")

    def _on_single(self):
        """単発取得"""
        waveform = self.controller.acquire()
        if waveform:
            self._on_waveform_ready(waveform)

    def _on_waveform_ready(self, waveform: WaveformData):
        """波形データ受信"""
        self.current_waveform = waveform
        self.plot_widget.update_waveform(waveform)
        self.plot_widget.clear_decode_overlay()
        self.measurement_panel.update_measurements(waveform)
        self.data_logger.history.add(waveform)
        self.decode_panel.set_waveform(waveform)

        # 履歴スライダーの範囲更新
        self.history_panel.history_slider.setMaximum(len(self.data_logger.history) - 1)

    def _on_error(self, error_msg: str):
        """エラー処理"""
        self.statusBar().showMessage(f"エラー: {error_msg}")

    def _on_save_waveform(self):
        """波形を保存"""
        if not self.current_waveform:
            QMessageBox.warning(self, "警告", "保存する波形がありません")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "波形を保存", "", "NPZ Files (*.npz)"
        )
        if filepath:
            self.data_logger.save_single_waveform(self.current_waveform, filepath)
            self.statusBar().showMessage(f"波形を保存しました: {filepath}")

    def _on_time_base_changed(self, index):
        """タイムベース変更時"""
        time_base = self.settings_panel.time_base.itemData(index)
        self.plot_widget.set_time_base(time_base)

    def _on_voltage_range_changed(self, index):
        """V/div変更時: CH1のV/divをY軸スケールに反映"""
        v_div = self.settings_panel.ch1_range.currentData()
        self.plot_widget.set_voltage_range(v_div)

    def _on_history_toggled(self, show):
        """履歴表示切替"""
        if show:
            count = self.history_panel.history_count.value()
            waveforms = self.data_logger.history.get_latest(count)
            self.plot_widget.show_history(waveforms)
        else:
            self.plot_widget.clear_history()

    def _on_load_saved_waveform(self, waveform: WaveformData):
        """保存波形を読み込み"""
        # 実行中の場合は一時停止して波形を表示
        was_running = self.btn_run.isChecked()
        if was_running:
            self.btn_run.setChecked(False)

        # 現在のタイムベースとV/divを取得してプロットに設定
        time_base = self.settings_panel.time_base.currentData()
        v_div = self.settings_panel.ch1_range.currentData()
        self.plot_widget.set_time_base(time_base)
        self.plot_widget.set_voltage_range(v_div)

        # 波形データを読み込み（タイムベースに基づいて表示）
        self.plot_widget.load_waveform_data(waveform)
        self.measurement_panel.update_measurements(waveform)
        self.current_waveform = waveform

        # ステータスバーに情報表示
        samples = len(waveform.time_array)
        duration = waveform.time_array[-1] - waveform.time_array[0]
        self.statusBar().showMessage(
            f"読込完了: {samples:,}サンプル, {duration:.3f}秒 (ドラッグでスクロール)"
        )

    def closeEvent(self, event):
        """終了処理"""
        self.acq_thread.stop()
        self.data_logger.stop_logging()
        self.controller.disconnect()
        event.accept()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="VDS1022I データロガー")
    parser.add_argument("--simulation", "-s", action="store_true",
                        help="シミュレーションモードで起動")
    parser.add_argument("--real", "-r", action="store_true",
                        help="実機モードで起動（接続失敗時はエラー）")
    args = parser.parse_args()

    # モード決定
    if args.simulation:
        simulation_mode = True
    elif args.real:
        simulation_mode = False
    else:
        simulation_mode = None  # 自動検出

    app = QApplication(sys.argv)

    # ダークテーマ
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)

    window = MainWindow(simulation_mode=simulation_mode)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
