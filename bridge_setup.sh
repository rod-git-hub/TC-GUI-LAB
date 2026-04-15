#!/usr/bin/env bash
set -euo pipefail
BRIDGE="${1:-br0}";IFACE1="${2:-eth0}";IFACE2="${3:-eth1}"
ip link set "$IFACE1" down;ip addr flush dev "$IFACE1"
ip link set "$IFACE2" down;ip addr flush dev "$IFACE2"
ip link show "$BRIDGE" &>/dev/null||ip link add name "$BRIDGE" type bridge
ip link set "$BRIDGE" type bridge stp_state 0
ip link set "$IFACE1" master "$BRIDGE";ip link set "$IFACE2" master "$BRIDGE"
echo 1>/proc/sys/net/ipv4/ip_forward
ip link set "$IFACE1" up;ip link set "$IFACE2" up;ip link set "$BRIDGE" up
echo "[+] FW<->$IFACE1 [$BRIDGE] $IFACE2<->WAN"
