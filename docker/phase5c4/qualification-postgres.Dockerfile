FROM postgres:16@sha256:33f923b05f64ca54ac4401c01126a6b92afe839a0aa0a52bc5aeb5cc958e5f20

RUN apt-get update \
    && apt-get install --yes --no-install-recommends pgbackrest=2.58.0-1.pgdg13+1 \
    && install --directory --owner=postgres --group=postgres --mode=0750 \
        /tmp/pgbackrest /var/log/pgbackrest \
    && rm -rf /var/lib/apt/lists/*

COPY docker/phase5c4/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
