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
- **プロトコルデコード**: 単発取得波形から4種のプロトコルを自動デコード、波形上にオーバーレイ表示
  - **UART**: TTL UART（9600〜921600 bps）
  - **I2C**: SDA+SCL 2線式（Standard 100kHz / Fast 400kHz）
  - **SPI**: SCLK+MOSI/MISO 2線式（Mode 0〜3、MSB/LSB対応）
  - **CAN**: NRZ符号（125kbps〜1Mbps、ビットスタッフィング・CRC-15検証対応）
- **プローブ補正**: x1/x10プローブ設定に応じた電圧値の自動補正
- **設定変更**: 電圧レンジ、タイムベース、トリガー設定をGUIで変更
- **シミュレーションモード**: 実機なしで動作確認可能（全プロトコルのシミュレーション信号生成対応）
- **自動検出**: 起動時に実機を自動検出、なければシミュレーションモードで起動

## 動作環境

- Python 3.10以上
- Windows 10/11
- OWON VDS1022I USBオシロスコープ（実機使用時）

## exeファイルで使う（推奨）

Pythonのインストール不要で、すぐに使い始められます。

1. [Releases](https://github.com/hijimasa/VDS1022_DataLogger/releases) ページから最新版の `VDS1022_DataLogger.zip` をダウンロード
2. ZIP を任意のフォルダに展開
3. `VDS1022_DataLogger.exe` をダブルクリックして起動

> **注意**: 実機（OWON VDS1022I）を使用する場合は、事前に下記「USBドライバー設定」の手順が必要です。シミュレーションモードで試すだけならドライバー不要です。

## ソースからインストール

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
| チャネル設定 | 有効/無効、電圧レンジ（V/div）、カップリング、プローブ（x1/x10） |
| タイムベース | 5ns〜10s/div |
| トリガー | モード（Auto/Normal/Single）、ソース、エッジ、レベル |
| シミュレーション設定 | 周波数、振幅、波形種類（uart/i2c/spi/can含む）、ノイズ量 |

### プローブ設定（x1 / x10）

チャネル設定の「プローブ」コンボボックスでプローブの減衰比を設定できます。

| 設定 | 動作 |
|------|------|
| **x1** | 補正なし。パッシブプローブ x1 モードまたは直接接続時に使用 |
| **x10** | 電圧値を10倍に補正。x10 パッシブプローブ使用時に設定 |

x10プローブは信号を1/10に減衰してオシロスコープに入力するため、正しい電圧値を表示するにはこの設定が必要です。設定は電圧レンジ（V/div）の表示にも反映されます。

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

単発取得した波形からプロトコルを自動デコードし、結果を波形上にオーバーレイ表示します。UART / I2C / SPI / CAN の4プロトコルに対応しています。

#### 操作手順（共通）

1. **設定タブ**でタイムベースをプロトコルに合わせて設定（後述の推奨値を参照）
2. 2チャネル必要なプロトコル（I2C/SPI）は CH1, CH2 両方を有効にする
3. **トリガーを設定**する（後述の各プロトコル推奨設定を参照）
4. **「単発」ボタン**で波形を取得 → トリガ条件が満たされるまで待機し、自動的にキャプチャされる
5. **デコードタブ**を開き、プロトコルを選択
6. デコード設定を入力し、**「自動」ボタン**でスレッショルドを自動設定
7. **「デコード実行」**をクリック

デコード完了後、波形は自動的に全データが10divに収まるように表示が切り替わります。設定タブのタイムベースで拡大/縮小、ドラッグでスクロールが可能です。

#### トリガー設定の基本

通信波形をデコードするには、**送信開始のタイミングで正確にキャプチャする**ことが重要です。トリガーを適切に設定することで、送信の先頭からフレーム全体を確実に取得できます。

| 設定項目 | 説明 |
|---------|------|
| **モード** | **Single**（単発）を推奨。1回のトリガでキャプチャし、波形が上書きされない |
| **ソース** | 信号が接続されているチャネル（UARTならCH1、I2CならSDAのチャネルなど） |
| **エッジ** | プロトコルの送信開始を示すエッジ方向（後述） |
| **レベル** | 信号の中間電圧（3.3Vロジックなら **1.65V**、5Vロジックなら **2.5V**） |

> **Autoモード** は信号の有無に関わらず連続取得するため、送信途中からキャプチャされることがあります。デコード用途には **Single** が最適です。

#### デコード結果のオーバーレイ色

| 色 | 意味 |
|----|------|
| 緑 | 正常フレーム（OK） |
| 青 | START/STOP 条件（I2C） |
| 黄 | NACK / パリティエラー |
| 赤 | フレームエラー / CRCエラー / スタッフエラー |

---

#### UART デコード

TTL UART（アイドルHIGH）をデコードします。1チャネルのみ使用。RS-232レベル等アイドルLOWの信号は「信号反転」チェックで対応できます。

| 設定項目 | 説明 | 典型値 |
|---------|------|-------|
| チャネル | デコード対象チャネル | CH1 |
| ボーレート | 通信速度（bps） | 9600 / 115200 |
| データビット | 1フレームのデータビット数 | 8 |
| パリティ | パリティ検証方式 | なし |
| ストップビット | ストップビット数 | 1 |
| スレッショルド | HIGH/LOW判定電圧（V） | 「自動」ボタンで (Vmax+Vmin)/2 |
| 信号反転 | アイドルLOW信号の場合にチェック | 通常OFF |

**推奨トリガー設定:**

UARTはアイドル=HIGH で、スタートビットで HIGH→LOW に遷移します。

| 項目 | 設定 |
|------|------|
| ソース | UART信号のチャネル（CH1等） |
| エッジ | **立ち下がり**（スタートビット検出） |
| レベル | 信号の中間電圧（3.3Vなら1.65V） |
| モード | **Single** |

**推奨タイムベース:**

単発取得は常に5,000サンプル固定で、**キャプチャ時間 = タイムベース × 10div** です。

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

結果テーブル: `# | 時刻(s) | HEX | ASCII | 状態`

---

#### I2C デコード

SDA（データ）+ SCL（クロック）の2線式同期通信をデコードします。CH1/CH2 の両方が必要です。

| 設定項目 | 説明 | 典型値 |
|---------|------|-------|
| SDA チャネル | SDA信号のチャネル | CH1 |
| SCL チャネル | SCL信号のチャネル | CH2 |
| SDA スレッショルド | SDAのHIGH/LOW判定電圧 | 「自動」ボタン推奨 |
| SCL スレッショルド | SCLのHIGH/LOW判定電圧 | 「自動」ボタン推奨 |
| アドレスフィルタ | 特定スレーブのみ表示（空欄=全表示） | 0x68 |

**推奨トリガー設定:**

I2CのSTARTコンディションはSCL=HIGHの間にSDAが立ち下がることで発生します。SDAの立ち下がりでトリガすると送信開始を捕捉できます。

| 項目 | 設定 |
|------|------|
| ソース | **SDA のチャネル**（CH1等） |
| エッジ | **立ち下がり**（STARTコンディション検出） |
| レベル | 信号の中間電圧（3.3Vなら1.65V） |
| モード | **Single** |

**推奨タイムベース:**

| I2Cモード | クロック速度 | 推奨タイムベース |
|----------|------------|----------------|
| Standard | 100 kHz | 0.6 ms/div 以下 |
| Fast | 400 kHz | 0.15 ms/div 以下 |

結果テーブル: `# | 種別(START/ADDR/DATA/STOP) | 時刻(s) | アドレス/データ | R/W | ACK`

**シミュレーション設定:** 波形を「i2c」に切替えると、スレーブアドレス、クロック周波数、送信データを指定できます。

---

#### SPI デコード

SCLK + MOSI/MISO の2線式同期通信をデコードします。CH1/CH2 の両方が必要です。VDS1022I は2チャネルのため、CS信号なしでSCLKのアイドル期間からフレームを自動区切りします。

| 設定項目 | 説明 | 典型値 |
|---------|------|-------|
| SCLK チャネル | クロック信号のチャネル | CH1 |
| DATA チャネル | MOSI または MISO のチャネル | CH2 |
| データ種別 | MOSI / MISO | MOSI |
| SPIモード | Mode 0〜3（CPOL/CPHA の組合せ） | Mode 0 |
| ビット順序 | MSBファースト / LSBファースト | MSBファースト |
| データビット | 1ワードあたりのビット数 | 8 |
| SCLK スレッショルド | SCLKのHIGH/LOW判定電圧 | 「自動」ボタン推奨 |
| DATA スレッショルド | データラインのHIGH/LOW判定電圧 | 「自動」ボタン推奨 |

**推奨トリガー設定:**

SPIはCSがLOWになった後にSCLKが動き出します。CS信号は観測できないため、SCLKの最初のエッジでトリガします。

| 項目 | 設定（CPOL=0の場合） | 設定（CPOL=1の場合） |
|------|---------------------|---------------------|
| ソース | **SCLK のチャネル**（CH1等） | **SCLK のチャネル** |
| エッジ | **立ち上がり** | **立ち下がり** |
| レベル | 信号の中間電圧 | 信号の中間電圧 |
| モード | **Single** | **Single** |

> CPOL=0 ではSCLKのアイドルがLOWなので立ち上がりでトリガ、CPOL=1 ではアイドルがHIGHなので立ち下がりでトリガします。

**SPIモード一覧:**

| モード | CPOL | CPHA | サンプルエッジ |
|-------|------|------|-------------|
| 0 | 0 | 0 | 立ち上がり |
| 1 | 0 | 1 | 立ち下がり |
| 2 | 1 | 0 | 立ち下がり |
| 3 | 1 | 1 | 立ち上がり |

結果テーブル: `# | 時刻(s) | HEX | ASCII | 状態`

**シミュレーション設定:** 波形を「spi」に切替えると、クロック周波数、SPIモード、送信データを指定できます。

---

#### CAN デコード

CAN（Controller Area Network）の NRZ 符号をデコードします。1チャネルのみ使用。ビットスタッフィング除去と CRC-15/CAN 検証を行います。標準フレーム（11ビットID）と拡張フレーム（29ビットID）に対応。

| 設定項目 | 説明 | 典型値 |
|---------|------|-------|
| チャネル | CAN信号のチャネル | CH1 |
| ビットレート | 通信速度 | 250kbps |
| スレッショルド | ドミナント/リセッシブ判定電圧 | 「自動」ボタン推奨 |
| IDフィルタ | 特定IDのみ表示（空欄=全表示） | 0x123 |

**推奨トリガー設定:**

CANのSOF（Start Of Frame）はバスがリセッシブ（HIGH）からドミナント（LOW）に遷移する立ち下がりエッジです。

| 項目 | 設定 |
|------|------|
| ソース | CAN信号のチャネル（CH1等） |
| エッジ | **立ち下がり**（SOFのドミナント遷移） |
| レベル | 信号の中間電圧（CAN-Hを直接測定する場合は約2.0V） |
| モード | **Single** |

> CAN-Hを直接プローブする場合、リセッシブ≒2.5V / ドミナント≒3.5V のため、スレッショルドは約3.0V に設定してください。トランシーバのTX出力（TTLレベル）を測定する場合は通常の1.65V でOKです。

**推奨タイムベース:**

| CAN速度 | 推奨タイムベース | 1フレームの時間 |
|--------|----------------|--------------|
| 125 kbps | 0.5 ms/div 以下 | ~1 ms |
| 250 kbps | 0.25 ms/div 以下 | ~0.5 ms |
| 500 kbps | 0.12 ms/div 以下 | ~0.25 ms |

結果テーブル: `# | 時刻(s) | ID(HEX) | DLC | データ | 状態`

**シミュレーション設定:** 波形を「can」に切替えると、ビットレート、CAN ID、送信データを指定できます。

---

#### シミュレーションでの動作確認

実機なしで全プロトコルのデコードをテストできます:

1. 設定タブ → シミュレーション設定 → 波形を選択（uart / i2c / spi / can）
2. 各プロトコル固有のパラメータを設定
3. 2チャネルプロトコル（i2c/spi）の場合は CH2 を有効にする
4. タイムベースを推奨値に設定
5. 「単発」→ デコードタブで「デコード実行」

## ファイル構成

```
VDS1022_DataLogger/
├── main_gui.py         # メインGUIアプリケーション
├── oscilloscope.py     # オシロスコープ制御（実機/シミュレーション）
├── data_logger.py      # データロガー（CSV記録、波形保存、CSV変換）
├── signal_decoder.py   # プロトコルデコーダー（UART/I2C/SPI/CAN）
├── requirements.txt            # 依存パッケージ
├── build.bat                   # exe ビルドスクリプト
├── vds1022_datalogger.spec     # PyInstaller 設定ファイル
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

### I2Cデコード

```python
from oscilloscope import VDS1022Controller
from signal_decoder import I2CDecoder

controller = VDS1022Controller(simulation_mode=False)
controller.connect()
controller.set_channel_enabled(1, True)  # CH1=SDA
controller.set_channel_enabled(2, True)  # CH2=SCL
controller.set_time_base(0.5e-3)  # 0.5ms/div（100kHz I2C推奨）

waveform = controller.acquire()

decoder = I2CDecoder()
frames = decoder.decode(
    waveform.time_array,
    waveform.ch1_data,   # SDA
    waveform.ch2_data,   # SCL
    sda_threshold=1.65,
    scl_threshold=1.65,
)

for frame in frames:
    print(f"{frame.frame_type}: {frame.overlay_label}  {frame.status}")

controller.disconnect()
```

### SPIデコード

```python
from signal_decoder import SPIDecoder

decoder = SPIDecoder(mode=0, data_bits=8, bit_order='msb')
frames = decoder.decode(
    waveform.time_array,
    waveform.ch1_data,   # SCLK
    waveform.ch2_data,   # MOSI
    sclk_threshold=1.65,
    data_threshold=1.65,
    data_label='MOSI',
)

for frame in frames:
    print(f"0x{frame.hex_str}  '{frame.ascii_str}'  {frame.status}")
```

### CANデコード

```python
from signal_decoder import CANDecoder

decoder = CANDecoder(bitrate=250000)
frames = decoder.decode(
    waveform.time_array,
    waveform.ch1_data,
    threshold=1.65,
)

for frame in frames:
    print(f"ID=0x{frame.frame_id:03X}  DLC={frame.dlc}  data={frame.data_hex}  "
          f"CRC={'OK' if frame.crc_ok else 'NG'}  {frame.status}")
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
python -m PyInstaller vds1022_datalogger.spec
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

### デコードでフレームが検出されない

- **スレッショルド電圧を確認**: 「自動」ボタンで (Vmax+Vmin)/2 を自動設定
- **タイムベースを確認**: サンプリングレートが不足するとエラーメッセージが表示される（1ビットあたり3サンプル以上必要）
- **チャネルの有効化**: I2C/SPI は CH1, CH2 両方を有効にする必要がある
- **UART**: 信号がTTL UART（アイドルHIGH）であることを確認
- **I2C**: SDA/SCL のチャネル割り当てが正しいか確認
- **SPI**: SPIモード（CPOL/CPHA）がデバイスの設定と一致しているか確認
- **CAN**: ビットレートが正しいか確認。CAN-Hを直接測定する場合はスレッショルドを調整

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
sigrok（PulseView）のデコーダーと同等のアルゴリズムを採用しています:

- **UART**: エッジ検出 → 中央サンプリング → LSBファースト再構成
- **I2C**: SCL立ち上がりエッジでSDAサンプリング → START/STOP条件検出 → 9ビット単位（8データ+ACK）
- **SPI**: CPOL/CPHA に応じたエッジでサンプリング → SCLKアイドル期間でフレーム区切り
- **CAN**: NRZ符号のサンプルポイントサンプリング → ストリーミングデスタッファー → CRC-15/CAN検証
- **PyInstaller対応**: `signal_decoder.py` 単体をバンドルするだけで動作
- **共通インターフェース**: 各 `XxxFrame` は `start_time`/`end_time`/`status`/`overlay_label` を持ち、オーバーレイ表示を共通化

## プロトコルデコード対応状況

| プロトコル | 必要チャネル | VDS1022I適性 | 状態 |
|-----------|------------|------------|------|
| UART | CH1のみ | ◎ 全ボーレート対応 | 実装済み |
| I2C | CH1+CH2 | ○ Standard/Fastモード | 実装済み |
| SPI | CH1+CH2 | ○ 低〜中速SPI | 実装済み |
| CAN | CH1のみ | △ 125/250kbps推奨 | 実装済み |

各デコーダーは `signal_decoder.py` に純Python実装されており、外部Cライブラリ不要でPyInstallerによるexeバンドルにも対応しています。

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
