"""
OITC Access Control System: MQTT to Pushover Bridge
Author: Michael Oberdorf <info@oberdorf-itc.de>
Date: 2021-01-02
Copyright (c) 2024, Michael Oberdorf IT-Consulting. All rights reserved.
This software may be modified and distributed under the terms of the Apache 2.0 license. See the LICENSE file for details.
"""
import sys
import os
import logging
import json
import ssl
import paho.mqtt.client as mqtt
import http.client, urllib

__author__ = "Michael Oberdorf <info@oberdorf-itc.de>"
__status__ = "production"
__date__ = "2026-03-18"
__version_info__ = ("1", "0", "0")
__version__ = ".".join(__version_info__)

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

def __validate_configuration() -> None:
    """
    Validate the configuration from environment variables.

    :return None
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
        with open(os.environ['PUSHOVER_USER_KEY_FILE'], 'r') as file:
            __pushover_user_key__ = file.read().strip()
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
        with open(os.environ['PUSHOVER_APP_TOKEN_FILE'], 'r') as file:
            __pushover_app_token__ = file.read().strip()
            if __pushover_app_token__ == "":
                raise ValueError(f"PUSHOVER_APP_TOKEN_FILE file {os.environ.get("PUSHOVER_APP_TOKEN_FILE")} is empty.")
    else:
        if os.environ.get("PUSHOVER_APP_TOKEN", None) is not None:
            log.debug("Use pushover app token from environment variable.")
            __pushover_app_token__ = os.environ.get("PUSHOVER_APP_TOKEN")


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

        __ca_cert_file__ = '/etc/ssl/certs/ca-certificates.crt'
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
        with open(os.environ.get("MQTT_PASSWORD_FILE", None), "r") as f:
            mqtt_pass = f.read().strip()
    if os.environ.get("MQTT_USERNAME", None) is not None and mqtt_pass is not None:
        log.debug("Set username ({}) and password for MQTT connection".format(os.environ.get("MQTT_USERNAME", None)))
        client.username_pw_set(os.environ.get("MQTT_USERNAME", None), mqtt_pass)

    # register callback functions
    client.on_connect = on_connect
    client.on_message = on_message

    return client

def on_connect(client: mqtt.Client, userdata: dict, flags: dict, rc: int) -> None:
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

    # check for return code
    if rc!=0:
        log.error(f"Error in connecting to MQTT Server, RC={rc}")
        sys.exit(1)

    # Subscribing in on_connect() means that if we lose the connection and reconnect then subscriptions will be renewed.
    for topic in [os.environ.get('MQTT_TOPIC_DOOR_ACCESS', None), os.environ.get('MQTT_TOPIC_ACS_STATUS', None)]:
        log.debug(f"MQTT client subscribing to topic: {topic}")
        client.subscribe(topic)

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

    # prepare pushover message title
    title = "[OITC Access Control System] " + PAYLOAD['userName'] + ' is '
    priority = 0
    if PAYLOAD['access'] != 'granted':
        title+= 'not '
        priority = 1
    title+= 'authorized to access resource at ' + PAYLOAD['accessTime']

    # prepare pushover message body
    message = 'User: ' + PAYLOAD['userName'] + ' (' + PAYLOAD['userID'] + ')' + "\n"
    message+= 'Access Point: ' + PAYLOAD['accessPoint'] + "\n"
    message+= 'is '
    if PAYLOAD['access'] != 'granted':
        message+= '<b>not</b> '
    message+= 'authorized to access resource' + "\n"
    message+= 'Access time: ' + PAYLOAD['accessTime']

    #open connection to pushover service
    log.debug(f"Open connection to pushover: https://{__pushover_server__}")
    conn = http.client.HTTPSConnection(__pushover_server__)
    
    # send push message
    log.debug(f"Send push message with title: {title} and message: {message}")
    conn.request("POST", "/1/messages.json",
      urllib.parse.urlencode({
      "token": __pushover_app_token__,
      "user": __pushover_user_key__,
      "title": title,
      "message": message,
      "priority": priority
      }), { "Content-type": "application/x-www-form-urlencoded" })

    # get repsonse
    conn.getresponse()

"""
###############################################################################
# M A I N
###############################################################################
"""
# initialize logger
if os.getenv("DEBUG", "false").lower() == "true":
    log = __initialize_logger(logging.DEBUG)
else:
    log = __initialize_logger(logging.INFO)

if __name__ == "__main__":
    log.info(f"Starting OITC Access Control System Pushover bridge service version {__version__}")

    # validate configuration
    __validate_configuration()

    # Initialize MQTT client
    client = __initialize_mqtt_client()
    log.debug("MQTT client initialized")
    # connect to MQTT server
    log.debug("Connecting to MQTT server {}:{}".format(os.environ.get("MQTT_SERVER", "localhost"), os.environ.get("MQTT_PORT", 1883)))
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