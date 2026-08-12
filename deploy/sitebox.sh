#!/bin/sh
# Site box — publish one site camera to the Sand Planet relay.
#
# A camera sits on the site LAN behind carrier NAT, so nothing can reach it
# from outside. This script runs on any always-on machine on that same LAN
# (a spare laptop, a mini-PC, a Raspberry Pi): it pulls the camera's local
# RTSP and pushes it out to the relay, which is what the app reads.
#
# It is a STREAM COPY — no transcoding — so even a Pi runs it at a few percent
# CPU. Register the camera in the app first (Live Feeds → + Add camera); the
# stream path and key come from that camera's card.
#
#   CAMERA_IP=192.168.100.240 CAMERA_PASSWORD='…' \
#   STREAM_PATH=mle-office STREAM_KEY='…' sh sitebox.sh
#
# ⚠ This publishes CONTINUOUSLY — roughly 1 Mbps, ~10 GB/day — whether or not
# anyone is watching. That is fine on office broadband for a test, but do NOT
# leave it running on an island uplink until on-demand publishing is built.
set -e

: "${CAMERA_IP:?set CAMERA_IP (the camera's address on the site LAN)}"
: "${CAMERA_PASSWORD:?set CAMERA_PASSWORD (the camera's device password)}"
: "${STREAM_PATH:?set STREAM_PATH (from the camera's card in the app)}"
: "${STREAM_KEY:?set STREAM_KEY (from the camera's card in the app)}"
RELAY_HOST="${RELAY_HOST:-159.223.35.180}"
CAMERA_USER="${CAMERA_USER:-admin}"
# The SUB stream: H264 (browsers can play it) and ~1 Mbps. The main stream is
# 4K H265, which browsers largely cannot decode and no uplink here would carry.
CAMERA_STREAM="${CAMERA_STREAM:-Preview_01_sub}"

command -v ffmpeg >/dev/null 2>&1 || {
  echo "ffmpeg is not installed."
  echo "  macOS:  brew install ffmpeg"
  echo "  Debian/Ubuntu/Raspberry Pi OS:  sudo apt install -y ffmpeg"
  exit 1
}

echo "camera : rtsp://${CAMERA_USER}@${CAMERA_IP}:554/${CAMERA_STREAM}"
echo "relay  : rtsp://${RELAY_HOST}:8554/${STREAM_PATH}"
echo "Publishing. Ctrl-C to stop."

# Reconnect for ever: island uplinks drop, cameras reboot, power flickers. A
# site box that gives up on the first failure is a site box someone has to
# visit — the whole point is that nobody has to.
while true; do
  ffmpeg -loglevel warning \
    -rtsp_transport tcp \
    -i "rtsp://${CAMERA_USER}:${CAMERA_PASSWORD}@${CAMERA_IP}:554/${CAMERA_STREAM}" \
    -an -c:v copy \
    -f rtsp -rtsp_transport tcp \
    "rtsp://${STREAM_PATH}:${STREAM_KEY}@${RELAY_HOST}:8554/${STREAM_PATH}" \
    || echo "$(date '+%Y-%m-%d %H:%M:%S') stream ended — reconnecting in 10s"
  sleep 10
done
