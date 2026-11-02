"""Loopback fixture for tests/claude-use-first-continue-ui.cjs: the real Claude pool_server (page + API + Use first
watcher) in front of the fake broker and fake original login from tests/claude-use-first-continue.py. No CLI, no
provider, no credentials. Control routes under /__fixture/ only exist here.
Usage: python3 -I tests/claude-use-first-fixture.py <port>"""
import importlib.util
import json
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('use_first_tests', Path(__file__).with_name('claude-use-first-continue.py'))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
pool = t.pool
pool.USE_FIRST_POLL = 0.3
STATE = {}


def reset():
    STATE['broker'] = t.Broker()
    pool.Hermes = STATE['broker']
    pool.LEGACY, pool.LEGACY_RENEW, pool.PASSWORD = t.Login(), None, ''
    pool.USE_FIRST.clear()


class Fixture(pool.Handler):
    def do_GET(self):
        if self.path == '/__fixture/calls':
            return self.send(200, {'actions': STATE['broker'].actions()})
        return super().do_GET()

    def do_POST(self):
        if self.path == '/__fixture/reset':
            reset()
            return self.send(200, {'ok': True})
        if self.path.startswith('/__fixture/submit/'):
            # The code pasted somewhere else (another window, after the app reloaded): not through this page.
            job = STATE['broker'].request('claude', '/operations', {'action': 'submit', 'operation': t.OP, 'code': self.path.rsplit('/', 1)[1]})
            return self.send(200, {'status': job.get('status')})
        return super().do_POST()


if __name__ == '__main__':
    reset()
    server = pool.Server(('127.0.0.1', int(sys.argv[1])), Fixture)
    print(json.dumps({'ready': server.server_port}), flush=True)
    server.serve_forever()
