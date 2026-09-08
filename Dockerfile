# TC Lab — container image.
#
# This app manipulates the HOST's network stack, so the container must run with
# --network host and CAP_NET_ADMIN (see docker-compose.yml). It still gains a lot
# over an unconfined systemd root process: all other capabilities are dropped,
# no-new-privileges is set, and the root filesystem is read-only.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        iproute2 bridge-utils kmod \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    TC_LAB_STATE_DIR=/opt/tc_lab/state

WORKDIR /opt/tc_lab

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Ship the default impairment profiles as seed data; entrypoint copies them into
# the state volume on first run (the app only ever reads/writes state/profiles).
RUN mv profiles profiles.default \
    && chmod +x entrypoint.sh restore_network.sh restore_helper.py

EXPOSE 5000
ENTRYPOINT ["/opt/tc_lab/entrypoint.sh"]
