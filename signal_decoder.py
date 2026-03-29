"""
信号プロトコルデコーダー
UART デコードをサポート（sigrok互換アルゴリズム）

PyInstaller対応: 外部Cライブラリ不要の純Pythonで実装。
sigrokのUARTデコーダーと同等のエッジ検出・中央サンプリングアルゴリズムを使用。
将来的にlibsigrokdecoderへの差し替えも可能な構造。
"""

import numpy as np
from dataclasses import dataclass
from typing import List


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
