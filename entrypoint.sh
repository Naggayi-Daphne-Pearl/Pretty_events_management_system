#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py setup_groups
python manage.py setup_chart_of_accounts
python manage.py post_ledger_history

exec gunicorn config.wsgi:application --bind 0.0.0.0:"${PORT:-8000}" --workers 3
