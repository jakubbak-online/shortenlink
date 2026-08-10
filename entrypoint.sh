#!/bin/sh
set -e

# Tylko usługa web ma nakładać migracje (ustawia RUN_MIGRATIONS=1 w
# docker-compose.yml) - worker startuje równolegle z tym samym obrazem i
# tym samym entrypointem, więc bez tego dwa procesy próbowałyby migrować
# bazę naraz.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
