#!/usr/bin/env python3
"""
Prototype script for OnSiteLogistics handheld reader.

Reads barcode data from a USB HID scanner (tested with MINJCODE MJ2818A)
via evdev, drives the Waveshare 2.13" e-Paper HAT V4, and manages a
two-step workflow (A-code then B-code).

Run on Raspberry Pi Zero 2 W:
    sudo ./handheld_scan_display.py
"""

import os
import time
from pathlib import Path
from typing import Optional

from evdev import InputDevice, categorize, ecodes
from PIL import Image, ImageDraw, ImageFont

try:
    from waveshare_epd import epd2in13_V4  # legacy module name
except ImportError:
    try:
        from waveshare_epaper import epd2in13_V4  # pip package name
    except ImportError:
        import sys

        alt_paths = []
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            alt_paths.append(Path("/home") / sudo_user / "e-Paper/RaspberryPi_JetsonNano/python/lib")

        alt_paths.append(Path(__file__).resolve().parent / "e-Paper/RaspberryPi_JetsonNano/python/lib")
        alt_paths.append(Path("/home") / Path.home().name / "e-Paper/RaspberryPi_JetsonNano/python/lib")

        for candidate in alt_paths:
            if candidate.exists():
                if str(candidate) not in sys.path:
                    sys.path.append(str(candidate))
                try:
                    from waveshare_epd import epd2in13_V4  # type: ignore
                    break
                except ImportError:
                    continue
        else:
            raise

# ====== Configurable parameters ======
DEVICE_PATH = Path("/dev/input/event2")  # Update if the scanner is mapped elsewhere
IDLE_TIMEOUT_S = 30
PARTIAL_BATCH_N = 5
CANCEL_CODES = {"CANCEL", "RESET"}
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SIZE = 22


class KeyboardScanner:
    """Read barcode strings via evdev from a HID scanner."""

    LETTER_PREFIX = "KEY_"

    SYMBOL_MAP = {
        "KEY_0": "0",
        "KEY_1": "1",
        "KEY_2": "2",
        "KEY_3": "3",
        "KEY_4": "4",
        "KEY_5": "5",
        "KEY_6": "6",
        "KEY_7": "7",
        "KEY_8": "8",
        "KEY_9": "9",
        "KEY_MINUS": "-",
        "KEY_EQUAL": "=",
        "KEY_SLASH": "/",
        "KEY_DOT": ".",
        "KEY_COMMA": ",",
        "KEY_SPACE": " ",
        "KEY_SEMICOLON": ";",
        "KEY_APOSTROPHE": "'",
        "KEY_BACKSLASH": "\\",
    }

    def __init__(self, device_path: Path):
        if not device_path.exists():
            raise FileNotFoundError(f"Scanner input device not found: {device_path}")
        self.device = InputDevice(str(device_path))
        self._buffer: list[str] = []
        self._shift = False
        try:
            self.device.grab()
            self._grabbed = True
        except OSError:
            self._grabbed = False

    def read_code(self, timeout: float = 0.1) -> Optional[str]:
        """Return a single barcode as text (delimited by Enter)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.device.read_one()
            if event is None:
                time.sleep(0.01)
                continue
            if event.type != ecodes.EV_KEY:
                continue

            key = categorize(event)
            code = key.keycode
            state = key.keystate

            if code in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"):
                self._shift = bool(state)
                continue

            if state != 1:  # process only key-down events
                continue

            if code == "KEY_ENTER":
                text = "".join(self._buffer)
                self._buffer.clear()
                return text

            if code == "KEY_BACKSPACE":
                if self._buffer:
                    self._buffer.pop()
                continue

            ch = self._translate(code)
            if ch:
                self._buffer.append(ch.upper() if self._shift else ch)

        return None

    def close(self) -> None:
        if getattr(self, "_grabbed", False):
            try:
                self.device.ungrab()
            except OSError:
                pass
        self.device.close()

    def _translate(self, code: str) -> Optional[str]:
        if code in ("KEY_SEMICOLON",):
            return ":" if self._shift else ";"
        if code in ("KEY_APOSTROPHE",):
            return '"' if self._shift else "'"
        if code in ("KEY_COMMA",):
            return "<" if self._shift else ","
        if code in ("KEY_DOT",):
            return ">" if self._shift else "."
        if code in ("KEY_SLASH",):
            return "?" if self._shift else "/"
        if code in ("KEY_MINUS",):
            return "_" if self._shift else "-"
        if code in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[code]
        if code.startswith(self.LETTER_PREFIX) and len(code) == 5:
            # e.g. KEY_A, KEY_Z
            return code[-1].lower()
        return None


class EPaperUI:
    """Helper to render status on Waveshare 2.13\" e-Paper (V4)."""

    def __init__(self):
        self.epd = epd2in13_V4.EPD()
        self.epd.init()

        # For V4, width/height are swapped when rotated to landscape
        self.width, self.height = self.epd.height, self.epd.width
        self.line_height = self.height // 3
        self.font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        self._partial_count = 0

        base = self._render("A: WAIT", "B: WAIT", "Status: WAIT")
        self.epd.displayPartBaseImage(self.epd.getbuffer(base))

    def _render(self, line_a: str, line_b: str, line_status: str) -> Image.Image:
        image = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(image)
        draw.text((4, 2 + 0 * self.line_height), line_a, font=self.font, fill=0)
        draw.text((4, 2 + 1 * self.line_height), line_b, font=self.font, fill=0)
        draw.text((4, 2 + 2 * self.line_height), line_status, font=self.font, fill=0)
        return image

    def update(self, a: Optional[str] = None, b: Optional[str] = None,
               status: Optional[str] = None, force_full: bool = False) -> None:
        line_a = a if a is not None else "A: WAIT"
        line_b = b if b is not None else "B: WAIT"
        line_status = status if status is not None else "Status: WAIT"

        print(f"[UI] update -> a='{line_a}' b='{line_b}' status='{line_status}' force_full={force_full}")

        image = self._render(line_a, line_b, line_status)

        if force_full or self._partial_count >= PARTIAL_BATCH_N:
            buf = self.epd.getbuffer(image)
            self.epd.display(buf)
            # Reset the partial base so subsequent partial updates reflect this frame
            self.epd.displayPartBaseImage(buf)
            self._partial_count = 0
        else:
            self.epd.displayPartial(self.epd.getbuffer(image))
            self._partial_count += 1

    def sleep(self) -> None:
        self.epd.sleep()


def format_line(prefix: str, code: str, done: bool, max_len: int = 24) -> str:
    suffix = " [OK]" if done else ""
    text = code
    ellipsis = "..."
    if len(text) > max_len:
        text = text[: max_len - len(ellipsis)] + ellipsis
    return f"{prefix}: {text}{suffix}"


def main() -> None:
    scanner = KeyboardScanner(DEVICE_PATH)
    ui = EPaperUI()
    print(f"[INFO] Scanner device: {scanner.device.path} ({scanner.device.name})")

    state = "WAIT_A"
    code_a: Optional[str] = None
    last_action = time.monotonic()

    try:
        ui.update(force_full=True)

        while True:
            now = time.monotonic()
            if state != "WAIT_A" and now - last_action > IDLE_TIMEOUT_S:
                print("[WARN] Timeout. Resetting state.")
                state = "WAIT_A"
                code_a = None
                ui.update(status="Status: TIMEOUT→RESET", force_full=True)
                continue

            code = scanner.read_code(timeout=0.3)
            if code is None:
                continue

            last_action = now
            code = code.strip()
            if not code:
                print("[DEBUG] Empty code detected. Ignoring.")
                continue
            print(f"[DEBUG] Read code: {code}")
            print(f"[STATE] before transition: state={state}, code_a={code_a}")

            if code.upper() in CANCEL_CODES:
                state = "WAIT_A"
                code_a = None
                ui.update(status="Status: CANCELLED")
                continue

            # Handle based on current state (prefixes are hints only)
            if state == "WAIT_A":
                code_a = code[2:].strip() if code.startswith("A:") else code
                state = "WAIT_B"
                print(f"[STATE] transition -> WAIT_B (code_a={code_a})")
                ui.update(a=format_line("A", code_a, True), status="Status: A RECEIVED")
                continue

            # state == WAIT_B
            code_b = code[2:].strip() if code.startswith("B:") else code
            if code_a is None:
                ui.update(b=format_line("B", code_b, False),
                          status="Status: ONLY B → RESET", force_full=True)
            else:
                ui.update(a=format_line("A", code_a, True),
                          b=format_line("B", code_b, True),
                          status="Status: DONE", force_full=True)
            print(f"[STATE] transition -> WAIT_A (completed) with B={code_b}")
            state = "WAIT_A"
            code_a = None

    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.")
    finally:
        scanner.close()
        ui.sleep()


if __name__ == "__main__":
    main()
