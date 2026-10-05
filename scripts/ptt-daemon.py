#!/usr/bin/env python3
"""#385: push-to-talk on a hardware key or foot pedal via evdev.

Press-and-hold a key (foot pedals usually show up as a keyboard) and this
fires the app's dictation-toggle global shortcut; release it and it fires the
same shortcut again, which the Electron HUD treats as commit-while-listening.
So press = start dictation, release = stop + transcribe + type at cursor.

Needs read access to /dev/input — either run as root or add yourself to the
`input` group and re-login:  sudo usermod -aG input $USER

Usage:
  uv run scripts/ptt-daemon.py --list-devices
  uv run scripts/ptt-daemon.py --device "foot pedal" --key KEY_F13
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys

from evdev import InputDevice, ecodes

WTYPE = "/usr/bin/wtype" if os.path.exists("/usr/bin/wtype") else "wtype"


def send_toggle() -> None:
    """Press Ctrl+Alt+Space through the compositor, exactly like the real key."""
    try:
        subprocess.Popen([WTYPE, "-M", "ctrl", "-M", "alt", "-P", "space"])
    except FileNotFoundError:
        print("wtype not found on PATH", file=sys.stderr)


def candidates() -> list[InputDevice]:
    out = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            out.append(InputDevice(path))
        except PermissionError:
            print(f"{path}: permission denied (join the input group or run as root)", file=sys.stderr)
        except OSError:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="", help="substring of the device name")
    ap.add_argument("--key", default="KEY_F13", help=f"ecodes key name, e.g. KEY_F13 ({ecodes.KEY_F13})")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()

    if args.list_devices:
        for dev in candidates():
            print(dev.path, dev.name)
        return 0

    keycode = getattr(ecodes, args.key, None)
    if keycode is None:
        sys.exit(f"unknown key name: {args.key}")

    devices = candidates()
    if not devices:
        sys.exit("no readable input devices")
    dev = next((d for d in devices if args.device.lower() in d.name.lower()), None)
    if dev is None:
        sys.exit(f"no device matching '{args.device}' — try --list-devices")

    print(f"listening on {dev.name} ({dev.path}) for {args.key} (code {keycode})")
    for event in dev.read_loop():
        if event.type != ecodes.EV_KEY or event.code != keycode:
            continue
        if event.value == 1:  # press
            print("press → start dictation")
            send_toggle()
        elif event.value == 0:  # release
            print("release → commit dictation")
            send_toggle()
        # 2 = key repeat, ignored
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
