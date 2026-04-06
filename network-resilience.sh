#!/bin/bash
# 1. Célpontok (Google DNS és Tailscale belső szerver)
INTERNET_TARGET="8.8.8.8"
TS_TARGET="100.100.100.100"

# 2. Ellenőrizzük a fizikai internetet
if ! ping -c 1 $INTERNET_TARGET &> /dev/null; then
    echo "$(date) - Nincs internet! WiFi újraindítása..." >> /var/log/network-resilience.log
    sudo ifconfig wlan0 down
    sleep 5
    sudo ifconfig wlan0 up
    sleep 20
fi

# 3. Ellenőrizzük a Tailscale-t (csak ha van net)
if ping -c 1 $INTERNET_TARGET &> /dev/null; then
    if ! ping -c 1 $TS_TARGET &> /dev/null; then
        echo "$(date) - Internet van, de Tailscale nem válaszol! Restart..." >> /var/log/network-resilience.log
        sudo systemctl restart tailscaled
    fi
fi