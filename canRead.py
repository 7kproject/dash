#!/usr/bin/python3
#
# can_logging_to_sdcard.py
# 
# This python3 program logs all CAN messages to the sd card.
# For use with PiCAN boards on the Raspberry Pi
# http://skpang.co.uk/catalog/pican2-canbus-board-for-raspberry-pi-2-p-1475.html
#
# Make sure Python-CAN is installed first http://skpang.co.uk/blog/archives/1220
#
# 01-02-16 SK Pang
#
#
#
# TODO check for queue full
 
import can
import time
import os
import queue
from threading import Thread
import CanProtocol
 
 
outfile = open('log.txt','w')
count = 0
tool = CanProtocol.CanTool()
 
print('\n\rCAN Rx test')
print('Bring up CAN0....')
 
# Bring up can0 interface at 500kbps
#os.system("sudo /sbin/ip link set can0 up type can bitrate 500000")
time.sleep(0.1) 
print('Press CTL-C to exit')
 
try:
	bus = can.interface.Bus(bustype='socketcan', channel='can0', bitrate=500000)
    #bus = can.interface.Bus(channel='can0', bustype='socketcan_native')
except OSError:
    print('Cannot find PiCAN board.')
    exit()
 
# CAN receive thread
def can_rx_task():
    while True:
        message = bus.recv()
		
        data = str(message)
        idr = data[41:44]
        print(idr,message)
        if idr != "":
            if int(idr,16) == id:
                mess = data[69:].replace(' ', '' )
                message = idr+"#"+mess
                print(message)
                tool.decode( message )
        #q.put(message)          # Put message into queue
 
q = queue.Queue()   
t = Thread(target = can_rx_task)    # Start receive thread
t.start()
 
# Main loop
try:
    while True:
		print(tool.Tps, tool.Lambda1, tool.Rpm, tool.Temp,"\n")
          
 
     
except KeyboardInterrupt:
    #Catch keyboard interrupt
    #outfile.close()
    #os.system("sudo /sbin/ip link set can0 down")
    print('\n\rKeyboard interrtupt')  
    exit
