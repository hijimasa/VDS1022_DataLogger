"""
信号プロトコルデコーダー
UART / I2C / SPI / CAN デコードをサポート（sigrok互換アルゴリズム）

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


# ---------------------------------------------------------------------------
# SPI デコーダー
# ---------------------------------------------------------------------------

@dataclass
class SPIFrame:
    """デコードされたSPIフレーム"""
    start_time: float    # フレーム開始時刻（秒）
    end_time: float      # フレーム終了時刻（秒）
    start_idx: int       # 開始サンプルインデックス
    end_idx: int         # 終了サンプルインデックス
    data: int            # デコードされたバイト値
    channel: str         # 'MOSI' または 'MISO'
    bit_count: int       # 実際に取得できたビット数（不完全フレーム検出用）

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
        return f"[{self.data:02X}]"

    @property
    def overlay_label(self) -> str:
        return f"{self.hex_str}\n{self.ascii_str}"

    @property
    def status(self) -> str:
        if self.bit_count < 8:
            return 'フレームエラー'
        return 'OK'


class SPIDecoder:
    """
    SPIプロトコルデコーダー

    sigrok互換アルゴリズム:
    - CPOL/CPHA の4モード対応
    - CSなし時はSCLKアイドル期間をフレーム区切りとして使用
    - MSBファースト / LSBファースト選択可

    Mode 0 (CPOL=0, CPHA=0): アイドルLOW、立ち上がりでサンプリング
    Mode 1 (CPOL=0, CPHA=1): アイドルLOW、立ち下がりでサンプリング
    Mode 2 (CPOL=1, CPHA=0): アイドルHIGH、立ち下がりでサンプリング
    Mode 3 (CPOL=1, CPHA=1): アイドルHIGH、立ち上がりでサンプリング
    """

    def __init__(self, mode: int = 0, data_bits: int = 8,
                 bit_order: str = 'msb', cs_active_low: bool = True):
        """
        Args:
            mode: SPIモード (0-3)
            data_bits: 1ワードあたりのビット数 (通常8)
            bit_order: 'msb' (MSBファースト) または 'lsb' (LSBファースト)
            cs_active_low: CSがアクティブLOWかどうか
        """
        self.mode = mode
        self.data_bits = data_bits
        self.bit_order = bit_order
        self.cs_active_low = cs_active_low
        # CPOL/CPHA を展開
        self.cpol = (mode >> 1) & 1  # 0 or 1
        self.cpha = mode & 1          # 0 or 1

    def decode(self,
               time_array: np.ndarray,
               sclk_voltage: np.ndarray,
               data_voltage: np.ndarray,
               sclk_threshold: float,
               data_threshold: float,
               cs_voltage: np.ndarray = None,
               cs_threshold: float = 1.65,
               data_label: str = 'MOSI') -> List[SPIFrame]:
        """
        SCLK + データライン電圧波形からSPIフレームをデコード

        Args:
            time_array: 時間配列（秒）
            sclk_voltage: SCLK電圧配列（V）
            data_voltage: MOSI または MISO 電圧配列（V）
            sclk_threshold: SCLKスレッショルド電圧（V）
            data_threshold: データラインスレッショルド電圧（V）
            cs_voltage: CS電圧配列（V）。Noneの場合SCLKアイドルで区切り
            cs_threshold: CSスレッショルド電圧（V）
            data_label: フレームの channel ラベル ('MOSI' or 'MISO')

        Returns:
            デコードされたSPIフレームのリスト

        Raises:
            ValueError: サンプリングレートが不足している場合
        """
        if len(time_array) < 4:
            return []

        sclk = threshold_signal(sclk_voltage, sclk_threshold)
        data = threshold_signal(data_voltage, data_threshold)
        n = len(time_array)

        # CS信号がある場合
        cs = None
        if cs_voltage is not None:
            cs = threshold_signal(cs_voltage, cs_threshold)
            if self.cs_active_low:
                cs = 1 - cs  # active=1, inactive=0 に正規化

        # サンプリングレートとSPBチェック
        dt = float(time_array[1] - time_array[0])
        sample_rate = 1.0 / dt

        # SCLKエッジ間隔からクロック周波数を推定
        sclk_edges = np.where(np.diff(sclk) != 0)[0]
        if len(sclk_edges) >= 2:
            avg_half_period = float(np.mean(np.diff(sclk_edges)))
            if avg_half_period < 1.5:
                est_freq = sample_rate / (avg_half_period * 2)
                raise ValueError(
                    f"サンプリングレートが不足: {sample_rate / 1000:.1f}kHz, "
                    f"推定SPI {est_freq / 1000:.0f}kHz には "
                    f"{est_freq * 3 / 1000:.0f}kHz 以上必要"
                )

        # サンプリングエッジを決定
        # CPHA=0: 最初のエッジ(leading)でサンプリング
        # CPHA=1: 2番目のエッジ(trailing)でサンプリング
        # CPOL=0: leading=立ち上がり, trailing=立ち下がり
        # CPOL=1: leading=立ち下がり, trailing=立ち上がり
        if self.cpha == 0:
            # leading edge でサンプリング
            if self.cpol == 0:
                # 立ち上がり (0→1)
                sample_edges = np.where((sclk[:-1] == 0) & (sclk[1:] == 1))[0] + 1
            else:
                # 立ち下がり (1→0)
                sample_edges = np.where((sclk[:-1] == 1) & (sclk[1:] == 0))[0] + 1
        else:
            # trailing edge でサンプリング
            if self.cpol == 0:
                # 立ち下がり (1→0)
                sample_edges = np.where((sclk[:-1] == 1) & (sclk[1:] == 0))[0] + 1
            else:
                # 立ち上がり (0→1)
                sample_edges = np.where((sclk[:-1] == 0) & (sclk[1:] == 1))[0] + 1

        if len(sample_edges) == 0:
            return []

        # トランザクション区切りを検出
        # CSがある場合: CSアクティブ区間のエッジのみ使用
        # CSがない場合: SCLKエッジ間隔が平均の3倍以上をアイドルとみなす
        if cs is not None:
            # CSアクティブなエッジのみ抽出
            active_mask = np.array([cs[min(e, n - 1)] == 1 for e in sample_edges])
            sample_edges = sample_edges[active_mask]
            if len(sample_edges) == 0:
                return []

        # エッジ間隔からアイドル検出してグループ分け
        if len(sample_edges) < 2:
            groups = [sample_edges]
        else:
            gaps = np.diff(sample_edges)
            median_gap = float(np.median(gaps))
            idle_threshold = median_gap * 3.0
            split_points = np.where(gaps > idle_threshold)[0] + 1
            groups = np.split(sample_edges, split_points)

        frames: List[SPIFrame] = []

        for group in groups:
            if len(group) == 0:
                continue
            # グループ内のエッジをdata_bitsごとに区切ってフレーム化
            for word_start in range(0, len(group), self.data_bits):
                word_edges = group[word_start:word_start + self.data_bits]
                actual_bits = len(word_edges)

                # ビットを収集
                bits = [int(data[e]) for e in word_edges]

                # ビット順に応じてバイト値を再構成
                if self.bit_order == 'msb':
                    val = sum(b << (actual_bits - 1 - k) for k, b in enumerate(bits))
                else:
                    val = sum(b << k for k, b in enumerate(bits))

                frames.append(SPIFrame(
                    start_time=float(time_array[word_edges[0]]),
                    end_time=float(time_array[word_edges[-1]]),
                    start_idx=int(word_edges[0]),
                    end_idx=int(word_edges[-1]),
                    data=val,
                    channel=data_label,
                    bit_count=actual_bits,
                ))

        return frames


# ---------------------------------------------------------------------------
# CAN デコーダー
# ---------------------------------------------------------------------------

def _crc15_can(data_bits: List[int]) -> int:
    """CRC-15/CAN計算（多項式: x^15+x^14+x^10+x^8+x^7+x^4+x^3+1 = 0x4599）"""
    crc = 0
    for bit in data_bits:
        crc_next = ((crc << 1) & 0x7FFF) ^ (0x4599 if (crc >> 14) ^ bit else 0)
        crc = crc_next
    return crc


def _stuff_bits(bits: List[int]) -> List[int]:
    """ビットスタッフィングを適用（CAN信号生成用）

    同極性5ビット連続の直後に逆極性のスタッフビットを挿入。
    """
    result = []
    count = 0
    last = -1
    for b in bits:
        result.append(b)
        if b == last:
            count += 1
        else:
            count = 1
            last = b
        if count == 5:
            result.append(1 - b)  # スタッフビット挿入
            count = 1
            last = 1 - b
    return result


def _destuff_bits(bits: List[int]) -> Tuple[List[int], int]:
    """ビットスタッフィングを除去（CANデコード用）

    Returns:
        (destuffed_bits, stuff_error_count)
    """
    result = []
    errors = 0
    count = 0
    last = -1
    i = 0
    while i < len(bits):
        b = bits[i]
        if count == 5:
            # スタッフビット: lastの逆であるべき
            if b == last:
                errors += 1
            count = 1
            last = b
            i += 1
            continue
        result.append(b)
        if b == last:
            count += 1
        else:
            count = 1
            last = b
        i += 1
    return result, errors


@dataclass
class CANFrame:
    """デコードされたCANフレーム"""
    start_time: float      # フレーム開始時刻（秒）
    end_time: float        # フレーム終了時刻（秒）
    start_idx: int         # 開始サンプルインデックス
    end_idx: int           # 終了サンプルインデックス
    frame_id: int          # アービトレーションID
    is_extended: bool      # True=29ビット拡張フレーム
    is_remote: bool        # True=リモートフレーム
    data: bytes            # データフィールド（0〜8バイト）
    dlc: int               # データ長コード
    crc_ok: bool           # CRC検証結果
    stuff_errors: int      # ビットスタッフィングエラー数

    @property
    def hex_str(self) -> str:
        return f"{self.frame_id:03X}" if not self.is_extended else f"{self.frame_id:08X}"

    @property
    def data_hex(self) -> str:
        return ' '.join(f'{b:02X}' for b in self.data)

    @property
    def overlay_label(self) -> str:
        id_str = self.hex_str
        rtr = 'RTR' if self.is_remote else self.data_hex
        return f"ID:{id_str}\n{rtr}"

    @property
    def status(self) -> str:
        if self.stuff_errors > 0:
            return 'スタッフエラー'
        if not self.crc_ok:
            return 'CRCエラー'
        return 'OK'


class CANDecoder:
    """
    CANプロトコルデコーダー

    sigrok互換アルゴリズム:
    - NRZ符号: ビット周期ごとにサンプルポイントで信号をサンプリング
    - ビットスタッフィング除去: 同極性5ビット連続後のスタッフビットを除去
    - CRC-15/CAN検証
    - 標準（11ビットID）および拡張（29ビットID）フレーム対応

    CAN物理層: ドミナント=LOW(0), リセッシブ=HIGH(1)
    """

    def __init__(self, bitrate: int = 250000, sample_point: float = 0.75):
        """
        Args:
            bitrate: ビットレート (bps)
            sample_point: ビット周期内のサンプリング位置 (0.0-1.0, 通常0.75)
        """
        self.bitrate = bitrate
        self.sample_point = sample_point

    def decode(self,
               time_array: np.ndarray,
               voltage_array: np.ndarray,
               threshold: float) -> List[CANFrame]:
        """
        電圧波形からCANフレームをデコード

        Args:
            time_array: 時間配列（秒）
            voltage_array: 電圧配列（V）
            threshold: スレッショルド電圧（V）。リセッシブ=HIGH, ドミナント=LOW。

        Returns:
            デコードされたCANフレームのリスト

        Raises:
            ValueError: サンプリングレートが不足している場合
        """
        if len(time_array) < 10:
            return []

        logic = threshold_signal(voltage_array, threshold)
        n = len(time_array)

        dt = float(time_array[1] - time_array[0])
        sample_rate = 1.0 / dt
        spb = sample_rate / self.bitrate  # samples per bit

        if spb < 3.0:
            raise ValueError(
                f"サンプリングレートが不足: {sample_rate / 1000:.1f}kHz, "
                f"{self.bitrate / 1000:.0f}kbps には "
                f"{self.bitrate * 3 / 1000:.0f}kHz 以上必要"
            )

        # サンプルポイントオフセット
        sp_offset = spb * self.sample_point

        frames: List[CANFrame] = []
        i = 0

        while i < n - 1:
            # SOF検出: リセッシブ(1)→ドミナント(0) 立ち下がりエッジ
            if logic[i] == 1 and logic[i + 1] == 0:
                sof_idx = i + 1
                sof_time = float(time_array[sof_idx])

                # SOFからビットストリームを収集
                # 最大フレーム長: SOF(1) + ID(11) + RTR(1) + IDE(1) + r0(1) + DLC(4) +
                #   DATA(64) + CRC(15) + CRC_DEL(1) + ACK(1) + ACK_DEL(1) + EOF(7) = 108
                # スタッフビット込みで最大 108 + 108/5 ≒ 130 ビット
                max_bits = 150
                raw_bits = []
                for k in range(max_bits):
                    sample_idx = int(sof_idx + sp_offset + k * spb)
                    if sample_idx >= n:
                        break
                    raw_bits.append(int(logic[sample_idx]))

                if len(raw_bits) < 20:
                    i = sof_idx + 1
                    continue

                # フレーム解析を試みる
                frame = self._parse_frame(raw_bits, sof_idx, sof_time,
                                          time_array, spb)
                if frame is not None:
                    frames.append(frame)
                    # フレーム終端までスキップ
                    i = frame.end_idx + 1
                else:
                    i = sof_idx + 1
            else:
                i += 1

        return frames

    def _parse_frame(self, raw_bits: List[int], sof_idx: int,
                     sof_time: float, time_array: np.ndarray,
                     spb: float):
        """生ビット列からCANフレームをパースする

        ビットスタッフィングはSOFからCRC末尾までのみ適用される。
        CRCデリミタ以降（ACK, EOF）はスタッフィング対象外。
        ストリーミングデスタッフで正確にraw_bits位置を追跡する。
        """
        if raw_bits[0] != 0:
            return None

        # ストリーミングデスタッフャー: raw_bitsから1ビットずつ読み出し、
        # スタッフビットをスキップしながらデスタッフ済みビットを返す。
        raw_pos = 0        # raw_bits 内の現在位置
        stuff_count = 0    # 同一ビット連続数
        stuff_last = -1    # 最後のビット値
        stuff_errors = 0

        def read_destuffed(num: int) -> List[int]:
            """スタッフビットを除去しながら num ビット読み出す"""
            nonlocal raw_pos, stuff_count, stuff_last, stuff_errors
            result = []
            while len(result) < num and raw_pos < len(raw_bits):
                b = raw_bits[raw_pos]
                if stuff_count == 5:
                    # スタッフビット位置: lastの逆であるべき
                    if b == stuff_last:
                        stuff_errors += 1
                    stuff_count = 1
                    stuff_last = b
                    raw_pos += 1
                    continue
                result.append(b)
                if b == stuff_last:
                    stuff_count += 1
                else:
                    stuff_count = 1
                    stuff_last = b
                raw_pos += 1
            return result

        def read_raw(num: int) -> List[int]:
            """スタッフ除去なしで直接 num ビット読み出す"""
            nonlocal raw_pos
            result = []
            while len(result) < num and raw_pos < len(raw_bits):
                result.append(raw_bits[raw_pos])
                raw_pos += 1
            return result

        # SOF (1ビット ドミナント) — スタッフ対象
        sof = read_destuffed(1)
        if not sof or sof[0] != 0:
            return None

        # アービトレーションID (11ビット)
        id_bits = read_destuffed(11)
        if len(id_bits) < 11:
            return None
        frame_id = sum(b << (10 - k) for k, b in enumerate(id_bits))

        # RTRビット
        rtr_bits = read_destuffed(1)
        if len(rtr_bits) < 1:
            return None
        rtr_bit = rtr_bits[0]

        # IDEビット
        ide_bits = read_destuffed(1)
        if len(ide_bits) < 1:
            return None
        ide_bit = ide_bits[0]

        is_extended = (ide_bit == 1)
        is_remote = (rtr_bit == 1) and not is_extended

        if is_extended:
            # 拡張フレーム: ID拡張18ビット
            ext_id_bits = read_destuffed(18)
            if len(ext_id_bits) < 18:
                return None
            ext_id = sum(b << (17 - k) for k, b in enumerate(ext_id_bits))
            frame_id = (frame_id << 18) | ext_id
            # 拡張フレームのRTRビット
            ext_rtr = read_destuffed(1)
            if len(ext_rtr) < 1:
                return None
            is_remote = (ext_rtr[0] == 1)

        # r0 (予約ビット)
        r0 = read_destuffed(1)
        if len(r0) < 1:
            return None

        # DLC (4ビット)
        dlc_bits = read_destuffed(4)
        if len(dlc_bits) < 4:
            return None
        dlc = sum(b << (3 - k) for k, b in enumerate(dlc_bits))
        dlc = min(dlc, 8)

        # データフィールド
        data_len = 0 if is_remote else dlc
        data_bytes = []
        for _ in range(data_len):
            byte_bits = read_destuffed(8)
            if len(byte_bits) < 8:
                return None
            byte_val = sum(b << (7 - k) for k, b in enumerate(byte_bits))
            data_bytes.append(byte_val)

        # CRC (15ビット) — スタッフ対象最後のフィールド
        crc_bits = read_destuffed(15)
        if len(crc_bits) < 15:
            return None
        received_crc = sum(b << (14 - k) for k, b in enumerate(crc_bits))

        # CRC検証: SOFからデータ末尾までで計算
        # 再構成: SOF + ID + RTR + IDE + [拡張] + r0 + DLC + DATA
        crc_input = [0]  # SOF
        crc_input.extend(id_bits)
        crc_input.append(rtr_bit)
        crc_input.append(ide_bit)
        if is_extended:
            crc_input.extend(ext_id_bits)
            crc_input.append(ext_rtr[0])
        crc_input.extend(r0)
        crc_input.extend(dlc_bits)
        for byte_val in data_bytes:
            for k in range(7, -1, -1):
                crc_input.append((byte_val >> k) & 1)
        computed_crc = _crc15_can(crc_input)
        crc_ok = (computed_crc == received_crc)

        # CRCデリミタ以降はスタッフィング対象外 → 直接読み出し
        # CRC_DEL(1) + ACK(1) + ACK_DEL(1) + EOF(7) = 10ビット
        _tail = read_raw(10)

        # フレーム終端インデックス
        end_idx = min(int(sof_idx + raw_pos * spb), len(time_array) - 1)
        end_time = float(time_array[end_idx])

        return CANFrame(
            start_time=sof_time,
            end_time=end_time,
            start_idx=sof_idx,
            end_idx=end_idx,
            frame_id=frame_id,
            is_extended=is_extended,
            is_remote=is_remote,
            data=bytes(data_bytes),
            dlc=dlc,
            crc_ok=crc_ok,
            stuff_errors=stuff_errors,
        )
