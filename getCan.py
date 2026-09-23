from __future__ import print_function

import can
from can.bus import BusState


def receive_all():

    bus = can.interface.Bus(bustype='socketcan', channel='can0', bitrate=500000)
    
    bus.state = BusState.ACTIVE

    try:
        while True:
            msg = bus.recv(1)
            if msg is not None:
                print(msg)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    receive_all()	
