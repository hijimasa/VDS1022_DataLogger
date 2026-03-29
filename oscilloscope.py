"""
VDS1022I オシロスコープ制御モジュール
実機接続とシミュレーションモードをサポート
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum
import time


def _setup_libusb_backend():
    """libusb_packageのバックエンドを設定（Windows用）"""
    try:
        import libusb_package
        import usb.backend.libusb1

        backend = libusb_package.get_libusb1_backend()
        if backend:
            original_get_backend = usb.backend.libusb1.get_backend

            def patched_get_backend(*args, **kwargs):
                return backend

            usb.backend.libusb1.get_backend = patched_get_backend
            return True
    except ImportError:
        pass
    return False


# Windows環境でlibusb_packageを使用
_setup_libusb_backend()


class TriggerMode(Enum):
    AUTO = "auto"
    NORMAL = "normal"
    SINGLE = "single"


class TriggerEdge(Enum):
    RISING = "rising"
    FALLING = "falling"


class Coupling(Enum):
    DC = "dc"
    AC = "ac"
    GND = "gnd"


@dataclass
class WaveformData:
    """波形データを格納するクラス"""
    timestamp: float
    time_array: np.ndarray  # 時間軸 (秒)
    ch1_data: Optional[np.ndarray]  # CH1電圧データ
    ch2_data: Optional[np.ndarray]  # CH2電圧データ
    sample_rate: float  # サンプリングレート (Hz)
    voltage_range_ch1: float  # CH1電圧レンジ
    voltage_range_ch2: float  # CH2電圧レンジ

    def get_measurements(self, channel: int = 1) -> dict:
        """測定値を計算"""
        data = self.ch1_data if channel == 1 else self.ch2_data
        if data is None:
            return {}

        return {
            "vpp": float(np.max(data) - np.min(data)),
            "vmax": float(np.max(data)),
            "vmin": float(np.min(data)),
            "vrms": float(np.sqrt(np.mean(data ** 2))),
            "vavg": float(np.mean(data)),
            "frequency": self._estimate_frequency(data),
        }

    def _estimate_frequency(self, data: np.ndarray) -> float:
        """ゼロクロス法で周波数を推定"""
        if len(data) < 10:
            return 0.0

        # DCオフセットを除去
        data_centered = data - np.mean(data)

        # ゼロクロス点を検出
        zero_crossings = np.where(np.diff(np.signbit(data_centered)))[0]

        if len(zero_crossings) < 2:
            return 0.0

        # 平均周期を計算
        avg_samples_per_half_period = np.mean(np.diff(zero_crossings))
        period = 2 * avg_samples_per_half_period / self.sample_rate

        if period > 0:
            return 1.0 / period
        return 0.0


class VDS1022Controller:
    """VDS1022I オシロスコープコントローラー"""

    # 利用可能な電圧レンジ (V/div)
    VOLTAGE_RANGES = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]

    # 利用可能なサンプリングレート
    SAMPLE_RATES = [
        100e6, 50e6, 25e6, 10e6, 5e6, 2.5e6, 1e6,
        500e3, 250e3, 100e3, 50e3, 25e3, 10e3, 5e3, 2.5e3, 1e3
    ]

    # タイムベース (s/div)
    TIME_BASES = [
        5e-9, 10e-9, 25e-9, 50e-9, 100e-9, 250e-9, 500e-9,
        1e-6, 2.5e-6, 5e-6, 10e-6, 25e-6, 50e-6, 100e-6, 250e-6, 500e-6,
        1e-3, 2.5e-3, 5e-3, 10e-3, 25e-3, 50e-3, 100e-3, 250e-3, 500e-3,
        1.0, 2.5, 5.0, 10.0
    ]

    def __init__(self, simulation_mode: bool = True):
        """
        Args:
            simulation_mode: Trueの場合、実機なしでシミュレーション動作
        """
        self.simulation_mode = simulation_mode
        self.connected = False
        self.device = None

        # チャネル設定
        self.ch1_enabled = True
        self.ch2_enabled = False
        self.voltage_range_ch1 = 1.0  # V/div
        self.voltage_range_ch2 = 1.0
        self.coupling_ch1 = Coupling.DC
        self.coupling_ch2 = Coupling.DC
        self.offset_ch1 = 0.0
        self.offset_ch2 = 0.0
        self.probe_ratio_ch1 = 1  # 1x or 10x
        self.probe_ratio_ch2 = 1

        # タイムベース設定
        self.time_base = 1e-3  # s/div
        self.sample_rate = 1e6  # Hz

        # トリガー設定
        self.trigger_mode = TriggerMode.AUTO
        self.trigger_source = 1  # 1 or 2
        self.trigger_level = 0.0
        self.trigger_edge = TriggerEdge.RISING

        # シミュレーション用パラメータ
        self._sim_frequency = 1000  # Hz
        self._sim_amplitude = 2.0   # V
        self._sim_waveform = "sine"
        self._sim_noise_level = 0.05

    def connect(self) -> bool:
        """オシロスコープに接続"""
        if self.simulation_mode:
            self.connected = True
            return True

        try:
            from vds1022 import VDS1022
            self.device = VDS1022()

            # 初期チャネル設定
            self._apply_channel_settings()

            self.connected = True
            print("VDS1022I に接続しました")
            return True
        except ImportError:
            print("vds1022モジュールが見つかりません。シミュレーションモードで動作します。")
            self.simulation_mode = True
            self.connected = True
            return True
        except Exception as e:
            print(f"接続エラー: {e}")
            return False

    def _apply_channel_settings(self):
        """実機にチャネル設定を適用"""
        if not self.device or self.simulation_mode:
            return

        try:
            # vds1022のチャネル定数: CH1=0, CH2=1
            from vds1022.vds1022 import CH1, CH2

            # CH1設定
            if self.ch1_enabled:
                # range: V/div の8倍が全範囲（8divなので）
                volt_range = self.voltage_range_ch1 * 8
                coupling = 1 if self.coupling_ch1 == Coupling.DC else 0
                self.device.set_channel(CH1, range=volt_range, probe=self.probe_ratio_ch1, coupling=coupling)

            # CH2設定
            if self.ch2_enabled:
                volt_range = self.voltage_range_ch2 * 8
                coupling = 1 if self.coupling_ch2 == Coupling.DC else 0
                self.device.set_channel(CH2, range=volt_range, probe=self.probe_ratio_ch2, coupling=coupling)
        except Exception as e:
            print(f"チャネル設定エラー: {e}")

    def disconnect(self):
        """接続を切断"""
        if self.device:
            try:
                self.device.dispose()
            except:
                try:
                    self.device.stop()
                except:
                    pass
        self.connected = False
        self.device = None

    def set_channel_enabled(self, channel: int, enabled: bool):
        """チャネルの有効/無効を設定"""
        if channel == 1:
            self.ch1_enabled = enabled
        else:
            self.ch2_enabled = enabled

        # 実機に設定を適用
        self._apply_channel_settings()

    def set_voltage_range(self, channel: int, voltage_range: float):
        """電圧レンジを設定 (V/div)"""
        if channel == 1:
            self.voltage_range_ch1 = voltage_range
        else:
            self.voltage_range_ch2 = voltage_range

        # 実機に設定を適用
        self._apply_channel_settings()

    def set_time_base(self, time_base: float):
        """タイムベースを設定 (s/div)"""
        self.time_base = time_base
        # サンプリングレートを自動調整
        total_time = time_base * 10  # 10 divisions
        self.sample_rate = 5000 / total_time  # 5000サンプル目標

        # 実機に設定を適用
        if self.device and not self.simulation_mode:
            try:
                self.device.set_timerange(total_time)
            except Exception as e:
                print(f"タイムベース設定エラー: {e}")

    def set_sample_rate(self, sample_rate: float):
        """サンプリングレートを設定"""
        self.sample_rate = sample_rate

        if self.device and not self.simulation_mode:
            try:
                self.device.set_sampling(sample_rate)
            except Exception as e:
                print(f"サンプリングレート設定エラー: {e}")

    def set_trigger(self, mode: TriggerMode = None, source: int = None,
                    level: float = None, edge: TriggerEdge = None):
        """トリガー設定"""
        if mode is not None:
            self.trigger_mode = mode
        if source is not None:
            self.trigger_source = source
        if level is not None:
            self.trigger_level = level
        if edge is not None:
            self.trigger_edge = edge

    def acquire(self) -> Optional[WaveformData]:
        """波形データを取得"""
        if not self.connected:
            return None

        if self.simulation_mode:
            return self._generate_simulation_data()

        try:
            # 実機からデータ取得 (vds1022ライブラリのfetch APIを使用)
            frames = self.device.fetch()

            # to_numpy() で [2, N] の配列を取得
            # data[0] = 時間配列 (秒)
            # data[1] = CH1電圧データ (V)
            # CH2が有効な場合は data[2] に CH2電圧データ
            data = frames.to_numpy()

            # 時間配列は最初の行
            time_array = data[0]
            num_samples = len(time_array)

            ch1_data = None
            ch2_data = None

            # CH1データは2行目 (index 1)
            if data.shape[0] >= 2 and self.ch1_enabled:
                ch1_data = data[1]

            # CH2データは3行目 (index 2) - 両チャネル有効時のみ
            if data.shape[0] >= 3 and self.ch2_enabled:
                ch2_data = data[2]

            # サンプリングレートを取得 (プロパティ)
            actual_sample_rate = self.device.sampling_rate

            return WaveformData(
                timestamp=time.time(),
                time_array=time_array,
                ch1_data=ch1_data,
                ch2_data=ch2_data,
                sample_rate=actual_sample_rate,
                voltage_range_ch1=self.voltage_range_ch1,
                voltage_range_ch2=self.voltage_range_ch2,
            )
        except Exception as e:
            print(f"データ取得エラー: {e}")
            return None

    def acquire_continuous(self, duration: float) -> Optional[WaveformData]:
        """
        指定時間の連続波形データを取得

        Args:
            duration: 記録時間（秒）

        Returns:
            WaveformData: 連続波形データ（サンプリングレート×duration のサンプル数）
        """
        if not self.connected:
            return None

        if self.simulation_mode:
            return self._generate_continuous_simulation_data(duration)

        try:
            # 実機から連続データ取得 (read APIを使用)
            frames = self.device.read(duration=duration)

            # to_numpy() で配列を取得
            data = frames.to_numpy()

            # 時間配列は最初の行
            time_array = data[0]

            ch1_data = None
            ch2_data = None

            # CH1データは2行目 (index 1)
            if data.shape[0] >= 2 and self.ch1_enabled:
                ch1_data = data[1]

            # CH2データは3行目 (index 2) - 両チャネル有効時のみ
            if data.shape[0] >= 3 and self.ch2_enabled:
                ch2_data = data[2]

            # サンプリングレートを取得
            actual_sample_rate = self.device.sampling_rate

            return WaveformData(
                timestamp=time.time(),
                time_array=time_array,
                ch1_data=ch1_data,
                ch2_data=ch2_data,
                sample_rate=actual_sample_rate,
                voltage_range_ch1=self.voltage_range_ch1,
                voltage_range_ch2=self.voltage_range_ch2,
            )
        except Exception as e:
            print(f"連続データ取得エラー: {e}")
            return None

    def _generate_continuous_simulation_data(self, duration: float) -> WaveformData:
        """シミュレーション用連続データを生成"""
        sample_rate = 250000  # 250kHz (実機と同等)
        num_samples = int(sample_rate * duration)
        time_array = np.linspace(0, duration, num_samples)

        ch1_data = None
        ch2_data = None

        if self.ch1_enabled:
            ch1_data = self._generate_waveform(time_array, self._sim_frequency,
                                                self._sim_amplitude, self._sim_waveform)
            ch1_data += np.random.normal(0, self._sim_noise_level, num_samples)
            ch1_data += self.offset_ch1

        if self.ch2_enabled:
            ch2_data = self._generate_waveform(time_array, self._sim_frequency * 2,
                                                self._sim_amplitude * 0.5, "square")
            ch2_data += np.random.normal(0, self._sim_noise_level * 0.5, num_samples)
            ch2_data += self.offset_ch2

        return WaveformData(
            timestamp=time.time(),
            time_array=time_array,
            ch1_data=ch1_data,
            ch2_data=ch2_data,
            sample_rate=sample_rate,
            voltage_range_ch1=self.voltage_range_ch1,
            voltage_range_ch2=self.voltage_range_ch2,
        )

    def _generate_simulation_data(self) -> WaveformData:
        """シミュレーション用データを生成"""
        num_samples = 5000
        total_time = self.time_base * 10
        time_array = np.linspace(0, total_time, num_samples)

        ch1_data = None
        ch2_data = None

        if self.ch1_enabled:
            ch1_data = self._generate_waveform(time_array, self._sim_frequency,
                                                self._sim_amplitude, self._sim_waveform)
            ch1_data += np.random.normal(0, self._sim_noise_level, num_samples)
            ch1_data += self.offset_ch1

        if self.ch2_enabled:
            # CH2は異なる周波数・位相
            ch2_data = self._generate_waveform(time_array, self._sim_frequency * 2,
                                                self._sim_amplitude * 0.5, "square")
            ch2_data += np.random.normal(0, self._sim_noise_level * 0.5, num_samples)
            ch2_data += self.offset_ch2

        return WaveformData(
            timestamp=time.time(),
            time_array=time_array,
            ch1_data=ch1_data,
            ch2_data=ch2_data,
            sample_rate=num_samples / total_time,
            voltage_range_ch1=self.voltage_range_ch1,
            voltage_range_ch2=self.voltage_range_ch2,
        )

    def _generate_waveform(self, t: np.ndarray, freq: float,
                           amplitude: float, waveform: str) -> np.ndarray:
        """波形を生成"""
        phase = 2 * np.pi * freq * t

        if waveform == "sine":
            return amplitude * np.sin(phase)
        elif waveform == "square":
            return amplitude * np.sign(np.sin(phase))
        elif waveform == "triangle":
            return amplitude * (2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1)
        elif waveform == "sawtooth":
            return amplitude * (2 * (t * freq - np.floor(t * freq)) - 1)
        else:
            return amplitude * np.sin(phase)

    def set_simulation_params(self, frequency: float = None, amplitude: float = None,
                              waveform: str = None, noise_level: float = None):
        """シミュレーションパラメータを設定"""
        if frequency is not None:
            self._sim_frequency = frequency
        if amplitude is not None:
            self._sim_amplitude = amplitude
        if waveform is not None:
            self._sim_waveform = waveform
        if noise_level is not None:
            self._sim_noise_level = noise_level

    def get_status(self) -> dict:
        """現在のステータスを取得"""
        return {
            "connected": self.connected,
            "simulation_mode": self.simulation_mode,
            "ch1_enabled": self.ch1_enabled,
            "ch2_enabled": self.ch2_enabled,
            "voltage_range_ch1": self.voltage_range_ch1,
            "voltage_range_ch2": self.voltage_range_ch2,
            "time_base": self.time_base,
            "sample_rate": self.sample_rate,
            "trigger_mode": self.trigger_mode.value,
            "trigger_level": self.trigger_level,
        }
