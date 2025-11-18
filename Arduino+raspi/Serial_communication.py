#!/usr/bin/env python3
import serial, time, glob, sys

BAUD = 9600

COMMANDS = [
    COMMANDS = [
    "2, OB",
    "1, RF",
    "1, YB",
    "2, OF",
    "1, GB",
    "1, GB",
    "2, OB",
    "1, GB",
    "2, WF",
    "2, WF",
    "END"
]

def find_ports():
    return glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")

def wait_for_done(serials):
    """
    BLOCKS until ANY Arduino prints 'DONE'.
    """
    print("  Waiting for DONE...")
    while True:
        for s in serials:
            if s.in_waiting:
                try:
                    msg = s.readline().decode(errors="ignore").strip()
                except:
                    msg = ""
                if msg:
                    print(f"    {s.port}: {msg}")
                if msg == "DONE":
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
            time.sleep(2)  # allow Arduino reset
            serials.append(s)
        except Exception as e:
            print(f"Could not open {port}: {e}")

    if not serials:
        print("No serial connections opened.")
        sys.exit(1)

    # ---- NEW LOGIC: Send → Wait for DONE → Send next ----
    for cmd in COMMANDS:
        line = cmd.strip() + "\n"
        
        # Send to all Arduinos
        for s in serials:
            s.write(line.encode())

        print("\nSent:", cmd)

        # If END, stop sending
        if cmd == "END":
            break

        # BLOCK until Arduino says DONE
        wait_for_done(serials)

        # tiny safety delay
        time.sleep(0.05)

    print("\nAll commands completed.")

    # Read any trailing messages
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

    print("Finished.")

if __name__ == "__main__":
    main()
