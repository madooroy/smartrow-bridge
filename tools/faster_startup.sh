#!/usr/bin/env bash
# Optional: make the Pi start faster (about 4 s less from power-on to the bridge being
# visible on a Pi 4). It changes the Pi's boot settings, not the bridge.
#
#   sudo bash ~/smartrow-bridge/tools/faster_startup.sh           apply, then reboot
#   sudo bash ~/smartrow-bridge/tools/faster_startup.sh --undo    put everything back, then reboot
#
# What it changes:
#   1. /boot/firmware/config.txt  - no firmware pause or splash screen, no camera/display
#                                   probing, no initramfs (not needed to boot from an SD card).
#   2. Bootloader (Pi 4 only)     - NET_INSTALL_AT_POWER_ON=0: no wait for a keyboard at power-on.
#                                   This is stored on the Pi's board, not on the SD card.
# The first time it runs it keeps the original file next to the changed one as
# config.txt.before-speedup. It is on the SD card's boot partition, which any computer can
# read: if the Pi ever fails to start, put the card in a computer and copy it back over
# config.txt.
#
# It deliberately leaves cloud-init alone. Disabling it (cloud-init=disabled in cmdline.txt)
# would save another 2 s, but on a card set up with Raspberry Pi Imager the Pi then no
# longer joins the Wi-Fi.
set -euo pipefail

BOOT=${BOOT_DIR:-/boot/firmware}  # BOOT_DIR: try it on a copy of the file
CONFIG=$BOOT/config.txt
SUFFIX=.before-speedup
UNDO=0
[[ ${1:-} == --undo ]] && UNDO=1

if [[ -z ${BOOT_DIR:-} && $EUID -ne 0 ]]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi
[[ -f $CONFIG ]] || { echo "$CONFIG not found - is this Raspberry Pi OS?" >&2; exit 1; }

# Set NET_INSTALL_AT_POWER_ON in the bootloader configuration (Raspberry Pi 4 only).
set_net_install() {
    local value=$1 current tmp
    [[ -z ${BOOT_DIR:-} ]] || return 0
    if ! grep -q "Raspberry Pi 4" /proc/device-tree/model 2>/dev/null || ! command -v rpi-eeprom-config >/dev/null; then
        echo "   bootloader: skipped (not a Raspberry Pi 4, or rpi-eeprom-config is missing)"
        return 0
    fi
    current=$(rpi-eeprom-config)
    if grep -q "^NET_INSTALL_AT_POWER_ON=$value\$" <<<"$current"; then
        echo "   bootloader: NET_INSTALL_AT_POWER_ON=$value already set"
        return 0
    fi
    tmp=$(mktemp)
    grep -v '^NET_INSTALL_AT_POWER_ON=' <<<"$current" >"$tmp" || true
    echo "NET_INSTALL_AT_POWER_ON=$value" >>"$tmp"
    rpi-eeprom-config --apply "$tmp" >/dev/null
    rm -f "$tmp"
    echo "   bootloader: NET_INSTALL_AT_POWER_ON=$value (written at the next reboot)"
}

if [[ $UNDO -eq 1 ]]; then
    echo "== Undoing the faster start-up settings =="
    if [[ -f $CONFIG$SUFFIX ]]; then
        cp "$CONFIG$SUFFIX" "$CONFIG"
        echo "   restored $CONFIG"
    else
        echo "   $CONFIG: no $SUFFIX copy, left as it is"
    fi
    set_net_install 1
    echo "Done. Reboot to apply: sudo reboot"
    exit 0
fi

echo "== Faster start-up =="
[[ -f $CONFIG$SUFFIX ]] || cp "$CONFIG" "$CONFIG$SUFFIX"

# config.txt: change a setting where it already is, otherwise add it under [all] at the end.
missing=()
for setting in camera_auto_detect=0 display_auto_detect=0 auto_initramfs=0 boot_delay=0 disable_splash=1; do
    key=${setting%%=*}
    if grep -q "^$key=" "$CONFIG"; then
        sed -i "s/^$key=.*/$setting/" "$CONFIG"
    else
        missing+=("$setting")
    fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
    {
        echo
        echo "# Faster start-up (smartrow-bridge tools/faster_startup.sh)"
        echo "[all]"
        printf '%s\n' "${missing[@]}"
    } >>"$CONFIG"
fi
echo "   $CONFIG: camera_auto_detect=0 display_auto_detect=0 auto_initramfs=0 boot_delay=0 disable_splash=1"

set_net_install 0

echo "Done. Reboot to apply: sudo reboot"
echo "Original kept as $CONFIG$SUFFIX"
