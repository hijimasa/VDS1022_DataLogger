"""
信号プロトコルデコーダー
UART / I2C デコードをサポート（sigrok互換アルゴリズム）

PyInstaller対応: 外部Cライブラリ不要の純Pythonで実装。
sigrokのデコーダーと同等のアルゴリズムを使用。
将来的にlibsigrokdecoderへの差し替えも可能な構造。
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class UARTFrame:
    """デコードされたUARTフレーム"""
    start_time: float    # フレーム開始時刻（秒）
    end_time: float      # フレーム終了時刻（秒）
    data: int            # データバイト値 (0-255)
    parity_ok: bool      # パリティ正常 (パリティなし時はTrue)
    frame_ok: bool       # フレーム正常 (ストップビットがHIGH)
    start_idx: int       # 開始サンプルインデックス
    end_idx: int         # 終了サンプルインデックス

    @property
    def hex_str(self) -> str:
        return f"{self.data:02X}"

    @property
    def ascii_str(self) -> str:
        if 0x20 <= self.data <= 0x7E:
            return chr(self.data)
        elif self.data == 0x0A:
            return "\\n"
        elif self.data == 0x0D:
            return "\\r"
        elif self.data == 0x09:
            return "\\t"
        elif self.data == 0x00:
            return "\\0"
        return f"[{self.data:02X}]"

    @property
    def overlay_label(self) -> str:
        return f"{self.hex_str}\n{self.ascii_str}"

    @property
    def status(self) -> str:
        if not self.frame_ok:
            return "フレームエラー"
        if not self.parity_ok:
            return "パリティエラー"
        return "OK"


def threshold_signal(voltage_array: np.ndarray, threshold: float) -> np.ndarray:
    """電圧信号を論理信号（0/1）に変換"""
    return (voltage_array > threshold).astype(np.uint8)


class UARTDecoder:
    """
    UARTプロトコルデコーダー

    sigrokのuartデコーダーと同等のアルゴリズムを使用:
    - 立ち下がりエッジ（HIGH→LOW）をスタートビットとして検出
    - 各ビットの中央をサンプリング（center sampling）
    - LSBファーストのデータ再構成

    TTL UART標準 (アイドルHIGH=1, スタートビット=LOW=0) に対応。
    invert=TrueにすることでアイドルLOW信号にも対応可能。
    """

    STANDARD_BAUDRATES = [
        300, 600, 1200, 2400, 4800, 9600, 14400, 19200,
        28800, 38400, 57600, 115200, 230400, 460800, 921600
    ]

    def __init__(self, baudrate: int = 9600, data_bits: int = 8,
                 parity: str = 'none', stop_bits: float = 1.0,
                 invert: bool = False):
        """
        Args:
            baudrate: ボーレート（bps）
            data_bits: データビット数（5-9, 通常8）
            parity: パリティ（'none', 'even', 'odd'）
            stop_bits: ストップビット数（1, 1.5, 2）
            invert: 論理反転フラグ（アイドルLOW信号の場合True）
        """
        self.baudrate = baudrate
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.invert = invert

    def decode(self, time_array: np.ndarray, voltage_array: np.ndarray,
               threshold: float) -> List[UARTFrame]:
        """
        電圧波形からUARTフレームをデコード

        Args:
            time_array: 時間配列（秒）
            voltage_array: 電圧配列（V）
            threshold: スレッショルド電圧（V）。この電圧以上をHIGH(1)とする。

        Returns:
            デコードされたUARTフレームのリスト

        Raises:
            ValueError: サンプリングレートが不足している場合
        """
        if len(time_array) < 2 or len(voltage_array) < 2:
            return []

        # 電圧 → 論理レベル変換
        logic = threshold_signal(voltage_array, threshold)
        if self.invert:
            logic = 1 - logic

        # サンプリングレートと1ビットあたりサンプル数
        dt = float(time_array[1] - time_array[0])
        sample_rate = 1.0 / dt
        spb = sample_rate / self.baudrate  # samples per bit

        if spb < 3.0:
            raise ValueError(
                f"サンプリングレートが不足: {sample_rate / 1000:.1f}kHz, "
                f"{self.baudrate}baud には {self.baudrate * 3 / 1000:.1f}kHz 以上必要"
            )

        n = len(logic)
        frames: List[UARTFrame] = []
        i = 0

        while i < n - 1:
            # スタートビット検出: HIGH(1) → LOW(0) の立ち下がりエッジ
            if logic[i] == 1 and logic[i + 1] == 0:
                frame_start = i + 1  # スタートビットの先頭インデックス

                # データビットをsigrok方式で中央サンプリング
                # データビット k の中央インデックス:
                #   frame_start + spb * (k + 1.5)
                #   = スタートビット1bit分 + kビット分 + 0.5ビット(中央)
                bits = []
                valid = True

                for k in range(self.data_bits):
                    idx = int(frame_start + spb * (k + 1.5))
                    if idx >= n:
                        valid = False
                        break
                    bits.append(int(logic[idx]))

                if not valid:
                    i += 1
                    continue

                # パリティビット検証
                parity_ok = True
                # bit_offset: start(1) + data_bits の次のビット番号
                bit_offset = self.data_bits + 1

                if self.parity != 'none':
                    pidx = int(frame_start + spb * (bit_offset + 0.5))
                    if pidx >= n:
                        i += 1
                        continue
                    parity_bit = int(logic[pidx])
                    ones = sum(bits)
                    if self.parity == 'even':
                        # 偶数パリティ: 1の数 + パリティビットが偶数 → parity_bit = ones%2
                        parity_ok = (ones % 2) == parity_bit
                    else:  # 'odd'
                        # 奇数パリティ: 1の数 + パリティビットが奇数 → parity_bit = 1 - ones%2
                        parity_ok = (ones % 2) != parity_bit
                    bit_offset += 1

                # ストップビット確認（最初の1ビットのみ）
                stop_idx = int(frame_start + spb * (bit_offset + 0.5))
                if stop_idx >= n:
                    i += 1
                    continue
                frame_ok = (logic[stop_idx] == 1)  # ストップビットはHIGHであるべき

                # フレーム終端インデックス
                frame_end = int(frame_start + spb * (bit_offset + self.stop_bits))
                frame_end = min(frame_end, n - 1)

                # バイト値を再構成（LSBファースト）
                byte_val = sum(b << k for k, b in enumerate(bits))

                frames.append(UARTFrame(
                    start_time=float(time_array[frame_start]),
                    end_time=float(time_array[frame_end]),
                    data=byte_val,
                    parity_ok=parity_ok,
                    frame_ok=frame_ok,
                    start_idx=frame_start,
                    end_idx=frame_end,
                ))

                # このフレームの終端から検索を再開
                i = frame_end + 1
            else:
                i += 1

        return frames


# ---------------------------------------------------------------------------
# I2C デコーダー
# ---------------------------------------------------------------------------

@dataclass
class I2CFrame:
    """デコードされたI2Cフレーム"""
    start_time: float    # フレーム開始時刻（秒）
    end_time: float      # フレーム終了時刻（秒）
    start_idx: int       # 開始サンプルインデックス
    end_idx: int         # 終了サンプルインデックス
    frame_type: str      # 'start', 'restart', 'address', 'data', 'stop'
    data: int            # アドレス値（7bit）またはデータバイト値
    is_read: bool        # True=読み込み方向（アドレスフレームのR/Wビット）
    ack: bool            # True=ACK, False=NACK

    @property
    def hex_str(self) -> str:
        if self.frame_type in ('start', 'restart'):
            return 'S' if self.frame_type == 'start' else 'RS'
        if self.frame_type == 'stop':
            return 'P'
        return f"{self.data:02X}"

    @property
    def ascii_str(self) -> str:
        if self.frame_type in ('start', 'restart', 'stop'):
            return ''
        if 0x20 <= self.data <= 0x7E:
            return chr(self.data)
        elif self.data == 0x0A:
            return "\\n"
        elif self.data == 0x0D:
            return "\\r"
        return f"[{self.data:02X}]"

    @property
    def overlay_label(self) -> str:
        if self.frame_type == 'start':
            return 'S'
        if self.frame_type == 'restart':
            return 'RS'
        if self.frame_type == 'stop':
            return 'P'
        ack_str = 'ACK' if self.ack else 'NAK'
        if self.frame_type == 'address':
            rw = 'R' if self.is_read else 'W'
            return f"{self.hex_str}\n{rw}|{ack_str}"
        # data
        return f"{self.hex_str}\n{self.ascii_str}\n{ack_str}"

    @property
    def status(self) -> str:
        if self.frame_type in ('start', 'restart', 'stop'):
            return 'START/STOP'
        if not self.ack:
            return 'NACK'
        return 'OK'


class I2CDecoder:
    """
    I2Cプロトコルデコーダー

    sigrok互換アルゴリズム:
    - SCL立ち上がりエッジでSDAをサンプリング（クロック同期）
    - SCL=HIGHのときにSDA立ち下がり → START条件
    - SCL=HIGHのときにSDA立ち上がり → STOP条件
    - 8ビット（MSBファースト）収集後の9ビット目 → ACK/NACK

    標準モード (100kHz): サンプリングレート ≥ 300kHz 推奨 (3 samples/bit)
    ファーストモード (400kHz): サンプリングレート ≥ 1.2MHz 推奨
    """

    def decode(self,
               time_array: np.ndarray,
               sda_voltage: np.ndarray,
               scl_voltage: np.ndarray,
               sda_threshold: float,
               scl_threshold: float) -> List[I2CFrame]:
        """
        SDA/SCL電圧波形からI2Cフレームをデコード

        Args:
            time_array: 時間配列（秒）
            sda_voltage: SDA電圧配列（V）
            scl_voltage: SCL電圧配列（V）
            sda_threshold: SDAスレッショルド電圧（V）
            scl_threshold: SCLスレッショルド電圧（V）

        Returns:
            デコードされたI2Cフレームのリスト

        Raises:
            ValueError: サンプリングレートが不足している場合
        """
        if len(time_array) < 4:
            return []

        sda = threshold_signal(sda_voltage, sda_threshold)
        scl = threshold_signal(scl_voltage, scl_threshold)
        n = len(time_array)

        # サンプリングレートと最小SPBを確認
        dt = float(time_array[1] - time_array[0])
        sample_rate = 1.0 / dt

        # SCL立ち上がりエッジ間隔からI2Cクロック周波数を推定してSPBをチェック
        scl_rising = np.where((scl[:-1] == 0) & (scl[1:] == 1))[0]
        if len(scl_rising) >= 2:
            avg_period_samples = float(np.mean(np.diff(scl_rising)))
            if avg_period_samples < 3.0:
                est_freq = sample_rate / avg_period_samples
                raise ValueError(
                    f"サンプリングレートが不足: {sample_rate / 1000:.1f}kHz, "
                    f"推定I2C {est_freq / 1000:.0f}kHz には "
                    f"{est_freq * 3 / 1000:.0f}kHz 以上必要"
                )

        frames: List[I2CFrame] = []
        state = 'IDLE'   # 'IDLE', 'ADDR', 'DATA'
        bits: List[int] = []
        bit_start_idx = 0
        in_transaction = False

        i = 1
        while i < n:
            scl_prev = int(scl[i - 1])
            scl_cur = int(scl[i])
            sda_prev = int(sda[i - 1])
            sda_cur = int(sda[i])

            # START / RESTART 条件: SCL=HIGH のとき SDA 立ち下がり
            if scl_prev == 1 and scl_cur == 1 and sda_prev == 1 and sda_cur == 0:
                ftype = 'restart' if in_transaction else 'start'
                frames.append(I2CFrame(
                    start_time=float(time_array[i - 1]),
                    end_time=float(time_array[i]),
                    start_idx=i - 1, end_idx=i,
                    frame_type=ftype,
                    data=0, is_read=False, ack=True,
                ))
                state = 'ADDR'
                bits = []
                bit_start_idx = i
                in_transaction = True
                i += 1
                continue

            # STOP 条件: SCL=HIGH のとき SDA 立ち上がり
            if scl_prev == 1 and scl_cur == 1 and sda_prev == 0 and sda_cur == 1:
                frames.append(I2CFrame(
                    start_time=float(time_array[i - 1]),
                    end_time=float(time_array[i]),
                    start_idx=i - 1, end_idx=i,
                    frame_type='stop',
                    data=0, is_read=False, ack=True,
                ))
                state = 'IDLE'
                bits = []
                in_transaction = False
                i += 1
                continue

            # データビット: SCL 立ち上がりエッジでSDAをサンプリング
            if state in ('ADDR', 'DATA') and scl_prev == 0 and scl_cur == 1:
                if not bits:
                    bit_start_idx = i
                bits.append(int(sda_cur))

                # 9ビット収集でバイト確定（8データビット + 1 ACK/NACKビット）
                if len(bits) == 9:
                    data_bits = bits[:8]
                    ack_bit = bits[8]

                    # MSBファーストで再構成
                    byte_val = sum(b << (7 - k) for k, b in enumerate(data_bits))
                    ack = (ack_bit == 0)  # ACK=LOW, NACK=HIGH

                    if state == 'ADDR':
                        addr = byte_val >> 1          # 上位7ビット
                        is_read = bool(byte_val & 1)  # ビット0 = R/W
                        frames.append(I2CFrame(
                            start_time=float(time_array[bit_start_idx]),
                            end_time=float(time_array[i]),
                            start_idx=bit_start_idx, end_idx=i,
                            frame_type='address',
                            data=addr, is_read=is_read, ack=ack,
                        ))
                        state = 'DATA'
                    else:
                        frames.append(I2CFrame(
                            start_time=float(time_array[bit_start_idx]),
                            end_time=float(time_array[i]),
                            start_idx=bit_start_idx, end_idx=i,
                            frame_type='data',
                            data=byte_val, is_read=False, ack=ack,
                        ))

                    bits = []

                i += 1
                continue

            i += 1

        return frames
