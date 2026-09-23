#!/bin/bash
sudo xinit /usr/bin/python3 /home/pi/dashboard/main.py -- :0 &
./start.sh &
