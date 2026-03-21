FROM alpine:3.23.3

LABEL maintainer="Michael Oberdorf IT-Consulting <info@oberdorf-itc.de>"
LABEL site.local.program.version="1.0.0"

ENV MQTT_SERVER=localhost \
    MQTT_PORT=1883 \
    MQTT_TLS_enabled=false \
    MQTT_TLS_no_hostname_validation=false \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PROMETHEUS_LISTENER_ADDR=0.0.0.0 \
    PROMETHEUS_LISTENER_PORT=8080

RUN apk upgrade --available --no-cache --update \
    && apk add --no-cache --update \
       ca-certificates=20251003-r0 \
       python3=3.12.12-r0 \
       py3-pip=25.1.1-r1 \
       curl=8.17.0-r1 \
    && addgroup -g 2100 -S pythonuser \
    && adduser -u 2100 -S pythonuser -G pythonuser \
    && rm -rf /var/cache/apk/* /tmp/* /var/tmp/*

COPY --chown=root:root /src /

RUN pip3 install --no-cache-dir -r /requirements.txt --break-system-packages

USER pythonuser:pythonuser
EXPOSE ${PROMETHEUS_LISTENER_PORT}
HEALTHCHECK --interval=1m --timeout=5s --retries=30 --start-period=5m \
            CMD curl -skSL http://localhost:${PROMETHEUS_LISTENER_PORT}/ -o /dev/null || exit 1

# Start Server
CMD ["python", "-u", "/app/service.py"]
