"""
serial_communication.py
Raspberry Pi broadcast script for multiple Arduinos.

Sends all cube commands at once.  
Each Arduino filters by its BOARD_ID and executes its own moves.
"""

import serial, time, glob, sys

BAUD = 9600
COMMANDS = [
    "1, R",   
    "2, G",  
    "1, Y",   
    "END"   
]

def find_ports():
    """Return list of likely Arduino serial ports."""
    return glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")

def main():
    ports = find_ports()
    if not ports:
        print("❌ No Arduino ports found.")
        sys.exit(1)

    print("Found ports:", ports)

    serials = []
    for port in ports:
        try:
            s = serial.Serial(port, BAUD, timeout=1)
            time.sleep(2)  # allow Arduino reset
            serials.append(s)
        except Exception as e:
            print(f"⚠️ Could not open {port}: {e}")

    if not serials:
        print("❌ No serial connections opened.")
        sys.exit(1)

    for cmd in COMMANDS:
        line = cmd.strip() + "\n"
        for s in serials:
            s.write(line.encode())
        print("➡️  Sent:", cmd)
    print("✅ All commands broadcast.\n")

    t0 = time.time()
    while time.time() - t0 < 3:
        for s in serials:
            if s.in_waiting:
                try:
                    msg = s.readline().decode(errors="ignore").strip()
                    if msg:
                        print(f"{s.port}: {msg}")
                except:
                    pass
    for s in serials:
        s.close()
    print("🔚 Finished.")

if __name__ == "__main__":
    main()
