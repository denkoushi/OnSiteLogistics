# ハンディリーダ開発ノート

この文書はハンディリーダ装置（バーコードスキャナ + Raspberry Pi Zero 2 W + 電子ペーパー）の構想・検討内容・実装ステップを記録するものです。会話で合意した内容と今後の作業手順をここに集約します。

## 1. 目的と運用イメージ
- 紙の移動票に印字された部品番号／製造オーダー番号と、棚バーコードを順番に読み取り、各部品の所在をリアルタイムに可視化する。
- ハンディリーダは Pi Zero 2 W と USB ハンディスキャナを OTG で接続し、電子ペーパー上で状態を表示する。
- サーバー送信は後工程で実装し、まずはローカルで「A読取 → B読取 → 完了表示」を確実に行う。

## 2. ハードウェア構成案
- Raspberry Pi Zero 2 W（Wi-Fi 内蔵、モバイルバッテリー駆動想定）。
- USB ハンディバーコードスキャナ（CDC-ACM もしくは HID モード切替可が望ましい）。
- Waveshare 2.13″ e-Paper HAT V4（白黒、250×122、部分更新対応）。STEMDIY ブランド版を購入予定。
- 三色 LED / ブザー / キャンセルボタン（任意）：進捗通知やエラー通知の補助。
- 5 V / 2 A 以上出力のモバイルバッテリー（10,000 mAh クラスで 8–16 時間稼働目標）。

## 3. UI 方針
- 電子ペーパーを 3 行構成にし、「A 読取」「B 読取」「状態（送信含む）」を表示。
- 各行は部分更新（約 0.42 s）で書き換え、5 回ごとに全更新を挟みゴーストを抑制。
- エラー時やタイムアウト時は電子ペーパー表示で明示し、必要であれば LED／ブザーで冗長化。

## 4. ソフトウェア構成（初期段階）
1. **Step 1**: Pi Zero 2 W から Waveshare 2.13″ V4 を駆動し、ベンダー提供の `epd_2in13_V4_test.py` で表示テスト。
2. **Step 2**: ハンディスキャナ単体で読み取り確認。CDC-ACM を優先し、HID モードでも evdev で取得できるようにする。
3. **Step 3**: スキャナ入力と電子ペーパー表示を統合し、A → B → 完了の状態遷移をローカル完結させる（サーバー通信なし）。
4. **Step 4**: HTTP POST 送信と再送キュー（SQLite）を実装し、通信断耐性を確保。
5. **Step 5**: サイネージ表示／ダッシュボードとの連携仕様を設計・実装。

## 5. 試作スクリプト（ローカル完結版）
以下は Raspberry Pi OS 上で動作する想定の Python スクリプト例です。CDC-ACM（`/dev/ttyACM*` / `/dev/ttyUSB*`）を優先し、見つからない場合は HID 入力 (evdev) を利用します。電子ペーパーは V4 ドライバを使用し、A/B/状態の 3 行を部分更新します。今後の検証に伴い調整します。

```python
#!/usr/bin/env python3
import os, time
from PIL import Image, ImageDraw, ImageFont
from waveshare_epd import epd2in13_V4

SERIAL_DEVICES = ["/dev/ttyACM0", "/dev/ttyUSB0"]
SERIAL_BAUDS = [115200, 9600]
IDLE_TIMEOUT_S = 30
PARTIAL_BATCH_N = 5
CANCEL_CODES = {"CANCEL", "RESET"}

class EPaperUI:
    def __init__(self):
        self.epd = epd2in13_V4.EPD()
        self.epd.init()
        self.W, self.H = self.epd.height, self.epd.width
        self.line_h = self.H // 3
        self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        self.partial_cnt = 0
        base = self._render("A: 待機", "B: 待機", "状態: 待機")
        self.epd.displayPartBaseImage(self.epd.getbuffer(base))

    def _render(self, a, b, status):
        img = Image.new("1", (self.W, self.H), 255)
        draw = ImageDraw.Draw(img)
        draw.text((4, 2 + 0*self.line_h), a, font=self.font, fill=0)
        draw.text((4, 2 + 1*self.line_h), b, font=self.font, fill=0)
        draw.text((4, 2 + 2*self.line_h), status, font=self.font, fill=0)
        return img

    def show(self, a=None, b=None, status=None, full=False):
        img = self._render(
            a or "A: 待機",
            b or "B: 待機",
            status or "状態: 待機",
        )
        if full or self.partial_cnt >= PARTIAL_BATCH_N:
            self.epd.display(self.epd.getbuffer(img))
            self.partial_cnt = 0
        else:
            self.epd.displayPartial(self.epd.getbuffer(img))
            self.partial_cnt += 1

    def sleep(self):
        self.epd.sleep()

class Scanner:
    def __init__(self):
        self.backend = None
        self.ser = None
        self.evdev = None
        self.keymap = None
        self.shift = False
        self._detect()

    def _detect(self):
        # CDC-ACM 優先
        for dev in SERIAL_DEVICES:
            if not os.path.exists(dev):
                continue
            import serial
            for baud in SERIAL_BAUDS:
                try:
                    self.ser = serial.Serial(dev, baud, timeout=0.2)
                    self.backend = f"SERIAL:{dev}@{baud}"
                    return
                except Exception:
                    continue
        # HID fallback
        try:
            from evdev import InputDevice, list_devices, ecodes
            for path in list_devices():
                d = InputDevice(path)
                if "scanner" in (d.name or "").lower() or "barcode" in (d.name or "").lower():
                    self.evdev = d
                    self.ecodes = ecodes
                    self.keymap = self._build_keymap()
                    self.backend = f"HID:{path}"
                    return
        except Exception:
            pass

    def _build_keymap(self):
        return {
            "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3", "KEY_4": "4",
            "KEY_5": "5", "KEY_6": "6", "KEY_7": "7", "KEY_8": "8", "KEY_9": "9",
            "KEY_A": "a", "KEY_B": "b", "KEY_C": "c", "KEY_D": "d", "KEY_E": "e",
            "KEY_F": "f", "KEY_G": "g", "KEY_H": "h", "KEY_I": "i", "KEY_J": "j",
            "KEY_K": "k", "KEY_L": "l", "KEY_M": "m", "KEY_N": "n", "KEY_O": "o",
            "KEY_P": "p", "KEY_Q": "q", "KEY_R": "r", "KEY_S": "s", "KEY_T": "t",
            "KEY_U": "u", "KEY_V": "v", "KEY_W": "w", "KEY_X": "x", "KEY_Y": "y",
            "KEY_Z": "z", "KEY_MINUS": "-", "KEY_DOT": ".", "KEY_SLASH": "/", "KEY_SPACE": " ",
        }

    def readline(self, timeout=0.1):
        if self.backend and self.backend.startswith("SERIAL") and self.ser:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
                return line or None
            except Exception:
                return None
        if self.backend and self.backend.startswith("HID") and self.evdev:
            from evdev import categorize
            buf = []
            end = time.time() + timeout
            while time.time() < end:
                event = self.evdev.read_one()
                if not event:
                    time.sleep(0.01)
                    continue
                if event.type != self.ecodes.EV_KEY:
                    continue
                key = categorize(event)
                if key.keystate != 1:
                    continue
                code = self.ecodes.KEY[key.scancode]
                if code in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"):
                    self.shift = True
                    continue
                if code == "KEY_ENTER":
                    return "".join(buf)
                char = self.keymap.get(code)
                if char:
                    buf.append(char.upper() if self.shift else char)
            return None
        return None

def main():
    ui = EPaperUI()
    scanner = Scanner()
    print(f"[INFO] scanner backend: {scanner.backend or 'not detected'}")
    state = "WAIT_A"
    a_val = None
    last = time.time()

    try:
        ui.show(full=True)
        while True:
            line = scanner.readline(timeout=0.3)
            now = time.time()

            if state != "WAIT_A" and (now - last) > IDLE_TIMEOUT_S:
                state = "WAIT_A"
                a_val = None
                ui.show(status="状態: タイムアウト→初期化", full=True)
                continue

            if not line:
                continue

            code = line.strip()
            last = now

            if code in CANCEL_CODES:
                state = "WAIT_A"
                a_val = None
                ui.show(status="状態: キャンセル")
                continue

            if code.startswith("A:"):
                a_val = code[2:].strip()
                state = "WAIT_B"
                ui.show(a=f"A: {a_val} ✔", status="状態: A受領")
                continue

            if code.startswith("B:"):
                b_val = code[2:].strip()
                if a_val is None:
                    ui.show(b=f"B: {b_val}", status="状態: Bのみ→初期化", full=True)
                    state = "WAIT_A"
                    continue
                ui.show(a=f"A: {a_val} ✔", b=f"B: {b_val} ✔", status="状態: 完了", full=True)
                state = "WAIT_A"
                a_val = None
                continue

            if state == "WAIT_A":
                a_val = code
                state = "WAIT_B"
                ui.show(a=f"A: {a_val} ✔", status="状態: A受領")
            else:
                ui.show(a=f"A: {a_val} ✔", b=f"B: {code} ✔", status="状態: 完了", full=True)
                state = "WAIT_A"
                a_val = None

    except KeyboardInterrupt:
        pass
    finally:
        ui.sleep()

if __name__ == "__main__":
    main()
```

> **注意**: 上記スクリプトは今後の検証で調整が必要です。特に HID 入力時のシフト解除やキャンセルバーコードの実装、evdev のデバイス選択ロジックなどは実機挙動を見ながら精度を高めます。

## 6. 残課題・今後の検証ポイント
- Step 1（電子ペーパー単体テスト）の実施結果 log 化。
- スキャナのモード切替手順（接頭辞付加、改行コード設定）の確認。
- HID 読み取り時のシフトキー状態管理・国際配列対応。
- 再送キュー実装時に利用する SQLite ファイル配置と保護。
- ブザー／LED の GPIO 配線と制御モジュール追加。
- サーバー API 仕様と JSON フォーマットの確定。

必要な情報が増えた場合は本ファイルに追記し、決定事項は `docs/requirements.md` へリンクを残すこと。

### 6.1 Raspberry Pi Zero 2 W セットアップ時の注意
- **電源余裕の確保**: 5 V/2 A 以上のアダプタを使用し、`apt install` など高負荷処理時は HDMI・マウス・キーボードなどの周辺機器を外しておくと安定した。必要に応じてセルフパワー USB ハブを利用する。
- **リモート操作**: 初期構築では RealVNC を使い、VNC 経由で作業することで HDMI・USB 機器を外した状態でも操作可能だった。
- **低電圧監視**: `vcgencmd get_throttled` や `dmesg | grep -i voltage` で低電圧警告を確認できる。警告が出た場合は電源系を見直す。
- **再現手順の標準化**: 新しい Pi を構築する際も、「周辺機器を最小構成にする→VNC/SSH で接続→依存パッケージ導入→電子ペーパー動作確認」という手順を踏襲する。

## 7. セットアップログ
| 日付 | 内容 | 備考 |
| --- | --- | --- |
| 2025-02-15 | Raspberry Pi OS インストール | 最新の 64-bit Desktop 版を Raspberry Pi Imager で書き込み。RealVNC 経由で Mac から操作予定。 |
| 2025-02-15 | 初期設定 | SPI / SSH / Wi-Fi 設定済み。`apt install` 実行時に再起動する問題が発生したが、HDMI・マウス・キーボードを外し VNC越しに再実行したところ完了。 |
| 2025-02-15 | Step 1: e-Paper ベンダーテスト | `epd_2in13_V4_test.py` を実行し、画面フラッシュとテスト画像表示を確認。ログに `e-Paper busy` → `Clear ...` → `Goto Sleep` が出力。 |
| 2025-02-15 | Step 2: スキャナ接続確認 | MINJCODE MJ2818A を接続。`lsusb` で `34eb:1502` を確認。`dmesg` より USB HID Keyboard として認識（`hid-generic ...`）。 |
| 2025-02-15 | Step 3: 統合スクリプト確認 | `handheld_scan_display.py` を実行し、A → B の順でスキャン時に電子ペーパーへ `Status: DONE` とともに `B` 行まで表示されることを確認。長い URL バーコードも省略表示で反映。 |

### 7.1 実行コマンドメモ
- 依存パッケージ導入（再起動対策後に完了）:
  ```bash
  sudo apt update
  sudo apt install -y python3-pip python3-rpi.gpio python3-spidev \
      python3-evdev python3-serial python3-pil fonts-dejavu-core git unzip
  ```
- Waveshare サンプル取得・展開・テスト:
  ```bash
  cd ~
  wget -O E-Paper_code.zip https://files.waveshare.com/upload/7/71/E-Paper_code.zip
  unzip E-Paper_code.zip -d e-Paper
  cd e-Paper/RaspberryPi_JetsonNano/python/examples
  sudo -E python3 epd_2in13_V4_test.py
  ```
- スキャナ確認関連:
  ```bash
  lsusb
  dmesg | tail -n 20
  dmesg | grep -i hid
  sudo apt install -y evtest        # HID 入力イベント確認用（未導入だったため次回実施）
  sudo evtest                       # 追加後、デバイス一覧からスキャナを選択
  ```
- HID 入力テスト用スクリプト:
  ```bash
  nano ~/scan_test.py
  sudo chmod +x ~/scan_test.py
  sudo ~/scan_test.py
  ```

## 8. スキャナ入力検証メモ（進行中）
- MINJCODE MJ2818A は初期状態で USB HID キーボードとして認識。`/dev/ttyACM*` や `/dev/ttyUSB*` は未作成。
- `evtest` を導入済み。次は `sudo evtest` でデバイスを選び、バーコード読取時のイベントを確認する。
- HID で運用する場合に備え、キーマップとシフトキー制御の実装を強化する。
- `sudo evtest` で `/dev/input/event2` を選択し、スキャン時に `KEY_LEFTSHIFT` と英字キーが対で出力されることを確認（例: Shift→KEY_T→Shift解除→KEY_T→Shift→KEY_E…）。大文字を送るたびに Shift 押下/解放イベントが発行されるため、HID 実装側で Shift 状態をトグル管理する。
- バーコード終端時に `KEY_ENTER`（値 0/1）が送られることを確認。改行処理は Enter を区切りとして扱う。
- `scan_test.py` を作成・実行し、`SCAN: TEST-002` と出力されることを確認。HID 入力から文字列化する処理が機能した。
- Step 3 として `scripts/handheld_scan_display.py` を用意（Pi 上に転送後、`sudo ./handheld_scan_display.py` で実行）。A/B の順序管理と電子ペーパー表示を統合する。デフォルトの入力デバイスは `/dev/input/event2` としているため、環境に応じて `DEVICE_PATH` を更新する。モジュール import は `waveshare_epd` / `waveshare_epaper` の順で試行し、さらに `e-Paper/RaspberryPi_JetsonNano/python/lib`（SUDO_USER を考慮）を動的に検索する。起動時にスキャナを `grab()` してコンソールへのキー入力を抑止、表示文言は ASCII のみ（例: "Status: WAIT"）。
- 長いコードは 24 文字で省略表示されるように調整（例: `https://...`）。
- 空文字（スキャナから Enter のみが送られた場合）は無視するログを追加し、誤検知で状態が進まないようにした。
