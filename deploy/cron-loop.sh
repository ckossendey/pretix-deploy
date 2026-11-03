#!/bin/bash
# pretix needs `runperiodic` at regular intervals (expire unpaid orders, send
# payment reminders, clean up files, ...). The official image has no cron, so
# supervisord keeps this loop running next to web server and worker.
INTERVAL="${PRETIX_CRON_INTERVAL_SECONDS:-300}"

# Let web server and worker start first.
sleep 60

while true; do
  if ! /usr/local/bin/pretix cron; then
    echo "[pretix-cron] runperiodic fehlgeschlagen, nächster Versuch in ${INTERVAL}s"
  fi
  sleep "$INTERVAL"
done
