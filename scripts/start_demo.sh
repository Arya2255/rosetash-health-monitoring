#!/usr/bin/env bash
# راه‌اندازی سریع دمو — بروکر، پل زنده و برنامهٔ فلت
#
#   bash scripts/start_demo.sh            # دسکتاپ
#   bash scripts/start_demo.sh --web      # نسخهٔ وب روی پورت ۸۵۵۰
#   bash scripts/start_demo.sh --check    # فقط بررسی وضعیت اجزا
#
# هر جزئی که از قبل بالا باشد، دوباره اجرا نمی‌شود.
set -u
cd "$(dirname "$0")/.." || exit 1

MODE="${1:-}"

is_up() { pgrep -f "$1" >/dev/null 2>&1; }

check() {
  local ok=0
  if is_up "mosquitto -c tools/mosquitto" || is_up "mosquitto.*1884"; then
    echo "[ok]   بروکر MQTT"
  else
    echo "[--]   بروکر MQTT بالا نیست"
    ok=1
  fi
  if curl -sf --max-time 1 http://127.0.0.1:8726/health >/dev/null 2>&1; then
    echo "[ok]   پل زنده روی ۸۷۲۶"
  else
    echo "[--]   پل زنده بالا نیست"
    ok=1
  fi
  if is_up "record_loop.sh"; then
    echo "[ok]   ضبط‌کنندهٔ رویدادها"
  else
    echo "[--]   ضبط‌کنندهٔ رویدادها خاموش است"
  fi
  return $ok
}

if [ "$MODE" = "--check" ]; then
  check
  exit $?
fi

echo "بررسی اجزا:"
check || true
echo

if ! is_up "mosquitto -c tools/mosquitto" && [ -f tools/mosquitto/mosquitto.conf ]; then
  echo "بروکر را بالا می‌آورم…"
  nohup mosquitto -c tools/mosquitto/mosquitto.conf >/tmp/roztash-mosquitto.log 2>&1 &
  sleep 1
fi

if ! curl -sf --max-time 1 http://127.0.0.1:8726/health >/dev/null 2>&1; then
  echo "پل زنده را بالا می‌آورم…"
  mkdir -p backend/state
  nohup python3 backend/bridge.py >backend/state/bridge.log 2>&1 &
  sleep 2
  curl -sf --max-time 2 http://127.0.0.1:8726/health >/dev/null 2>&1 \
    && echo "پل آماده است." || echo "هشدار: پل جواب نداد — backend/state/bridge.log را ببین."
fi

if [ "$MODE" = "--web" ]; then
  echo "نسخهٔ وب: http://127.0.0.1:8550"
  exec uv run flet run --web --port 8550
else
  echo "برنامه را باز می‌کنم…"
  exec uv run flet run
fi
