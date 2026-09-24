import serial
import time
import glob
from datetime import datetime

def find_scs_port():
    ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    if not ports:
        raise Exception("Aucun USB-CAN SCS Delta détecté.")
    return ports[0]

def parse_scs_frame(frame):
    frame = frame.strip()
    if len(frame) < 5:
        return None

    # Standard frame
    if frame[0] == 't':
        can_id = frame[1:4]
        dlc = int(frame[4])
        data = frame[5:5 + dlc*2]
        return can_id, data

    # Extended frame
    if frame[0] == 'T':
        can_id = frame[1:9]
        dlc = int(frame[9])
        data = frame[10:10 + dlc*2]
        return can_id, data

    return None

def main():
    # Nom de fichier compact
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = f"log_{timestamp}.txt"
    print(f"Fichier de log : {logfile}")

    port = find_scs_port()
    print(f"USB-CAN détecté sur : {port}")

    ser = serial.Serial(port, baudrate=115200, timeout=0.1)

    print("Capture CAN compacte pendant 30 minutes...")

    end_time = time.time() + 1800  # 30 minutes

    with open(logfile, "w") as f:
        while time.time() < end_time:
            raw = ser.readline().decode(errors="ignore")
            if raw:
                parsed = parse_scs_frame(raw)
                if parsed:
                    can_id, data = parsed
                    ts = datetime.now().strftime("%H%M%S.%f")[:-3]
                    f.write(f"{ts};{can_id};{data}\n")

    print("Capture terminée.")

if __name__ == "__main__":
    main()

