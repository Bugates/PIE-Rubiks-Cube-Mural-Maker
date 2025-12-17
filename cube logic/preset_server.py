#!/usr/bin/env python3
import json
import socket
import time
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional

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
# SERIAL HELPERS
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
# MOVE / PRESET HELPERS
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


INSERT_BOTTOM = [241]
INSERT_SIDES  = [222, 231, 222, 231]

EJECT_SIDES   = [221, 232, 221, 232]
EJECT_BOTTOM  = [213, 242, 214]


VALID_COLS = set(["w", "r", "o", "b", "g", "y", "."])


def _norm_cell(ch: str) -> str:
    if not ch:
        return "."
    c = str(ch).strip().lower()
    if c in ["w", "r", "o", "b", "g", "y"]:
        return c
    if c == ".":
        return "."
    return "."


def build_preview_12x15_from_u_faces(preset: Dict[str, object]) -> List[List[str]]:
    rows = int(preset.get("rows", 5))
    cols = int(preset.get("cols", 4))
    cubes = preset.get("cubes", {}) or {}

    out = [["." for _ in range(cols * 3)] for __ in range(rows * 3)]

    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            pos = key_rc(r, c)
            entry = cubes.get(pos) or {}
            face = entry.get("u_face")

            if not face:
                continue

            for i in range(3):
                for j in range(3):
                    ch = "."
                    try:
                        ch = _norm_cell(face[i][j])
                    except Exception:
                        ch = "."
                    out[(r - 1) * 3 + i][(c - 1) * 3 + j] = ch

    return out


def make_order(rows: int, cols: int) -> List[str]:
    return [key_rc(r, c) for r in range(1, rows + 1) for c in range(1, cols + 1)]


def empty_5x4_preset(title: str) -> Dict[str, object]:
    return {
        "title": title,
        "rows": 5,
        "cols": 4,
        "order": make_order(5, 4),
        "cubes": {}
    }

PRESETS: Dict[str, Dict[str, object]] = {
    "mario": {
        "title": "Mario",
        "rows": 5,
        "cols": 4,
        "order": make_order(5, 4),
        "cubes": {
            "1,1": {
                "u_face": [['w','w','w'],['w','w','r'],['w','w','o']],
                "moves": ['R', 'F', "R'", "F'"],
                "serial": [122, 112, 121, 111],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'r', 'B': 'o', 'R': 'b', 'L': 'g'},
                "notes": []
            },
            "1,2": {
                "u_face": [['r','r','r'],['r','r','r'],['o','o','y']],
                "moves": ['F', "D'", 'F'],
                "serial": [112, 212, 112],
                "orientation": {'U': 'r', 'D': 'o', 'F': 'w', 'B': 'y', 'R': 'g', 'L': 'b'},
                "notes": []
            },
            "1,3": {
                "u_face": [['r','r','w'],['r','r','r'],['y','b','y']],
                "moves": ['D', "F'", 'D', "R'", 'F', "D'", 'R'],
                "serial": [211, 111, 211, 121, 112, 212, 122],
                "orientation": {'U': 'r', 'D': 'o', 'F': 'b', 'B': 'g', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "1,4": {
                "u_face": [['w','w','w'],['r','r','w'],['w','w','w']],
                "moves": ['D', 'F', "B'", 'R'],
                "serial": [211, 112, 131, 122],
                "orientation": {'U': 'r', 'D': 'o', 'F': 'b', 'B': 'g', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "2,1": {
                "u_face": [['w','o','y'],['w','o','y'],['w','w','o']],
                "moves": ['R', "D'", 'L', "F'"],
                "serial": [122, 212, 142, 111],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'w', 'B': 'y', 'R': 'b', 'L': 'g'},
                "notes": []
            },
            "2,2": {
                "u_face": [['o','y','y'],['o','o','y'],['y','y','y']],
                "moves": ["L'", 'D', "B'", 'L', 'F', 'R'],
                "serial": [141, 211, 131, 142, 112, 122],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'b', 'B': 'g', 'R': 'y', 'L': 'w'},
                "notes": []
            },
            "2,3": {
                "u_face": [['y','b','y'],['y','b','b'],['y','b','b']],
                "moves": ['B', "D'", "B'", "L'"],
                "serial": [132, 212, 131, 141],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'w', 'B': 'y', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Blue up change center to white"]
            },
            "2,4": {
                "u_face": [['y','y','w'],['y','y','y'],['b','b','w']],
                "moves": ["R'", 'D', 'F', 'D', 'R', 'F'],
                "serial": [121, 211, 112, 211, 122, 112],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'o', 'B': 'r', 'R': 'b', 'L': 'g'},
                "notes": []
            },
            "3,1": {
                "u_face": [['w','w','w'],['w','w','r'],['w','r','r']],
                "moves": ["D'", "B'", 'R', 'B', "D'", "F'"],
                "serial": [212, 131, 122, 132, 212, 111],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'b', 'B': 'g', 'R': 'o', 'L': 'r'},
                "notes": []
            },
            "3,2": {
                "u_face": [['y','y','y'],['r','b','r'],['r','b','r']],
                "moves": ['R', "L'", 'B'],
                "serial": [122, 141, 132],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "3,3": {
                "u_face": [['y','y','y'],['r','b','r'],['r','b','r']],
                "moves": ['R', "L'", 'B'],
                "serial": [122, 141, 132],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "3,4": {
                "u_face": [['w','w','w'],['r','w','w'],['r','r','w']],
                "moves": ['D', 'B', "L'", "B'", 'D', 'F'],
                "serial": [211, 132, 141, 131, 211, 112],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "4,1": {
                "u_face": [['r','r','r'],['o','o','r'],['o','o','o']],
                "moves": ['B', 'R', "F'", 'R', 'F', 'B'],
                "serial": [132, 122, 111, 122, 112, 132],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'g', 'B': 'b', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "4,2": {
                "u_face": [['r','b','b'],['b','b','b'],['b','b','b']],
                "moves": ['L', 'D', "L'"],
                "serial": [142, 211, 141],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'w', 'B': 'y', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Blue up make center orange"]
            },
            "4,3": {
                "u_face": [['b','b','r'],['b','b','b'],['b','b','b']],
                "moves": ["R'", 'D', 'R'],
                "serial": [121, 211, 122],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'w', 'B': 'y', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Blue up make center orange"]
            },
            "4,4": {
                "u_face": [['r','r','r'],['r','o','o'],['o','o','o']],
                "moves": ['B', "L'", "B'", 'L', 'B', "L'"],
                "serial": [132, 141, 131, 142, 132, 141],
                "orientation": {'U': 'o', 'D': 'r', 'F': 'g', 'B': 'b', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "5,1": {
                "u_face": [['o','o','b'],['w','w','b'],['w','o','o']],
                "moves": ['B', 'R', "D'", "F'"],
                "serial": [132, 122, 212, 111],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "5,2": {
                "u_face": [['b','b','b'],['b','b','w'],['o','w','w']],
                "moves": ["F'", 'D', 'R', 'D', 'R', 'F'],
                "serial": [111, 211, 122, 211, 122, 112],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "5,3": {
                "u_face": [['b','b','b'],['w','b','b'],['w','w','o']],
                "moves": ['D', 'F', 'B', "L'", "B'"],
                "serial": [211, 112, 132, 141, 131],
                "orientation": {'U': 'b', 'D': 'g', 'F': 'o', 'B': 'r', 'R': 'w', 'L': 'y'},
                "notes": []
            },
            "5,4": {
                "u_face": [['b','o','o'],['b','w','w'],['o','o','o']],
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
        "cubes": {
            "1,1": {
                "u_face": [['w','w','w'],['w','w','w'],['w','w','o']],
                "moves": ['R', 'D', "R'"],
                "serial": [122, 211, 121],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "1,2": {
                "u_face": [['y','y','y'],['y','y','y'],['y','b','y']],
                "moves": ["R'", 'L', "F'", 'R', "L'"],
                "serial": [121, 142, 111, 122, 141],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'r', 'B': 'o', 'R': 'g', 'L': 'b'},
                "notes": []
            },
            "1,3": {
                "u_face": [['y','w','w'],['y','y','w'],['y','y','w']],
                "moves": ['R', "B'", "R'", 'B', 'R', "B'"],
                "serial": [122, 131, 121, 132, 122, 131],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "1,4": {
                "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: white side up (WWW/WWW/WWW)"]
            },
            "2,1": {
                "u_face": [['o','o','o'],['w','o','o'],['w','w','w']],
                "moves": ['D',"L'","F'",'L'],
                "serial": [211,141,111,142],
                "orientation": {'U':'o','D':'r','F':'b','B':'g','R':'y','L':'w'},
                "notes": []
            },
            "2,2": {
                "u_face": [['y','y','y'],['o','y','y'],['y','y','y']],
                "moves": ["F'", 'B', "L'", 'F', "B'"],
                "serial": [111, 132, 141, 112, 131],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'r', 'B': 'o', 'R': 'g', 'L': 'b'},
                "notes": []
            },
            "2,3": {
                "u_face": [['y','y','w'],['y','w','w'],['w','w','w']],
                "moves": ["B'", 'L', 'D', 'L', 'D', "B'"],
                "serial": [131, 142, 211, 142, 211, 131],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "2,4": {
                "u_face": [['w','w','w'],['w','w','w'],['w','w','y']],
                "moves": ["F'", "R'", 'F', 'R', "D'", 'F'],
                "serial": [111, 121, 112, 122, 212, 112],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "3,1": {
                "u_face": [['w','w','y'],['w','y','y'],['w','y','y']],
                "moves": ['L', 'B', "R'", 'B', 'R', 'L'],
                "serial": [142, 132, 121, 132, 122, 142],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "3,2": {
                "u_face": [['y','y','y'],['y','y','y'],['y','y','o']],
                "moves": ['R', 'D', "R'"],
                "serial": [122, 211, 121],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": ["Center exchange: Orange center switch"]
            },
            "3,3": {
                "u_face": [['y','w','w'],['y','y','y'],['y','y','y']],
                "moves": ['B', "R'", "D'", 'R', "D'", 'B'],
                "serial": [132, 121, 212, 122, 212, 132],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "3,4": {
                "u_face": [['w','y','y'],['y','y','y'],['o','y','y']],
                "moves": ["L'", 'D', 'L', "B'", "D'", 'B'],
                "serial": [141, 211, 142, 131, 212, 132],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "4,1": {
                "u_face": [['w','y','y'],['w','w','y'],['b','w','b']],
                "moves": ['F', 'D', 'R', "F'", "B'", 'D', "B'", 'R'],
                "serial": [112, 211, 122, 111, 131, 211, 131, 122],
                "orientation": {'U': 'w', 'D': 'y', 'F': 'g', 'B': 'b', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "4,2": {
                "u_face": [['y','y','y'],['y','y','y'],['y','y','y']],
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: yellow side up (YYY/YYY/YYY)"]
            },
            "4,3": {
                "u_face": [['o','o','o'],['y','y','y'],['y','y','y']],
                "moves": ['B'],
                "serial": [132],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "4,4": {
                "u_face": [['y','y','y'],['y','y','w'],['y','w','w']],
                "moves": ["F'", 'R', 'D', 'R', 'D', "F'"],
                "serial": [111, 122, 211, 122, 211, 111],
                "orientation": {'U': 'y', 'D': 'w', 'F': 'b', 'B': 'g', 'R': 'r', 'L': 'o'},
                "notes": []
            },
            "5,1": {
                "u_face": [['b','b','b'],['b','b','b'],['b','b','b']],
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
            "5,2": {
                "u_face": [['b','b','b'],['b','b','b'],['b','b','b']],
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
            "5,3": {
                "u_face": [['b','b','b'],['b','b','b'],['b','b','b']],
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
            "5,4": {
                "u_face": [['b','b','b'],['b','b','b'],['b','b','b']],
                "moves": [],
                "serial": [],
                "orientation": None,
                "notes": ["Already solved / stack: blue side up (BBB/BBB/BBB)"]
            },
        }
    },

"silly": {
    "title": "Silly Face",
    "rows": 5,
    "cols": 4,
    "order": make_order(5, 4),
    "cubes": {

        "1,1": {
            "u_face": [['g','g','g'],['g','g','g'],['g','g','g']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack green side up"]
        },

        "1,2": {
            "u_face": [['g','g','g'],['g','g','g'],['y','y','y']],
            "moves": ["F'"],
            "serial": [111],
            "orientation": {'U':'g','D':'b','F':'r','B':'o','R':'w','L':'y'},
            "notes": []
        },

        "1,3": {
            "u_face": [['g','g','g'],['g','g','g'],['y','y','y']],
            "moves": ["F'"],
            "serial": [111],
            "orientation": {'U':'g','D':'b','F':'r','B':'o','R':'w','L':'y'},
            "notes": []
        },

        "1,4": {
            "u_face": [['g','g','g'],['g','g','g'],['g','g','g']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack green side up"]
        },

        "2,1": {
            "u_face": [['g','g','y'],['g','y','y'],['g','y','y']],
            "moves": ['D',"B'","L'",'B'],
            "serial": [211,131,141,132],
            "orientation": {'U':'y','D':'w','F':'b','B':'g','R':'r','L':'o'},
            "notes": []
        },

        "2,2": {
            "u_face": [['y','y','y'],['b','w','y'],['b','b','y']],
            "moves": ['F',"R'",'D',"R'",'F','L',"B'"],
            "serial": [112,121,211,121,112,142,131],
            "orientation": {'U':'w','D':'y','F':'b','B':'g','R':'o','L':'r'},
            "notes": []
        },

        "2,3": {
            "u_face": [['y','y','y'],['y','b','w'],['y','b','b']],
            "moves": ['R','L','D','B','R','B'],
            "serial": [122,142,211,132,122,132],
            "orientation": {'U':'b','D':'g','F':'y','B':'w','R':'o','L':'r'},
            "notes": []
        },

        "2,4": {
            "u_face": [['y','g','g'],['y','y','g'],['y','y','g']],
            "moves": ["D'",'B','R',"B'"],
            "serial": [212,132,122,131],
            "orientation": {'U':'y','D':'w','F':'b','B':'g','R':'r','L':'o'},
            "notes": []
        },

        "3,1": {
            "u_face": [['g','y','y'],['g','y','y'],['g','y','y']],
            "moves": ["L'"],
            "serial": [141],
            "orientation": {'U':'y','D':'w','F':'b','B':'g','R':'r','L':'o'},
            "notes": []
        },

        "3,2": {
            "u_face": [['y','y','y'],['y','y','y'],['y','y','y']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack yellow side up"]
        },

        "3,3": {
            "u_face": [['y','y','y'],['y','y','y'],['y','y','b']],
            "moves": ["F'",'D','F'],
            "serial": [111,211,112],
            "orientation": {'U':'y','D':'w','F':'b','B':'g','R':'r','L':'o'},
            "notes": []
        },

        "3,4": {
            "u_face": [['y','y','g'],['y','y','g'],['y','y','g']],
            "moves": ['R'],
            "serial": [122],
            "orientation": {'U':'y','D':'w','F':'b','B':'g','R':'r','L':'o'},
            "notes": []
        },

        "4,1": {
            "u_face": [['g','y','y'],['g','g','y'],['g','g','g']],
            "moves": ["D'","L'",'B','L',"D'","R'"],
            "serial": [212,141,132,142,212,121],
            "orientation": {'U':'g','D':'b','F':'y','B':'w','R':'r','L':'o'},
            "notes": []
        },

        "4,2": {
            "u_face": [['y','b','r'],['y','y','r'],['y','y','y']],
            "moves": ["L'",'B','L',"D'","R'"],
            "serial": [141,132,142,212,121],
            "orientation": {'U':'y','D':'w','F':'r','B':'o','R':'g','L':'b'},
            "notes": []
        },

        "4,3": {
            "u_face": [
                ['r','b','y'],
                ['r','y','y'],
                ['y','y','y']
            ],
            "moves": ['R', 'B', "R'", "F'", 'L', 'F'],
            "serial": [122, 132, 121, 111, 142, 112],
            "orientation": {
                'U': 'y',
                'D': 'w',
                'F': 'r',
                'B': 'o',
                'R': 'g',
                'L': 'b'
            },
            "notes": []
        },


        "4,4": {
            "u_face": [['y','y','g'],['y','g','g'],['g','g','g']],
            "moves": ['D','R',"B'","R'",'D','L'],
            "serial": [211,122,131,121,211,142],
            "orientation": {'U':'g','D':'b','F':'y','B':'w','R':'r','L':'o'},
            "notes": []
        },

        "5,1": {
            "u_face": [['g','g','g'],['g','g','g'],['g','g','g']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack green side up"]
        },

        "5,2": {
            "u_face": [['g','g','g'],['g','g','g'],['g','g','g']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack green side up"]
        },

        "5,3": {
            "u_face": [['g','g','g'],['g','g','g'],['g','g','g']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack green side up"]
        },

        "5,4": {
            "u_face": [['g','g','g'],['g','g','g'],['g','g','g']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack green side up"]
        },
    }
},


"bunny": {
    "title": "Bunny",
    "rows": 5,
    "cols": 4,
    "order": make_order(5, 4),
    "cubes": {

        "1,1": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },

        "1,2": {
            "u_face": [['w','w','w'],['w','w','w'],['b','b','w']],
            "moves": ["R'", "F'", 'R'],
            "serial": [121,111,122],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        "1,3": {
            "u_face": [['w','w','w'],['w','w','w'],['b','b','w']],
            "moves": ["R'", "F'", 'R'],
            "serial": [121,111,122],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        "1,4": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },

        "2,1": {
            "u_face": [['w','w','b'],['w','w','b'],['w','w','b']],
            "moves": ['R'],
            "serial": [122],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        "2,2": {
            "u_face": [['w','w','b'],['w','w','b'],['w','w','b']],
            "moves": ['R'],
            "serial": [122],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        "2,3": {
            "u_face": [['w','w','b'],['w','w','b'],['w','w','b']],
            "moves": ['R'],
            "serial": [122],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        "2,4": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },

        "3,1": {
            "u_face": [['w','b','w'],['b','w','w'],['b','w','w']],
            "moves": ['D',"B'","L'","D'",'B'],
            "serial": [211,131,141,212,132],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        "3,2": {
            "u_face": [['w','w','w'],['w','w','w'],['b','w','w']],
            "moves": ['F','D',"F'"],
            "serial": [112,211,111],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        "3,3": {
            "u_face": [['w','w','w'],['w','w','w'],['w','b','w']],
            "moves": ["R'",'L',"F'",'R',"L'"],
            "serial": [121,142,111,122,141],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        "3,4": {
            "u_face": [['b','w','w'],['w','b','w'],['w','b','w']],
            "moves": ['L',"D'",'R',"B'","L'"],
            "serial": [142,212,122,131,141],
            "orientation": {'U':'b','D':'g','F':'y','B':'w','R':'o','L':'r'},
            "notes": []
        },

        "4,1": {
            "u_face": [['b','w','r'],['b','w','r'],['w','b','w']],
            "moves": ["R'","D'",'R',"F'","R'",'L','F'],
            "serial": [121,212,122,111,121,142,112],
            "orientation": {'U':'w','D':'y','F':'r','B':'o','R':'b','L':'g'},
            "notes": []
        },

        "4,2": {
            "u_face": [['b','w','b'],['r','w','w'],['w','w','w']],
            "moves": ["R'","D'","F'","L'",'F','R'],
            "serial": [121,212,111,141,112,122],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        "4,3": {
            "u_face": [['w','b','r'],['w','r','r'],['w','w','w']],
            "moves": ['B','D',"R'",'L',"D'",'F',"R'"],
            "serial": [132,211,121,142,212,112,121],
            "orientation": {'U':'r','D':'o','F':'w','B':'y','R':'g','L':'b'},
            "notes": []
        },

        "4,4": {
            "u_face": [['w','b','w'],['w','b','w'],['b','w','w']],
            "moves": ["L'",'D',"R'",'F','L'],
            "serial": [141,211,121,112,142],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },

        "5,1": {
            "u_face": [['w','w','b'],['w','w','w'],['w','w','w']],
            "moves": ['B',"D'","B'"],
            "serial": [132,212,131],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        "5,2": {
            "u_face": [['b','b','b'],['w','w','w'],['w','w','w']],
            "moves": ['B'],
            "serial": [132],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        "5,3": {
            "u_face": [['b','b','b'],['w','w','w'],['w','w','w']],
            "moves": ['B'],
            "serial": [132],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        "5,4": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },

    }
},
"parrot": {
    "title": "Parrot",
    "rows": 5,
    "cols": 4,
    "order": make_order(5, 4),
    "cubes": {

        # ---------- Row 1 ----------
        "1,1": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
        "1,2": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
        "1,3": {
            "u_face": [['w','w','w'],['w','r','r'],['r','w','w']],
            "moves": ['F', "D'", 'B', "L'", "F'"],
            "serial": [112, 212, 132, 141, 111],
            "orientation": {'U':'r','D':'o','F':'g','B':'b','R':'y','L':'w'},
            "notes": []
        },
        "1,4": {
            "u_face": [['w','w','w'],['r','w','w'],['r','r','w']],
            "moves": ['D', 'B', "L'", "B'", 'D', 'F'],
            "serial": [211, 132, 141, 131, 211, 112],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        # ---------- Row 2 ----------
        "2,1": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
        "2,2": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','r']],
            "moves": ['R', "D'", "R'"],
            "serial": [122, 212, 121],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "2,3": {
            "u_face": [['r','w','b'],['r','w','w'],['r','r','w']],
            "moves": ["R'", 'D', "F'", 'L', 'D', 'R'],
            "serial": [121, 211, 111, 142, 211, 122],
            "orientation": {'U':'w','D':'y','F':'b','B':'g','R':'o','L':'r'},
            "notes": []
        },
        "2,4": {
            "u_face": [['o','o','w'],['o','o','w'],['b','o','w']],
            "moves": ['R', "L'", 'D', 'L'],
            "serial": [122, 141, 211, 142],
            "orientation": {'U':'o','D':'r','F':'y','B':'w','R':'g','L':'b'},
            "notes": []
        },

        # ---------- Row 3 ----------
        "3,1": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
        "3,2": {
            "u_face": [['w','w','r'],['w','r','y'],['w','y','y']],
            "moves": ["D'", "F'", 'L', "B'", 'R'],
            "serial": [212, 111, 142, 131, 122],
            "orientation": {'U':'r','D':'o','F':'b','B':'g','R':'w','L':'y'},
            "notes": []
        },
        "3,3": {
            "u_face": [['r','r','r'],['y','r','r'],['y','y','r']],
            "moves": ['D', 'B', "L'", "B'", 'D', 'F'],
            "serial": [211, 132, 141, 131, 211, 112],
            "orientation": {'U':'r','D':'o','F':'g','B':'b','R':'y','L':'w'},
            "notes": []
        },
        "3,4": {
            "u_face": [['w','w','w'],['r','w','w'],['r','w','w']],
            "moves": ['B', "L'", "B'"],
            "serial": [132, 141, 131],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },

        # ---------- Row 4 ----------
        "4,1": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','g']],
            "moves": ["F'", 'D', 'F'],
            "serial": [111, 211, 112],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "4,2": {
            "u_face": [['y','y','y'],['g','g','g'],['g','b','b']],
            "moves": ["D'", "F'", 'D', 'B', 'D', "F'"],
            "serial": [212, 111, 211, 132, 211, 111],
            "orientation": {'U':'g','D':'b','F':'r','B':'o','R':'w','L':'y'},
            "notes": []
        },
        "4,3": {
            "u_face": [['y','b','r'],['b','r','r'],['b','r','r']],
            "moves": ['D', "B'", "L'", 'D', 'B'],
            "serial": [211, 131, 141, 211, 132],
            "orientation": {'U':'r','D':'o','F':'g','B':'b','R':'y','L':'w'},
            "notes": []
        },
        "4,4": {
            "u_face": [['r','w','w'],['w','w','w'],['w','w','w']],
            "moves": ['L', 'D', "L'"],
            "serial": [142, 211, 141],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        # ---------- Row 5 ----------
        "5,1": {
            "u_face": [['w','w','b'],['w','w','r'],['w','w','r']],
            "moves": ["D'", 'R'],
            "serial": [212, 122],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },
        "5,2": {
            "u_face": [['b','b','b'],['b','w','w'],['w','w','w']],
            "moves": ["D'", 'L', 'B', "L'"],
            "serial": [212, 142, 132, 141],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },
        "5,3": {
            "u_face": [['r','r','w'],['w','w','w'],['w','w','w']],
            "moves": ['R', "B'", "R'"],
            "serial": [122, 131, 121],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "5,4": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
    }
},
"penguin": {
    "title": "Penguin",
    "rows": 5,
    "cols": 4,
    "order": make_order(5, 4),
    "cubes": {

        # ---------- Row 1 ----------
        "1,1": {
            "u_face": [['w','w','w'],['w','w','b'],['w','w','b']],
            "moves": ["B'", 'R', 'B'],
            "serial": [131, 122, 132],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "1,2": {
            "u_face": [['b','b','b'],['b','b','b'],['w','b','b']],
            "moves": ['F', "D'", "F'"],
            "serial": [112, 212, 111],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },
        "1,3": {
            "u_face": [['b','b','b'],['b','b','b'],['b','b','w']],
            "moves": ["F'", 'D', 'F'],
            "serial": [111, 211, 112],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },
        "1,4": {
            "u_face": [['w','w','w'],['b','w','w'],['b','w','w']],
            "moves": ['B', "L'", "B'"],
            "serial": [132, 141, 131],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },

        # ---------- Row 2 ----------
        "2,1": {
            "u_face": [['w','b','w'],['w','b','w'],['w','b','w']],
            "moves": ["R'", 'L'],
            "serial": [121, 142],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },
        "2,2": {
            "u_face": [['w','w','b'],['b','w','b'],['b','w','w']],
            "moves": ['F', 'R', "D'", "F'", "L'"],
            "serial": [112, 122, 212, 111, 141],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "2,3": {
            "u_face": [['b','w','w'],['b','w','b'],['w','w','b']],
            "moves": ["F'", "L'", 'D', 'F', 'R'],
            "serial": [111, 141, 211, 112, 122],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "2,4": {
            "u_face": [['w','b','w'],['w','b','w'],['w','b','w']],
            "moves": ["R'", 'L'],
            "serial": [121, 142],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },

        # ---------- Row 3 ----------
        "3,1": {
            "u_face": [['w','b','w'],['w','b','w'],['w','w','b']],
            "moves": ['R', "D'", 'L', "F'", "R'"],
            "serial": [122, 212, 142, 111, 121],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },
        "3,2": {
            "u_face": [['w','o','o'],['w','w','o'],['w','w','w']],
            "moves": ['D', 'F', "R'", "F'", 'D', 'B'],
            "serial": [211, 112, 121, 111, 211, 132],
            "orientation": {'U':'w','D':'y','F':'g','B':'b','R':'r','L':'o'},
            "notes": []
        },
        "3,3": {
            "u_face": [['o','o','w'],['o','w','w'],['w','w','w']],
            "moves": ["D'", "F'", 'L', 'F', "D'", "B'"],
            "serial": [212, 111, 142, 112, 212, 131],
            "orientation": {'U':'w','D':'y','F':'b','B':'g','R':'o','L':'r'},
            "notes": []
        },
        "3,4": {
            "u_face": [['w','b','w'],['w','b','w'],['b','w','w']],
            "moves": ["L'", 'D', "R'", 'F', 'L'],
            "serial": [141, 211, 121, 112, 142],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },

        # ---------- Row 4 ----------
        "4,1": {
            "u_face": [['w','b','b'],['w','b','b'],['w','b','b']],
            "moves": ['L'],
            "serial": [142],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },
        "4,2": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
        "4,3": {
            "u_face": [['w','w','w'],['w','w','w'],['w','w','w']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": ["Place the cube into stack white side up"]
        },
        "4,4": {
            "u_face": [['b','b','w'],['b','b','w'],['b','b','w']],
            "moves": ["R'"],
            "serial": [121],
            "orientation": {'U':'b','D':'g','F':'w','B':'y','R':'r','L':'o'},
            "notes": []
        },

        # ---------- Row 5 ----------
        "5,1": {
            "u_face": [['w','b','w'],['w','w','w'],['w','w','w']],
            "moves": ['R', "L'", 'B', "R'", 'L'],
            "serial": [122, 141, 132, 121, 142],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },
        "5,2": {
            "u_face": [['b','w','w'],['o','o','b'],['w','w','w']],
            "moves": ["R'", "D'", 'B', 'D', "F'"],
            "serial": [121, 212, 132, 211, 111],
            "orientation": {'U':'o','D':'r','F':'b','B':'g','R':'y','L':'w'},
            "notes": []
        },
        "5,3": {
            "u_face": [['w','w','b'],['b','o','o'],['w','w','w']],
            "moves": ["L'", "F'", 'D', 'L', 'B'],
            "serial": [141, 111, 211, 142, 132],
            "orientation": {'U':'o','D':'r','F':'b','B':'g','R':'y','L':'w'},
            "notes": []
        },
        "5,4": {
            "u_face": [['w','b','w'],['w','w','w'],['w','w','w']],
            "moves": ['R', "L'", 'B', "R'", 'L'],
            "serial": [122, 141, 132, 121, 142],
            "orientation": {'U':'w','D':'y','F':'o','B':'r','R':'g','L':'b'},
            "notes": []
        },
    }
},
}


def get_cube_entry(preset_name: str, pos_key: str) -> Dict[str, object]:
    p = PRESETS.get(preset_name, {})
    cubes = p.get("cubes", {})
    entry = cubes.get(pos_key)
    if entry is None:
        return {
            "u_face": [['.','.','.'],['.','.','.'],['.','.','.']],
            "moves": [],
            "serial": [],
            "orientation": None,
            "notes": []
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
        "preview_15x12": [],
        "cubes": {},
    }
    for k in out["order"]:
        out["cubes"][k] = get_cube_entry(name, k)

    out["preview_15x12"] = build_preview_12x15_from_u_faces({
        "rows": out["rows"],
        "cols": out["cols"],
        "cubes": out["cubes"]
    })

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
# UI (HTML)
# =========================================================

APP_HTML = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Rubik’s Cube Mural Presets</title>
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
    .grid3{ display:grid; grid-template-columns:1fr; gap:12px; }
    @media(min-width:900px){ .grid3{ grid-template-columns:1fr 1fr; } }
    .section{ display:none; }
    .section.active{ display:block; }
    .h2{ font-size:16px; font-weight:800; margin:0 0 6px; }
    .preview-wrap{ display:flex; gap:14px; align-items:flex-start; flex-wrap:wrap; margin-top:10px; }
    .preview{
      border:1px solid var(--border); border-radius:12px; padding:10px; background:#fff;
      display:grid; grid-template-columns:repeat(12, 10px); gap:2px;
    }
    .px{ width:10px; height:10px; border-radius:2px; border:1px solid rgba(0,0,0,0.08); background:#fff; }
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

    .modal-backdrop{
      position:fixed; inset:0;
      background:rgba(15,23,42,0.45);
      display:none;
      z-index:500;
      align-items:center;
      justify-content:center;
      padding:16px;
    }
    .modal-backdrop.open{ display:flex; }
    .modal{
      width:min(520px, 100%);
      background:#fff;
      border:1px solid var(--border);
      border-radius:16px;
      box-shadow:0 24px 60px rgba(15,23,42,0.25);
      padding:14px;
    }
    .modal .h2{ margin:0 0 6px; }
    .modal .row{ justify-content:space-between; }
    .modal select{
      width:100%;
      padding:10px 10px;
      border-radius:12px;
      border:1px solid var(--border);
      font-size:14px;
      background:#fff;
    }
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
        <button class="btn secondary" id="insertBtn" type="button">Insert ▾</button>
        <div class="menu" id="insertMenu">
          <button class="btn secondary" type="button" id="insertBottomBtn">Insert bottom (241)</button>
          <button class="btn secondary" type="button" id="insertSidesBtn">Insert sides (222,231,222,231)</button>
          <div class="mini-note">Always available. Sends bytes to all detected ports, waits for DONE after each byte.</div>
        </div>
      </div>

      <div class="dropdown">
        <button class="btn secondary" id="ejectBtn" type="button">Eject ▾</button>
        <div class="menu" id="ejectMenu">
          <button class="btn secondary" type="button" id="ejectSidesBtn">Eject sides (221,232,221,232)</button>
          <button class="btn secondary" type="button" id="ejectBottomBtn">Eject bottom (213, 242, 214)</button>
          <div class="mini-note">Always available.</div>
        </div>
      </div>

      <button class="btn secondary" id="send251Btn" type="button">
        Send 251
      </button>

      <button class="btn secondary" id="homeBtn" type="button">Home</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="undoModalBackdrop" aria-hidden="true">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="undoModalTitle">
    <div class="h2" id="undoModalTitle">Choose undo</div>
    <div class="muted" id="undoModalSubtitle">A previous preset was run. Choose what to undo before starting.</div>
    <div class="hr"></div>

    <div class="box">
      <div class="muted" style="margin-bottom:8px;"><b>Undo option</b></div>
      <select id="undoSelect">
        <option value="none">Undo NONE</option>
      </select>
      <div class="mini-note" id="undoModalNote"></div>
    </div>

    <div class="hr"></div>

    <div class="row">
      <button class="btn secondary" type="button" id="undoCancelBtn">Cancel</button>
      <button class="btn" type="button" id="undoConfirmBtn">Confirm</button>
    </div>
  </div>
</div>

<div class="shell">

  <div id="homeSection" class="section active">
    <div class="grid2" id="presetCards"></div>

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
          <div class="muted" id="placeSub">Page 1 · Place the cube in the fixture</div>
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
          <button class="btn" type="button" id="runSolverBtn">Run solver →</button>
        </div>
      </div>

      <div class="mini-note">
        “Run solver” here just means: go to the cube execution page for this cube, where you can send the preset bytes multiple times.
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
          <div class="muted" id="cubeSub">Page 2 · Send commands</div>
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
    ".": { name: "Empty", css: "" },
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

  const PRESET_LIST = ["mario","duck","silly","bunny","parrot","penguin"];
  const PRESET_DISPLAY = {
    mario: "Mario",
    duck: "Duck",
    silly: "Silly Face",
    bunny: "Bunny",
    parrot: "Parrot",
    penguin: "Penguin",
  };

  const homeSection = document.getElementById("homeSection");
  const placeSection = document.getElementById("placeSection");
  const cubeSection = document.getElementById("cubeSection");

  const presetCards = document.getElementById("presetCards");
  const subTitle = document.getElementById("subTitle");

  const homeBtn = document.getElementById("homeBtn");

  const insertBtn = document.getElementById("insertBtn");
  const ejectBtn = document.getElementById("ejectBtn");
  const insertMenu = document.getElementById("insertMenu");
  const ejectMenu = document.getElementById("ejectMenu");
  const insertBottomBtn = document.getElementById("insertBottomBtn");
  const insertSidesBtn = document.getElementById("insertSidesBtn");
  const ejectSidesBtn = document.getElementById("ejectSidesBtn");
  const ejectBottomBtn = document.getElementById("ejectBottomBtn");
  const send251Btn = document.getElementById("send251Btn");

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

  const undoModalBackdrop = document.getElementById("undoModalBackdrop");
  const undoSelect = document.getElementById("undoSelect");
  const undoCancelBtn = document.getElementById("undoCancelBtn");
  const undoConfirmBtn = document.getElementById("undoConfirmBtn");
  const undoModalSubtitle = document.getElementById("undoModalSubtitle");
  const undoModalNote = document.getElementById("undoModalNote");
  const undoModalTitle = document.getElementById("undoModalTitle");

  const presetCache = {};

  let activePresetName = null;
  let activePreset = null;

  let storedLastPresetName = localStorage.getItem("lastPresetName") || "";

  let undoFromPreset = "";
  let phase = "make";
  let idx = 0;
  let currentPos = "";
  let currentEntry = null;
  let currentUndoInfo = null;

  let pendingStartPresetName = "";

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
  ejectBottomBtn.addEventListener("click", () => sendBytes([213, 242, 214], "Eject bottom"));

  send251Btn.addEventListener("click", () => {
    sendBytes([251], "Trigger R&P");
  });

  function renderPreview(container, grid){
    container.innerHTML = "";
    const ROWS = 15;
    const COLS = 12;

    for(let r = 0; r < ROWS; r++){
      const row = grid[r] || [];
      for(let c = 0; c < COLS; c++){
        const ch = (row[c] || ".").toLowerCase();
        const meta = COLOR_META[ch] || COLOR_META["."];
        const d = document.createElement("div");
        d.className = "px" + (meta.css ? (" " + meta.css) : "");
        container.appendChild(d);
      }
    }
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

  async function fetchPreset(name){
    const res = await fetch("/api/preset/" + name);
    if(!res.ok) throw new Error("Failed to fetch preset " + name);
    return await res.json();
  }

  async function ensurePresetLoaded(name){
    if(presetCache[name]) return presetCache[name];
    const p = await fetchPreset(name);
    presetCache[name] = p;
    return p;
  }

  function buildPresetCard(name){
    const card = document.createElement("div");
    card.className = "card";

    const h = document.createElement("div");
    h.className = "h2";
    h.textContent = PRESET_DISPLAY[name] || name;

    const m = document.createElement("div");
    m.className = "muted";
    m.textContent = "20 cubes (5×4). Order: 1,1 → 1,4 then 2,1 → 2,4 ... 5,4";

    const wrap = document.createElement("div");
    wrap.className = "preview-wrap";

    const left = document.createElement("div");
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.textContent = "Preview 12×15";
    const preview = document.createElement("div");
    preview.className = "preview";
    preview.id = name + "Preview";
    left.appendChild(pill);
    left.appendChild(preview);

    const right = document.createElement("div");
    right.style.minWidth = "240px";

    const kpi = document.createElement("div");
    kpi.className = "kpi";
    const kpiPill = document.createElement("span");
    kpiPill.className = "pill";
    kpiPill.id = name + "Kpi";
    kpi.appendChild(kpiPill);

    if(name === "mario"){
      const last = document.createElement("span");
      last.className = "pill";
      last.id = "lastPresetPill";
      kpi.appendChild(last);
    }

    const hr = document.createElement("div");
    hr.className = "hr";

    const btn = document.createElement("button");
    btn.className = "btn";
    btn.type = "button";
    btn.textContent = "Start " + (PRESET_DISPLAY[name] || name);
    btn.addEventListener("click", () => startPreset(name));

    const note = document.createElement("div");
    note.className = "mini-note";
    note.textContent = "If you previously ran another preset, you can choose Undo (that preset) or Undo NONE before starting.";

    right.appendChild(kpi);
    right.appendChild(hr);
    right.appendChild(btn);
    right.appendChild(note);

    wrap.appendChild(left);
    wrap.appendChild(right);

    card.appendChild(h);
    card.appendChild(m);
    card.appendChild(wrap);

    return card;
  }

  function updateHomeKPIs(){
    PRESET_LIST.forEach(name => {
      const pill = document.getElementById(name + "Kpi");
      if(pill){
        const p = presetCache[name];
        const count = p ? (p.order ? p.order.length : 0) : 0;
        pill.textContent = (PRESET_DISPLAY[name] || name) + ": " + count + " cubes";
      }
    });

    const lastPresetPill = document.getElementById("lastPresetPill");
    if(lastPresetPill){
      lastPresetPill.textContent = "Last preset: " + (storedLastPresetName || "none");
    }
  }

  function openUndoModal(forPresetName){
    pendingStartPresetName = forPresetName;

    undoSelect.innerHTML = "";

    const optNone = document.createElement("option");
    optNone.value = "none";
    optNone.textContent = "Undo NONE";
    undoSelect.appendChild(optNone);

    const last = (storedLastPresetName || "").toLowerCase().trim();
    if(last && last !== forPresetName){
      const optLast = document.createElement("option");
      optLast.value = last;
      optLast.textContent = "Undo " + last.toUpperCase();
      undoSelect.appendChild(optLast);

      undoModalNote.textContent =
        "Last preset is " + last.toUpperCase() +
        ". Choose Undo " + last.toUpperCase() +
        " to run cube-by-cube UNDO before making " + forPresetName.toUpperCase() + ".";
    }else if(last && last === forPresetName){
      undoModalNote.textContent =
        "Last preset is the same (" + last.toUpperCase() + "). Undo is optional; you can also choose Undo NONE.";
    }else{
      undoModalNote.textContent = "No previous preset stored. You can start immediately.";
    }

    undoModalTitle.textContent = "Choose undo for " + (forPresetName.toUpperCase());
    undoModalSubtitle.textContent = "Select what to undo before starting " + (forPresetName.toUpperCase()) + ".";
    undoModalBackdrop.classList.add("open");
    undoModalBackdrop.setAttribute("aria-hidden", "false");
  }

  function closeUndoModal(){
    undoModalBackdrop.classList.remove("open");
    undoModalBackdrop.setAttribute("aria-hidden", "true");
    pendingStartPresetName = "";
  }

  undoCancelBtn.addEventListener("click", () => {
    logAll("UI: Undo choice canceled.");
    closeUndoModal();
  });

  undoConfirmBtn.addEventListener("click", async () => {
    const choice = (undoSelect.value || "none").toLowerCase();
    const startName = pendingStartPresetName;
    if(!startName){
      closeUndoModal();
      return;
    }

    let chosenUndo = "";
    if(choice && choice !== "none" && choice !== startName){
      chosenUndo = choice;
    }else{
      chosenUndo = "";
    }

    closeUndoModal();
    await startPresetWithUndoChoice(startName, chosenUndo);
  });

  async function startPreset(name){
    const last = (storedLastPresetName || "").toLowerCase().trim();
    if(last){
      openUndoModal(name);
      return;
    }
    await startPresetWithUndoChoice(name, "");
  }

  async function startPresetWithUndoChoice(name, undoChoice){
    activePresetName = name;
    activePreset = await ensurePresetLoaded(name);
    idx = 0;

    undoFromPreset = "";
    if(undoChoice && undoChoice !== name && storedLastPresetName === undoChoice){
      undoFromPreset = undoChoice;
      phase = "undo";
    }else{
      phase = "make";
    }

    placeLog.textContent = "";
    cubeLog.textContent = "";
    logAll("Selected preset: " + activePresetName + " (stored last: " + (storedLastPresetName || "none") + ")");
    logAll("Undo choice: " + (undoFromPreset ? ("UNDO " + undoFromPreset.toUpperCase()) : "Undo NONE"));

    await loadStep();
    show(placeSection);
    subTitle.textContent = "Page 1 · Place cube";
  }

  async function loadStep(){
    currentPos = activePreset.order[idx];
    currentEntry = activePreset.cubes[currentPos] || { moves:[], serial:[], orientation:null, notes:[] };
    currentUndoInfo = null;

    modePill.textContent = "phase: " + phase.toUpperCase();
    posPill.textContent = "cube " + currentPos;
    idxPill.textContent = "idx " + (idx+1) + " / " + activePreset.order.length;

    placeTitle.textContent = (phase === "undo")
      ? ("UNDO " + undoFromPreset.toUpperCase() + " → then MAKE " + activePresetName.toUpperCase())
      : ("MAKE " + activePresetName.toUpperCase());

    placeSub.textContent = "Page 1 · Place cube in fixture (then go to execution page)";

    if(phase === "undo"){
      if(!undoFromPreset){
        renderOrientation(null, "No undo selected.");
        currentUndoInfo = { ok:false, message:"No undo selected", undo_moves:[], undo_serial:[], undo_orientation:null };
      }else{
        const res = await fetch("/api/undo_info", {
          method:"POST",
          headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ prev_preset: undoFromPreset, pos: currentPos })
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
        logAll("Note: no orientation for this entry (might be already-solved or placeholder).");
      }
    }
  }

  function loadCubePage(){
    cubeTitle.textContent = "Cube " + currentPos;
    cubeSub.textContent = "Page 2 · Send bytes to solver (you can send multiple times)";
    cubeModePill.textContent = "phase: " + phase.toUpperCase();
    cubePosPill.textContent = "cube " + currentPos;
    cubeIdxPill.textContent = "idx " + (idx+1) + " / " + activePreset.order.length;

    let entry = currentEntry;
    let notes = entry.notes || [];
    let moves = entry.moves || [];
    let serial = entry.serial || [];

    if(phase === "undo"){
      if(currentUndoInfo && currentUndoInfo.ok){
        notes = ["UNDO of " + undoFromPreset + " at cube " + currentPos].concat(notes || []);
        moves = currentUndoInfo.undo_moves || [];
        serial = currentUndoInfo.undo_serial || [];
      }else{
        notes = ["UNDO not available for this cube. You may still use Insert/Eject, then press Next."].concat(notes || []);
        moves = [];
        serial = [];
      }
    }

    notesBox.innerHTML = (notes && notes.length) ? notes.map(n => "• " + n).join("<br>") : "(none)";
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
      phase = "make";
      await loadStep();
      show(placeSection);
      subTitle.textContent = "Page 1 · Place cube";
      logAll("Switched to MAKE for the same cube " + currentPos);
      return;
    }

    if(idx < activePreset.order.length - 1){
      idx += 1;
      phase = undoFromPreset ? "undo" : "make";
      await loadStep();
      show(placeSection);
      subTitle.textContent = "Page 1 · Place cube";
      return;
    }

    storedLastPresetName = activePresetName;
    localStorage.setItem("lastPresetName", activePresetName);
    logAll("Finished preset: " + activePresetName + ". Stored as lastPresetName.");
    updateHomeKPIs();
    show(homeSection);
    subTitle.textContent = "Home";
  }

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
    subTitle.textContent = "Page 2 · Cube execution";
  });

  backToPlaceBtn.addEventListener("click", async () => {
    show(placeSection);
    subTitle.textContent = "Page 1 · Place cube";
  });

  redoBtn.addEventListener("click", async () => {
    logAll("UI: Redo pressed. Reloading current step.");
    await loadStep();
    show(placeSection);
    subTitle.textContent = "Page 1 · Place cube";
  });

  sendBtn.addEventListener("click", doSendCurrent);
  nextBtn.addEventListener("click", nextStep);

  async function init(){
    try{
      presetCards.innerHTML = "";
      PRESET_LIST.forEach(name => presetCards.appendChild(buildPresetCard(name)));

      for(const name of PRESET_LIST){
        const p = await ensurePresetLoaded(name);
        const prev = document.getElementById(name + "Preview");
        renderPreview(prev, p.preview_15x12);
      }

      updateHomeKPIs();
      logTo(globalLog, "Ready. Detected lastPresetName: " + (storedLastPresetName || "none"));
    }catch(e){
      logTo(globalLog, "ERROR loading presets: " + e);
    }
  }

  init();
</script>
</body>
</html>
"""


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
            name = self.path.split("/")[-1].strip().lower()
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
                prev_preset = (data.get("prev_preset") or "").strip().lower()
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


def run_server(host: str = "0.0.0.0", port: int = 5000) -> None:
    server = HTTPServer((host, port), CubeHandler)
    ip = get_local_ip()
    url = f"http://{ip}:{port}"
    print_qr(url)
    print("\nServing on", url)
    print("Home: /")
    print("API:  /api/preset/<name>  where name in:", ", ".join(sorted(PRESETS.keys())))
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
