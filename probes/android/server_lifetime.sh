#!/usr/bin/env bash
# Usage: probes/android/server_lifetime.sh
# Prints whether the uiautomator2 server answers after its launcher exits, for an attached and a detached start.
set -u
here=$(cd "$(dirname "$0")" && pwd)
ping() { curl -s -m 1 -o /dev/null -w "%{http_code}" http://127.0.0.1:19008/ping; }
adb forward tcp:19008 tcp:9008 >/dev/null
adb shell pkill -f uia2.Main

uv run --project "$here/../.." python -I -c "import uiautomator2 as u2; u2.connect().info"
echo "attached start, after launcher exit: ping=$(ping)"

adb shell 'CLASSPATH=/data/local/tmp/u2.jar nohup app_process / com.wetest.uia2.Main -p 9008 >/dev/null 2>&1 &'
for i in 1 2 3 4 5 6 7 8; do [ "$(ping)" = 200 ] && break; sleep 1; done
echo "detached start, after ${i}s: ping=$(ping)"
sleep 5
echo "detached start, 5s later: ping=$(ping)"

adb shell pkill -f uia2.Main
adb forward --remove tcp:19008
