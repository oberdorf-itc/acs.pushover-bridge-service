"""
OITC Access Control System: MQTT to Pushover Bridge
Author: Michael Oberdorf <info@oberdorf-itc.de>
Date: 2021-01-02
Copyright (c) 2021, Michael Oberdorf IT-Consulting. All rights reserved.
This software may be modified and distributed under the terms of the Apache 2.0 license. See the LICENSE file for details.
"""

import datetime
import http.client
import json
import logging
import os
import ssl
import sys
import urllib

import paho.mqtt.client as mqtt
import prometheus_client as prom
import pytz

__author__ = "Michael Oberdorf <info@oberdorf-itc.de>"
__status__ = "production"
__date__ = "2026-03-19"
__version_info__ = ("1", "0", "0")
__version__ = ".".join(__version_info__)

__local_tz__ = pytz.timezone(os.environ.get("TZ", "UTC"))
__pushover_server__ = "api.pushover.net:443"
__pushover_app_token__ = None
__pushover_user_key__ = None

"""
###############################################################################
# F U N C T I O N S
###############################################################################
"""


def __initialize_logger(severity: int = logging.INFO) -> logging.Logger:
    """
    Initialize the logger with the given severity level.

    :param severity int: The optional severity level for the logger. (default: 20 (INFO))
    :return logging.RootLogger: The initialized logger.
    :raise ValueError: If the severity level is not valid.
    :raise TypeError: If the severity level is not an integer.
    :raise Exception: If the logger cannot be initialized.
    """
    valid_severity = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]
    if severity not in valid_severity:
        raise ValueError(f"Invalid severity level: {severity}. Must be one of {valid_severity}.")

    log = logging.getLogger()
    log_handler = logging.StreamHandler(sys.stdout)

    log.setLevel(severity)
    log_handler.setLevel(severity)
    log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    log_handler.setFormatter(log_formatter)
    log.addHandler(log_handler)

    return log


def __validate_configuration() -> tuple[str, str]:
    """
    Validate the configuration from environment variables.

    :return tuple[str, str]: The validated pushover app token and user key.
    :raise ValueError: If the configuration is not valid.
    :raise Exception: If the configuration cannot be validated.
    """
    if os.environ.get("MQTT_SERVER", None) is None:
        raise ValueError("MQTT_SERVER environment variable is not set.")
    if os.environ.get("MQTT_TOPIC_DOOR_ACCESS", None) is None:
        raise ValueError("MQTT_TOPIC_DOOR_ACCESS environment variable is not set.")
    if os.environ.get("MQTT_TOPIC_ACS_STATUS", None) is None:
        raise ValueError("MQTT_TOPIC_ACS_STATUS environment variable is not set.")

    # validate and read pushover user key from environment variables or files
    if os.environ.get("PUSHOVER_USER_KEY", None) is None and os.environ.get("PUSHOVER_USER_KEY_FILE", None) is None:
        raise ValueError("PUSHOVER_USER_KEY or PUSHOVER_USER_KEY_FILE environment variable must be set.")
    if os.environ.get("PUSHOVER_USER_KEY_FILE", None) is not None:
        if not os.path.isfile(os.environ.get("PUSHOVER_USER_KEY_FILE", None)):
            raise ValueError(f"PUSHOVER_USER_KEY_FILE file {os.environ.get("PUSHOVER_USER_KEY_FILE")} not found.")
        with open(os.environ["PUSHOVER_USER_KEY_FILE"]) as file:
            __pushover_user_key__ = file.read().strip().replace("\n", "")
            if __pushover_user_key__ == "":
                raise ValueError(f"PUSHOVER_USER_KEY_FILE file {os.environ.get("PUSHOVER_USER_KEY_FILE")} is empty.")
    else:
        if os.environ.get("PUSHOVER_USER_KEY", None) is not None:
            log.debug("Use pushover user key from environment variable.")
            __pushover_user_key__ = os.environ.get("PUSHOVER_USER_KEY")

    # validate and read pushover app token from environment variables or files
    if os.environ.get("PUSHOVER_APP_TOKEN", None) is None and os.environ.get("PUSHOVER_APP_TOKEN_FILE", None) is None:
        raise ValueError("PUSHOVER_APP_TOKEN or PUSHOVER_APP_TOKEN_FILE environment variable must be set.")
    if os.environ.get("PUSHOVER_APP_TOKEN_FILE", None) is not None:
        if not os.path.isfile(os.environ.get("PUSHOVER_APP_TOKEN_FILE", None)):
            raise ValueError(f"PUSHOVER_APP_TOKEN_FILE file {os.environ.get("PUSHOVER_APP_TOKEN_FILE")} not found.")
        with open(os.environ["PUSHOVER_APP_TOKEN_FILE"]) as file:
            __pushover_app_token__ = file.read().strip().replace("\n", "")
            if __pushover_app_token__ == "":
                raise ValueError(f"PUSHOVER_APP_TOKEN_FILE file {os.environ.get("PUSHOVER_APP_TOKEN_FILE")} is empty.")
    else:
        if os.environ.get("PUSHOVER_APP_TOKEN", None) is not None:
            log.debug("Use pushover app token from environment variable.")
            __pushover_app_token__ = os.environ.get("PUSHOVER_APP_TOKEN")

    return __pushover_app_token__, __pushover_user_key__


def __initialize_prometheus_exporter() -> dict:
    """
    Intialize and start the prometheus exporter endpoint

    :return The different initialized prometheus metrics as a dict of objects
    :rtype dict
    :raise Exception: If the prometheus exporter cannot be initialized or started.
    """
    log.debug("def initialize_prometheus_exporter() -> dict:")

    m = {}
    # TODO: Define prometheus metrics here, e.g.:
    # - a counter for the number of door access events received (overall and per entry point)
    # - a counter for the number of access granted and denied events received (overall and per entry point)

    prometheus_listener_addr = os.environ.get("PROMETHEUS_LISTENER_ADDR", "0.0.0.0")
    prometheus_listener_port = int(os.environ.get("PROMETHEUS_LISTENER_PORT", "8080"))
    log.info("Starting prometheus exporter listener: %s:%s", prometheus_listener_addr, prometheus_listener_port)
    s, t = prom.start_http_server(port=prometheus_listener_port, addr=prometheus_listener_addr)
    if not s or not t:
        raise RuntimeError("The Prometheus exporter http endpoint failed to start.")

    return m


def __initialize_mqtt_client() -> mqtt.Client:
    """
    Initialize the MQTT client with the given configuration from environment.

    :return mqtt.Client: The initialized MQTT client.
    :raise ValueError: If the MQTT client configuration is not valid.
    :raise Exception: If the MQTT client cannot be initialized.
    """
    if os.environ.get("MQTT_CLIENT_ID", None) is not None:
        log.debug("Use MQTT client ID: {}".format(os.environ.get("MQTT_CLIENT_ID", None)))

    if os.environ.get("MQTT_PROTOCOL_VERSION") == "5":
        log.debug("MQTT protocol version 5")
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=os.environ.get("MQTT_CLIENT_ID", None),
            userdata=None,
            transport="tcp",
            protocol=mqtt.MQTTv5,
        )
    else:
        log.debug("MQTT protocol version 3.1.1")
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=os.environ.get("MQTT_CLIENT_ID", None),
            clean_session=True,
            userdata=None,
            transport="tcp",
            protocol=mqtt.MQTTv311,
        )

    # configure TLS
    if os.environ.get("MQTT_TLS", "false").lower() == "true":
        log.debug("Configure MQTT connection to use TLS encryption.")

        __ca_cert_file__ = "/etc/ssl/certs/ca-certificates.crt"
        if os.environ.get("REQUESTS_CA_BUNDLE", None) is not None:
            __ca_cert_file__ = os.environ.get("REQUESTS_CA_BUNDLE")
        if os.environ.get("MQTT_CACERT_FILE", None) is not None:
            __ca_cert_file__ = os.environ.get("MQTT_CACERT_FILE")

        if os.environ.get("MQTT_TLS_INSECURE", "false").lower() == "true":
            log.debug("Configure MQTT connection to use TLS with insecure mode.")
            client.tls_set(
                ca_certs=__ca_cert_file__,
                cert_reqs=ssl.CERT_NONE,
                tls_version=ssl.PROTOCOL_TLSv1_2,
                ciphers=None,
            )
            client.tls_insecure_set(True)
        else:
            log.debug("Configure MQTT connection to use TLS with secure mode.")
            client.tls_set(
                ca_certs=__ca_cert_file__,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLSv1_2,
                ciphers=None,
            )
            client.tls_insecure_set(False)

    # configure authentication
    mqtt_pass = None
    if os.environ.get("MQTT_PASSWORD", None) is not None:
        mqtt_pass = os.environ.get("MQTT_PASSWORD")
    if os.environ.get("MQTT_PASSWORD_FILE", None) is not None:
        if not os.path.isfile(os.environ.get("MQTT_PASSWORD_FILE", None)):
            raise ValueError("MQTT password file {} not found.".format(os.environ.get("MQTT_PASSWORD_FILE", None)))
        with open(os.environ.get("MQTT_PASSWORD_FILE", None)) as f:
            mqtt_pass = f.read().strip().replace("\n", "")
    if os.environ.get("MQTT_USERNAME", None) is not None and mqtt_pass is not None:
        log.debug("Set username ({}) and password for MQTT connection".format(os.environ.get("MQTT_USERNAME", None)))
        client.username_pw_set(os.environ.get("MQTT_USERNAME", None), mqtt_pass)

    # register callback functions
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe

    return client


def on_connect(client: mqtt.Client, userdata: dict, flags: dict, rc: int, properties: mqtt.Properties) -> None:
    """
    on_connect - The MQTT callback for when the client receives a CONNACK response from the server.

    :param client: The object of the MQTT connection
    :type client: paho.mqtt.client.Client
    :param userdata: the user data of the MQTT connection
    :type userdata: dict
    :param flags: connection parameters
    :type flags: dict
    :param rc: the return code
    :type rc: int
    :return None
    """
    log.debug(f"MQTT client connected with result code {rc}")
    log.debug(f"MQTT connection flags: {flags}")
    log.debug(f"MQTT connection userdata: {userdata}")
    log.debug(f"MQTT connection properties: {properties}")

    # check for return code
    if rc != 0:
        log.error(f"Error in connecting to MQTT Server, RC={rc}")
        sys.exit(1)

    # Subscribing in on_connect() means that if we lose the connection and reconnect then subscriptions will be renewed.
    for topic in [os.environ.get("MQTT_TOPIC_DOOR_ACCESS", None), os.environ.get("MQTT_TOPIC_ACS_STATUS", None)]:
        log.debug(f"MQTT client subscribing to topic: {topic}")
        client.subscribe(topic)


def on_subscribe(
    client: mqtt.Client, userdata: dict, mid: int, reason_code_list: list, properties: mqtt.Properties
) -> None:
    """
    on_subscribe - The MQTT callback for when the client receives a SUBACK response from the server.

    :param client: The object of the MQTT connection
    :type client: paho.mqtt.client.Client
    :param userdata: the user data of the MQTT connection
    :type userdata: dict
    :param mid: the message ID of the subscribe request
    :type mid: int
    :param reason_code_list: the list of reason codes for the subscribe request
    :type reason_code_list: list
    :param properties: the MQTT properties of the subscribe response
    :type properties: paho.mqtt.client.MQTTProperties
    :return None
    """
    log.debug(
        f"MQTT client received SUBACK for message ID {mid} with reason codes {reason_code_list} and properties {properties}"
    )
    log.debug(f"MQTT client userdata: {userdata}")
    if reason_code_list[0].is_failure:
        log.error(f"Broker rejected you subscription: {reason_code_list[0]}")
    else:
        log.debug(f"Broker granted the following QoS: {reason_code_list[0].value}")


def on_message(client: mqtt.Client, userdata: dict, msg: mqtt.MQTTMessage) -> None:
    """
    on_message - The MQTT callback for when a PUBLISH message is received from the server.

    :param client: the object of the MQTT connection
    :type client: paho.mqtt.client.Client
    :param userdata: the user data of the MQTT connection
    :type userdata: dict
    :param msg: the object of the MQTT message received
    :type msg: paho.mqtt.client.MQTTMessage
    :return None
    """
    log.debug(f"MQTT message received on topic {msg.topic} with QoS {msg.qos} and retain flag {msg.retain}")

    # parse message payload as JSON object
    PAYLOAD = json.loads(str(msg.payload.decode("utf-8")))
    log.debug(f"MQTT message payload: {PAYLOAD}")

    # parse timestamp from payload and compare with current time to check if message is not too old (older than 10 seconds)
    timestamp = PAYLOAD.get("timestamp", None)
    if timestamp:
        # Convert timestamp to datetime object
        msg_timestamp = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        # Get current time
        current_time = datetime.datetime.now(__local_tz__)
        # Check if message is older than 10 seconds
        if (current_time - msg_timestamp).total_seconds() > 10:
            log.warning(f"MQTT message is too old: {timestamp}")
            return

    if mqtt.topic_matches_sub(os.environ.get("MQTT_TOPIC_ACS_STATUS", None), msg.topic):
        title, message, priority = __prepare_status_message(PAYLOAD)
    elif mqtt.topic_matches_sub(os.environ.get("MQTT_TOPIC_DOOR_ACCESS", None), msg.topic):
        title, message, priority = __prepare_access_message(PAYLOAD)

    # open connection to pushover service
    log.debug(f"Open connection to pushover: https://{__pushover_server__}")
    conn = http.client.HTTPSConnection(__pushover_server__, timeout=2)

    # send push message
    log.debug(f"Send push message with priority {priority}, title: {title} and message: {message}")
    conn.request(
        method="POST",
        url="/1/messages.json",
        body=urllib.parse.urlencode(
            {
                "token": __pushover_app_token__,
                "user": __pushover_user_key__,
                "title": title,
                "message": message,
                "priority": priority,
            }
        ),
        headers={"Content-type": "application/x-www-form-urlencoded"},
    )
    log.debug(f"Connected to pushover at {conn.sock.getpeername()}")

    # get repsonse
    response = conn.getresponse()
    if response.status != 200:
        log.error(f"Error in sending push message to pushover: {response.status} {response.reason}")
    else:
        log.debug(f"Push message sent successfully to pushover: {response.status} {response.reason}")


def __prepare_access_message(payload: dict) -> tuple[str, str, int]:
    """
    Prepare the message to be sent to pushover based on the payload of the MQTT message received.

    :param payload: The payload of the MQTT message received.
    :type payload: dict
    :return tuple[str, str, int]: The formatted title, message, and priority to be sent to pushover.
    """

    # prepare pushover message title
    title = "[OITC Access Control System] " + payload.get("user_display_name", "Unknown User") + " is "
    if payload.get("status") != "granted":
        title += "not "
    title += "authorized to access resource at " + payload.get("timestamp", "Unknown Time")

    # prepare pushover message
    message = (
        "User: "
        + payload.get("user_display_name", "Unknown User")
        + " ("
        + payload.get("user_id", "Unknown ID")
        + ")"
        + "\n"
    )
    message += "Entrypoint: " + payload.get("entrypoint_location", "Unknown Entrypoint") + "\n"
    message += "is "
    if payload.get("status") != "granted":
        message += "<b>not</b> "
    message += "authorized to access resource" + "\n"
    message += "Access time: " + payload.get("timestamp", "Unknown Time")

    # set message priority to 1 if access is not granted, otherwise 0
    priority = 0
    if payload.get("status") != "granted":
        priority = 1

    return title, message, priority


def __prepare_status_message(payload: dict) -> tuple[str, str, int]:
    """
    Prepare the message to be sent to pushover based on the payload of the MQTT message received.

    :param payload: The payload of the MQTT message received.
    :type payload: dict
    :return tuple[str, str, int]: The formatted title, message, and priority to be sent to pushover.
    """
    # set message priority to 1 if acs status is not ok, otherwise 0
    severity = payload.get("severity", "unknown").lower().strip()
    priority = 0
    if severity == "info":
        priority = 0
    elif severity == "warning":
        priority = 1
    elif severity == "error":
        priority = 1
    else:
        priority = 0

    # prepare pushover message title
    title = f"[OITC Access Control System] {severity.upper()} {payload.get('status', '')}"

    # prepare pushover message
    message = payload.get("description", "No message provided.") + "\n"

    return title, message, priority


"""
###############################################################################
# M A I N
###############################################################################
"""
if __name__ == "__main__":
    # initialize logger
    if os.getenv("DEBUG", "false").lower() == "true":
        log = __initialize_logger(logging.DEBUG)
    else:
        log = __initialize_logger(logging.INFO)
    log.info(f"Starting OITC Access Control System Pushover bridge service version {__version__}")

    # validate configuration
    __pushover_app_token__, __pushover_user_key__ = __validate_configuration()

    # initialize prometheus exporter
    metrics = __initialize_prometheus_exporter()

    # Initialize MQTT client
    client = __initialize_mqtt_client()
    log.debug("MQTT client initialized")
    # connect to MQTT server
    log.debug(
        "Connecting to MQTT server {}:{}".format(
            os.environ.get("MQTT_SERVER", "localhost"), os.environ.get("MQTT_PORT", 1883)
        )
    )
    try:
        client.connect(os.environ.get("MQTT_SERVER", "localhost"), int(os.environ.get("MQTT_PORT", 1883)), 60)
    except ssl.SSLCertVerificationError as e:
        log.error("SSL certificate verification error: {}".format(e))
        sys.exit(1)
    log.debug("Connected to MQTT server")

    client.loop_forever()

    client.disconnect()

    log.info(f"Stopping OITC Access Control System Pushover bridge service version {__version__}")
    sys.exit()
