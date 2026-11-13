import serial
import time

class ServoController:

    def __init__(self, port, baudrate=115200):
        self.ser = serial.Serial(port, baudrate)
        time.sleep(2)

    def set_angle(self, angle):
        angle = max(0, min(180, int(angle)))
        self.ser.write(f"{angle}\n".encode())

    def close(self):
        self.ser.close()