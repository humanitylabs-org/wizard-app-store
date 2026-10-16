"""Token-free bridge to the authenticated Hermes dashboard."""
import http.cookiejar
import json
import os
import threading
import urllib.request

class Hermes:
    lock = threading.Lock()
    opener = None

    @classmethod
    def accounts(cls, provider):
        prefix = 'WIZARD_' + provider.upper()
        origin = os.environ.get(prefix + '_HERMES_URL', 'http://hermes-agent:9119').rstrip('/')
        with cls.lock:
            if cls.opener is None:
                password = os.environ.get(prefix + '_HERMES_PASSWORD', '')
                if not password:
                    raise RuntimeError('Hermes dashboard not configured')
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                data = json.dumps({'provider': 'basic', 'username': os.environ.get(prefix + '_HERMES_USER', 'hermes'), 'password': password}).encode()
                request = urllib.request.Request(origin + '/auth/password-login', data=data, headers={'Content-Type': 'application/json'}, method='POST')
                with opener.open(request, timeout=15) as response:
                    response.read()
                cls.opener = opener
            try:
                with cls.opener.open(origin + '/api/plugins/wizard-os/provider-accounts/' + provider, timeout=45) as response:
                    result = json.load(response)
                if result.get('owner') != 'hermes' or result.get('provider') != provider or not isinstance(result.get('accounts'), list):
                    raise ValueError('Invalid inventory')
                return result
            except Exception:
                cls.opener = None
                raise RuntimeError('Hermes account inventory unavailable') from None
