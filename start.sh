#!/bin/bash
export DISPLAY=:0
export MPLCONFIGDIR=~/.cache/matplotlib

# Forcer la résolution 1024x600
xrandr --newmode "1024x600_60.00" 49.00 1024 1072 1168 1312 600 603 613 624 -hsync +vsync 2>/dev/null
xrandr --addmode HDMI-1 "1024x600_60.00" 2>/dev/null
xrandr --output HDMI-1 --mode "1024x600_60.00"

# Masquer le curseur
unclutter -idle 0 &

