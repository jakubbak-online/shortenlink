#!/bin/sh
# Generuje .env pod produkcje z .env.example - podmienia SECRET_KEY i
# IP_SALT na losowe wartosci, ustawia DEBUG=False i ALLOWED_HOSTS z
# argumentu. Reszta (DB_*, REDIS_URL, CELERY_BROKER_URL) zostaje taka,
# jak w .env.example - domyslne wartosci pasuja do
# docker-compose.prod.yml (haslo do bazy tam jest na sztywno "shortenlink",
# wiec zmiana DB_PASSWORD tutaj bez zmiany tam zerwie polaczenie).
#
# Uzycie: ./scripts/gen_prod_env.sh <IP_lub_domena>
set -e

if [ -z "$1" ]; then
    echo "Uzycie: $0 <IP_lub_domena>" >&2
    exit 1
fi

if [ -f .env ]; then
    echo ".env juz istnieje - usun go najpierw (rm .env), jesli chcesz wygenerowac nowy." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Brak python3 - zainstaluj: sudo apt install -y python3" >&2
    exit 1
fi

HOST="$1"
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
IP_SALT=$(python3 -c "import secrets; print(secrets.token_hex(32))")

cp .env.example .env
sed -i "s#^SECRET_KEY=.*#SECRET_KEY=$SECRET_KEY#" .env
sed -i "s#^DEBUG=.*#DEBUG=False#" .env
sed -i "s#^ALLOWED_HOSTS=.*#ALLOWED_HOSTS=$HOST#" .env
sed -i "s#^IP_SALT=.*#IP_SALT=$IP_SALT#" .env

echo "Wygenerowano .env:"
echo "---"
cat .env
