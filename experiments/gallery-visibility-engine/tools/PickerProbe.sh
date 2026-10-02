#!/system/bin/sh
OUT="/sdcard/Download/GalleryPickerProbe_$(date +%Y%m%d_%H%M%S).txt"
{
  echo "=== Gallery / Photo Picker Probe ==="
  date
  echo
  echo "[packages]"
  pm list packages | grep -Ei 'media|picker|gallery|photos|file' || true
  echo
  echo "[top activity]"
  dumpsys activity activities 2>/dev/null | grep -E 'mResumedActivity|topResumedActivity|ResumedActivity' | head -20
  echo
  echo "[processes]"
  ps -A 2>/dev/null | grep -Ei 'media|picker|gallery|photos|file' || true
  echo
  echo "[providers]"
  dumpsys package 2>/dev/null | grep -Ei 'PhotoPicker|MediaProvider|media\.module|picker' | head -200
} > "$OUT" 2>&1
echo "$OUT"
