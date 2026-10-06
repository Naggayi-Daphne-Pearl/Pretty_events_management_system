#!/bin/sh
set -e

# `./entrypoint.sh worker` runs the background task worker (emails queued when
# TASK_WORKER_ENABLED=True). The web container owns migrations, so the worker
# doesn't run them too.
if [ "$1" = "worker" ]; then
    exec python manage.py db_worker
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py setup_groups
python manage.py setup_chart_of_accounts
python manage.py post_ledger_history

exec gunicorn config.wsgi:application --bind 0.0.0.0:"${PORT:-8000}" --workers 3
