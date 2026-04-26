#!/bin/bash
# Launch the display game hub server and Chromium kiosk for ILI9341 320x240.
cd "$(dirname "$0")/.."
echo "[DISPLAY] Starting game hub on :5555..."
DISPLAY=:0 unclutter -idle 1 -root &
python3 -m display.server &
DISPLAY_PID=$!
sleep 3
echo "[DISPLAY] Launching Chromium kiosk..."
DISPLAY=:0 chromium --kiosk --window-size=320,240 --disable-infobars \
    --noerrdialogs --disable-translate --no-first-run \
    --disable-features=TranslateUI --disable-session-crashed-bubble \
    --app=http://localhost:5555 &
echo "[DISPLAY] Running (server PID: $DISPLAY_PID)"
wait $DISPLAY_PID
