import json
import socket
import time
import glob
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from dataclasses import dataclass
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


U, R, F, D, L, B = range(6)


@dataclass(frozen=True)
class Sticker:
    x: int
    y: int
    z: int
    nx: int
    ny: int
    nz: int


sticker_to_index: Dict[Sticker, int] = {}
index_to_sticker: Dict[int, Sticker] = {}


def add_face(face: int, coord_func, normal: Tuple[int, int, int]) -> None:
    for pos in range(9):
        r, c = divmod(pos, 3)
        x, y, z = coord_func(r, c)
        nx, ny, nz = normal
        st = Sticker(x, y, z, nx, ny, nz)
        idx = face * 9 + pos
        if st in sticker_to_index:
            raise ValueError("Duplicate sticker mapping")
        sticker_to_index[st] = idx
        index_to_sticker[idx] = st


def coord_U(r, c):
    return -1 + c, 1, -1 + r


def coord_D(r, c):
    return -1 + c, -1, 1 - r


def coord_F(r, c):
    return -1 + c, 1 - r, 1


def coord_B(r, c):
    return 1 - c, 1 - r, -1


def coord_R(r, c):
    return 1, 1 - r, 1 - c


def coord_L(r, c):
    return -1, 1 - r, -1 + c


add_face(U, coord_U, (0, 1, 0))
add_face(D, coord_D, (0, -1, 0))
add_face(F, coord_F, (0, 0, 1))
add_face(B, coord_B, (0, 0, -1))
add_face(R, coord_R, (1, 0, 0))
add_face(L, coord_L, (-1, 0, 0))


def rot_z_cw(x, y, z):
    return y, -x, z


def rot_z_ccw(x, y, z):
    return -y, x, z


def rot_x_cw(x, y, z):
    return x, z, -y


def rot_x_ccw(x, y, z):
    return x, -z, y


def rot_y_cw(x, y, z):
    return z, y, -x


def rot_y_ccw(x, y, z):
    return -z, y, x


def make_perm(layer_cond, rot_func) -> List[int]:
    perm = list(range(54))
    for idx, st in index_to_sticker.items():
        if layer_cond(st):
            x2, y2, z2 = rot_func(st.x, st.y, st.z)
            nx2, ny2, nz2 = rot_func(st.nx, st.ny, st.nz)
            st2 = Sticker(x2, y2, z2, nx2, ny2, nz2)
            j = sticker_to_index[st2]
            perm[idx] = j
    return perm


def invert_perm(p: List[int]) -> List[int]:
    q = [0] * len(p)
    for i, j in enumerate(p):
        q[j] = i
    return q


perm_F_cw = make_perm(lambda st: st.z == 1, rot_z_cw)
perm_B_cw = make_perm(lambda st: st.z == -1, rot_z_ccw)
perm_R_cw = make_perm(lambda st: st.x == 1, rot_x_cw)
perm_L_cw = make_perm(lambda st: st.x == -1, rot_x_ccw)
perm_D_cw = make_perm(lambda st: st.y == -1, rot_y_ccw)

perm_F_ccw = invert_perm(perm_F_cw)
perm_B_ccw = invert_perm(perm_B_cw)
perm_R_ccw = invert_perm(perm_R_cw)
perm_L_ccw = invert_perm(perm_L_cw)
perm_D_ccw = invert_perm(perm_D_cw)


MOVE_PERMS: Dict[str, List[int]] = {
    'F': perm_F_cw,
    "F'": perm_F_ccw,
    'B': perm_B_cw,
    "B'": perm_B_ccw,
    'R': perm_R_cw,
    "R'": perm_R_ccw,
    'L': perm_L_cw,
    "L'": perm_L_ccw,
    'D': perm_D_cw,
    "D'": perm_D_ccw,
}

INV_MOVE: Dict[str, str] = {
    'F': "F'", "F'": 'F',
    'B': "B'", "B'": 'B',
    'R': "R'", "R'": 'R',
    'L': "L'", "L'": 'L',
    'D': "D'", "D'": 'D',
}

U_FACE_IDX = [U * 9 + i for i in range(9)]


def apply_perm(state: str, perm: List[int]) -> str:
    return ''.join(state[perm[i]] for i in range(54))


ORIENTATIONS: List[Dict[str, str]] = [
    {'B': 'b', 'D': 'y', 'F': 'g', 'L': 'o', 'R': 'r', 'U': 'w'},
    {'B': 'g', 'D': 'w', 'F': 'b', 'L': 'o', 'R': 'r', 'U': 'y'},
    {'B': 'g', 'D': 'y', 'F': 'b', 'L': 'r', 'R': 'o', 'U': 'w'},
    {'B': 'b', 'D': 'w', 'F': 'g', 'L': 'r', 'R': 'o', 'U': 'y'},
    {'B': 'w', 'D': 'b', 'F': 'y', 'L': 'o', 'R': 'r', 'U': 'g'},
    {'B': 'y', 'D': 'g', 'F': 'w', 'L': 'o', 'R': 'r', 'U': 'b'},
    {'B': 'y', 'D': 'b', 'F': 'w', 'L': 'r', 'R': 'o', 'U': 'g'},
    {'B': 'w', 'D': 'g', 'F': 'y', 'L': 'r', 'R': 'o', 'U': 'b'},
    {'B': 'g', 'D': 'o', 'F': 'b', 'L': 'y', 'R': 'w', 'U': 'r'},
    {'B': 'b', 'D': 'r', 'F': 'g', 'L': 'y', 'R': 'w', 'U': 'o'},
    {'B': 'b', 'D': 'o', 'F': 'g', 'L': 'w', 'R': 'y', 'U': 'r'},
    {'B': 'g', 'D': 'r', 'F': 'b', 'L': 'w', 'R': 'y', 'U': 'o'},
    {'B': 'o', 'D': 'b', 'F': 'r', 'L': 'y', 'R': 'w', 'U': 'g'},
    {'B': 'r', 'D': 'g', 'F': 'o', 'L': 'y', 'R': 'w', 'U': 'b'},
    {'B': 'r', 'D': 'b', 'F': 'o', 'L': 'w', 'R': 'y', 'U': 'g'},
    {'B': 'o', 'D': 'g', 'F': 'r', 'L': 'w', 'R': 'y', 'U': 'b'},
    {'B': 'y', 'D': 'o', 'F': 'w', 'L': 'b', 'R': 'g', 'U': 'r'},
    {'B': 'w', 'D': 'r', 'F': 'y', 'L': 'b', 'R': 'g', 'U': 'o'},
    {'B': 'w', 'D': 'o', 'F': 'y', 'L': 'g', 'R': 'b', 'U': 'r'},
    {'B': 'y', 'D': 'r', 'F': 'w', 'L': 'g', 'R': 'b', 'U': 'o'},
    {'B': 'r', 'D': 'y', 'F': 'o', 'L': 'b', 'R': 'g', 'U': 'w'},
    {'B': 'o', 'D': 'w', 'F': 'r', 'L': 'b', 'R': 'g', 'U': 'y'},
    {'B': 'o', 'D': 'y', 'F': 'r', 'L': 'g', 'R': 'b', 'U': 'w'},
    {'B': 'r', 'D': 'w', 'F': 'o', 'L': 'g', 'R': 'b', 'U': 'y'},
]


def build_state_for_orientation(ori: Dict[str, str]) -> str:
    colors_by_face = {
        U: ori['U'],
        R: ori['R'],
        F: ori['F'],
        D: ori['D'],
        L: ori['L'],
        B: ori['B'],
    }
    s: List[str] = []
    for face in range(6):
        s.extend([colors_by_face[face]] * 9)
    return ''.join(s)


def up_matches(state: str, target_face: List[List[str]]) -> bool:
    for pos in range(9):
        if state[U_FACE_IDX[pos]] != target_face[pos // 3][pos % 3]:
            return False
    return True


ALLOWED_MOVES = ['F', "F'", 'B', "B'", 'R', "R'", 'L', "L'", 'D', "D'"]
MAX_DEPTH_DEFAULT = 40


def solve_u_mural(
    target_face: List[List[str]],
    max_depth: int = MAX_DEPTH_DEFAULT
) -> Tuple[Optional[List[str]], Optional[Dict[str, str]], int]:

    center_color = target_face[1][1]
    best_moves: Optional[List[str]] = None
    best_ori: Optional[Dict[str, str]] = None

    candidates = [o for o in ORIENTATIONS if o['U'] == center_color]
    if not candidates:
        return None, None, max_depth

    for ori in candidates:
        init_state = build_state_for_orientation(ori)

        if up_matches(init_state, target_face):
            if best_moves is None or 0 < len(best_moves):
                best_moves = []
                best_ori = ori
            continue

        visited_cache = {}

        def dfs(state: str, depth: int, last_move: Optional[str]) -> Optional[List[str]]:
            key = (state, depth, last_move)
            if key in visited_cache:
                return None
            visited_cache[key] = True

            if depth == 0:
                return None

            for m in ALLOWED_MOVES:
                if last_move is not None:
                    if INV_MOVE[last_move] == m:
                        continue
                    if last_move[0] == m[0]:
                        continue

                new_state = apply_perm(state, MOVE_PERMS[m])

                if up_matches(new_state, target_face):
                    return [m]

                if depth > 1:
                    res = dfs(new_state, depth - 1, m)
                    if res is not None:
                        return [m] + res

            return None

        for d in range(1, max_depth + 1):
            visited_cache.clear()
            res = dfs(init_state, d, None)
            if res is not None:
                if best_moves is None or len(res) < len(best_moves):
                    best_moves = res
                    best_ori = ori
                break

    return best_moves, best_ori, max_depth


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


def compute_solution(grid: List[List[str]]) -> Dict[str, object]:
    if len(grid) != 3 or any(len(row) != 3 for row in grid):
        return {
            "moves": [],
            "serial": [],
            "orientation": None,
            "elapsed": 0.0,
            "message": "Grid must be 3×3.",
        }

    face = [[str(c).lower() for c in row] for row in grid]
    valid = {'r', 'o', 'b', 'g', 'w', 'y'}
    for r in range(3):
        for c in range(3):
            if face[r][c] not in valid:
                return {
                    "moves": [],
                    "serial": [],
                    "orientation": None,
                    "elapsed": 0.0,
                    "message": (
                        f"Invalid color '{face[r][c]}' at ({r+1},{c+1}). "
                        "Use r/o/b/g/w/y."
                    ),
                }

    msg_prefix = (
        "Solving U (top) face from a solved cube whose Up center color "
        "matches your pattern. Shorter sequences are preferred; "
        "search depth is limited.\n"
    )

    t0 = time.time()
    moves, ori_used, depth_limit = solve_u_mural(face, max_depth=MAX_DEPTH_DEFAULT)
    elapsed = time.time() - t0

    if moves is None or ori_used is None:
        return {
            "moves": [],
            "serial": [],
            "orientation": None,
            "elapsed": elapsed,
            "message": (
                msg_prefix
                + "Pattern is NOT solvable from a real solved cube using R/L/F/B/D moves "
                  "within the current search depth. It is treated as ILLEGAL. "
                  f"(Search depth limit = {depth_limit}.)"
            ),
        }

    serial_cmds = moves_to_serial(moves)

    return {
        "moves": moves,
        "serial": serial_cmds,
        "orientation": ori_used,
        "elapsed": elapsed,
        "message": msg_prefix + f"Found solution with {len(moves)} moves.",
    }


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


def wait_for_done(serials, log: List[str], required_dones: int = 3) -> None:
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
                raise ValueError(f"Command {cmd} out of byte range")

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

            wait_for_done(serials, log, required_dones=3)
            time.sleep(0.05)

        log.append("All commands completed.")
        print("\nAll commands completed.")

        t0 = time.time()
        while time.time() - t0 < 2:
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


def run_manual_motor_command(cmd_raw: object) -> Dict[str, object]:
    log: List[str] = []

    if not HAS_SERIAL:
        err = "pyserial is not installed on this system."
        log.append(err)
        return {"ok": False, "log": log, "error": err}

    cmd = _coerce_cmd_to_int(cmd_raw)
    if cmd is None:
        err = f"Manual command must be an integer. Got: {cmd_raw!r}"
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
        for s in serials:
            try:
                msgs = read_all_available(s)
                for m in msgs:
                    line = f"{s.port}: {m}"
                    log.append(line)
                    print("   ", line)
            except Exception:
                pass

        if 0 <= cmd <= 255:
            payload_desc = f"byte:{cmd}"
            data = bytes([cmd])
        else:
            payload_desc = f"ascii:{cmd}"
            data = (str(cmd) + "\n").encode("utf-8")

        for s in serials:
            s.write(data)

        log.append(f"Sent manual command ({payload_desc})")
        print("\nSent manual command:", cmd, f"({payload_desc})")

        t0 = time.time()
        while time.time() - t0 < 0.8:
            for s in serials:
                msgs = read_all_available(s)
                for m in msgs:
                    line = f"{s.port}: {m}"
                    log.append(line)
                    print("   ", line)
            time.sleep(0.05)

        return {"ok": True, "log": log, "error": ""}

    except Exception as e:
        err = f"Error while sending manual command: {e}"
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


HTML_PAGE = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Cube U-Face Mural Solver</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #f3f4f6;
      --card-bg: #ffffff;
      --border: #d1d5db;
      --text: #111827;
      --muted: #6b7280;
      --accent: #2563eb;
      --error: #b91c1c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .shell {
      max-width: 780px;
      margin: 0 auto;
      padding: 16px;
    }
    .card {
      background: var(--card-bg);
      border-radius: 6px;
      border: 1px solid var(--border);
      padding: 16px;
      box-shadow: 0 10px 25px rgba(15,23,42,0.04);
    }
    h1 {
      margin: 0 0 6px;
      font-size: 18px;
    }
    p {
      margin: 0 0 10px;
      font-size: 13px;
      color: var(--muted);
    }
    .step-block {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid #e5e7eb;
    }
    .step-title {
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 6px;
    }
    .section-title {
      font-size: 13px;
      font-weight: 600;
      margin-top: 8px;
      margin-bottom: 4px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      max-width: 260px;
      margin: 10px 0;
    }
    .cell {
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: 4px;
      border: 1px solid var(--border);
      cursor: pointer;
      background: #ffffff;
      transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .cell.selected {
      box-shadow: 0 0 0 2px var(--accent);
      border-color: var(--accent);
    }
    .mini-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 4px;
      max-width: 160px;
      margin: 6px 0;
    }
    .mini-cell {
      width: 100%;
      aspect-ratio: 1 / 1;
      border-radius: 3px;
      border: 1px solid var(--border);
      background: #ffffff;
    }
    .palette {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 6px 0 4px;
    }
    .swatch {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      border: 2px solid transparent;
      cursor: pointer;
      box-shadow: 0 0 0 1px rgba(0,0,0,0.1);
      padding: 0;
      position: relative;
    }
    .swatch.active {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(37,99,235,0.4);
    }
    .row {
      margin-top: 10px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      font-size: 12px;
      color: var(--muted);
    }
    button {
      border-radius: 4px;
      border: 1px solid var(--accent);
      padding: 6px 12px;
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      font-size: 13px;
    }
    button.secondary {
      border-color: var(--border);
      background: #ffffff;
      color: var(--text);
    }
    button.danger {
      border-color: #ef4444;
      background: #ef4444;
      color: #ffffff;
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    pre {
      background: #f9fafb;
      border-radius: 4px;
      border: 1px solid var(--border);
      padding: 8px;
      font-size: 12px;
      overflow-x: auto;
      margin: 6px 0 0;
    }
    .hidden {
      display: none;
    }
    .progress {
      margin-top: 6px;
      font-size: 11px;
      color: var(--muted);
    }
    .progress-bar {
      width: 100%;
      height: 6px;
      border-radius: 999px;
      background: #e5e7eb;
      overflow: hidden;
      margin-top: 4px;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: var(--accent);
      transition: width 0.2s linear;
    }
    .orientation-box {
      margin-top: 6px;
      padding: 8px;
      border-radius: 4px;
      border: 1px solid var(--border);
      background: #f9fafb;
      font-size: 13px;
    }
    .orientation-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 2px 0;
    }
    .orientation-swatch {
      width: 16px;
      height: 16px;
      border-radius: 3px;
      border: 1px solid #9ca3af;
      flex-shrink: 0;
    }
    .c-r { background: #ff0000; }
    .c-o { background: #ffa500; }
    .c-b { background: #0000ff; }
    .c-g { background: #00ff00; }
    .c-w { background: #ffffff; }
    .c-y { background: #ffff00; }
    .hint-small {
      font-size: 11px;
      color: var(--muted);
      margin-top: 4px;
    }
    .stack {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .error-text {
      color: var(--error);
    }
    .page {
      margin-top: 8px;
    }

    .settings-fab {
      position: fixed;
      top: 12px;
      right: 12px;
      z-index: 1500;
      border-radius: 999px;
      padding: 8px 12px;
      border: 1px solid var(--border);
      background: #ffffff;
      color: var(--text);
      box-shadow: 0 10px 25px rgba(15,23,42,0.10);
      cursor: pointer;
      font-size: 13px;
    }
    .settings-fab:hover {
      box-shadow: 0 12px 28px rgba(15,23,42,0.14);
    }

    /* FIX: make overlay reliably clickable and above page content */
    .settings-overlay {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.35);
      z-index: 2400;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 56px 16px 16px;
      pointer-events: auto;
    }
    .settings-overlay.hidden { display: none; }

    .settings-panel {
      width: 100%;
      max-width: 780px;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      box-shadow: 0 20px 40px rgba(15,23,42,0.22);
      padding: 14px;
      pointer-events: auto;
    }

    .settings-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }
    .settings-title {
      font-size: 13px;
      font-weight: 700;
      color: var(--text);
      margin: 0;
    }
    .settings-sub {
      font-size: 12px;
      color: var(--muted);
      margin: 2px 0 0;
    }
    .settings-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin-top: 8px;
    }
    @media (min-width: 620px){
      .settings-grid {
        grid-template-columns: 1fr 1fr;
      }
    }
    .settings-card {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      background: #fafafa;
    }
    .settings-card h3 {
      margin: 0 0 6px;
      font-size: 13px;
    }
    .btn-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .btn-row button {
      border-radius: 6px;
      padding: 7px 10px;
      font-size: 13px;
    }
    .btn-row button.secondary {
      background: #ffffff;
    }
    .log-wrap {
      margin-top: 10px;
    }
    .tiny-note {
      font-size: 11px;
      color: var(--muted);
      margin-top: 6px;
    }
  </style>
</head>
<body>

<button id="settingsFab" class="settings-fab" type="button">⚙ Settings</button>

<div id="settingsOverlay" class="settings-overlay hidden" aria-hidden="true">
  <div id="settingsPanel" class="settings-panel" role="dialog" aria-modal="true">
    <div class="settings-header">
      <div>
        <div class="settings-title">Settings · Manual Motor Control</div>
        <div class="settings-sub">These buttons send integer denotation codes to the Arduinos.</div>
      </div>
      <button id="closeSettingsBtn" type="button" class="secondary">Close</button>
    </div>

    <div class="settings-grid">
      <div class="settings-card">
        <h3>RL pulley motor</h3>
        <div class="btn-row">
          <button type="button" class="secondary" data-manualcmd="252">IN (252)</button>
          <button type="button" class="secondary" data-manualcmd="251">OUT (251)</button>
        </div>
        <div class="tiny-note">Sends 252 for IN, 251 for OUT.</div>
      </div>

      <div class="settings-card">
        <h3>FB pulley motor</h3>
        <div class="btn-row">
          <button type="button" class="secondary" data-manualcmd="231">IN (231)</button>
          <button type="button" class="secondary" data-manualcmd="232">OUT (232)</button>
        </div>
        <div class="tiny-note">Sends 231 for IN, 232 for OUT.</div>
      </div>

      <div class="settings-card">
        <h3>Bottom motor motor</h3>
        <div class="btn-row">
          <button type="button" class="secondary" data-manualcmd="231">IN (231)</button>
          <button type="button" class="secondary" data-manualcmd="232">OUT (232)</button>
        </div>
        <div class="tiny-note">Sends 241 for IN, 242 for OUT.</div>
      </div>

      <div class="settings-card">
        <h3>DC rack-and-pinion</h3>
        <div class="btn-row">
          <button type="button" class="secondary" data-manualcmd="300">RUN (300)</button>
        </div>
        <div class="tiny-note">Sends 300.</div>
      </div>
    </div>

    <div class="log-wrap">
      <div class="section-title">Manual command log</div>
      <pre id="settingsLogPre"></pre>
      <div class="tiny-note">This shows the same Arduino log lines you already print on the server.</div>
    </div>
  </div>
</div>

<div class="shell">
  <div class="card">

    <h1>Cube U-Face Mural Solver</h1>
    <p>
      Draw ANY 3×3 pattern for the top (U) face using cube colors.
    </p>

    <div id="page1" class="page">
      <div class="step-block">
        <div class="step-title">Page 1 · Draw the U face</div>

        <p id="hintText">
          Click a sticker to select it, then choose a color from the palette.
        </p>

        <div class="section-title">Choose color for the selected sticker</div>
        <div class="palette" id="palette"></div>

        <div class="section-title">Paint the 3×3 U face</div>
        <div class="grid" id="grid"></div>

        <div class="row">
          <div id="legalStatus">
            Draw any pattern you like. The solver will check solvability on the next page.
          </div>
          <button id="toPage2Btn">Next: configure solver</button>
        </div>
      </div>
    </div>

    <div id="page2" class="page hidden">
      <div class="step-block">
        <div class="step-title">Page 2 · Run the solver search</div>
        <p>
          When you start, the solver will search for a sequence of moves that
          draws your U-face mural using R/L/F/B/D turns.
        </p>

        <button id="startSolveBtn">Start solver</button>

        <div class="progress hidden" id="solveProgress">
          <div id="solveLabel">Solver running...</div>
          <div class="progress-bar">
            <div class="progress-fill" id="solveFill"></div>
          </div>
        </div>

        <p id="solveStatus">Solver not started yet.</p>

        <button id="toPage3Btn" class="secondary" disabled>Next: place cube</button>
      </div>
    </div>

    <div id="page3" class="page hidden">
      <div class="step-block">
        <div class="step-title">Page 3 · Place the cube</div>
        <p>
          Place the cube in the fixture so each face center matches the colors
          below. The Up (U) face is the mural face you drew.
        </p>

        <div class="orientation-box" id="orientationBox">
          <em>Orientation will appear after the solver finishes.</em>
        </div>
        <div class="hint-small">
          Centers: match these colors exactly on the cube before continuing.
        </div>

        <div class="section-title" style="margin-top:10px;">Original U-face pattern you drew</div>
        <div class="mini-grid" id="patternPreview"></div>

        <div class="hint-small">
          This 3×3 pattern is the U (top) face the solver will draw on your cube.
        </div>

        <div class="row" style="margin-top:12px;">
          <div>When the cube is placed correctly, continue to the physical solver.</div>
          <button id="toPage4Btn" class="secondary">Next: run solver</button>
        </div>
      </div>
    </div>

    <div id="page4" class="page hidden">
      <div class="step-block">
        <div class="step-title">Page 4 · Run the physical solver and finish</div>
        <p>
          The solver is ready to send moves to the cube. Make sure the cube is
          placed according to the previous page, then send the commands.
          When the solver is done, carefully remove the cube and go back to
          the drawing page to design a new mural.
        </p>

        <div class="section-title" style="margin-top:10px;">Moves and serial commands</div>
        <pre id="movesPre"></pre>
        <pre id="serialPre"></pre>

        <div class="section-title" style="margin-top:10px;">Run the physical solver</div>
        <div class="stack">
          <button id="runBtn" disabled>Send commands to solver</button>
        </div>

        <div class="progress hidden" id="runProgress">
          <div id="runLabel">Running commands on solver...</div>
          <div class="progress-bar">
            <div class="progress-fill" id="runFill"></div>
          </div>
        </div>

        <pre id="solverLogPre" class="hidden"></pre>

        <div class="row" style="margin-top:12px;">
          <div>After the solver finishes and you remove the cube, go back to draw a new mural.</div>
          <button id="backToStartBtn" class="secondary">Back to drawing page</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
  const COLORS = {
    r: "#ff0000",
    o: "#ffa500",
    b: "#0000ff",
    g: "#00ff00",
    w: "#ffffff",
    y: "#ffff00",
  };

  const COLOR_META = {
    r: { name: "Red",    css: "c-r" },
    o: { name: "Orange", css: "c-o" },
    b: { name: "Blue",   css: "c-b" },
    g: { name: "Green",  css: "c-g" },
    w: { name: "White",  css: "c-w" },
    y: { name: "Yellow", css: "c-y" },
  };

  const FACE_LABELS = {
    U: "Up (U)",
    L: "Left (L)",
    F: "Front (F)",
    R: "Right (R)",
    B: "Back (B)",
    D: "Down (D)",
  };

  const paletteOrder = ["r","o","b","g","w","y"];

  const page1 = document.getElementById("page1");
  const page2 = document.getElementById("page2");
  const page3 = document.getElementById("page3");
  const page4 = document.getElementById("page4");

  const toPage2Btn = document.getElementById("toPage2Btn");
  const startSolveBtn = document.getElementById("startSolveBtn");
  const toPage3Btn = document.getElementById("toPage3Btn");
  const toPage4Btn = document.getElementById("toPage4Btn");
  const backToStartBtn = document.getElementById("backToStartBtn");

  const paletteEl = document.getElementById("palette");
  const gridEl = document.getElementById("grid");

  const solveProgress  = document.getElementById("solveProgress");
  const solveFill      = document.getElementById("solveFill");
  const solveLabel     = document.getElementById("solveLabel");
  const solveStatus    = document.getElementById("solveStatus");

  const orientationBox = document.getElementById("orientationBox");
  const patternPreview = document.getElementById("patternPreview");

  const movesPre       = document.getElementById("movesPre");
  const serialPre      = document.getElementById("serialPre");
  const runBtn         = document.getElementById("runBtn");
  const runProgress    = document.getElementById("runProgress");
  const runFill        = document.getElementById("runFill");
  const runLabel       = document.getElementById("runLabel");
  const solverLogPre   = document.getElementById("solverLogPre");

  const settingsFab = document.getElementById("settingsFab");
  const settingsOverlay = document.getElementById("settingsOverlay");
  const settingsPanel = document.getElementById("settingsPanel");
  const closeSettingsBtn = document.getElementById("closeSettingsBtn");
  const settingsLogPre = document.getElementById("settingsLogPre");

  const cells = [];
  const swatches = {};
  const patternCells = [];
  let selectedCell = null;
  let centerColor = "w";
  let runInterval = null;
  let currentSerial = [];
  let lastPattern = null;

  function showPage(pageId) {
    [page1, page2, page3, page4].forEach(p => p.classList.add("hidden"));
    document.getElementById(pageId).classList.remove("hidden");
  }

  function setActiveSwatch(color) {
    Object.entries(swatches).forEach(([c, btn]) => {
      if (c === color) btn.classList.add("active");
      else btn.classList.remove("active");
    });
  }

  function selectCell(cell) {
    if (selectedCell) selectedCell.classList.remove("selected");
    selectedCell = cell;
    selectedCell.classList.add("selected");
  }

  function handleColorClick(color) {
    if (!selectedCell) return;

    const r = parseInt(selectedCell.dataset.r, 10);
    const c = parseInt(selectedCell.dataset.c, 10);

    if (r === 1 && c === 1 && color !== centerColor) {
      centerColor = color;
    }

    selectedCell.dataset.color = color;
    selectedCell.style.background = COLORS[color];
    setActiveSwatch(color);
  }

  function getGridColors() {
    const g = [];
    for (let r = 0; r < 3; r++) {
      const row = [];
      for (let c = 0; c < 3; c++) {
        row.push(cells[r][c].dataset.color);
      }
      g.push(row);
    }
    return g;
  }

  function updatePatternPreview() {
    if (!lastPattern) return;
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        const color = lastPattern[r][c];
        patternCells[r][c].style.background = COLORS[color] || "#ffffff";
      }
    }
  }

  function appendLogLines(lines) {
    if (!Array.isArray(lines) || lines.length === 0) return;

    const text = lines.join("\n") + "\n";

    if (settingsLogPre) {
      settingsLogPre.textContent = (settingsLogPre.textContent || "") + text;
      settingsLogPre.scrollTop = settingsLogPre.scrollHeight;
    }
    if (solverLogPre && !solverLogPre.classList.contains("hidden")) {
      solverLogPre.textContent = (solverLogPre.textContent || "") + text;
      solverLogPre.scrollTop = solverLogPre.scrollHeight;
    }
  }

  function openSettings() {
    settingsOverlay.classList.remove("hidden");
    settingsOverlay.setAttribute("aria-hidden", "false");
  }

  function closeSettings() {
    settingsOverlay.classList.add("hidden");
    settingsOverlay.setAttribute("aria-hidden", "true");
  }

  settingsFab.addEventListener("click", openSettings);
  closeSettingsBtn.addEventListener("click", closeSettings);

  /* FIX: overlay always closes on background click */
  settingsOverlay.addEventListener("click", () => closeSettings());

  /* FIX: panel should NOT close overlay when clicking inside it */
  settingsPanel.addEventListener("click", (e) => {
    e.stopPropagation();
  });

  /* FIX: ESC closes settings */
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !settingsOverlay.classList.contains("hidden")) {
      closeSettings();
    }
  });

  document.querySelectorAll("[data-manualcmd]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();

      const cmdStr = btn.getAttribute("data-manualcmd");
      const cmd = parseInt(cmdStr, 10);
      if (!Number.isFinite(cmd)) return;

      const oldText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Sending...";

      try {
        const res = await fetch("/manual_cmd", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cmd })
        });
        const data = await res.json();

        appendLogLines([`UI: Manual command ${cmd} -> ${data.ok ? "OK" : "ERROR"}`]);
        if (Array.isArray(data.log)) appendLogLines(data.log);
        if (data.error) appendLogLines([`ERROR: ${data.error}`]);

      } catch (err) {
        console.error(err);
        appendLogLines([`UI ERROR: Failed to send manual command ${cmd}`]);
      } finally {
        btn.disabled = false;
        btn.textContent = oldText;
      }
    });
  });

  paletteOrder.forEach(c => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "swatch";
    btn.style.background = COLORS[c];
    btn.onclick = () => handleColorClick(c);
    paletteEl.appendChild(btn);
    swatches[c] = btn;
  });

  for (let r = 0; r < 3; r++) {
    cells[r] = [];
    for (let c = 0; c < 3; c++) {
      const div = document.createElement("div");
      div.className = "cell";
      div.dataset.r = r;
      div.dataset.c = c;
      div.dataset.color = "w";
      div.style.background = COLORS["w"];
      div.onclick = () => selectCell(div);
      gridEl.appendChild(div);
      cells[r][c] = div;
    }
  }

  for (let r = 0; r < 3; r++) {
    patternCells[r] = [];
    for (let c = 0; c < 3; c++) {
      const d = document.createElement("div");
      d.className = "mini-cell";
      d.style.background = COLORS["w"];
      patternPreview.appendChild(d);
      patternCells[r][c] = d;
    }
  }

  centerColor = "w";
  selectCell(cells[1][1]);
  setActiveSwatch("w");

  toPage2Btn.onclick = () => showPage("page2");

  let solveIntervalRef = null;

  startSolveBtn.onclick = async () => {
    solveStatus.classList.remove("error-text");

    const grid = getGridColors();
    lastPattern = grid;
    updatePatternPreview();

    solveStatus.textContent = "Solver is running on the server...";
    solveProgress.classList.remove("hidden");
    solveFill.style.width = "0%";
    solveLabel.textContent = "Solver search in progress...";
    let prog = 5;
    solveFill.style.width = prog + "%";
    if (solveIntervalRef) clearInterval(solveIntervalRef);
    solveIntervalRef = setInterval(() => {
      if (prog < 90) {
        prog += 5;
        solveFill.style.width = prog + "%";
      }
    }, 300);

    startSolveBtn.disabled = true;
    toPage3Btn.disabled = true;

    try {
      const res = await fetch("/solve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grid })
      });
      const data = await res.json();

      if (solveIntervalRef) clearInterval(solveIntervalRef);
      solveFill.style.width = "100%";
      if (typeof data.elapsed === "number") {
        solveLabel.textContent =
          `Solver finished in ${data.elapsed.toFixed(2)} s (search depth ≤ ${data.depth_limit || 10}).`;
      } else {
        solveLabel.textContent = "Solver run complete.";
      }

      const isIllegal = !data.orientation;

      solveStatus.textContent = data.message || (isIllegal
        ? "Pattern is not solvable from a solved cube. It is treated as illegal."
        : "Solver finished.");

      if (isIllegal) solveStatus.classList.add("error-text");
      else solveStatus.classList.remove("error-text");

      movesPre.textContent = data.moves && data.moves.length
        ? "Moves:\n" + data.moves.join(" ")
        : (isIllegal ? "No moves: pattern is illegal / not solvable." : "No moves needed.");

      serialPre.textContent = data.serial && data.serial.length
        ? "Serial commands:\n" + data.serial.join("\n")
        : (isIllegal ? "" : "No serial commands.");

      currentSerial = Array.isArray(data.serial) ? data.serial : [];

      if (data.orientation) renderOrientation(data.orientation);
      else orientationBox.innerHTML = "<em>Pattern is not solvable / illegal, so no orientation is available.</em>";

      if (!isIllegal && data.moves && data.moves.length >= 0) toPage3Btn.disabled = false;
      else toPage3Btn.disabled = true;

    } catch (err) {
      console.error(err);
      if (solveIntervalRef) clearInterval(solveIntervalRef);
      solveFill.style.width = "0%";
      solveLabel.textContent = "Error while solving.";
      solveStatus.textContent = "Error contacting solver.";
      solveStatus.classList.add("error-text");
    } finally {
      startSolveBtn.disabled = false;
    }
  };

  toPage3Btn.onclick = () => showPage("page3");

  function renderOrientation(o) {
    const faces = ["U","L","F","R","B","D"];
    let html = "";
    faces.forEach(face => {
      const col = o[face];
      const meta = COLOR_META[col] || {name: "?", css: ""};
      const label = FACE_LABELS[face] || face;
      const symbol = col ? col.toUpperCase() : "?";
      html += `
        <div class="orientation-row">
          <span class="orientation-swatch ${meta.css}"></span>
          <span>${label}: ${meta.name} (${symbol})</span>
        </div>
      `;
    });
    orientationBox.innerHTML = html;
  }

  toPage4Btn.onclick = () => {
    if (!currentSerial || !currentSerial.length) {
      alert("No solver commands are available yet. Make sure the solver finished successfully.");
      return;
    }
    runBtn.disabled = false;
    runProgress.classList.add("hidden");
    runFill.style.width = "0%";
    runLabel.textContent = "Running commands on solver...";
    solverLogPre.classList.add("hidden");
    solverLogPre.textContent = "";
    showPage("page4");
  };

  runBtn.onclick = async () => {
    if (!currentSerial || !currentSerial.length) {
      alert("No serial commands to send from the solver.");
      return;
    }

    runBtn.disabled = true;
    solverLogPre.classList.remove("hidden");
    solverLogPre.textContent = "";
    runProgress.classList.remove("hidden");
    runFill.style.width = "0%";
    runLabel.textContent = "Running commands on solver...";

    let prog = 5;
    runFill.style.width = prog + "%";
    if (runInterval) clearInterval(runInterval);
    runInterval = setInterval(() => {
      if (prog < 90) {
        prog += 3;
        runFill.style.width = prog + "%";
      }
    }, 400);

    try {
      const res = await fetch("/run_robot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ serial: currentSerial })
      });
      const data = await res.json();

      if (runInterval) clearInterval(runInterval);
      runFill.style.width = "100%";

      if (data.ok) runLabel.textContent = "Solver run complete. The cube mural should now be drawn.";
      else runLabel.textContent = "Solver run finished with an error.";

      if (Array.isArray(data.log)) {
        solverLogPre.textContent = data.log.join("\n");
      } else if (data.error) {
        solverLogPre.textContent = data.error;
      }

    } catch (err) {
      console.error(err);
      if (runInterval) clearInterval(runInterval);
      runFill.style.width = "0%";
      runLabel.textContent = "Error talking to solver.";
      solverLogPre.textContent = "Error contacting /run_robot.";
    } finally {
      runBtn.disabled = false;
    }
  };

  backToStartBtn.onclick = () => {
    centerColor = "w";
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        const cell = cells[r][c];
        cell.dataset.color = "w";
        cell.style.background = COLORS["w"];
      }
    }
    selectCell(cells[1][1]);
    setActiveSwatch("w");

    lastPattern = null;
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        patternCells[r][c].style.background = COLORS["w"];
      }
    }

    solveProgress.classList.add("hidden");
    solveFill.style.width = "0%";
    solveLabel.textContent = "Solver running...";
    solveStatus.textContent = "Solver not started yet.";
    solveStatus.classList.remove("error-text");
    toPage3Btn.disabled = true;
    movesPre.textContent = "";
    serialPre.textContent = "";
    orientationBox.innerHTML = "<em>Orientation will appear after the solver finishes.</em>";
    runProgress.classList.add("hidden");
    runFill.style.width = "0%";
    runLabel.textContent = "Running commands on solver...";
    solverLogPre.classList.add("hidden");
    solverLogPre.textContent = "";
    runBtn.disabled = true;
    currentSerial = [];

    showPage("page1");
  };

  showPage("page1");
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
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        else:
            self._set_headers(404, "text/plain; charset=utf-8")
            self.wfile.write(b"Not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        if self.path == "/solve":
            try:
                data = json.loads(body.decode("utf-8"))
                grid = data.get("grid")
                sol = compute_solution(grid)

                sol["depth_limit"] = MAX_DEPTH_DEFAULT

                ori = sol.get("orientation")
                if ori is not None:
                    sol["orientation"] = {
                        "U": ori["U"],
                        "D": ori["D"],
                        "F": ori["F"],
                        "B": ori["B"],
                        "R": ori["R"],
                        "L": ori["L"],
                    }

                self._set_headers(200, "application/json; charset=utf-8")
                self.wfile.write(json.dumps(sol).encode("utf-8"))

                print("\n=== New /solve request ===")
                print("U-face grid:")
                if isinstance(grid, list):
                    for row in grid:
                        print(" ", row)
                print("Moves:", sol.get("moves"))
                print("Serial:", sol.get("serial"))
                print("Orientation:", sol.get("orientation"))
                print("Elapsed (s):", sol.get("elapsed"))

            except Exception as e:
                print("Error in /solve:", e)
                self._set_headers(500, "application/json; charset=utf-8")
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif self.path == "/run_robot":
            try:
                data = json.loads(body.decode("utf-8"))
                serial_list = data.get("serial") or []
                print("\n=== New /run_robot request ===")
                print("Commands:", serial_list)

                result = run_serial_commands(serial_list)

                self._set_headers(200, "application/json; charset=utf-8")
                self.wfile.write(json.dumps(result).encode("utf-8"))

            except Exception as e:
                print("Error in /run_robot:", e)
                self._set_headers(500, "application/json; charset=utf-8")
                self.wfile.write(json.dumps({"ok": False, "log": [], "error": str(e)}).encode("utf-8"))

        elif self.path == "/manual_cmd":
            try:
                data = json.loads(body.decode("utf-8"))
                cmd = data.get("cmd")

                print("\n=== New /manual_cmd request ===")
                print("Manual cmd:", cmd)

                result = run_manual_motor_command(cmd)

                self._set_headers(200, "application/json; charset=utf-8")
                self.wfile.write(json.dumps(result).encode("utf-8"))

            except Exception as e:
                print("Error in /manual_cmd:", e)
                self._set_headers(500, "application/json; charset=utf-8")
                self.wfile.write(json.dumps({"ok": False, "log": [], "error": str(e)}).encode("utf-8"))

        else:
            self._set_headers(404, "text/plain; charset=utf-8")
            self.wfile.write(b"Not found")


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    server = HTTPServer((host, port), CubeHandler)
    ip = get_local_ip()
    url = f"http://{ip}:{port}"
    print_qr(url)
    print("\nServing on", url)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
