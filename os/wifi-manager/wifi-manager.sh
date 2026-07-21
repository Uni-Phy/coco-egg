#!/bin/bash

# Enhanced WiFi Management Script for Common Compute OS
# Handles automatic switching between hotspot and station modes

set -e

# Configuration
WIFI_STATUS_FILE="/etc/coco/wifi-status"
WIFI_CONFIG_FILE="/boot/dietpi-wifi.txt"
LOG_FILE="/var/log/coco-setup.log"
HOTSPOT_TIMEOUT=30  # seconds to wait for WiFi connection before starting hotspot

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

log_message() {
    echo "$(date): $1" >> $LOG_FILE
    echo -e "${BLUE}[WiFi Manager]${RESET} $1"
}

log_error() {
    echo "$(date): ERROR - $1" >> $LOG_FILE
    echo -e "${RED}[WiFi Manager ERROR]${RESET} $1"
}

log_success() {
    echo "$(date): SUCCESS - $1" >> $LOG_FILE
    echo -e "${GREEN}[WiFi Manager]${RESET} $1"
}

# Check if WiFi credentials are configured
has_wifi_credentials() {
    if [ ! -f "$WIFI_CONFIG_FILE" ]; then
        return 1
    fi
    
    # Extract SSID from config file
    local ssid=$(grep "aWIFI_SSID\[0\]=" "$WIFI_CONFIG_FILE" | cut -d"'" -f2)
    
    # Check if SSID is empty or contains default placeholder
    if [ -z "$ssid" ] || [ "$ssid" = "" ]; then
        return 1
    else
        return 0
    fi
}

# Check if device is connected to WiFi
is_wifi_connected() {
    # Check if wlan0 has an IP address from DHCP (not our hotspot range)
    local ip=$(ip -4 addr show wlan0 2>/dev/null | grep inet | grep -v "192.168.4" | awk '{print $2}' | cut -d'/' -f1)
    
    if [ -n "$ip" ] && ip route | grep -q "default.*wlan0"; then
        log_message "WiFi connected with IP: $ip"
        return 0
    else
        return 1
    fi
}

# Start WiFi hotspot mode
start_hotspot_mode() {
    log_message "Starting WiFi hotspot mode..."
    
    # Stop any existing network services
    systemctl stop wpa_supplicant 2>/dev/null || true
    systemctl stop dhcpcd 2>/dev/null || true
    
    # Kill any existing wpa_supplicant processes
    pkill wpa_supplicant 2>/dev/null || true
    
    # Wait a moment for processes to stop
    sleep 2
    
    # Configure wlan0 for hotspot
    ip link set wlan0 down
    sleep 1
    ip addr flush dev wlan0
    ip addr add 192.168.4.1/24 dev wlan0
    ip link set wlan0 up
    
    # Start hostapd (WiFi Access Point)
    systemctl start hostapd
    if [ $? -eq 0 ]; then
        log_success "hostapd started successfully"
    else
        log_error "Failed to start hostapd"
        return 1
    fi
    
    # Start dnsmasq (DHCP server)
    systemctl start dnsmasq
    if [ $? -eq 0 ]; then
        log_success "dnsmasq started successfully"
    else
        log_error "Failed to start dnsmasq"
    fi
    
    # Update status
    echo "hotspot" > $WIFI_STATUS_FILE
    log_success "Hotspot mode active - SSID: CommonCompute-Setup, Password: coco1234"
    log_message "Device accessible at: http://coco.local or http://192.168.4.1"
    
    return 0
}

# Stop WiFi hotspot mode
stop_hotspot_mode() {
    log_message "Stopping WiFi hotspot mode..."
    
    # Stop services
    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true
    
    # Reset network interface
    ip addr flush dev wlan0
    ip link set wlan0 down
    sleep 1
    ip link set wlan0 up
    
    log_success "Hotspot mode stopped"
    return 0
}

# Attempt to connect to configured WiFi
connect_to_wifi() {
    if ! has_wifi_credentials; then
        log_message "No WiFi credentials configured"
        return 1
    fi
    
    log_message "Attempting to connect to configured WiFi..."
    
    # Stop hotspot if running
    if [ "$(cat $WIFI_STATUS_FILE 2>/dev/null)" = "hotspot" ]; then
        stop_hotspot_mode
    fi
    
    # Start wpa_supplicant and dhcpcd services
    systemctl start wpa_supplicant 2>/dev/null || true
    systemctl start dhcpcd 2>/dev/null || true
    
    # Wait for connection with timeout
    local count=0
    while [ $count -lt $HOTSPOT_TIMEOUT ]; do
        if is_wifi_connected; then
            echo "station" > $WIFI_STATUS_FILE
            log_success "Connected to WiFi successfully"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    
    log_error "Failed to connect to WiFi after ${HOTSPOT_TIMEOUT} seconds"
    return 1
}

# Main WiFi management logic
manage_wifi() {
    # Ensure status directory exists
    mkdir -p $(dirname $WIFI_STATUS_FILE)
    
    # Initialize status file if it doesn't exist
    if [ ! -f "$WIFI_STATUS_FILE" ]; then
        echo "unconfigured" > $WIFI_STATUS_FILE
    fi
    
    local current_status=$(cat $WIFI_STATUS_FILE)
    log_message "Current WiFi status: $current_status"
    
    if has_wifi_credentials; then
        log_message "WiFi credentials found, attempting connection..."
        
        if is_wifi_connected; then
            # Already connected, ensure hotspot is stopped
            if [ "$current_status" = "hotspot" ]; then
                stop_hotspot_mode
            fi
            echo "station" > $WIFI_STATUS_FILE
            log_success "WiFi connection verified"
        else
            # Try to connect to WiFi
            if ! connect_to_wifi; then
                # Connection failed, start hotspot as fallback
                log_message "WiFi connection failed, starting hotspot as fallback"
                start_hotspot_mode
            fi
        fi
    else
        log_message "No WiFi credentials configured"
        
        # No credentials, start hotspot mode
        if [ "$current_status" != "hotspot" ]; then
            start_hotspot_mode
        else
            log_message "Hotspot already running"
        fi
    fi
}

# Command line interface
case "${1:-auto}" in
    "start-hotspot")
        start_hotspot_mode
        ;;
    "stop-hotspot")
        stop_hotspot_mode
        ;;
    "connect-wifi")
        connect_to_wifi
        ;;
    "status")
        echo "WiFi Status: $(cat $WIFI_STATUS_FILE 2>/dev/null || echo 'unknown')"
        echo "Has Credentials: $(has_wifi_credentials && echo 'yes' || echo 'no')"
        echo "WiFi Connected: $(is_wifi_connected && echo 'yes' || echo 'no')"
        ;;
    "auto"|"")
        manage_wifi
        ;;
    *)
        echo "Usage: $0 {start-hotspot|stop-hotspot|connect-wifi|status|auto}"
        echo "  auto: Automatic WiFi management (default)"
        echo "  start-hotspot: Force start hotspot mode"
        echo "  stop-hotspot: Stop hotspot mode"
        echo "  connect-wifi: Try to connect to configured WiFi"
        echo "  status: Show current WiFi status"
        exit 1
        ;;
esac
