import time
import glob
import serial

BAUD = 9600

def find_ports():
    return glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")

ports = find_ports()
print("Found ports:", ports)

serials = []

for p in ports:
    try:
        s = serial.Serial(
            port=p,
            baudrate=BAUD,
            timeout=1,
            write_timeout=1
        )
        time.sleep(3)
        serials.append(s)
        print("Opened", p)
    except serial.SerialException as e:
        print("Failed to open", p, e)

commands = [222, 121, 221]

for cmd in commands:
    data = bytes([cmd])
    print("Sending byte:", cmd)

    for s in serials[:]:
        try:
            if not s.is_open:
                raise serial.SerialException("Closed")

            s.write(data)
            s.flush()

        except (serial.SerialException, OSError):
            print("Port error, removing:", s.port)
            try:
                s.close()
            except:
                pass
            serials.remove(s)

    time.sleep(0.2)

    for s in serials[:]:
        try:
            while s.in_waiting:
                print(s.port, s.read(1))
        except (serial.SerialException, OSError):
            print("Read error, removing:", s.port)
            try:
                s.close()
            except:
                pass
            serials.remove(s)

    time.sleep(0.4)

for s in serials:
    try:
        s.close()
    except:
        pass

print("Done safely")
