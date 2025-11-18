#!/usr/bin/env python3
import serial, time, glob, sys

BAUD = 9600

COMMANDS = [
    "2, OF",
    "2, OF",
    "2, OF",
    "1, RF",
    "1, YF",
    "1, YF",
    "1, YF",
    "2, OF",
    "1, GF",
    "1, GF",
    "1, GF",
    "1, GF",
    "1, GF",
    "1, GF",
    "2, OF",
    "2, OF",
    "2, OF",
    "1, GF",
    "1, GF",
    "1, GF",
    "2, WF",
    "2, WF",
    "END"
]

def find_ports():
    return glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")


def read_all_available(s):
    """
    Reads ALL pending messages from a serial port.
    Returns list of decoded strings.
    """
    msgs = []
    while s.in_waiting:
        try:
            msg = s.readline().decode(errors="ignore").strip()
            if msg:
                msgs.append(msg)
        except:
            pass
    return msgs


def wait_for_done(serials):
    """
    BLOCKS until ANY Arduino prints 'DONE'.
    Also prints ALL intermediate messages.
    """
    print("  Waiting for DONE...")

    while True:
        for s in serials:
            msgs = read_all_available(s)
            for m in msgs:
                print(f"    {s.port}: {m}")
                if m == "DONE":
                    return


def main():
    ports = find_ports()
    if not ports:
        print("No Arduino ports found.")
        sys.exit(1)

    print("Found ports:", ports)

    serials = []
    for port in ports:
        try:
            s = serial.Serial(port, BAUD, timeout=1)
            time.sleep(2)  # allow Arduino to auto-reset
            serials.append(s)
        except Exception as e:
            print(f"Could not open {port}: {e}")

    if not serials:
        print("No serial connections opened.")
        sys.exit(1)

    # --------------------------------------------
    # Send → read prints → wait for DONE → repeat
    # --------------------------------------------
    for cmd in COMMANDS:
        line = cmd.strip() + "\n"

        # Send command to all Arduinos
        for s in serials:
            s.write(line.encode())

        print("\nSent:", cmd)

        # Stop sending at END
        if cmd == "END":
            break

        # Drain initial prints
        time.sleep(0.05)
        for s in serials:
            msgs = read_all_available(s)
            for m in msgs:
                print(f"    {s.port}: {m}")

        # Wait until any Arduino prints DONE
        wait_for_done(serials)

        # small safety delay
        time.sleep(0.05)

    print("\nAll commands completed.")

    # Read trailing messages for 2 seconds
    t0 = time.time()
    while time.time() - t0 < 2:
        for s in serials:
            msgs = read_all_available(s)
            for m in msgs:
                print(f"{s.port}: {m}")

    for s in serials:
        s.close()

    print("Finished.")

if __name__ == "__main__":
    main()
