"""
Unit tests for src/app/service.py

Tests cover:
- Message preparation functions
- MQTT callback functions
- Module imports
"""

import datetime
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import pytz

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from app import service


# Initialize module-level variables that tests depend on
@pytest.fixture(autouse=True)
def setup_service_module():
    """Setup module-level variables before each test"""
    # Set up mock metrics before each test
    original_metrics = getattr(service, 'metrics', None)
    service.metrics = {
        "mqtt_messages": MagicMock(),
        "mqtt_messages_refused": MagicMock(),
        "acs_access_granted": MagicMock(return_value=MagicMock()),
        "acs_access_denied": MagicMock(return_value=MagicMock()),
        "acs_status_messages": MagicMock(return_value=MagicMock()),
        "pushover_messages_sent": MagicMock(return_value=MagicMock()),
        "mqtt_connects": MagicMock(),
    }
    
    # Set up mock log
    service.log = MagicMock()
    
    yield
    
    # Restore original values
    if original_metrics is not None:
        service.metrics = original_metrics


class TestPrepareAccessMessage:
    """Test cases for __prepare_access_message function"""

    def test_prepare_access_message_granted(self):
        """Test preparing access granted message"""
        prepare_access = getattr(service, "__prepare_access_message")
        
        payload = {
            "user_display_name": "John Doe",
            "user_id": "user123",
            "status": "granted",
            "entrypoint_location": "Front Door",
            "timestamp": "2026-03-21T10:30:00Z",
            "entrypoint_ip": "192.168.1.100",
        }

        title, message, priority = prepare_access(payload)

        assert "John Doe" in title
        assert "authorized" in title
        assert priority == 0
        assert "user123" in message
        assert "Front Door" in message

    def test_prepare_access_message_denied(self):
        """Test preparing access denied message"""
        prepare_access = getattr(service, "__prepare_access_message")
        
        payload = {
            "user_display_name": "Jane Smith",
            "user_id": "user456",
            "status": "denied",
            "entrypoint_location": "Back Door",
            "timestamp": "2026-03-21T10:30:00Z",
            "entrypoint_ip": "192.168.1.101",
        }

        title, message, priority = prepare_access(payload)

        assert "Jane Smith" in title
        assert "not authorized" in title
        assert priority == 1
        assert "<b>not</b>" in message

    def test_prepare_access_message_missing_fields(self):
        """Test preparing access message with missing optional fields"""
        prepare_access = getattr(service, "__prepare_access_message")
        
        payload = {
            "status": "granted",
            "entrypoint_ip": "192.168.1.100",
        }

        title, message, priority = prepare_access(payload)

        assert "Unknown User" in title
        assert "Unknown ID" in message
        assert "Unknown Entrypoint" in message
        assert priority == 0

    def test_prepare_access_message_with_unknown_status(self):
        """Test preparing access message with unknown status"""
        prepare_access = getattr(service, "__prepare_access_message")
        
        payload = {
            "user_display_name": "Test User",
            "user_id": "user789",
            "status": "unknown",
            "entrypoint_location": "Main Gate",
            "timestamp": "2026-03-21T10:30:00Z",
            "entrypoint_ip": "192.168.1.102",
        }

        title, message, priority = prepare_access(payload)

        assert priority == 1
        assert "not authorized" in title


class TestPrepareStatusMessage:
    """Test cases for __prepare_status_message function"""

    def test_prepare_status_message_info(self):
        """Test preparing info status message"""
        prepare_status = getattr(service, "__prepare_status_message")
        
        payload = {
            "severity": "info",
            "status": "System OK",
            "description": "System is operating normally",
        }

        title, message, priority = prepare_status(payload)

        assert "INFO" in title
        assert "System OK" in title
        assert priority == 0
        assert "System is operating normally" in message

    def test_prepare_status_message_warning(self):
        """Test preparing warning status message"""
        prepare_status = getattr(service, "__prepare_status_message")
        
        payload = {
            "severity": "warning",
            "status": "Low Memory",
            "description": "System memory is running low",
        }

        title, message, priority = prepare_status(payload)

        assert "WARNING" in title
        assert priority == 1
        assert "System memory is running low" in message

    def test_prepare_status_message_error(self):
        """Test preparing error status message"""
        prepare_status = getattr(service, "__prepare_status_message")
        
        payload = {
            "severity": "error",
            "status": "Connection Lost",
            "description": "Connection to database lost",
        }

        title, message, priority = prepare_status(payload)

        assert "ERROR" in title
        assert priority == 1

    def test_prepare_status_message_case_insensitive_severity(self):
        """Test that severity is processed case-insensitively"""
        prepare_status = getattr(service, "__prepare_status_message")
        
        payloads = [
            {"severity": "INFO", "status": "OK", "description": "Test"},
            {"severity": "Info", "status": "OK", "description": "Test"},
            {"severity": "info", "status": "OK", "description": "Test"},
        ]

        titles = []
        for payload in payloads:
            title, _, _ = prepare_status(payload)
            titles.append(title)

        assert all("INFO" in t for t in titles)

    def test_prepare_status_message_unknown_severity(self):
        """Test preparing status message with unknown severity"""
        prepare_status = getattr(service, "__prepare_status_message")
        
        payload = {
            "severity": "unknown",
            "status": "Unknown Status",
            "description": "Unknown status message",
        }

        title, message, priority = prepare_status(payload)

        assert "UNKNOWN" in title
        assert priority == 0

    def test_prepare_status_message_missing_description(self):
        """Test preparing status message with missing description"""
        prepare_status = getattr(service, "__prepare_status_message")
        
        payload = {
            "severity": "info",
            "status": "System OK",
        }

        title, message, priority = prepare_status(payload)

        assert "No message provided" in message


class TestOnConnect:
    """Test cases for on_connect callback function"""

    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_connect_success(self):
        """Test on_connect callback with successful connection"""
        mock_client = MagicMock()
        
        userdata = {}
        flags = {"session present": 0}
        rc = 0
        properties = MagicMock()

        service.on_connect(mock_client, userdata, flags, rc, properties)

        service.metrics["mqtt_connects"].inc.assert_called_once()
        assert mock_client.subscribe.call_count == 2

    @patch("sys.exit")
    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_connect_failure(self, mock_exit):
        """Test on_connect callback with connection failure"""
        mock_client = MagicMock()
        
        userdata = {}
        flags = {"session present": 0}
        rc = 1
        properties = MagicMock()

        service.on_connect(mock_client, userdata, flags, rc, properties)

        mock_exit.assert_called_with(1)


class TestOnSubscribe:
    """Test cases for on_subscribe callback function"""

    def test_on_subscribe_success(self):
        """Test on_subscribe callback with successful subscription"""
        mock_client = MagicMock()
        userdata = {}
        mid = 1
        reason_code = MagicMock()
        reason_code.is_failure = False
        reason_code.value = 0
        reason_code_list = [reason_code]
        properties = MagicMock()

        service.on_subscribe(mock_client, userdata, mid, reason_code_list, properties)

    def test_on_subscribe_failure(self):
        """Test on_subscribe callback with failed subscription"""
        mock_client = MagicMock()
        userdata = {}
        mid = 1
        reason_code = MagicMock()
        reason_code.is_failure = True
        reason_code_list = [reason_code]
        properties = MagicMock()

        service.on_subscribe(mock_client, userdata, mid, reason_code_list, properties)


class TestOnMessage:
    """Test cases for on_message callback function"""

    @patch("http.client.HTTPSConnection")
    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_message_access_granted(self, mock_https):
        """Test on_message callback with access granted event"""
        mock_client = MagicMock()
        userdata = {}

        timestamp = datetime.datetime.now(pytz.UTC).isoformat()

        payload = {
            "user_display_name": "John Doe",
            "user_id": "user123",
            "status": "granted",
            "entrypoint_location": "Front Door",
            "timestamp": timestamp,
            "entrypoint_ip": "192.168.1.100",
        }

        mock_msg = MagicMock()
        mock_msg.topic = "topic/access"
        mock_msg.qos = 1
        mock_msg.retain = False
        mock_msg.payload = json.dumps(payload).encode("utf-8")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.reason = "OK"
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_response
        mock_https.return_value = mock_conn

        with patch.object(service, "__local_tz__", pytz.UTC):
            service.on_message(mock_client, userdata, mock_msg)
            service.metrics["mqtt_messages"].inc.assert_called()

    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_message_timestamp_too_old(self):
        """Test on_message callback refuses old messages"""
        mock_client = MagicMock()
        userdata = {}

        old_timestamp = (datetime.datetime.now(pytz.UTC) - datetime.timedelta(seconds=15)).isoformat()

        payload = {
            "user_display_name": "John Doe",
            "timestamp": old_timestamp,
        }

        mock_msg = MagicMock()
        mock_msg.topic = "topic/access"
        mock_msg.payload = json.dumps(payload).encode("utf-8")

        with patch.object(service, "__local_tz__", pytz.UTC):
            service.on_message(mock_client, userdata, mock_msg)
            service.metrics["mqtt_messages_refused"].inc.assert_called()

    @patch("http.client.HTTPSConnection")
    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_message_access_denied(self, mock_https):
        """Test on_message callback with access denied event"""
        mock_client = MagicMock()
        userdata = {}

        timestamp = datetime.datetime.now(pytz.UTC).isoformat()

        payload = {
            "user_display_name": "Jane Smith",
            "user_id": "user456",
            "status": "denied",
            "entrypoint_location": "Back Door",
            "timestamp": timestamp,
            "entrypoint_ip": "192.168.1.101",
        }

        mock_msg = MagicMock()
        mock_msg.topic = "topic/access"
        mock_msg.qos = 1
        mock_msg.retain = False
        mock_msg.payload = json.dumps(payload).encode("utf-8")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.reason = "OK"
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_response
        mock_https.return_value = mock_conn

        with patch.object(service, "__local_tz__", pytz.UTC):
            service.on_message(mock_client, userdata, mock_msg)
            service.metrics["mqtt_messages"].inc.assert_called()

    @patch("http.client.HTTPSConnection")
    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_message_status_message(self, mock_https):
        """Test on_message callback with status message"""
        mock_client = MagicMock()
        userdata = {}

        timestamp = datetime.datetime.now(pytz.UTC).isoformat()

        payload = {
            "severity": "warning",
            "status": "Low Memory",
            "description": "System memory is running low",
            "timestamp": timestamp,
        }

        mock_msg = MagicMock()
        mock_msg.topic = "topic/status"
        mock_msg.qos = 1
        mock_msg.retain = False
        mock_msg.payload = json.dumps(payload).encode("utf-8")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.reason = "OK"
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_response
        mock_https.return_value = mock_conn

        with patch.object(service, "__local_tz__", pytz.UTC):
            service.on_message(mock_client, userdata, mock_msg)
            service.metrics["mqtt_messages"].inc.assert_called()

    @patch("http.client.HTTPSConnection")
    @patch.dict(
        os.environ,
        {
            "MQTT_TOPIC_DOOR_ACCESS": "topic/access",
            "MQTT_TOPIC_ACS_STATUS": "topic/status",
        },
    )
    def test_on_message_unknown_topic(self, mock_https):
        """Test on_message callback with unknown topic"""
        mock_client = MagicMock()
        userdata = {}

        timestamp = datetime.datetime.now(pytz.UTC).isoformat()

        payload = {
            "timestamp": timestamp,
        }

        mock_msg = MagicMock()
        mock_msg.topic = "unknown/topic"
        mock_msg.qos = 1
        mock_msg.retain = False
        mock_msg.payload = json.dumps(payload).encode("utf-8")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.reason = "OK"
        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_response
        mock_https.return_value = mock_conn

        with patch.object(service, "__local_tz__", pytz.UTC):
            service.on_message(mock_client, userdata, mock_msg)
            service.metrics["mqtt_messages"].inc.assert_called()


class TestModuleImports:
    """Test that required modules are available"""

    def test_mqtt_module_available(self):
        """Test that paho.mqtt is available"""
        assert hasattr(service, "mqtt")

    def test_prometheus_module_available(self):
        """Test that prometheus_client is available"""
        assert hasattr(service, "prom")

    def test_pytz_module_available(self):
        """Test that pytz is available"""
        assert hasattr(service, "pytz")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
