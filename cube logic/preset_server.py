#!/usr/bin/env python3
import json
import socket
import time
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Tuple

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# =========================================================
# NETWORK HELPERS
# =========================================================

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_qr(url: str) -> None:
    print("\nOpen this URL on your phone / laptop:")
    print("  ", url)
    if HAS_QR:
        print("\nScan this QR code:")
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    else:
        print("(Install 'qrcode' Python package to see ASCII QR code.)")


# =========================================================
# SERIAL HELPERS (BYTES ONLY, WAIT FOR DONE)
# =========================================================

def find_ports() -> List[str]:
    return glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")


def read_all_available(s) -> List[str]:
    msgs = []
    try:
        while s.in_waiting:
            try:
                msg = s.readline().decode(errors="ignore").strip()
                if msg:
                    msgs.append(msg)
            except Exception:
                break
    except Exception:
        pass
    return msgs


def wait_for_done(serials, log: List[str], required_dones: int = 1) -> None:
    required = min(required_dones, len(serials))
    if required <= 0:
        return

    done_ports = set()
    log.append(f"Waiting for DONE from {required} Arduino(s)...")
    print(f"  Waiting for {required} DONE(s)...")

    while True:
        for s in serials:
            msgs = read_all_available(s)
            for m in msgs:
                line = f"{s.port}: {m}"
                log.append(line)
                print("   ", line)
                if m.strip() == "DONE":
                    done_ports.add(s.port)
                    if len(done_ports) >= required:
                        return
        time.sleep(0.02)


def _coerce_cmd_to_int(cmd) -> Optional[int]:
    if isinstance(cmd, int):
        return cmd
    if isinstance(cmd, float) and cmd.is_integer():
        return int(cmd)
    if isinstance(cmd, str):
        s = cmd.strip()
        if s.isdigit():
            return int(s)
    return None


def run_serial_commands(commands: List[object]) -> Dict[str, object]:
    log: List[str] = []

    if not HAS_SERIAL:
        err = "pyserial is not installed on this system."
        log.append(err)
        return {"ok": False, "log": log, "error": err}

    ports = find_ports()
    if not ports:
        err = "No Arduino ports found."
        log.append(err)
        return {"ok": False, "log": log, "error": err}

    log.append("Found ports: " + ", ".join(ports))
    print("Found ports:", ports)

    serials = []
    for port in ports:
        try:
            s = serial.Serial(port, 9600, timeout=1)
            time.sleep(2)
            serials.append(s)
            log.append(f"Opened {port}")
            print(f"Opened {port}")
        except Exception as e:
            msg = f"Could not open {port}: {e}"
            log.append(msg)
            print(msg)

    if not serials:
        err = "No serial connections opened."
        log.append(err)
        return {"ok": False, "log": log, "error": err}

    try:
        for cmd_raw in commands:
            cmd = _coerce_cmd_to_int(cmd_raw)
            if cmd is None:
                log.append(f"Skipping non-numeric command: {cmd_raw!r}")
                continue
            if not (0 <= cmd <= 255):
                raise ValueError(f"Command {cmd} out of byte range (0-255)")

            data = bytes([cmd])

            for s in serials:
                s.write(data)

            log.append(f"Sent byte: {cmd}")
            print("\nSent byte:", cmd)

            time.sleep(0.05)
            for s in serials:
                msgs = read_all_available(s)
                for m in msgs:
                    line = f"{s.port}: {m}"
                    log.append(line)
                    print("   ", line)

            wait_for_done(serials, log, required_dones=1)
            time.sleep(0.05)

        log.append("All commands completed.")
        print("\nAll commands completed.")

        t0 = time.time()
        while time.time() - t0 < 1.5:
            for s in serials:
                msgs = read_all_available(s)
                for m in msgs:
                    line = f"{s.port}: {m}"
                    log.append(line)
                    print(line)

        return {"ok": True, "log": log, "error": ""}

    except Exception as e:
        err = f"Error while sending commands: {e}"
        log.append(err)
        print(err)
        return {"ok": False, "log": log, "error": err}
    finally:
        for s in serials:
            try:
                s.close()
            except Exception:
                pass
        log.append("Serial connections closed.")
        print("Serial connections closed.")
        print("Finished.")


# =========================================================
# MOVE / UNDO HELPERS
# =========================================================

INV_MOVE: Dict[str, str] = {
    'F': "F'", "F'": 'F',
    'B': "B'", "B'": 'B',
    'R': "R'", "R'": 'R',
    'L': "L'", "L'": 'L',
    'D': "D'", "D'": 'D',
}

def moves_to_serial(moves: List[str]) -> List[int]:
    cmd_map = {
        "RF": 121,
        "RB": 122,
        "LF": 141,
        "LB": 142,
        "BF": 131,
        "BB": 132,
        "FF": 111,
        "FB": 112,
        "DF": 211,
        "DB": 212,
    }

    cmds: List[int] = []
    for m in moves:
        face = m[0]
        clockwise = (len(m) == 1)

        if face == 'D':
            direction = 'F' if clockwise else 'B'
        else:
            direction = 'B' if clockwise else 'F'

        key = f"{face}{direction}"
        if key not in cmd_map:
            raise ValueError(f"Unknown robot command mapping for move '{m}' -> '{key}'")

        cmds.append(cmd_map[key])

    return cmds


def invert_moves(moves: List[str]) -> List[str]:
    inv = []
    for m in reversed(moves):
        inv.append(INV_MOVE.get(m, m))
    return inv


def key_rc(r: int, c: int) -> str:
    return f"{r},{c}"


# =========================================================
# INSERT / EJECT BYTE MACROS (ALWAYS AVAILABLE IN UI)
# =========================================================

INSERT_BOTTOM = [241]
INSERT_SIDES  = [222, 231, 222, 231]

EJECT_SIDES   = [221, 232, 221, 232]
EJECT_BOTTOM  = [242]


# =========================================================
# PRESET DATA (YOUR 5x4 = 20 CUBES)
# order is 1,1 -> 1,4 then 2,1 -> 2,4 ... 5,4
# =========================================================

def make_order(rows: int, cols: int) -> List[str]:
    return [key_rc(r, c) for r in range(1, rows + 1) for c in range(1, cols + 1)]


def preview_12x15_from_strings(lines: List[str]) -> List[str]:
    out = []
    for ln in lines[:12]:
        ln = (ln[:15]).ljust(15, ".")
        out.append(ln)
    while len(out) < 12:
        out.append("." * 15)
    return out


PRESETS: Dict[str, Dict[str, object]] = {
    "mario": {
        "title": "Mario",
        "rows": 5,
        "cols": 4,
        "order": make_order(5, 4),
        "preview_12x15": preview_12x15_from_strings([
            ".....MMMMM.....",
            "....MMMMMMM....",
            "...MM..M..MM...",
            "..MMM.MMM.MMM..",
            "..MM..MMM..MM..",
            "..MMMMMMMMMMM..",
            "..MM.MMMMM.MM..",
            "..MM..MMM..MM..",
            "...MM.....MM...",
            "....MMMMMMM....",
            ".....MMMMM.....",
            "...............",
        ]),
        "cubes": {
            "1,1": {
                "moves": ['R', 'F', "R'", "F'"],
                "serial": [122, 112, 121, 111],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'r', 'B': 'o', 'R': 'b', 'L': 'g'},
                "notes": []
            },
            "1,2": {
                "moves": ['F', "D'", 'F'],
                "serial": [112, 212, 112],
                "orientation": {'U': 'r', 'D': 'o', 'F': 'w', 'B': 'y', 'R': 'g', 'L': 'b'},
                "notes": []
            },
            "1,3": {
                "moves": ['D', "F'", 'D', "R'", 'F', "D'", 'R'],
                "serial": [211, 111, 211, 121, 112, 212, 122],
                "orientation": {'U': 'r', 'D': 'o', 'F': 'b', 'B': 'g', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "1,4": {
                "moves": ['D', 'F', "B'", 'R'],
                "serial": [211, 112, 131, 122],
                "orientation": {'U': 'r', 'D': 'o', 'F': 'b', 'B': 'g', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "2,1": {
                "moves": ['R', "D'", 'L', "F'"],
                "serial": [122, 212, 142, 111],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'w', 'B': 'y', 'R': 'b', 'L': 'g'},
                "notes": []
            },
            "2,2": {
                "moves": ["L'", 'D', "B'", 'L', 'F', 'R'],
                "serial": [141, 211, 131, 142, 112, 122],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'b', 'B': 'g', 'R': 'y', 'L': 'w'},
                "notes": []
            },
            "2,3": {
                "moves": ['B', "D'", "B'", "L'"],
                "serial": [132, 212, 131, 141],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'w', 'B': 'y', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Blue up change center to white"]
            },
            "2,4": {
                "moves": ["R'", 'D', 'F', 'D', 'R', 'F'],
                "serial": [121, 211, 112, 211, 122, 112],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'o', 'B': 'r', 'R': 'b', 'L': 'g'},
                "notes": []
            },
            "3,1": {
                "moves": ["D'", "B'", 'R', 'B', "D'", "F'"],
                "serial": [212, 131, 122, 132, 212, 111],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'b', 'B': 'g', 'R': 'o', 'L': 'r'},
                "notes": []
            },
            "3,2": {
                "moves": ['R', "L'", 'B'],
                "serial": [122, 141, 132],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "3,3": {
                "moves": ['R', "L'", 'B'],
                "serial": [122, 141, 132],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "3,4": {
                "moves": ['D', 'B', "L'", "B'", 'D', 'F'],
                "serial": [211, 132, 141, 131, 211, 112],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "4,1": {
                "moves": ['B', 'R', "F'", 'R', 'F', 'B'],
                "serial": [132, 122, 111, 122, 112, 132],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'g', 'B': 'b', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "4,2": {
                "moves": ['L', 'D', "L'"],
                "serial": [142, 211, 141],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'w', 'B': 'y', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Blue up make center orange"]
            },
            "4,3": {
                "moves": ["R'", 'D', 'R'],
                "serial": [121, 211, 122],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'w', 'B': 'y', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Blue up make center orange"]
            },
            "4,4": {
                "moves": ['B', "L'", "B'", 'L', 'B', "L'"],
                "serial": [132, 141, 131, 142, 132, 141],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'g', 'B': 'b', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "5,1": {
                "moves": ['B', 'R', "D'", "F'"],
                "serial": [132, 122, 212, 111],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "5,2": {
                "moves": ["F'", 'D', 'R', 'D', 'R', 'F'],
                "serial": [111, 211, 122, 211, 122, 112],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "5,3": {
                "moves": ['D', 'F', 'B', "L'", "B'"],
                "serial": [211, 112, 132, 141, 131],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "5,4": {
                "moves": ["B'", 'L', 'F'],
                "serial": [131, 142, 112],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'b', 'B': 'g', 'R': 'o', 'L': 'r'},
                "notes": []
            },
        }
    },

    "duck": {
        "title": "Duck",
        "rows": 5,
        "cols": 4,
        "order": make_order(5, 4),
        "preview_12x15": preview_12x15_from_strings([
            "...............",
            "......DD.......",
            "....DDDDDD.....",
            "...DDDDDDDD....",
            "..DDDDDDDDDD...",
            "..DDDDDDDDDD...",
            "...DDDDDDDDD...",
            "....DDDDDD.....",
            ".....DDDD......",
            "......DD.......",
            "...............",
            "...............",
        ]),
        "cubes": {
            "1,1": {
                "moves": ['R', 'D', "R'"],
                "serial": [122, 211, 121],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "1,2": {
                "moves": ["R'", 'L', "F'", 'R', "L'"],
                "serial": [121, 142, 111, 122, 141],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'r', 'B': 'o', 'R': 'g', 'L': 'b'},
                "notes": []
            },
            "1,3": {
                "moves": ['R', "B'", "R'", 'B', 'R', "B'"],
                "serial": [122, 131, 121, 132, 122, 131],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "1,4": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: white side up (WWW/WWW/WWW)"]
            },
            "2,1": {
                "moves": ['L', 'B', "R'", 'B', 'R', 'L'],
                "serial": [142, 132, 121, 132, 122, 142],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "2,2": {
                "moves": ["F'", 'B', "L'", 'F', "B'"],
                "serial": [111, 132, 141, 112, 131],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'r', 'B': 'o', 'R': 'g', 'L': 'b'},
                "notes": []
            },
            "2,3": {
                "moves": ["B'", 'L', 'D', 'L', 'D', "B'"],
                "serial": [131, 142, 211, 142, 211, 131],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "2,4": {
                "moves": ["F'", "R'", 'F', 'R', "D'", 'F'],
                "serial": [111, 121, 112, 122, 212, 112],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "3,1": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["No data for this cube yet (placeholder)."]
            },
            "3,2": {
                "moves": ['R', 'D', "R'"],
                "serial": [122, 211, 121],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Orange center switch"]
            },
            "3,3": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["No data for this cube yet (placeholder)."]
            },
            "3,4": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["No data for this cube yet (placeholder)."]
            },
            "4,1": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["No data for this cube yet (placeholder)."]
            },
            "4,2": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: yellow side up (YYY/YYY/YYY)"]
            },
            "4,3": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["No data for this cube yet (placeholder)."]
            },
            "4,4": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["No data for this cube yet (placeholder)."]
            },
            "5,1": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
            "5,2": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
            "5,3": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
            "5,4": {
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
        }
    }
}


def get_cube_entry(preset_name: str, pos_key: str) -> Dict[str, object]:
    p = PRESETS.get(preset_name, {})
    cubes = p.get("cubes", {})
    entry = cubes.get(pos_key)
    if entry is None:
        return {
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["No data for this cube yet (placeholder)."]
        }
    return entry


def build_preset_payload(name: str) -> Dict[str, object]:
    p = PRESETS[name]
    out = {
        "name": name,
        "title": p.get("title", name),
        "rows": p.get("rows", 5),
        "cols": p.get("cols", 4),
        "order": p.get("order", []),
        "preview_12x15": p.get("preview_12x15", ["." * 15] * 12),
        "cubes": {},
    }
    for k in out["order"]:
        out["cubes"][k] = get_cube_entry(name, k)
    return out


def compute_undo_for_cube(prev_preset: str, pos_key: str) -> Dict[str, object]:
    e = get_cube_entry(prev_preset, pos_key)
    moves = e.get("moves") or []
    ori = e.get("orientation", None)
    if not moves:
        return {
            "ok": False,
            "message": "No undo available (this cube has no recorded moves).",
            "undo_moves": [],
            "undo_serial": [],
            "undo_orientation": ori,
        }
    undo_moves = invert_moves(moves)
    undo_serial = moves_to_serial(undo_moves) if undo_moves else []
    return {
        "ok": True,
        "message": "Undo is available (inverse of previous preset moves).",
        "undo_moves": undo_moves,
        "undo_serial": undo_serial,
        "undo_orientation": ori,
    }


# =========================================================
# SINGLE-PAGE UI (HOME + ORIENTATION PAGE + CUBE PAGE)
# - No draw tab
# - No algorithm
# - Presets only
# - Insert/Eject available everywhere
# - Undo flow supported when switching presets (localStorage lastPresetName)
# =========================================================

APP_HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Rubikâ€™s Cube Mural Presets</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{
      --bg:#f3f4f6; --card:#fff; --border:#d1d5db; --text:#111827; --muted:#6b7280;
      --accent:#2563eb; --danger:#ef4444; --ok:#059669; --warn:#b45309;
    }
    *{ box-sizing:border-box }
    body{ margin:0; font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial; background:var(--bg); color:var(--text); }
    .shell{ max-width:1100px; margin:0 auto; padding:16px; }
    .topbar{
      position:sticky; top:0; z-index:30;
      background:rgba(243,244,246,0.92); backdrop-filter:saturate(180%) blur(8px);
      border-bottom:1px solid rgba(209,213,219,0.8);
      padding:10px 0; margin-bottom:14px;
    }
    .topbar-inner{ max-width:1100px; margin:0 auto; padding:0 16px; display:flex; gap:12px; align-items:center; justify-content:space-between; }
    .title{ font-weight:800; letter-spacing:-0.02em; }
    .muted{ color:var(--muted); font-size:13px; }
    .row{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .btn{
      border-radius:10px; padding:9px 12px; border:1px solid var(--accent);
      background:var(--accent); color:#fff; cursor:pointer; font-size:14px;
    }
    .btn.secondary{ border-color:var(--border); background:#fff; color:var(--text); }
    .btn.danger{ border-color:var(--danger); background:var(--danger); }
    .btn:disabled{ opacity:0.5; cursor:default }
    .card{
      background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px;
      box-shadow:0 10px 25px rgba(15,23,42,0.06);
    }
    .grid2{ display:grid; grid-template-columns:1fr; gap:12px; }
    @media(min-width:900px){ .grid2{ grid-template-columns:1fr 1fr; } }
    .section{ display:none; }
    .section.active{ display:block; }
    .h2{ font-size:16px; font-weight:800; margin:0 0 6px; }
    .preview-wrap{ display:flex; gap:14px; align-items:flex-start; flex-wrap:wrap; margin-top:10px; }
    .preview{
      border:1px solid var(--border); border-radius:12px; padding:10px; background:#fff;
      display:grid; grid-template-columns:repeat(15, 10px); gap:2px;
    }
    .px{ width:10px; height:10px; border-radius:2px; border:1px solid rgba(0,0,0,0.08); background:#fff; }
    .px.on.mario{ background:#ef4444; }
    .px.on.duck{ background:#f59e0b; }
    .pill{
      display:inline-block; padding:4px 8px; border:1px solid var(--border); border-radius:999px;
      font-size:12px; color:var(--muted); background:#fff;
    }
    .kpi{ display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
    pre{
      background:#0b1020; color:#b6fcb6; padding:10px; border-radius:12px; border:1px solid rgba(255,255,255,0.10);
      overflow:auto; max-height:280px;
    }
    .box{
      background:#fff; border:1px solid var(--border); border-radius:14px; padding:12px;
    }
    .sw{ width:14px; height:14px; border-radius:4px; border:1px solid rgba(0,0,0,0.35); display:inline-block; vertical-align:middle; margin-right:8px; }
    .c-r{ background:#ff0000 } .c-o{ background:#ffa500 } .c-b{ background:#0000ff } .c-g{ background:#00ff00 } .c-w{ background:#ffffff } .c-y{ background:#ffff00 }
    .ori-row{ display:flex; align-items:center; gap:10px; margin:3px 0; }
    .warn{ color:var(--warn); font-size:13px; }
    .ok{ color:var(--ok); font-size:13px; }
    .dropdown{ position:relative; display:inline-block; }
    .menu{
      position:absolute; top:44px; right:0;
      min-width:210px;
      background:#fff; border:1px solid var(--border); border-radius:12px; box-shadow:0 16px 40px rgba(15,23,42,0.18);
      padding:8px; display:none; z-index:200;
    }
    .menu.open{ display:block; }
    .menu .btn{ width:100%; justify-content:center; }
    .menu .btn + .btn{ margin-top:8px; }
    .mini-note{ font-size:12px; color:var(--muted); margin-top:6px; }
    .hr{ height:1px; background:#e5e7eb; margin:12px 0; }
  </style>
</head>
<body>

<div class="topbar">
  <div class="topbar-inner">
    <div>
      <div class="title">Mural Presets</div>
      <div class="muted" id="subTitle">Home</div>
    </div>

    <div class="row">
      <div class="dropdown">
        <button class="btn secondary" id="insertBtn" type="button">Insert â–¾</button>
        <div class="menu" id="insertMenu">
          <button class="btn secondary" type="button" id="insertBottomBtn">Insert bottom (241)</button>
          <button class="btn secondary" type="button" id="insertSidesBtn">Insert sides (222,231,222,231)</button>
          <div class="mini-note">Always available. Sends bytes to all detected ports, waits for DONE after each byte.</div>
        </div>
      </div>

      <div class="dropdown">
        <button class="btn secondary" id="ejectBtn" type="button">Eject â–¾</button>
        <div class="menu" id="ejectMenu">
          <button class="btn secondary" type="button" id="ejectSidesBtn">Eject sides (221,232,221,232)</button>
          <button class="btn secondary" type="button" id="ejectBottomBtn">Eject bottom (242)</button>
          <div class="mini-note">Always available.</div>
        </div>
      </div>

      <button class="btn secondary" id="homeBtn" type="button">Home</button>
    </div>
  </div>
</div>

<div class="shell">

  <div id="homeSection" class="section active">
    <div class="grid2">

      <div class="card">
        <div class="h2">Mario preset</div>
        <div class="muted">20 cubes (5Ã—4). Order: 1,1 â†’ 1,4 then 2,1 â†’ 2,4 ... 5,4</div>
        <div class="preview-wrap">
          <div>
            <div class="pill">Preview 12Ã—15</div>
            <div class="preview" id="marioPreview"></div>
          </div>
          <div style="min-width:240px;">
            <div class="kpi">
              <span class="pill" id="marioKpi"></span>
              <span class="pill" id="lastPresetPill"></span>
            </div>
            <div class="hr"></div>
            <button class="btn" type="button" id="startMarioBtn">Start Mario</button>
            <div class="mini-note">If you previously ran Duck, this will UNDO Duck cube-by-cube, then MAKE Mario.</div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="h2">Duck preset</div>
        <div class="muted">20 cubes (5Ã—4). Order: 1,1 â†’ 1,4 then 2,1 â†’ 2,4 ... 5,4</div>
        <div class="preview-wrap">
          <div>
            <div class="pill">Preview 12Ã—15</div>
            <div class="preview" id="duckPreview"></div>
          </div>
          <div style="min-width:240px;">
            <div class="kpi">
              <span class="pill" id="duckKpi"></span>
            </div>
            <div class="hr"></div>
            <button class="btn" type="button" id="startDuckBtn">Start Duck</button>
            <div class="mini-note">If you previously ran Mario, this will UNDO Mario cube-by-cube, then MAKE Duck.</div>
          </div>
        </div>
      </div>

    </div>

    <div class="card" style="margin-top:12px;">
      <div class="h2">Global log</div>
      <div class="muted">Insert/Eject and sends append here too.</div>
      <pre id="globalLog"></pre>
    </div>
  </div>

  <div id="placeSection" class="section">
    <div class="card">
      <div class="row" style="justify-content:space-between;">
        <div>
          <div class="h2" id="placeTitle">Place cube</div>
          <div class="muted" id="placeSub">Page 1 Â· Place the cube in the fixture</div>
        </div>
        <div class="row">
          <span class="pill" id="modePill">mode</span>
          <span class="pill" id="posPill">pos</span>
          <span class="pill" id="idxPill">idx</span>
        </div>
      </div>

      <div class="hr"></div>

      <div class="box">
        <div class="h2" style="font-size:14px;">Orientation to place cube</div>
        <div class="muted">Match cube centers to these faces before continuing.</div>
        <div id="orientationBox" style="margin-top:8px;"></div>
        <div id="orientationHint" class="mini-note"></div>
      </div>

      <div class="hr"></div>

      <div class="row" style="justify-content:space-between;">
        <div class="muted">Page 1 actions</div>
        <div class="row">
          <button class="btn secondary" type="button" id="placeBackBtn">Back</button>
          <button class="btn" type="button" id="runSolverBtn">Run solver â†’</button>
        </div>
      </div>

      <div class="mini-note">
        â€œRun solverâ€ here just means: go to the cube execution page for this cube, where you can send the preset bytes multiple times.
      </div>
    </div>

    <div class="card" style="margin-top:12px;">
      <div class="h2">Log</div>
      <pre id="placeLog"></pre>
    </div>
  </div>

  <div id="cubeSection" class="section">
    <div class="card">
      <div class="row" style="justify-content:space-between;">
        <div>
          <div class="h2" id="cubeTitle">Cube</div>
          <div class="muted" id="cubeSub">Page 2 Â· Send commands</div>
        </div>
        <div class="row">
          <span class="pill" id="cubeModePill">mode</span>
          <span class="pill" id="cubePosPill">pos</span>
          <span class="pill" id="cubeIdxPill">idx</span>
        </div>
      </div>

      <div class="hr"></div>

      <div class="box">
        <div class="h2" style="font-size:14px;">Target / entry info</div>
        <div class="muted">This shows the preset entry for this cube (moves + serial). You can send multiple times.</div>

        <div class="hr"></div>

        <div class="muted"><b>Notes</b></div>
        <div id="notesBox" class="mini-note"></div>

        <div class="hr"></div>

        <div class="muted"><b>Moves</b></div>
        <pre id="movesPre"></pre>

        <div class="muted" style="margin-top:10px;"><b>Serial bytes</b></div>
        <pre id="serialPre"></pre>
      </div>

      <div class="hr"></div>

      <div class="row" style="justify-content:space-between;">
        <div class="row">
          <button class="btn" type="button" id="sendBtn">Send commands to solver</button>
          <button class="btn secondary" type="button" id="backToPlaceBtn">Back to placement</button>
        </div>
        <div class="row">
          <button class="btn danger" type="button" id="redoBtn">Redo this step</button>
          <button class="btn" type="button" id="nextBtn">Next</button>
        </div>
      </div>

      <div class="mini-note" id="nextHint"></div>
    </div>

    <div class="card" style="margin-top:12px;">
      <div class="h2">Log</div>
      <pre id="cubeLog"></pre>
    </div>
  </div>

</div>

<script>
  const COLOR_META = {
    r: { name: "Red", css: "c-r" },
    o: { name: "Orange", css: "c-o" },
    b: { name: "Blue", css: "c-b" },
    g: { name: "Green", css: "c-g" },
    w: { name: "White", css: "c-w" },
    y: { name: "Yellow", css: "c-y" },
  };

  const FACE_ORDER = ["U","F","R","L","B","D"];
  const FACE_LABELS = {
    U: "UP",
    F: "FRONT",
    R: "RIGHT",
    L: "LEFT",
    B: "BACK",
    D: "DOWN",
  };

  const homeSection = document.getElementById("homeSection");
  const placeSection = document.getElementById("placeSection");
  const cubeSection = document.getElementById("cubeSection");

  const subTitle = document.getElementById("subTitle");

  const marioPreview = document.getElementById("marioPreview");
  const duckPreview = document.getElementById("duckPreview");
  const marioKpi = document.getElementById("marioKpi");
  const duckKpi = document.getElementById("duckKpi");
  const lastPresetPill = document.getElementById("lastPresetPill");

  const startMarioBtn = document.getElementById("startMarioBtn");
  const startDuckBtn = document.getElementById("startDuckBtn");
  const homeBtn = document.getElementById("homeBtn");

  const insertBtn = document.getElementById("insertBtn");
  const ejectBtn = document.getElementById("ejectBtn");
  const insertMenu = document.getElementById("insertMenu");
  const ejectMenu = document.getElementById("ejectMenu");
  const insertBottomBtn = document.getElementById("insertBottomBtn");
  const insertSidesBtn = document.getElementById("insertSidesBtn");
  const ejectSidesBtn = document.getElementById("ejectSidesBtn");
  const ejectBottomBtn = document.getElementById("ejectBottomBtn");

  const globalLog = document.getElementById("globalLog");
  const placeLog = document.getElementById("placeLog");
  const cubeLog = document.getElementById("cubeLog");

  const placeTitle = document.getElementById("placeTitle");
  const placeSub = document.getElementById("placeSub");
  const orientationBox = document.getElementById("orientationBox");
  const orientationHint = document.getElementById("orientationHint");

  const modePill = document.getElementById("modePill");
  const posPill = document.getElementById("posPill");
  const idxPill = document.getElementById("idxPill");

  const placeBackBtn = document.getElementById("placeBackBtn");
  const runSolverBtn = document.getElementById("runSolverBtn");

  const cubeTitle = document.getElementById("cubeTitle");
  const cubeSub = document.getElementById("cubeSub");
  const cubeModePill = document.getElementById("cubeModePill");
  const cubePosPill = document.getElementById("cubePosPill");
  const cubeIdxPill = document.getElementById("cubeIdxPill");
  const notesBox = document.getElementById("notesBox");
  const movesPre = document.getElementById("movesPre");
  const serialPre = document.getElementById("serialPre");
  const sendBtn = document.getElementById("sendBtn");
  const backToPlaceBtn = document.getElementById("backToPlaceBtn");
  const redoBtn = document.getElementById("redoBtn");
  const nextBtn = document.getElementById("nextBtn");
  const nextHint = document.getElementById("nextHint");

  let marioPreset = null;
  let duckPreset = null;

  let activePresetName = null;
  let activePreset = null;

  let prevPresetName = localStorage.getItem("lastPresetName") || "";
  let phase = "make"; // "undo" then "make" when switching
  let idx = 0;        // cube index
  let currentPos = "";
  let currentEntry = null;
  let currentUndoInfo = null;

  function show(section){
    [homeSection, placeSection, cubeSection].forEach(s => s.classList.remove("active"));
    section.classList.add("active");
  }

  function logTo(pre, lines){
    if(!Array.isArray(lines)) lines = [String(lines)];
    pre.textContent += lines.join("\\n") + "\\n";
    pre.scrollTop = pre.scrollHeight;
  }

  function logAll(lines){
    logTo(globalLog, lines);
    logTo(placeLog, lines);
    logTo(cubeLog, lines);
  }

  function closeMenus(){
    insertMenu.classList.remove("open");
    ejectMenu.classList.remove("open");
  }

  insertBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    ejectMenu.classList.remove("open");
    insertMenu.classList.toggle("open");
  });

  ejectBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    insertMenu.classList.remove("open");
    ejectMenu.classList.toggle("open");
  });

  document.addEventListener("click", () => closeMenus());

  async function sendBytes(bytes, label){
    closeMenus();
    logAll("UI: " + label + " -> sending: [" + bytes.join(", ") + "]");
    try{
      const res = await fetch("/api/send_bytes", {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ bytes })
      });
      const data = await res.json();
      if(Array.isArray(data.log)) logAll(data.log);
      if(data.error) logAll("ERROR: " + data.error);
      if(data.ok) logAll("UI: OK");
      else logAll("UI: FAILED");
      return data;
    }catch(e){
      logAll("UI ERROR: failed to send bytes: " + e);
      return { ok:false, log:[], error:String(e) };
    }
  }

  insertBottomBtn.addEventListener("click", () => sendBytes([241], "Insert bottom"));
  insertSidesBtn.addEventListener("click", () => sendBytes([222,231,222,231], "Insert sides"));

  ejectSidesBtn.addEventListener("click", () => sendBytes([221,232,221,232], "Eject sides"));
  ejectBottomBtn.addEventListener("click", () => sendBytes([242], "Eject bottom"));

  function renderPreview(container, presetName, lines12x15){
    container.innerHTML = "";
    const onClass = presetName;
    for(let r=0; r<12; r++){
      const row = lines12x15[r] || "...............";
      for(let c=0; c<15; c++){
        const ch = row[c] || ".";
        const d = document.createElement("div");
        d.className = "px" + (ch !== "." ? (" on " + onClass) : "");
        container.appendChild(d);
      }
    }
  }

  function setHomePills(){
    marioKpi.textContent = "Mario: " + (marioPreset ? marioPreset.order.length : 0) + " cubes";
    duckKpi.textContent = "Duck: " + (duckPreset ? duckPreset.order.length : 0) + " cubes";
    lastPresetPill.textContent = "Last preset: " + (prevPresetName || "none");
  }

  async function fetchPreset(name){
    const res = await fetch("/api/preset/" + name);
    if(!res.ok) throw new Error("Failed to fetch preset " + name);
    return await res.json();
  }

  function faceRow(face, col){
    const meta = COLOR_META[col] || { name:"?", css:"" };
    const sw = meta.css ? ("sw " + meta.css) : "sw";
    return `<div class="ori-row"><span class="${sw}"></span><span><b>${FACE_LABELS[face] || face}:</b> ${meta.name} (${(col||"?").toUpperCase()})</span></div>`;
  }

  function renderOrientation(ori, hintText){
    if(!ori){
      orientationBox.innerHTML = '<div class="warn">No orientation available for this entry.</div>';
      orientationHint.textContent = hintText || "";
      return;
    }
    let html = "";
    FACE_ORDER.forEach(f => {
      html += faceRow(f, ori[f]);
    });
    orientationBox.innerHTML = html;
    orientationHint.textContent = hintText || "";
  }

  async function startPreset(name){
    activePresetName = name;
    activePreset = (name === "mario") ? marioPreset : duckPreset;
    idx = 0;

    prevPresetName = localStorage.getItem("lastPresetName") || "";

    phase = (prevPresetName && prevPresetName !== activePresetName) ? "undo" : "make";

    placeLog.textContent = "";
    cubeLog.textContent = "";
    logAll("Selected preset: " + activePresetName + " (prev: " + (prevPresetName || "none") + ")");
    await loadStep();
    show(placeSection);
    subTitle.textContent = "Page 1 Â· Place cube";
  }

  async function loadStep(){
    currentPos = activePreset.order[idx];
    currentEntry = activePreset.cubes[currentPos] || { moves:[], serial:[], orientation:null, notes:["No data"] };
    currentUndoInfo = null;

    modePill.textContent = "phase: " + phase.toUpperCase();
    posPill.textContent = "cube " + currentPos;
    idxPill.textContent = "idx " + (idx+1) + " / " + activePreset.order.length;

    placeTitle.textContent = (phase === "undo")
      ? ("UNDO " + prevPresetName.toUpperCase() + " â†’ then MAKE " + activePresetName.toUpperCase())
      : ("MAKE " + activePresetName.toUpperCase());

    placeSub.textContent = "Page 1 Â· Place cube in fixture (then go to execution page)";

    if(phase === "undo"){
      if(!prevPresetName){
        renderOrientation(null, "No previous preset stored.");
        currentUndoInfo = { ok:false, message:"No previous preset", undo_moves:[], undo_serial:[], undo_orientation:null };
      }else{
        const res = await fetch("/api/undo_info", {
          method:"POST",
          headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ prev_preset: prevPresetName, pos: currentPos })
        });
        currentUndoInfo = await res.json();
        renderOrientation(currentUndoInfo.undo_orientation, "Place cube like it was placed when MAKING the previous preset (so UNDO works).");
        if(!currentUndoInfo.ok){
          logAll("UNDO not available for " + currentPos + ": " + currentUndoInfo.message);
        }else{
          logAll("UNDO prepared for " + currentPos + " (moves: " + currentUndoInfo.undo_moves.length + ")");
        }
      }
    }else{
      renderOrientation(currentEntry.orientation, "Place cube to match this orientation for MAKE.");
      if(!currentEntry.orientation){
        logAll("Note: no orientation for this entry (might be already-solved / placeholder).");
      }
    }
  }

  function loadCubePage(){
    cubeTitle.textContent = "Cube " + currentPos;
    cubeSub.textContent = "Page 2 Â· Send bytes to solver (you can send multiple times)";
    cubeModePill.textContent = "phase: " + phase.toUpperCase();
    cubePosPill.textContent = "cube " + currentPos;
    cubeIdxPill.textContent = "idx " + (idx+1) + " / " + activePreset.order.length;

    let entry = currentEntry;
    let notes = entry.notes || [];
    let moves = entry.moves || [];
    let serial = entry.serial || [];

    if(phase === "undo"){
      if(currentUndoInfo && currentUndoInfo.ok){
        notes = ["UNDO of " + prevPresetName + " at cube " + currentPos].concat(notes || []);
        moves = currentUndoInfo.undo_moves || [];
        serial = currentUndoInfo.undo_serial || [];
      }else{
        notes = ["UNDO not available for this cube. You may still use Insert/Eject, then press Next."] .concat(notes || []);
        moves = [];
        serial = [];
      }
    }

    notesBox.innerHTML = (notes && notes.length) ? notes.map(n => "â€¢ " + n).join("<br>") : "(none)";
    movesPre.textContent = (moves && moves.length) ? moves.join(" ") : "(none)";
    serialPre.textContent = (serial && serial.length) ? serial.join("\\n") : "(none)";

    if(phase === "undo"){
      if(currentUndoInfo && currentUndoInfo.ok){
        nextBtn.textContent = "Next: MAKE same cube";
        nextHint.textContent = "After UNDO, you MUST MAKE the new preset on this same cube before moving to the next cube.";
      }else{
        nextBtn.textContent = "Next";
        nextHint.textContent = "UNDO not available here, so Next will continue the flow.";
      }
    }else{
      nextBtn.textContent = (idx < activePreset.order.length - 1) ? "Next cube" : "Finish preset";
      nextHint.textContent = (idx < activePreset.order.length - 1)
        ? "After ejecting, go to the next cube."
        : "Finishing will return to Home and store this preset as lastPresetName.";
    }
  }

  async function doSendCurrent(){
    let bytes = [];
    if(phase === "undo"){
      bytes = (currentUndoInfo && currentUndoInfo.ok) ? (currentUndoInfo.undo_serial || []) : [];
      logAll("UI: Send (UNDO) bytes count: " + bytes.length);
    }else{
      bytes = (currentEntry && currentEntry.serial) ? currentEntry.serial : [];
      logAll("UI: Send (MAKE) bytes count: " + bytes.length);
    }

    if(!bytes.length){
      logAll("UI: No bytes to send for this step.");
      return;
    }

    sendBtn.disabled = true;
    try{
      const data = await sendBytes(bytes, "Send commands");
      if(data && data.ok){
        logAll("UI: Send complete.");
      }
    }finally{
      sendBtn.disabled = false;
    }
  }

  async function nextStep(){
    if(phase === "undo"){
      if(currentUndoInfo && currentUndoInfo.ok){
        phase = "make";
        await loadStep();
        show(placeSection);
        subTitle.textContent = "Page 1 Â· Place cube";
        logAll("Switched to MAKE for the same cube " + currentPos);
        return;
      }else{
        phase = "make";
        await loadStep();
        show(placeSection);
        subTitle.textContent = "Page 1 Â· Place cube";
        logAll("UNDO unavailable, continuing with MAKE for the same cube " + currentPos);
        return;
      }
    }

    if(idx < activePreset.order.length - 1){
      idx += 1;
      phase = (prevPresetName && prevPresetName !== activePresetName) ? "undo" : "make";
      await loadStep();
      show(placeSection);
      subTitle.textContent = "Page 1 Â· Place cube";
      return;
    }

    prevPresetName = activePresetName;
    localStorage.setItem("lastPresetName", activePresetName);
    logAll("Finished preset: " + activePresetName + ". Stored as lastPresetName.");
    setHomePills();
    show(homeSection);
    subTitle.textContent = "Home";
  }

  startMarioBtn.addEventListener("click", () => startPreset("mario"));
  startDuckBtn.addEventListener("click", () => startPreset("duck"));

  homeBtn.addEventListener("click", () => {
    show(homeSection);
    subTitle.textContent = "Home";
  });

  placeBackBtn.addEventListener("click", () => {
    show(homeSection);
    subTitle.textContent = "Home";
  });

  runSolverBtn.addEventListener("click", () => {
    loadCubePage();
    show(cubeSection);
    subTitle.textContent = "Page 2 Â· Cube execution";
  });

  backToPlaceBtn.addEventListener("click", async () => {
    show(placeSection);
    subTitle.textContent = "Page 1 Â· Place cube";
  });

  redoBtn.addEventListener("click", async () => {
    logAll("UI: Redo pressed. Reloading current step.");
    await loadStep();
    show(placeSection);
    subTitle.textContent = "Page 1 Â· Place cube";
  });

  sendBtn.addEventListener("click", doSendCurrent);
  nextBtn.addEventListener("click", nextStep);

  async function init(){
    try{
      marioPreset = await fetchPreset("mario");
      duckPreset = await fetchPreset("duck");

      renderPreview(marioPreview, "mario", marioPreset.preview_12x15);
      renderPreview(duckPreview, "duck", duckPreset.preview_12x15);

      setHomePills();
      logTo(globalLog, "Ready. Detected lastPresetName: " + (prevPresetName || "none"));
    }catch(e){
      logTo(globalLog, "ERROR loading presets: " + e);
    }
  }

  init();
</script>
</body>
</html>
"""


# =========================================================
# HTTP HANDLER
# =========================================================

class CubeHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._set_headers(200, "text/html; charset=utf-8")
            self.wfile.write(APP_HTML.encode("utf-8"))
            return

        if self.path.startswith("/api/preset/"):
            name = self.path.split("/")[-1].strip()
            if name not in PRESETS:
                self._set_headers(404, "application/json; charset=utf-8")
                self.wfile.write(json.dumps({"error": "Preset not found"}).encode("utf-8"))
                return
            payload = build_preset_payload(name)
            self._set_headers(200, "application/json; charset=utf-8")
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        self._set_headers(404, "text/plain; charset=utf-8")
        self.wfile.write(b"Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        if self.path == "/api/send_bytes":
            try:
                data = json.loads(body.decode("utf-8"))
                bytes_list = data.get("bytes") or []
                print("\n=== /api/send_bytes ===")
                print("Bytes:", bytes_list)
                result = run_serial_commands(bytes_list)
                self._set_headers(200, "application/json; charset=utf-8")
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self._set_headers(500, "application/json; charset=utf-8")
                self.wfile.write(json.dumps({"ok": False, "log": [], "error": str(e)}).encode("utf-8"))
            return

        if self.path == "/api/undo_info":
            try:
                data = json.loads(body.decode("utf-8"))
                prev_preset = (data.get("prev_preset") or "").strip()
                pos = (data.get("pos") or "").strip()

                if not prev_preset or prev_preset not in PRESETS:
                    out = {
                        "ok": False,
                        "message": "No previous preset stored / invalid previous preset.",
                        "undo_moves": [],
                        "undo_serial": [],
                        "undo_orientation": None,
                    }
                else:
                    out = compute_undo_for_cube(prev_preset, pos)

                self._set_headers(200, "application/json; charset=utf-8")
                self.wfile.write(json.dumps(out).encode("utf-8"))
            except Exception as e:
                self._set_headers(500, "application/json; charset=utf-8")
                self.wfile.write(json.dumps({
                    "ok": False,
                    "message": str(e),
                    "undo_moves": [],
                    "undo_serial": [],
                    "undo_orientation": None,
                }).encode("utf-8"))
            return

        self._set_headers(404, "text/plain; charset=utf-8")
        self.wfile.write(b"Not found")


# =========================================================
# RUN SERVER
# =========================================================

def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    server = HTTPServer((host, port), CubeHandler)
    ip = get_local_ip()
    url = f"http://{ip}:{port}"
    print_qr(url)
    print("\nServing on", url)
    print("Home: /")
    print("API:  /api/preset/mario , /api/preset/duck")
    print("API:  POST /api/send_bytes   {bytes:[...]}  (bytes only, waits for DONE after each byte)")
    print("API:  POST /api/undo_info    {prev_preset:'mario', pos:'1,1'}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
