#!/bin/sh
set -e

# Tylko usługa web ma nakładać migracje (ustawia RUN_MIGRATIONS=1 w
# docker-compose.yml) - worker startuje równolegle z tym samym obrazem i
# tym samym entrypointem, więc bez tego dwa procesy próbowałyby migrować
# bazę naraz.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
    # CompressedManifestStaticFilesStorage wymaga collectstatic przed
    # startem (buduje staticfiles/staticfiles.json z hashami w nazwach) -
    # bez tego DEBUG=False nie znajdzie żadnego pliku statycznego.
    python manage.py collectstatic --noinput
fi

exec "$@"
