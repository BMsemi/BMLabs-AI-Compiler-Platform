"""Bounded local readiness checks and sustained-outage detection for cloudflared."""
import json
import urllib.error
import urllib.request


def probe_ready(url='http://127.0.0.1:20246/ready'):
    # Loopback health checks must not depend on system proxy configuration.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=2) as response:
            payload = json.loads(response.read(4096))
            connections = payload.get('readyConnections', 0) if isinstance(payload, dict) else 0
            if response.status == 200 and isinstance(connections, int) and connections > 0:
                return True, f'{connections} active connections'
            return False, 'no active connections'
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return False, f'{type(exc).__name__}: {exc}'


class TunnelHealth:
    def __init__(self, started_at, grace=120, outage=60, interval=15):
        self.started_at = started_at
        self.grace = grace
        self.outage = outage
        self.interval = interval
        self.last_probe = None
        self.failed_since = None
        self.last_error = ''

    def should_restart(self, now, probe=probe_ready):
        if now - self.started_at < self.grace:
            return False
        if self.last_probe is not None and now - self.last_probe < self.interval:
            return False
        self.last_probe = now
        healthy, detail = probe()
        self.last_error = detail
        if healthy:
            self.failed_since = None
            return False
        if self.failed_since is None:
            self.failed_since = now
        return now - self.failed_since >= self.outage
