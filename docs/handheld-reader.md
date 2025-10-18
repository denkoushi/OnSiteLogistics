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

## 7. セットアップログ
| 日付 | 内容 | 備考 |
| --- | --- | --- |
| 2025-02-15 | Raspberry Pi OS インストール | 最新の 64-bit Desktop 版を Raspberry Pi Imager で書き込み。RealVNC 経由で Mac から操作予定。 |
| 2025-02-15 | 初期設定 | SPI 有効化、`ssh` 有効化、Wi-Fi 接続設定を実施予定。完了後に詳細追記する。 |
