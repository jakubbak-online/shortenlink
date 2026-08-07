FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# "sh entrypoint.sh", nie "./entrypoint.sh" — web montuje cały katalog
# projektu (volumes: .:/app), więc w kontenerze liczy się prawo wykonania
# pliku z hosta, a na Windowsie bind mount go nie gwarantuje. Wywołanie
# przez sh nie wymaga bitu +x.
ENTRYPOINT ["sh", "entrypoint.sh"]
