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
        self._sim_uart_baudrate = 9600
        self._sim_uart_message = b"Hello\r\n"
        self._sim_i2c_address = 0x68   # スレーブアドレス（7bit）例: MPU-6050
        self._sim_i2c_data = b'\x00\x01\x02'
        self._sim_i2c_freq = 100000    # Hz (Standard=100kHz)
        self._sim_spi_data = b'\xA5\x3C\x00'
        self._sim_spi_freq = 100000    # Hz
        self._sim_spi_mode = 0         # Mode 0 (CPOL=0, CPHA=0)
        self._sim_can_id = 0x123       # 11ビットID
        self._sim_can_data = b'\x01\x02\x03\x04'
        self._sim_can_bitrate = 250000 # bps

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

    def set_probe_ratio(self, channel: int, ratio: int):
        """プローブ倍率を設定 (1 or 10)"""
        if channel == 1:
            self.probe_ratio_ch1 = ratio
        else:
            self.probe_ratio_ch2 = ratio

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
                # プローブ倍率補正: x10プローブは信号を1/10に減衰するため、
                # 実際の電圧を得るにはprobe_ratio倍する
                if self.probe_ratio_ch1 > 1:
                    ch1_data = ch1_data * float(self.probe_ratio_ch1)

            # CH2データは3行目 (index 2) - 両チャネル有効時のみ
            if data.shape[0] >= 3 and self.ch2_enabled:
                ch2_data = data[2]
                if self.probe_ratio_ch2 > 1:
                    ch2_data = ch2_data * float(self.probe_ratio_ch2)

            # サンプリングレートを取得 (プロパティ)
            actual_sample_rate = self.device.sampling_rate

            return WaveformData(
                timestamp=time.time(),
                time_array=time_array,
                ch1_data=ch1_data,
                ch2_data=ch2_data,
                sample_rate=actual_sample_rate,
                voltage_range_ch1=self.voltage_range_ch1 * self.probe_ratio_ch1,
                voltage_range_ch2=self.voltage_range_ch2 * self.probe_ratio_ch2,
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
                if self.probe_ratio_ch1 > 1:
                    ch1_data = ch1_data * float(self.probe_ratio_ch1)

            # CH2データは3行目 (index 2) - 両チャネル有効時のみ
            if data.shape[0] >= 3 and self.ch2_enabled:
                ch2_data = data[2]
                if self.probe_ratio_ch2 > 1:
                    ch2_data = ch2_data * float(self.probe_ratio_ch2)

            # サンプリングレートを取得
            actual_sample_rate = self.device.sampling_rate

            return WaveformData(
                timestamp=time.time(),
                time_array=time_array,
                ch1_data=ch1_data,
                ch2_data=ch2_data,
                sample_rate=actual_sample_rate,
                voltage_range_ch1=self.voltage_range_ch1 * self.probe_ratio_ch1,
                voltage_range_ch2=self.voltage_range_ch2 * self.probe_ratio_ch2,
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

        if self._sim_waveform == "i2c":
            # I2C: CH1=SDA, CH2=SCL を同時生成
            sda, scl = self._generate_i2c_signal(time_array)
            noise = self._sim_noise_level * 0.05
            if self.ch1_enabled:
                ch1_data = sda + np.random.normal(0, noise, num_samples)
                ch1_data += self.offset_ch1
            if self.ch2_enabled:
                ch2_data = scl + np.random.normal(0, noise, num_samples)
                ch2_data += self.offset_ch2
        elif self._sim_waveform == "spi":
            # SPI: CH1=SCLK, CH2=MOSI を同時生成
            sclk, mosi = self._generate_spi_signal(time_array)
            noise = self._sim_noise_level * 0.05
            if self.ch1_enabled:
                ch1_data = sclk + np.random.normal(0, noise, num_samples)
                ch1_data += self.offset_ch1
            if self.ch2_enabled:
                ch2_data = mosi + np.random.normal(0, noise, num_samples)
                ch2_data += self.offset_ch2
        elif self._sim_waveform == "can":
            # CAN: CH1=CAN信号（1チャネル）
            can_sig = self._generate_can_signal(time_array)
            noise = self._sim_noise_level * 0.05
            if self.ch1_enabled:
                ch1_data = can_sig + np.random.normal(0, noise, num_samples)
                ch1_data += self.offset_ch1
            if self.ch2_enabled:
                ch2_data = can_sig + np.random.normal(0, noise, num_samples)
                ch2_data += self.offset_ch2
        else:
            if self.ch1_enabled:
                if self._sim_waveform == "uart":
                    ch1_data = self._generate_uart_signal(time_array)
                    ch1_data += np.random.normal(0, self._sim_noise_level * 0.1, num_samples)
                else:
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

    def _generate_uart_signal(self, time_array: np.ndarray,
                               v_high: float = 3.3, v_low: float = 0.0) -> np.ndarray:
        """
        TTL UART信号を生成（シミュレーション用）

        Args:
            time_array: 時間配列（秒）
            v_high: HIGH電圧（V）
            v_low: LOW電圧（V）

        Returns:
            UART信号の電圧配列
        """
        signal = np.full(len(time_array), v_high, dtype=np.float64)

        baudrate = self._sim_uart_baudrate
        bit_period = 1.0 / baudrate

        # 先頭に2ビット分のアイドル期間を設ける
        t_cursor = bit_period * 2.0

        for byte_val in self._sim_uart_message:
            if t_cursor >= time_array[-1]:
                break

            # ビット列: スタートビット(LOW) + 8データビット(LSBファースト) + ストップビット(HIGH)
            bit_levels = [0]  # START bit
            for k in range(8):
                bit_levels.append((byte_val >> k) & 1)
            bit_levels.append(1)  # STOP bit

            for level in bit_levels:
                t_end = t_cursor + bit_period
                i_start = int(np.searchsorted(time_array, t_cursor))
                i_end = int(np.searchsorted(time_array, t_end))
                signal[i_start:i_end] = v_high if level else v_low
                t_cursor = t_end

            # バイト間に1ビット分のアイドル時間
            t_cursor += bit_period

        return signal

    def _generate_i2c_signal(self, time_array: np.ndarray,
                              v_high: float = 3.3, v_low: float = 0.0) -> tuple:
        """
        I2C信号を生成（シミュレーション用）

        TTL I2C: 1ライトトランザクション（アドレス + データバイト列）を生成。
        CH1=SDA, CH2=SCL として使用する。

        Args:
            time_array: 時間配列（秒）
            v_high: HIGH電圧（V）
            v_low: LOW電圧（V）

        Returns:
            (sda_array, scl_array): SDA信号とSCL信号の電圧配列
        """
        n = len(time_array)
        sda = np.full(n, v_high, dtype=np.float64)
        scl = np.full(n, v_high, dtype=np.float64)

        freq = self._sim_i2c_freq
        hp = 1.0 / (2.0 * freq)   # ハーフクロック周期

        def set_sda(t0: float, t1: float, v: float):
            if t0 >= time_array[-1]:
                return
            i0 = int(np.searchsorted(time_array, t0))
            i1 = min(int(np.searchsorted(time_array, t1)), n)
            if i0 < i1:
                sda[i0:i1] = v

        def set_scl(t0: float, t1: float, v: float):
            if t0 >= time_array[-1]:
                return
            i0 = int(np.searchsorted(time_array, t0))
            i1 = min(int(np.searchsorted(time_array, t1)), n)
            if i0 < i1:
                scl[i0:i1] = v

        t = hp  # 1ハーフ周期アイドル

        # START 条件: SDA 立ち下がり（SCL=H のまま）
        set_sda(t, t + hp, v_low)
        t += hp
        # SCL 立ち下がり
        set_scl(t, t + hp, v_low)
        t += hp

        # 送信バイト列: アドレスバイト（7bit addr << 1 | W=0）+ データ
        address_byte = (self._sim_i2c_address << 1) | 0  # Write
        all_bytes = [address_byte] + list(self._sim_i2c_data)

        for byte_val in all_bytes:
            if t >= time_array[-1]:
                break
            # 8ビット MSBファースト送信
            for bit_pos in range(7, -1, -1):
                if t >= time_array[-1]:
                    break
                bit_v = v_high if ((byte_val >> bit_pos) & 1) else v_low
                # SCL LOW 期間: SDA セット
                set_scl(t, t + hp, v_low)
                set_sda(t, t + 2 * hp, bit_v)   # SDA は 1クロック周期保持
                # SCL HIGH 期間: サンプリング
                set_scl(t + hp, t + 2 * hp, v_high)
                t += 2 * hp

            if t >= time_array[-1]:
                break
            # ACK ビット（スレーブ = LOW）
            set_scl(t, t + hp, v_low)
            set_sda(t, t + 2 * hp, v_low)       # ACK = LOW
            set_scl(t + hp, t + 2 * hp, v_high)
            t += 2 * hp

        # STOP 条件: SCL HIGH → SDA 立ち上がり
        if t < time_array[-1]:
            set_scl(t, t + hp, v_low)
            set_sda(t, t + hp, v_low)     # SDA LOW を維持
            t += hp
            set_scl(t, t + hp, v_high)    # SCL HIGH
            set_sda(t, t + hp, v_low)     # SDA まだ LOW
            t += hp
            set_sda(t, t + hp, v_high)    # SDA HIGH: STOP

        return sda, scl

    def _generate_spi_signal(self, time_array: np.ndarray,
                              v_high: float = 3.3, v_low: float = 0.0) -> tuple:
        """
        SPI信号を生成（シミュレーション用）

        CH1=SCLK, CH2=MOSI として使用する。
        SCLKアイドル期間でトランザクションを区切る。

        Args:
            time_array: 時間配列（秒）
            v_high: HIGH電圧（V）
            v_low: LOW電圧（V）

        Returns:
            (sclk_array, mosi_array): SCLK信号とMOSI信号の電圧配列
        """
        n = len(time_array)
        cpol = (self._sim_spi_mode >> 1) & 1
        cpha = self._sim_spi_mode & 1
        idle_v = v_high if cpol else v_low

        sclk = np.full(n, idle_v, dtype=np.float64)
        mosi = np.full(n, v_low, dtype=np.float64)

        freq = self._sim_spi_freq
        hp = 1.0 / (2.0 * freq)  # ハーフクロック周期

        def set_range(arr, t0, t1, v):
            if t0 >= time_array[-1]:
                return
            i0 = int(np.searchsorted(time_array, t0))
            i1 = min(int(np.searchsorted(time_array, t1)), n)
            if i0 < i1:
                arr[i0:i1] = v

        t = hp * 2  # アイドル期間

        for byte_val in self._sim_spi_data:
            if t >= time_array[-1]:
                break

            for bit_pos in range(7, -1, -1):  # MSBファースト
                if t >= time_array[-1]:
                    break
                bit_v = v_high if ((byte_val >> bit_pos) & 1) else v_low

                if cpha == 0:
                    # CPHA=0: leadingエッジでサンプリング
                    # データをleadingエッジ前にセット
                    set_range(mosi, t, t + 2 * hp, bit_v)
                    # leading edge
                    leading_v = v_high if cpol == 0 else v_low
                    trailing_v = idle_v
                    set_range(sclk, t, t + hp, leading_v)
                    set_range(sclk, t + hp, t + 2 * hp, trailing_v)
                else:
                    # CPHA=1: trailingエッジでサンプリング
                    # leading edge（データ遷移用）
                    leading_v = v_high if cpol == 0 else v_low
                    trailing_v = idle_v
                    set_range(sclk, t, t + hp, leading_v)
                    # データをtrailingエッジ前にセット
                    set_range(mosi, t, t + 2 * hp, bit_v)
                    # trailing edge
                    set_range(sclk, t + hp, t + 2 * hp, trailing_v)

                t += 2 * hp

            # バイト間アイドル（2クロック分）
            set_range(sclk, t, t + 4 * hp, idle_v)
            set_range(mosi, t, t + 4 * hp, v_low)
            t += 4 * hp

        return sclk, mosi

    def _generate_can_signal(self, time_array: np.ndarray,
                              v_recessive: float = 3.3,
                              v_dominant: float = 0.0) -> np.ndarray:
        """
        CAN信号を生成（シミュレーション用）

        ビットスタッフィングを含む標準CANデータフレームを生成。
        CAN: リセッシブ=HIGH, ドミナント=LOW（NRZ符号）。

        Args:
            time_array: 時間配列（秒）
            v_recessive: リセッシブ電圧（V）= HIGH
            v_dominant: ドミナント電圧（V）= LOW

        Returns:
            CAN信号の電圧配列
        """
        from signal_decoder import _crc15_can, _stuff_bits

        n = len(time_array)
        signal = np.full(n, v_recessive, dtype=np.float64)

        bitrate = self._sim_can_bitrate
        bit_period = 1.0 / bitrate
        can_id = self._sim_can_id & 0x7FF  # 11ビット標準
        can_data = self._sim_can_data[:8]
        dlc = len(can_data)

        # フレームビット列を構築（スタッフィング前）
        frame_bits = []
        # SOF (1ビット ドミナント)
        frame_bits.append(0)
        # アービトレーションID (11ビット MSBファースト)
        for k in range(10, -1, -1):
            frame_bits.append((can_id >> k) & 1)
        # RTR (0=データフレーム)
        frame_bits.append(0)
        # IDE (0=標準フレーム)
        frame_bits.append(0)
        # r0 (予約=0)
        frame_bits.append(0)
        # DLC (4ビット)
        for k in range(3, -1, -1):
            frame_bits.append((dlc >> k) & 1)
        # データフィールド
        for byte_val in can_data:
            for k in range(7, -1, -1):
                frame_bits.append((byte_val >> k) & 1)

        # CRC計算（SOFからデータ末尾まで）
        crc = _crc15_can(frame_bits)
        # CRCフィールド (15ビット)
        for k in range(14, -1, -1):
            frame_bits.append((crc >> k) & 1)

        # ビットスタッフィング適用（SOFからCRC末尾まで）
        stuffed_bits = _stuff_bits(frame_bits)

        # CRCデリミタ (1ビット リセッシブ) — スタッフィング対象外
        stuffed_bits.append(1)
        # ACKスロット (1ビット ドミナント=ACK応答あり)
        stuffed_bits.append(0)
        # ACKデリミタ (1ビット リセッシブ)
        stuffed_bits.append(1)
        # EOF (7ビット リセッシブ)
        stuffed_bits.extend([1] * 7)
        # IFS (3ビット リセッシブ: インターフレームスペース)
        stuffed_bits.extend([1] * 3)

        # ビット列を信号に変換
        t_start = bit_period * 5  # 先頭にアイドル期間
        for k, bit_val in enumerate(stuffed_bits):
            t0 = t_start + k * bit_period
            t1 = t0 + bit_period
            if t0 >= time_array[-1]:
                break
            i0 = int(np.searchsorted(time_array, t0))
            i1 = min(int(np.searchsorted(time_array, t1)), n)
            if i0 < i1:
                signal[i0:i1] = v_dominant if bit_val == 0 else v_recessive

        return signal

    def set_simulation_params(self, frequency: float = None, amplitude: float = None,
                              waveform: str = None, noise_level: float = None,
                              uart_baudrate: int = None, uart_message: bytes = None,
                              i2c_address: int = None, i2c_data: bytes = None,
                              i2c_freq: int = None,
                              spi_data: bytes = None, spi_freq: int = None,
                              spi_mode: int = None,
                              can_id: int = None, can_data: bytes = None,
                              can_bitrate: int = None):
        """シミュレーションパラメータを設定"""
        if frequency is not None:
            self._sim_frequency = frequency
        if amplitude is not None:
            self._sim_amplitude = amplitude
        if waveform is not None:
            self._sim_waveform = waveform
        if noise_level is not None:
            self._sim_noise_level = noise_level
        if uart_baudrate is not None:
            self._sim_uart_baudrate = uart_baudrate
        if uart_message is not None:
            self._sim_uart_message = uart_message
        if i2c_address is not None:
            self._sim_i2c_address = i2c_address
        if i2c_data is not None:
            self._sim_i2c_data = i2c_data
        if i2c_freq is not None:
            self._sim_i2c_freq = i2c_freq
        if spi_data is not None:
            self._sim_spi_data = spi_data
        if spi_freq is not None:
            self._sim_spi_freq = spi_freq
        if spi_mode is not None:
            self._sim_spi_mode = spi_mode
        if can_id is not None:
            self._sim_can_id = can_id
        if can_data is not None:
            self._sim_can_data = can_data
        if can_bitrate is not None:
            self._sim_can_bitrate = can_bitrate

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
