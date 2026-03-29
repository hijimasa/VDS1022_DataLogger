"""
データロガーモジュール
波形データの記録、保存、読み込み機能を提供
"""

import json
import csv
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable
from dataclasses import dataclass, asdict
import numpy as np

from oscilloscope import WaveformData, VDS1022Controller


@dataclass
class LogEntry:
    """ログエントリ"""
    timestamp: float
    datetime_str: str
    ch1_vpp: Optional[float]
    ch1_vrms: Optional[float]
    ch1_vmax: Optional[float]
    ch1_vmin: Optional[float]
    ch1_freq: Optional[float]
    ch2_vpp: Optional[float]
    ch2_vrms: Optional[float]
    ch2_vmax: Optional[float]
    ch2_vmin: Optional[float]
    ch2_freq: Optional[float]


class WaveformHistory:
    """波形履歴を管理するクラス"""

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self._history: List[WaveformData] = []
        self._lock = threading.Lock()

    def add(self, waveform: WaveformData):
        """波形を履歴に追加"""
        with self._lock:
            self._history.append(waveform)
            if len(self._history) > self.max_history:
                self._history.pop(0)

    def get(self, index: int) -> Optional[WaveformData]:
        """指定インデックスの波形を取得"""
        with self._lock:
            if 0 <= index < len(self._history):
                return self._history[index]
            return None

    def get_latest(self, count: int = 1) -> List[WaveformData]:
        """最新のn個の波形を取得"""
        with self._lock:
            return self._history[-count:] if self._history else []

    def get_all(self) -> List[WaveformData]:
        """全履歴を取得"""
        with self._lock:
            return list(self._history)

    def clear(self):
        """履歴をクリア"""
        with self._lock:
            self._history.clear()

    def __len__(self) -> int:
        return len(self._history)


class DataLogger:
    """データロガークラス"""

    def __init__(self, controller: VDS1022Controller, log_dir: str = "logs"):
        self.controller = controller
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        self.history = WaveformHistory()
        self.log_entries: List[LogEntry] = []

        self._logging = False
        self._log_thread: Optional[threading.Thread] = None
        self._log_interval = 1.0  # 秒
        self._callbacks: List[Callable[[WaveformData], None]] = []

        self._current_log_file: Optional[Path] = None
        self._current_waveform_dir: Optional[Path] = None

        # 連続記録用
        self._continuous_recording = False
        self._continuous_thread: Optional[threading.Thread] = None

    def add_callback(self, callback: Callable[[WaveformData], None]):
        """新しい波形取得時のコールバックを追加"""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[WaveformData], None]):
        """コールバックを削除"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def start_logging(self, interval: float = 1.0, save_waveforms: bool = True):
        """ロギングを開始"""
        if self._logging:
            return

        self._log_interval = interval
        self._logging = True

        # ログファイルとディレクトリを作成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._current_log_file = self.log_dir / f"log_{timestamp}.csv"
        self._current_waveform_dir = self.log_dir / f"waveforms_{timestamp}"

        if save_waveforms:
            self._current_waveform_dir.mkdir(exist_ok=True)

        # CSVヘッダーを書き込み
        with open(self._current_log_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "datetime",
                "ch1_vpp", "ch1_vrms", "ch1_vmax", "ch1_vmin", "ch1_freq",
                "ch2_vpp", "ch2_vrms", "ch2_vmax", "ch2_vmin", "ch2_freq"
            ])

        self._log_thread = threading.Thread(target=self._logging_loop,
                                            args=(save_waveforms,), daemon=True)
        self._log_thread.start()

    def stop_logging(self):
        """ロギングを停止"""
        self._logging = False
        if self._log_thread:
            self._log_thread.join(timeout=2.0)
            self._log_thread = None

    def _logging_loop(self, save_waveforms: bool):
        """ロギングループ"""
        while self._logging:
            try:
                waveform = self.controller.acquire()
                if waveform:
                    self.history.add(waveform)

                    # 測定値を記録
                    entry = self._create_log_entry(waveform)
                    self.log_entries.append(entry)
                    self._write_log_entry(entry)

                    # 波形データを保存
                    if save_waveforms and self._current_waveform_dir:
                        self._save_waveform(waveform)

                    # コールバックを呼び出し
                    for callback in self._callbacks:
                        try:
                            callback(waveform)
                        except Exception as e:
                            print(f"Callback error: {e}")

            except Exception as e:
                print(f"Logging error: {e}")

            time.sleep(self._log_interval)

    def _create_log_entry(self, waveform: WaveformData) -> LogEntry:
        """波形データからログエントリを作成"""
        ch1_meas = waveform.get_measurements(1) if waveform.ch1_data is not None else {}
        ch2_meas = waveform.get_measurements(2) if waveform.ch2_data is not None else {}

        return LogEntry(
            timestamp=waveform.timestamp,
            datetime_str=datetime.fromtimestamp(waveform.timestamp).isoformat(),
            ch1_vpp=ch1_meas.get("vpp"),
            ch1_vrms=ch1_meas.get("vrms"),
            ch1_vmax=ch1_meas.get("vmax"),
            ch1_vmin=ch1_meas.get("vmin"),
            ch1_freq=ch1_meas.get("frequency"),
            ch2_vpp=ch2_meas.get("vpp"),
            ch2_vrms=ch2_meas.get("vrms"),
            ch2_vmax=ch2_meas.get("vmax"),
            ch2_vmin=ch2_meas.get("vmin"),
            ch2_freq=ch2_meas.get("frequency"),
        )

    def _write_log_entry(self, entry: LogEntry):
        """ログエントリをCSVに書き込み"""
        if not self._current_log_file:
            return

        with open(self._current_log_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                entry.timestamp, entry.datetime_str,
                entry.ch1_vpp, entry.ch1_vrms, entry.ch1_vmax, entry.ch1_vmin, entry.ch1_freq,
                entry.ch2_vpp, entry.ch2_vrms, entry.ch2_vmax, entry.ch2_vmin, entry.ch2_freq
            ])

    def _save_waveform(self, waveform: WaveformData):
        """波形データをファイルに保存"""
        if not self._current_waveform_dir:
            return

        filename = f"waveform_{int(waveform.timestamp * 1000)}.npz"
        filepath = self._current_waveform_dir / filename

        np.savez_compressed(
            filepath,
            timestamp=waveform.timestamp,
            time_array=waveform.time_array,
            ch1_data=waveform.ch1_data if waveform.ch1_data is not None else np.array([]),
            ch2_data=waveform.ch2_data if waveform.ch2_data is not None else np.array([]),
            sample_rate=waveform.sample_rate,
            voltage_range_ch1=waveform.voltage_range_ch1,
            voltage_range_ch2=waveform.voltage_range_ch2,
        )

    def save_single_waveform(self, waveform: WaveformData, filepath: str):
        """単一の波形をファイルに保存"""
        np.savez_compressed(
            filepath,
            timestamp=waveform.timestamp,
            time_array=waveform.time_array,
            ch1_data=waveform.ch1_data if waveform.ch1_data is not None else np.array([]),
            ch2_data=waveform.ch2_data if waveform.ch2_data is not None else np.array([]),
            sample_rate=waveform.sample_rate,
            voltage_range_ch1=waveform.voltage_range_ch1,
            voltage_range_ch2=waveform.voltage_range_ch2,
        )

    @staticmethod
    def load_waveform(filepath: str) -> Optional[WaveformData]:
        """保存された波形データを読み込み"""
        try:
            data = np.load(filepath)

            ch1_data = data['ch1_data']
            ch2_data = data['ch2_data']

            return WaveformData(
                timestamp=float(data['timestamp']),
                time_array=data['time_array'],
                ch1_data=ch1_data if len(ch1_data) > 0 else None,
                ch2_data=ch2_data if len(ch2_data) > 0 else None,
                sample_rate=float(data['sample_rate']),
                voltage_range_ch1=float(data['voltage_range_ch1']),
                voltage_range_ch2=float(data['voltage_range_ch2']),
            )
        except Exception as e:
            print(f"波形読み込みエラー: {e}")
            return None

    @staticmethod
    def convert_npz_to_csv(
        npz_filepath: str,
        csv_filepath: str,
        downsample: int = 1,
        max_rows: int = None
    ) -> bool:
        """
        NPZファイルをCSVに変換

        Args:
            npz_filepath: 入力NPZファイルパス
            csv_filepath: 出力CSVファイルパス
            downsample: 間引き率（1=全データ、10=10分の1、100=100分の1）
            max_rows: 最大行数（Noneで無制限、Excelは約100万行が上限）

        Returns:
            bool: 成功時True
        """
        try:
            waveform = DataLogger.load_waveform(npz_filepath)
            if waveform is None:
                return False

            # 間引き処理
            indices = np.arange(0, len(waveform.time_array), downsample)

            # 最大行数制限
            if max_rows and len(indices) > max_rows:
                indices = indices[:max_rows]

            time_data = waveform.time_array[indices]

            with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # ヘッダー
                headers = ["time_s"]
                if waveform.ch1_data is not None:
                    headers.append("ch1_v")
                if waveform.ch2_data is not None:
                    headers.append("ch2_v")
                writer.writerow(headers)

                # データ
                for i, idx in enumerate(indices):
                    row = [f"{time_data[i]:.9f}"]
                    if waveform.ch1_data is not None:
                        row.append(f"{waveform.ch1_data[idx]:.6f}")
                    if waveform.ch2_data is not None:
                        row.append(f"{waveform.ch2_data[idx]:.6f}")
                    writer.writerow(row)

            print(f"CSV変換完了: {len(indices):,}行 (間引き: {downsample})")
            return True

        except Exception as e:
            print(f"CSV変換エラー: {e}")
            return False

    @staticmethod
    def get_npz_info(npz_filepath: str) -> Optional[dict]:
        """NPZファイルの情報を取得"""
        try:
            waveform = DataLogger.load_waveform(npz_filepath)
            if waveform is None:
                return None

            duration = waveform.time_array[-1] - waveform.time_array[0]

            return {
                "samples": len(waveform.time_array),
                "sample_rate": waveform.sample_rate,
                "duration": duration,
                "has_ch1": waveform.ch1_data is not None,
                "has_ch2": waveform.ch2_data is not None,
                "timestamp": waveform.timestamp,
            }
        except Exception as e:
            print(f"NPZ情報取得エラー: {e}")
            return None

    def get_log_files(self) -> List[Path]:
        """利用可能なログファイル一覧を取得"""
        return sorted(self.log_dir.glob("log_*.csv"), reverse=True)

    def get_waveform_dirs(self) -> List[Path]:
        """利用可能な波形ディレクトリ一覧を取得"""
        return sorted(self.log_dir.glob("waveforms_*"), reverse=True)

    def load_log_file(self, filepath: str) -> List[LogEntry]:
        """ログファイルを読み込み"""
        entries = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    entry = LogEntry(
                        timestamp=float(row['timestamp']),
                        datetime_str=row['datetime'],
                        ch1_vpp=float(row['ch1_vpp']) if row['ch1_vpp'] else None,
                        ch1_vrms=float(row['ch1_vrms']) if row['ch1_vrms'] else None,
                        ch1_vmax=float(row['ch1_vmax']) if row['ch1_vmax'] else None,
                        ch1_vmin=float(row['ch1_vmin']) if row['ch1_vmin'] else None,
                        ch1_freq=float(row['ch1_freq']) if row['ch1_freq'] else None,
                        ch2_vpp=float(row['ch2_vpp']) if row['ch2_vpp'] else None,
                        ch2_vrms=float(row['ch2_vrms']) if row['ch2_vrms'] else None,
                        ch2_vmax=float(row['ch2_vmax']) if row['ch2_vmax'] else None,
                        ch2_vmin=float(row['ch2_vmin']) if row['ch2_vmin'] else None,
                        ch2_freq=float(row['ch2_freq']) if row['ch2_freq'] else None,
                    )
                    entries.append(entry)
        except Exception as e:
            print(f"ログ読み込みエラー: {e}")

        return entries

    def export_to_csv(self, filepath: str, entries: List[LogEntry] = None):
        """ログをCSVにエクスポート"""
        if entries is None:
            entries = self.log_entries

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "datetime",
                "ch1_vpp", "ch1_vrms", "ch1_vmax", "ch1_vmin", "ch1_freq",
                "ch2_vpp", "ch2_vrms", "ch2_vmax", "ch2_vmin", "ch2_freq"
            ])
            for entry in entries:
                writer.writerow([
                    entry.timestamp, entry.datetime_str,
                    entry.ch1_vpp, entry.ch1_vrms, entry.ch1_vmax, entry.ch1_vmin, entry.ch1_freq,
                    entry.ch2_vpp, entry.ch2_vrms, entry.ch2_vmax, entry.ch2_vmin, entry.ch2_freq
                ])

    @property
    def is_logging(self) -> bool:
        return self._logging

    @property
    def current_log_file(self) -> Optional[Path]:
        return self._current_log_file

    # ========== 連続記録機能 ==========

    def start_continuous_recording(
        self,
        duration: float,
        callback: Callable[[float, str], None] = None,
        completion_callback: Callable[[Optional[WaveformData], Optional[str]], None] = None
    ):
        """
        連続記録を開始（指定時間の波形を一括取得）

        Args:
            duration: 記録時間（秒）
            callback: 進捗コールバック (progress: 0-1, message: str)
            completion_callback: 完了コールバック (waveform, filepath)
        """
        if self._continuous_recording:
            return

        self._continuous_recording = True
        self._continuous_thread = threading.Thread(
            target=self._continuous_recording_worker,
            args=(duration, callback, completion_callback),
            daemon=True
        )
        self._continuous_thread.start()

    def _continuous_recording_worker(
        self,
        duration: float,
        callback: Callable[[float, str], None],
        completion_callback: Callable[[Optional[WaveformData], Optional[str]], None]
    ):
        """連続記録ワーカー"""
        try:
            if callback:
                callback(0.0, f"データ取得中... ({duration}秒間)")

            print(f"[連続記録] 開始: {duration}秒間のデータ取得")
            start_time = time.time()

            # 連続波形データを取得（これがブロッキング呼び出し）
            waveform = self.controller.acquire_continuous(duration)

            elapsed = time.time() - start_time
            print(f"[連続記録] データ取得完了: {elapsed:.1f}秒経過")

            if waveform is None:
                print("[連続記録] エラー: データ取得失敗")
                if completion_callback:
                    completion_callback(None, None)
                return

            samples = len(waveform.time_array)
            print(f"[連続記録] 取得サンプル数: {samples:,}")

            if callback:
                callback(0.7, f"NPZ保存中... ({samples:,}サンプル)")

            # ファイルに保存
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"continuous_{timestamp}_{duration}s.npz"
            filepath = self.log_dir / filename

            print(f"[連続記録] NPZ保存開始: {filepath}")
            self.save_single_waveform(waveform, str(filepath))
            print(f"[連続記録] NPZ保存完了")

            if callback:
                callback(0.9, "サマリーCSV保存中...")

            # 測定サマリーをCSVに保存
            summary_file = self.log_dir / f"continuous_{timestamp}_{duration}s_summary.csv"
            self._save_continuous_summary(waveform, summary_file, duration)
            print(f"[連続記録] サマリー保存完了")

            if callback:
                callback(1.0, f"完了: {samples:,}サンプル保存")

            if completion_callback:
                completion_callback(waveform, str(filepath))

        except Exception as e:
            print(f"[連続記録] エラー: {e}")
            import traceback
            traceback.print_exc()
            if completion_callback:
                completion_callback(None, None)
        finally:
            self._continuous_recording = False
            print("[連続記録] 処理終了")

    def _save_continuous_summary(self, waveform: WaveformData, filepath: Path, duration: float):
        """連続記録のサマリーをCSVに保存"""
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # メタ情報
            writer.writerow(["項目", "値"])
            writer.writerow(["記録開始時刻", datetime.fromtimestamp(waveform.timestamp).isoformat()])
            writer.writerow(["記録時間(秒)", duration])
            writer.writerow(["サンプル数", len(waveform.time_array)])
            writer.writerow(["サンプリングレート(Hz)", waveform.sample_rate])
            writer.writerow(["実効記録時間(秒)", waveform.time_array[-1] - waveform.time_array[0]])

            # CH1測定値
            if waveform.ch1_data is not None:
                meas = waveform.get_measurements(1)
                writer.writerow([])
                writer.writerow(["CH1測定値", ""])
                writer.writerow(["Vpp", meas.get("vpp")])
                writer.writerow(["Vrms", meas.get("vrms")])
                writer.writerow(["Vmax", meas.get("vmax")])
                writer.writerow(["Vmin", meas.get("vmin")])
                writer.writerow(["周波数(Hz)", meas.get("frequency")])

            # CH2測定値
            if waveform.ch2_data is not None:
                meas = waveform.get_measurements(2)
                writer.writerow([])
                writer.writerow(["CH2測定値", ""])
                writer.writerow(["Vpp", meas.get("vpp")])
                writer.writerow(["Vrms", meas.get("vrms")])
                writer.writerow(["Vmax", meas.get("vmax")])
                writer.writerow(["Vmin", meas.get("vmin")])
                writer.writerow(["周波数(Hz)", meas.get("frequency")])

    def stop_continuous_recording(self):
        """連続記録を中断（現在は即時停止不可）"""
        # read()はブロッキング呼び出しのため、中断は困難
        pass

    @property
    def is_continuous_recording(self) -> bool:
        return self._continuous_recording
