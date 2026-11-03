# pretix Community for the S+K Verlag ticket shop, deployed on Railway.
#
# Based on the official image (pinned version, see README "Updates").
# Plugins come from requirements.txt so Dependabot can update them.
FROM pretix/standalone:2026.9.0

USER root

# pretix-zugferd needs Ghostscript to turn the invoice into PDF/A-3; without
# it no e-invoice XML is embedded (and nothing complains).
RUN apt-get update && \
    apt-get install -y --no-install-recommends ghostscript && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/pretix-deploy-requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/pretix-deploy-requirements.txt && \
    rm /tmp/pretix-deploy-requirements.txt

COPY deploy/entrypoint.sh /usr/local/bin/railway-entrypoint
COPY deploy/cron-loop.sh deploy/secure_default_admin.py /usr/local/share/pretix-deploy/
# pretixtask.conf replaces the official file (limits Celery workers),
# pretixcron.conf adds the periodic job the official image lacks.
COPY deploy/supervisord/pretixtask.conf deploy/supervisord/pretixcron.conf /etc/supervisord/
RUN chmod 0755 /usr/local/bin/railway-entrypoint /usr/local/share/pretix-deploy/cron-loop.sh

# Rebuild static files and translations so the plugins' assets are included
# (official procedure: https://docs.pretix.eu/self-hosting/installation/docker_smallscale/)
USER pretixuser
RUN cd /pretix/src && make production

# The entrypoint starts as root only to fix the volume permissions (Railway
# mounts volumes owned by root) and then drops to pretixuser.
USER root

# Railway containers see all CPUs of the host, and pretix derives its worker
# counts from that. Fixed values keep memory use predictable.
ENV NUM_WORKERS=3 \
    CELERY_CONCURRENCY=2 \
    PRETIX_CRON_INTERVAL_SECONDS=300

EXPOSE 80
ENTRYPOINT ["/usr/local/bin/railway-entrypoint"]
CMD ["all"]
