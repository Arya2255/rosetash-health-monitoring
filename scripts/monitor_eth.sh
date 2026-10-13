#!/bin/bash
# Monitor ESP32 Ethernet connection - runs continuously
# Notifies when eth_connected=1

WIFI_IFACE="wlp2s0"
MIN_RUN_TIME=300  # Minimum 5 minutes
START_TIME=$(date +%s)

echo "=== Ethernet Monitor Started ==="
echo "Will run for at least $((MIN_RUN_TIME/60)) minutes..."
echo ""

NOTIFIED=0

while true; do
    # Check minimum run time
    ELAPSED=$(($(date +%s) - START_TIME))
    if [ $ELAPSED -lt $MIN_RUN_TIME ]; then
        echo "[$ELAPSED s] Still running... (min: ${MIN_RUN_TIME}s)"
    fi
    
    # Listen to MQTT topic (timeout 30s)
    MSG=$(timeout 30 mosquitto_sub -t "roztash/gateway/status" -C 1 -i monitor_eth 2>/dev/null)
    
    if echo "$MSG" | grep -q '"eth_connected":1'; then
        if [ $NOTIFIED -eq 0 ]; then
            echo "=== ⚠️ ETHERNET CONNECTED! ==="
            notify-send "⚠️ ESP32 Ethernet Connected" "Cable blocks phone internet!" 2>/dev/null || \
                echo "⚠️ ETHERNET CONNECTED!"
            NOTIFIED=1
        fi
    else
        if echo "$MSG" | grep -q '"eth_connected":0'; then
            if [ $NOTIFIED -eq 1 ]; then
                echo "=== Ethernet disconnected ==="
                NOTIFIED=0
            fi
        fi
    fi
    
    sleep 2
done