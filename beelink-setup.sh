#!/usr/bin/env bash
# =============================================================================
#  Platt Park Brewing - tap board kiosk + Computa keepalive
#  One-shot installer for a Beelink (or any x86 mini PC) running Debian 12
#  or Ubuntu 24.04 minimal. Run ONCE as your normal user, with sudo available:
#
#      curl -fsSL https://raw.githubusercontent.com/PlattPark/liveboard/main/beelink-setup.sh -o setup.sh
#      bash setup.sh
#
#  What it sets up
#    1. Chromium in kiosk mode showing the board, fullscreen, on every boot,
#       with a watchdog that relaunches it within 10s if it ever dies
#    2. No screen blanking, no sleep, no update pop-ups, no crash bubbles
#    3. A 10-minute keepalive that pokes the cloud Computa so it can never
#       stay asleep more than 10 minutes (needs the GitHub token, asked once)
#    4. Nightly 3:30am kiosk restart so browser updates actually take effect
#    5. Security updates only, never auto-reboot
#
#  BIOS (do this by hand, once): set "Restore on AC Power Loss" = Power On,
#  so a power blip brings the board back without anyone touching it.
# =============================================================================
set -euo pipefail

BOARD_URL="https://plattpark.github.io/liveboard/platt-park-live-board-v4.html"
REPO="PlattPark/liveboard"
USER_NAME="$(id -un)"
HOME_DIR="$HOME"

echo "== 1/6  packages"
sudo apt-get update -qq
sudo apt-get install -y -qq chromium unclutter xorg openbox lightdm curl \
    unattended-upgrades 2>/dev/null || \
sudo apt-get install -y -qq chromium-browser unclutter xorg openbox lightdm curl unattended-upgrades
CHROME="$(command -v chromium || command -v chromium-browser)"

echo "== 2/6  auto-login + kiosk session"
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-kiosk.conf >/dev/null <<EOF
[Seat:*]
autologin-user=${USER_NAME}
autologin-user-timeout=0
user-session=openbox
EOF

mkdir -p "$HOME_DIR/.config/openbox"
cat > "$HOME_DIR/.config/openbox/autostart" <<EOF
# never blank, never sleep
xset s off; xset s noblank; xset -dpms
unclutter -idle 1 -root &
# watchdog: relaunch the board if Chromium ever exits
"$HOME_DIR/kiosk.sh" &
EOF

cat > "$HOME_DIR/kiosk.sh" <<EOF
#!/usr/bin/env bash
# keeps the board on screen forever
while true; do
  "$CHROME" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \\
    --disable-translate --no-first-run --autoplay-policy=no-user-gesture-required \\
    --check-for-update-interval=31536000 --overscroll-history-navigation=0 \\
    --window-size=1920,1080 --window-position=0,0 \\
    --user-data-dir="$HOME_DIR/.kiosk-profile" "$BOARD_URL"
  sleep 10
done
EOF
chmod +x "$HOME_DIR/kiosk.sh"

echo "== 3/6  Computa keepalive"
if [ ! -f "$HOME_DIR/.computa-keepalive.env" ]; then
  echo
  echo "  Paste the GitHub token (the computa-liveboard fine-grained token)."
  echo "  It is stored only in $HOME_DIR/.computa-keepalive.env (mode 600)."
  read -rsp "  token: " GH_PAT; echo
  printf 'GH_PAT=%s\n' "$GH_PAT" > "$HOME_DIR/.computa-keepalive.env"
  chmod 600 "$HOME_DIR/.computa-keepalive.env"
fi
cat > "$HOME_DIR/keepalive.sh" <<EOF
#!/usr/bin/env bash
# Every 10 min: if no Computa run is in progress or queued, start one.
# Harmless when the chain is healthy (GitHub keeps one queued run and
# cancels extras); restarts it within 10 min if it ever breaks.
set -a; . "$HOME_DIR/.computa-keepalive.env"; set +a
H=(-H "Authorization: Bearer \$GH_PAT" -H "Accept: application/vnd.github+json")
active=\$(curl -sS "\${H[@]}" "https://api.github.com/repos/$REPO/actions/runs?status=in_progress&per_page=1" | grep -c '"id"' || true)
queued=\$(curl -sS "\${H[@]}" "https://api.github.com/repos/$REPO/actions/runs?status=queued&per_page=1"      | grep -c '"id"' || true)
if [ "\$active" = "0" ] && [ "\$queued" = "0" ]; then
  curl -sS -o /dev/null -w "\$(date '+%F %T') computa was idle - restarted (HTTP %{http_code})\n" -X POST "\${H[@]}" \\
    "https://api.github.com/repos/$REPO/dispatches" -d '{"event_type":"computa-next"}' >> "$HOME_DIR/keepalive.log"
fi
EOF
chmod +x "$HOME_DIR/keepalive.sh"
"$HOME_DIR/keepalive.sh" && echo "  keepalive test ok (see $HOME_DIR/keepalive.log)"

echo "== 4/6  cron: keepalive every 10 min, kiosk restart nightly 3:30"
( crontab -l 2>/dev/null | grep -v 'keepalive.sh\|kiosk-restart' ;
  echo "*/10 * * * * $HOME_DIR/keepalive.sh" ;
  echo "30 3 * * * pkill -f chromium; sleep 5; DISPLAY=:0 $HOME_DIR/kiosk.sh >/dev/null 2>&1 &  # kiosk-restart"
) | crontab -

echo "== 5/6  updates: security only, never reboot on their own"
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
sudo sed -i 's|^//Unattended-Upgrade::Automatic-Reboot .*|Unattended-Upgrade::Automatic-Reboot "false";|' /etc/apt/apt.conf.d/50unattended-upgrades || true

echo "== 6/6  done"
echo
echo "  Reboot now and the board comes up on its own:   sudo reboot"
echo "  Board URL:     $BOARD_URL"
echo "  Keepalive log: $HOME_DIR/keepalive.log"
echo "  Remember the BIOS setting: Restore on AC Power Loss = Power On"
