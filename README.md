# VDS1022I データロガー

OWON VDS1022I USBオシロスコープ用のPythonデータロガーアプリケーション。

## 機能

- **リアルタイム波形表示**: CH1/CH2の波形をリアルタイムで表示（OpenGL高速描画）
- **測定値表示**: Vpp, Vrms, Vmax, Vmin, 周波数を自動測定
- **波形履歴**: 過去の波形を重ねて表示可能
- **データロギング（間欠記録）**: 測定値をCSVファイルに自動記録
- **連続記録（高速）**: 約250kHzで指定時間の連続波形を一括取得（最大60秒）
- **NPZ→CSV変換**: 保存波形をExcel対応CSVに変換（間引き率指定可能）
- **波形ビューア**: 保存したNPZファイルをタイムベース/V/divに合わせて表示・スクロール
- **プロトコルデコード（UART）**: 単発取得波形からUARTフレームを自動デコード、波形上にオーバーレイ表示
- **設定変更**: 電圧レンジ、タイムベース、トリガー設定をGUIで変更
- **シミュレーションモード**: 実機なしで動作確認可能（UARTシミュレーション信号生成含む）
- **自動検出**: 起動時に実機を自動検出、なければシミュレーションモードで起動

## 動作環境

- Python 3.10以上
- Windows 10/11
- OWON VDS1022I USBオシロスコープ（実機使用時）

## インストール

### 1. 依存パッケージのインストール

```bash
pip install PyQt6 pyqtgraph numpy libusb-package pyusb
```

### 2. VDS1022ドライバーのインストール（実機使用時）

```bash
pip install git+https://github.com/florentbr/OWON-VDS1022.git#subdirectory=api/python
```

### 3. Windows: USBドライバー設定（実機使用時）

Zadigを使ってWinUSBドライバーをインストールします:

1. [Zadig](https://zadig.akeo.ie/) をダウンロード
2. VDS1022IをUSBで接続
3. Zadigを**管理者権限**で起動
4. **Options → List All Devices** にチェック
5. ドロップダウンから **VDS1022** / **OWON** / **ZPRO2.0** を選択
6. Driverを **WinUSB** に設定して **Replace Driver** をクリック

## 使用方法

### 起動

```bash
# 自動検出モード（推奨）: 実機があれば実機、なければシミュレーション
python main_gui.py

# 実機モード強制
python main_gui.py --real   # または -r

# シミュレーションモード強制
python main_gui.py --simulation  # または -s
```

接続ステータスはウィンドウ右上に表示されます:
- **● 接続済み** — 実機接続中
- **● 接続済み (シミュレーション)** — シミュレーションモード

## 画面構成

### メイン波形エリア
- CH1（黄色）/ CH2（シアン）をリアルタイム表示
- **▶ 実行 / ⏹ 停止**: 連続取得の開始/停止
- **単発**: 1回だけ取得
- **波形保存**: 現在の波形をNPZファイルに保存
- **カーソル**: 計測用カーソルの表示/非表示

### 設定タブ
| 項目 | 説明 |
|------|------|
| チャネル設定 | 有効/無効、電圧レンジ（V/div）、カップリング |
| タイムベース | 5ns〜10s/div |
| トリガー | モード（Auto/Normal/Single）、ソース、エッジ、レベル |
| シミュレーション設定 | 周波数、振幅、波形種類（uart含む）、ノイズ量 |

### 測定タブ
CH1/CH2の Vpp / Vrms / Vmax / Vmin / 周波数をリアルタイム表示。

### 履歴タブ
- **波形履歴**: 直近N波形を薄く重ねて表示
- **NPZ読込**: 保存済み波形ファイルを読み込み
  - ファイルのサンプル数・サンプリングレート・記録時間を表示
  - 読み込んだ波形は設定タブのタイムベース/V/divで表示
  - **ドラッグ**: 時間軸方向にスクロール
  - **マウスホイール**: Y軸スクロール（V/divの0.5倍刻み）
  - タイムベースを変更すると表示中央を基準に拡大縮小
- **CSV変換**: NPZファイルを間引き率指定でCSV出力（Excel対応）
- **ログファイル一覧**: 間欠記録のCSVログ一覧

### ロギングタブ

#### 連続記録（高速）
約250kHzの高速サンプリングで連続波形を一括取得して保存します。

| 項目 | 説明 |
|------|------|
| 記録時間 | 0.1〜60秒 |
| 出力ファイル | `logs/continuous_YYYYMMDD_HHMMSS_Xs.npz`（波形データ） |
| サマリー | `logs/continuous_YYYYMMDD_HHMMSS_Xs_summary.csv`（測定値） |

#### 間欠記録（測定値ログ）
指定間隔で測定値をCSVに記録します。

| 項目 | 説明 |
|------|------|
| 記録間隔 | 0.1〜60秒 |
| 出力ファイル | `logs/log_YYYYMMDD_HHMMSS.csv`（測定値） |
| 波形保存 | チェック時は各測定値のNPZも保存 |

#### 記録モードの使い分け

| | 連続記録 | 間欠記録 |
|---|---|---|
| **サンプリングレート** | 約250kHz（高速） | 測定値のみ（低速） |
| **最大記録時間** | 最大60秒 | 無制限（時間・日単位） |
| **出力形式** | NPZ（波形生データ）+ サマリーCSV | CSV（Vpp/Vrms/周波数など） |
| **ファイルサイズ** | 大（60秒で数十〜数百MB） | 小（86,400行/日） |
| **主な用途** | 過渡現象・短時間の高精度波形解析 | 長時間トレンド監視・システム稼働中の継続ログ |

**連続記録が向く場面**: モーター起動時のノイズ、通信波形の詳細解析、過渡応答の確認など短時間の高分解能が必要なケース。

**間欠記録が向く場面**: ロボットの長時間動作試験、電源品質の経時監視、耐久試験中の信号変化追跡など。

タイムスタンプはPCクロックと同期しており、CSVの `datetime` 列はISO 8601形式（例: `2026-03-29T14:32:07.123456`）で出力されます。ROSトピックログやモーションコントローラのエラーログと時刻を突き合わせることで、ロボットデバッグ時に異常発生時刻と電気信号の変化を紐づけた原因調査が可能です。

### デコードタブ

単発取得した波形からプロトコルを自動デコードし、結果を波形上にオーバーレイ表示します。

#### 操作手順

1. **設定タブ**でタイムベースをプロトコルに合わせて設定（後述の推奨値を参照）
2. **「単発」ボタン**で波形を取得（または「実行」後に「停止」）
3. **デコードタブ**を開く
4. デコード設定を入力し、**「自動」ボタン**でスレッショルドを自動設定
5. **「デコード実行」**をクリック

デコード完了後、波形は自動的に全データが10divに収まるように表示が切り替わります。設定タブのタイムベースで拡大/縮小、ドラッグでスクロールが可能です。

#### UART デコード設定

| 設定項目 | 説明 | 典型値 |
|---------|------|-------|
| チャネル | デコード対象チャネル | CH1 |
| ボーレート | 通信速度（bps） | 9600 / 115200 |
| データビット | 1フレームのデータビット数 | 8 |
| パリティ | パリティ検証方式 | なし |
| ストップビット | ストップビット数 | 1 |
| スレッショルド | HIGH/LOW判定電圧（V） | 「自動」ボタンで (Vmax+Vmin)/2 |

#### UART用タイムベース設定指針

単発取得は常に5,000サンプル固定で、**キャプチャ時間 = タイムベース × 10div** です。タイムベースが大きいほど長い時間を記録できますが、1ビットあたりのサンプル数（spb）が減り信頼性が下がります。

```
推奨タイムベース = 500 / (8 × ボーレート)  [s/div]
```

| ボーレート | 推奨タイムベース | キャプチャ時間 | 最大バイト数 | spb |
|-----------|---------------|-------------|------------|-----|
| 9,600 bps | 5 ms/div | 50 ms | ~48バイト | 10 |
| 19,200 bps | 2.5 ms/div | 25 ms | ~48バイト | 10 |
| 38,400 bps | 1 ms/div | 10 ms | ~38バイト | 13 |
| 57,600 bps | 1 ms/div | 10 ms | ~57バイト | 8.7 |
| 115,200 bps | 0.5 ms/div | 5 ms | ~57バイト | 4.3 |

> **1回の単発取得でデコードできる最大バイト数は約60バイト（推奨spb=8時）。** ボーレートに関わらずほぼ一定です。

#### デコード結果の見方

| 色 | 意味 |
|----|------|
| 緑（波形ハイライト） | 正常フレーム |
| 黄（波形ハイライト） | パリティエラー |
| 赤（波形ハイライト） | フレームエラー（ストップビット異常） |

結果テーブルには「時刻（秒）/ HEX / ASCII / 状態」が一覧表示されます。

#### シミュレーションでの動作確認

実機なしでUARTデコードをテストできます:

1. 設定タブ → シミュレーション設定 → 波形: **uart**
2. ボーレートとメッセージを設定（例: `Hello\r\n`）
3. タイムベースを推奨値に設定（9600bpsなら 5ms/div）
4. 「単発」→「デコード実行」

## ファイル構成

```
VDS1022_DataLogger/
├── main_gui.py         # メインGUIアプリケーション
├── oscilloscope.py     # オシロスコープ制御（実機/シミュレーション）
├── data_logger.py      # データロガー（CSV記録、波形保存、CSV変換）
├── signal_decoder.py   # プロトコルデコーダー（UART、将来: I2C/SPI/CAN）
├── requirements.txt    # 依存パッケージ
├── README.md
└── logs/               # 保存先（自動生成）
    ├── log_YYYYMMDD_HHMMSS.csv
    ├── continuous_YYYYMMDD_HHMMSS_Xs.npz
    ├── continuous_YYYYMMDD_HHMMSS_Xs_summary.csv
    └── waveforms_YYYYMMDD_HHMMSS/
```

## API使用例

### 基本的な波形取得

```python
from oscilloscope import VDS1022Controller

controller = VDS1022Controller(simulation_mode=False)
controller.connect()
controller.set_channel_enabled(1, True)
controller.set_voltage_range(1, 1.0)  # 1 V/div
controller.set_time_base(1e-3)        # 1 ms/div

waveform = controller.acquire()
print(f"CH1 Vpp: {waveform.get_measurements(1)['vpp']:.3f} V")
print(f"CH1 Freq: {waveform.get_measurements(1)['frequency']:.1f} Hz")

controller.disconnect()
```

### UARTデコード

```python
from oscilloscope import VDS1022Controller
from signal_decoder import UARTDecoder

controller = VDS1022Controller(simulation_mode=False)
controller.connect()
controller.set_channel_enabled(1, True)
controller.set_time_base(5e-3)   # 5ms/div → 50msキャプチャ（9600bps推奨）

waveform = controller.acquire()

decoder = UARTDecoder(baudrate=9600, data_bits=8, parity='none', stop_bits=1.0)
frames = decoder.decode(
    waveform.time_array,
    waveform.ch1_data,
    threshold=1.65  # (Vmax+Vmin)/2 を指定
)

for frame in frames:
    print(f"t={frame.start_time*1000:.2f}ms  0x{frame.hex_str}  '{frame.ascii_str}'  {frame.status}")

controller.disconnect()
```

### 連続記録

```python
from oscilloscope import VDS1022Controller
from data_logger import DataLogger

controller = VDS1022Controller(simulation_mode=False)
controller.connect()
controller.set_channel_enabled(1, True)

logger = DataLogger(controller)

def on_complete(waveform, filepath):
    if waveform:
        print(f"完了: {len(waveform.time_array):,}サンプル → {filepath}")

logger.start_continuous_recording(
    duration=5.0,
    completion_callback=on_complete
)

import time
while logger.is_continuous_recording:
    time.sleep(0.1)

controller.disconnect()
```

### NPZ→CSV変換

```python
from data_logger import DataLogger

# 間引き率10（1/10に削減）でCSV出力
DataLogger.convert_npz_to_csv(
    "logs/continuous_20260101_120000_5.0s.npz",
    "output.csv",
    downsample=10
)

# ファイル情報を取得
info = DataLogger.get_npz_info("logs/continuous_20260101_120000_5.0s.npz")
print(f"サンプル数: {info['samples']:,}")
print(f"記録時間: {info['duration']:.3f}秒")
print(f"サンプリングレート: {info['sample_rate']/1000:.1f} kHz")
```

## exeファイルのビルド（PyInstaller）

### ビルド手順

```bat
build.bat
```

または手動で:

```bash
pip install pyinstaller
pyinstaller vds1022_datalogger.spec
```

成功すると `dist/VDS1022_DataLogger/VDS1022_DataLogger.exe` が生成されます。

### 配布物

`dist/VDS1022_DataLogger/` フォルダ全体を配布します（exe単体では動きません）:

```
dist/VDS1022_DataLogger/
├── VDS1022_DataLogger.exe   # 起動ファイル
├── libusb-1.0.dll           # USB通信ライブラリ（自動配置）
├── PyQt6/                   # QtライブラリDLL群
├── ...
└── logs/                    # ログ保存先（初回起動時に自動生成）
```

### よくあるビルドエラー

**`ModuleNotFoundError: vds1022`**
vds1022がインストールされていない場合:
```bash
pip install git+https://github.com/florentbr/OWON-VDS1022.git#subdirectory=api/python
```

**`libusb-1.0.dll not found`**
specファイル内の `libusb_dll` パスが正しく検出されているか確認してください。

**起動時に画面が一瞬で消える**
デバッグのため一時的に `console=True` に変更してエラーを確認してください。

## トラブルシューティング

### "No backend available" エラー

```bash
pip install libusb-package
```

### 実機が検出されない

1. VDS1022IがUSBで接続されているか確認
2. Zadigで WinUSB ドライバーがインストールされているか確認
3. デバイスマネージャーで認識されているか確認

接続デバイス確認:
```bash
python -c "import libusb_package, usb.core; backend = libusb_package.get_libusb1_backend(); devs = list(usb.core.find(find_all=True, backend=backend)); print([f'{d.idVendor:04x}:{d.idProduct:04x}' for d in devs])"
```

VDS1022Iは `5345:1234` として表示されます。

### "8.0v range not available" の警告

vds1022ライブラリが自動的に最近い値（10V）に切り替えます。動作に問題はありません。

### 描画が重い場合

OpenGLが有効になっているか確認してください（`main_gui.py`の先頭付近）:
```python
pg.setConfigOptions(antialias=False, background='k', foreground='w', useOpenGL=True)
```

OpenGLが使えない環境では `useOpenGL=True` を削除してください。

### UARTデコードでフレームが検出されない

- スレッショルド電圧を確認（「自動」ボタンで (Vmax+Vmin)/2 を設定）
- タイムベースを確認（spbが3未満だとエラー、8以上を推奨）
- 信号がTTL UART（アイドルHIGH）であることを確認

## 技術情報

### vds1022 APIのデータ形式

`frames.to_numpy()` の戻り値（行列）:

| 行 | 内容 |
|----|------|
| Row 0 | 時間配列（秒） |
| Row 1 | CH1 電圧データ（V） |
| Row 2 | CH2 電圧データ（V）※両チャネル有効時のみ |

### 主要なAPIメソッド

| メソッド | 説明 |
|---------|------|
| `device.fetch()` | 単発取得（約5,000サンプル） |
| `device.read(duration)` | 連続取得（約250kHz × duration サンプル） |
| `device.sampling_rate` | サンプリングレート（プロパティ） |
| `device.dispose()` | デバイス切断（`close()`は使わない） |

### チャネル定数

```python
from vds1022.vds1022 import CH1, CH2  # CH1=0, CH2=1
```

### プロトコルデコーダーの実装方針

`signal_decoder.py` は外部Cライブラリ不要の純Python実装です。
sigrok（PulseView）のUARTデコーダーと同等のアルゴリズムを採用しています:

- **エッジ検出**: HIGH→LOW 立ち下がりをスタートビットとして検出
- **中央サンプリング**: 各ビットの中央時刻でサンプリング（sigrok方式）
- **LSBファースト**: 標準的なTTL UARTの再構成順序
- **PyInstaller対応**: `signal_decoder.py` 単体をバンドルするだけで動作

## 今後の実装計画：I2C / SPI / CAN デコード

現在UARTのみ対応しているデコード機能について、以下の順序での拡張を計画しています。

### Phase 1: I2C デコード

**プロトコル概要**:
I2CはSDA（データ）とSCL（クロック）の2線式同期通信。VDS1022IのCH1/CH2を両方使用します。

**実装アルゴリズム**:
1. SCLがHIGH中のSDA立ち下がり → **STARTコンディション**検出
2. SCL立ち上がりエッジでSDAをサンプリング → 1ビット取得
3. 先頭7ビット＋R/Wビット → **アドレスフレーム**
4. 9ビット目（SCLパルス時のSDA）→ **ACK/NACK**
5. 続くデータバイトを同様にデコード
6. SCLがHIGH中のSDA立ち上がり → **STOPコンディション**

**ハードウェア制約**:

| I2Cモード | クロック速度 | 必要サンプリングレート | 推奨タイムベース |
|----------|------------|-------------------|----------------|
| Standard | 100 kHz | 800 kHz以上 | 0.6 ms/div以下 |
| Fast | 400 kHz | 3.2 MHz以上 | 0.15 ms/div以下 |
| Fast+ | 1 MHz | 8 MHz以上 | 0.06 ms/div以下 |

VDS1022Iは最大1GSa/sですが、USB転送制限により連続取得は250kHzまで。単発取得（5,000サンプル）なら高サンプリングレートが利用可能なため、**Standard/Fastモードは単発取得でデコード可能**です。

**GUI変更点**:
- チャネル選択を「CH1=SDA, CH2=SCL」の2チャネル固定に
- アドレスフィルタ（特定スレーブのみ表示）
- 結果テーブル: アドレス / R(読込)/W(書込) / データ列 / ACK/NACK

---

### Phase 2: SPI デコード

**プロトコル概要**:
SPIはSCLK・MOSI・MISO・CS（チップセレクト）の最大4線式同期通信。VDS1022Iは2チャネルしかないため、1回の取得で観測できる信号は2本に限られます。

**実装アルゴリズム**:
1. CS LOW → トランザクション開始
2. SCLKエッジ（CPOL/CPHAモードにより立ち上がりor立ち下がり）でMOSI/MISOをサンプリング
3. 8ビット（または設定ビット数）でバイト再構成
4. CS HIGH → トランザクション終了

**4つのSPIモード（CPOL/CPHA）**:

| モード | CPOL | CPHA | サンプルエッジ |
|-------|------|------|-------------|
| 0 | 0 | 0 | 立ち上がり |
| 1 | 0 | 1 | 立ち下がり |
| 2 | 1 | 0 | 立ち下がり |
| 3 | 1 | 1 | 立ち上がり |

**ハードウェア制約**:
2チャネルしかないため、以下の組み合わせから選択:
- CH1=SCLK, CH2=MOSI（送信データをデコード）
- CH1=SCLK, CH2=MISO（受信データをデコード）
- CS信号はソフトウェアでアイドル期間から推定（CS端子を使わない簡易モード）

---

### Phase 3: CAN デコード

**プロトコル概要**:
CAN（Controller Area Network）は差動バス通信。VDS1022IはCAN-Hを単体測定して論理レベルに変換します。自動車・産業ロボット向け。

**実装アルゴリズム**（最も複雑）:
1. ドミナント→リセッシブ（LOW→HIGH）の立ち上がり → **SOF（フレーム開始）**
2. 11ビット または 29ビット（拡張フレーム）の **アービトレーションID**
3. **ビットスタッフィング除去**: 同極性5ビット連続の後に挿入されたスタッフビットを除去
4. **コントロールフィールド**: IDE, DLC（データ長）
5. **データフィールド**: 0〜8バイト
6. **CRC（15ビット）**: CRC-15/CAN多項式で検証
7. **ACKスロット** / **EOF**

**ハードウェア制約**:

| CAN速度 | 必要サンプリングレート | 推奨タイムベース | 1フレームの時間 |
|--------|-------------------|----------------|--------------|
| 125 kbps | 1 MHz以上 | 0.5 ms/div以下 | ~1 ms |
| 250 kbps | 2 MHz以上 | 0.25 ms/div以下 | ~0.5 ms |
| 500 kbps | 4 MHz以上 | 0.12 ms/div以下 | ~0.25 ms |
| 1 Mbps | 8 MHz以上 | 0.06 ms/div以下 | ~0.12 ms |

ビットスタッフィングとCRC検証のため、I2C/SPIより実装コストが高い。

---

### 実装優先度まとめ

| フェーズ | プロトコル | 必要チャネル | 実装難易度 | VDS1022I適性 |
|---------|-----------|------------|----------|------------|
| 済み | UART | CH1のみ | 低 | ◎ |
| Phase 1 | I2C | CH1+CH2 | 中 | ○（Standardモードまで） |
| Phase 2 | SPI | CH1+CH2 | 中 | ○（低速SPIまで） |
| Phase 3 | CAN | CH1のみ | 高 | △（125/250kbpsまで） |

各フェーズとも `signal_decoder.py` に新クラスを追加する形で実装でき、GUIの「プロトコル」セレクタに項目を追加するだけでデコードタブが拡張されます。

## 使用ライブラリとライセンス

| ライブラリ | バージョン | ライセンス | 用途 |
|-----------|-----------|-----------|------|
| [PyQt6](https://pypi.org/project/PyQt6/) | ≥6.4 | **GPL v3** / Commercial | GUIフレームワーク |
| [pyqtgraph](https://pypi.org/project/pyqtgraph/) | ≥0.13 | MIT | 波形グラフ描画 |
| [NumPy](https://pypi.org/project/numpy/) | ≥1.21 | BSD-3-Clause | 数値計算・配列処理 |
| [pyusb](https://pypi.org/project/pyusb/) | ≥1.2 | BSD | USB通信（Python層） |
| [libusb-package](https://pypi.org/project/libusb-package/) | ≥1.0.26 | Apache 2.0 (wrapper) / LGPL v2.1 (libusb本体) | USB通信バックエンド |
| [OWON-VDS1022](https://github.com/florentbr/OWON-VDS1022) | — | 要確認（著者に問い合わせ推奨） | オシロスコープ制御API |

**注意**: PyQt6のGPL v3ライセンスに従い、本プロジェクトはGPL v3で公開しています。

## ライセンス

Copyright (c) 2026 hijimasa

本プロジェクトは **GNU General Public License v3.0 (GPL v3)** の下で公開されています。

これは PyQt6（GPL v3）を使用しているためです。GPL v3 の主な条件:

- ソースコードを公開する義務がある
- 派生物も GPL v3 で公開しなければならない
- 著作権表示とライセンス文を保持しなければならない

詳細は [LICENSE](LICENSE) ファイルおよび https://www.gnu.org/licenses/gpl-3.0.html を参照してください。

**商用利用を検討する場合**: PyQt6の商用ライセンス（Riverbank Computing）を別途購入することで、GPL条件を回避できます。

## 参考リンク

- [florentbr/OWON-VDS1022](https://github.com/florentbr/OWON-VDS1022) — VDS1022 Python API
- [Zadig](https://zadig.akeo.ie/) — Windows USBドライバーインストーラー
- [PyQt6 ライセンス情報](https://www.riverbankcomputing.com/commercial/pyqt) — Riverbank Computing
- [sigrok プロトコルデコーダー一覧](https://sigrok.org/wiki/Protocol_decoders) — 参考実装
