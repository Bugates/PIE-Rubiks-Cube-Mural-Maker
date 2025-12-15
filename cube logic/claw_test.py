import serial
import serial.tools.list_ports
import time

BAUD = 115200

ports = [p.device for p in serial.tools.list_ports.comports()]
serial_connections = []

for port in ports:
    try:
        s = serial.Serial(port, BAUD, timeout=1)
        serial_connections.append(s)
    except:
        pass

time.sleep(2)

def send(cmd):
    message = f"{{{cmd}}}\n".encode()
    for ser in serial_connections:
        try:
            ser.write(message)
        except:
            pass
    for ser in serial_connections:
        while True:
            try:
                line = ser.readline().decode().strip()
                if line == "DONE":
                    break
            except:
                break

def rl_in():
    send("222")

def rl_out():
    send("221")

def fb_in():
    send("231")

def fb_out():
    send("232")

def R():
    send("121")

def F():
    send("111")

def B():
    send("132")

def execute_move(move):
    if move in ["R", "L"]:
        rl_in()
        if move == "R":
            R()
        rl_out()
    elif move in ["F", "B"]:
        fb_in()
        if move == "F":
            F()
        else:
            B()
        fb_out()

def claw_test():
    rl_in()
    R()
    rl_out()

    fb_in()
    F()
    B()
    F()
    fb_out()

    rl_in()
    R()
    rl_out()

claw_test()
