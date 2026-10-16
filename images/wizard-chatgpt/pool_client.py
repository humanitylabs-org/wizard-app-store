"""Authenticated dashboard bridge; provider credentials never leave Hermes."""
import http.cookiejar
import json
import os
import threading
import urllib.request
import urllib.error

class BridgeError(RuntimeError):
    def __init__(self, status=503):
        super().__init__('Hermes operation unavailable')
        self.status = status if status in (404, 409, 413) else 503


class Hermes:
    lock = threading.Lock()
    opener = None

    @classmethod
    def request(cls, provider, suffix='', body=None):
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
                req = urllib.request.Request(origin + '/api/plugins/wizard-os/provider-accounts/' + provider + suffix,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type': 'application/json', 'X-Wizard-Account-Action': '1'},
                    method='POST' if body is not None else 'GET')
                with cls.opener.open(req, timeout=45) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                cls.opener = None
                status = error.code
                error.close()
                raise BridgeError(status) from None
            except Exception:
                cls.opener = None
                # Never automatically retry a start/submit/remove after ambiguity.
                raise RuntimeError('Hermes operation unavailable; refresh before retrying') from None

    @classmethod
    def accounts(cls, provider):
        result = cls.request(provider)
        if result.get('owner') != 'hermes' or result.get('provider') != provider or not isinstance(result.get('accounts'), list):
            raise RuntimeError('Invalid inventory')
        return result
