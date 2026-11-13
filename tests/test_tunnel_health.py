import io
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from deploy.tunnel_health import TunnelHealth, probe_ready


class TunnelHealthTests(unittest.TestCase):
    def test_startup_grace_and_probe_interval(self):
        probe = Mock(return_value=(False, 'disconnected'))
        health = TunnelHealth(0)
        self.assertFalse(health.should_restart(119, probe))
        probe.assert_not_called()
        self.assertFalse(health.should_restart(120, probe))
        self.assertFalse(health.should_restart(121, probe))
        self.assertEqual(probe.call_count, 1)

    def test_persistent_outage_requests_restart(self):
        health = TunnelHealth(0)
        for now in (120, 135, 150, 165):
            self.assertFalse(health.should_restart(now, lambda: (False, 'offline')))
        self.assertTrue(health.should_restart(180, lambda: (False, 'offline')))
        self.assertEqual(health.last_error, 'offline')

    def test_recovery_resets_outage_window(self):
        health = TunnelHealth(0)
        health.should_restart(120, lambda: (False, 'offline'))
        health.should_restart(165, lambda: (True, '1 active connection'))
        self.assertFalse(health.should_restart(180, lambda: (False, 'offline')))
        self.assertFalse(health.should_restart(225, lambda: (False, 'offline')))
        self.assertTrue(health.should_restart(240, lambda: (False, 'offline')))

    def test_probe_requires_connections_and_bounded_direct_request(self):
        for body, expected in ((b'{"readyConnections":4}', True),
                               (b'{"readyConnections":0}', False), (b'garbage', False),
                               (b'null', False), (b'[]', False)):
            response = Mock(status=200)
            response.read.return_value = body
            opener = Mock()
            opener.open.return_value.__enter__ = Mock(return_value=response)
            opener.open.return_value.__exit__ = Mock(return_value=False)
            with patch('deploy.tunnel_health.urllib.request.build_opener', return_value=opener):
                self.assertEqual(probe_ready()[0], expected)
            opener.open.assert_called_once_with('http://127.0.0.1:20246/ready', timeout=2)

    def test_probe_handles_http_and_network_failure(self):
        for error in (HTTPError('http://localhost', 503, 'not ready', {}, io.BytesIO()),
                      TimeoutError('timeout'), ConnectionRefusedError('refused')):
            opener = Mock()
            opener.open.side_effect = error
            with patch('deploy.tunnel_health.urllib.request.build_opener', return_value=opener):
                self.assertFalse(probe_ready()[0])
