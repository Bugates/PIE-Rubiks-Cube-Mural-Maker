import time
import glob
import serial

def find_ports():
    return glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")

ports = find_ports()
print("Ports:", ports)

serials = []
for p in ports:
    s = serial.Serial(p, 9600, timeout=1)
    time.sleep(2)  # REQUIRED
    serials.append(s)
    print("Opened", p)

commands = [222, 121, 221]

for cmd in commands:
    print("Sending", cmd)
    data = bytes([cmd])
    for s in serials:
        s.write(data)

    time.sleep(0.1)

    for s in serials:
        while s.in_waiting:
            print(s.port, s.readline().decode(errors="ignore").strip())

    time.sleep(0.5)

for s in serials:
    s.close()

print("Done")
