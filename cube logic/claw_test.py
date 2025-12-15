import serial
import serial.tools.list_ports
import time

BAUD = 115200

ports = [p.device for p in serial.tools.list_ports.comports()]
serial_connections = []

for port in ports:
    try:
        s = serial.Serial(port, BAUD, timeout=0.1)
        serial_connections.append(s)
    except:
        pass

time.sleep(2)

CMD_RL_IN  = b"{222}\n"
CMD_RL_OUT = b"{221}\n"
CMD_FB_IN  = b"{231}\n"
CMD_FB_OUT = b"{232}\n"

CMD_R = b"{121}\n"
CMD_F = b"{111}\n"
CMD_B = b"{132}\n"

def send(cmd, timeout=2.0):
    for ser in serial_connections:
        try:
            ser.write(cmd)
        except:
            pass

    start = time.time()
    pending = set(serial_connections)

    while pending and (time.time() - start) < timeout:
        for ser in list(pending):
            try:
                line = ser.readline().strip()
                if line == b"DONE":
                    pending.remove(ser)
            except:
                pending.remove(ser)

def rl_in():
    send(CMD_RL_IN)

def rl_out():
    send(CMD_RL_OUT)

def fb_in():
    send(CMD_FB_IN)

def fb_out():
    send(CMD_FB_OUT)

def R():
    send(CMD_R)

def F():
    send(CMD_F)

def B():
    send(CMD_B)

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
