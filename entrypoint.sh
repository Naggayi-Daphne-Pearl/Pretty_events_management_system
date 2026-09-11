#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py setup_groups

exec gunicorn config.wsgi:application --bind 0.0.0.0:"${PORT:-8000}" --workers 3
