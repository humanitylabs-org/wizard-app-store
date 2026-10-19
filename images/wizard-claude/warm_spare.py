"""Single-use warm CLI spare, never a conversation/session cache.

Ported from Wisdom's broker: one tool-free fast process waits on stdin, is
consumed once and replaced off the request path. Secrets only live in the child
process environment, not in keys/logs. Every claimed resource is reaped by run().
"""
import atexit
import threading
import time


class WarmSpare:
    def __init__(self, ttl=600):
        self.ttl = ttl
        self.lock = threading.Lock()
        self.spare = None
        self.arming = False
        self.epoch = 0
        atexit.register(self.close)

    def close(self):
        with self.lock:
            row, self.spare = self.spare, None
            self.epoch += 1
        if row:
            row['dispose']()

    def take(self, key):
        with self.lock:
            row, self.spare = self.spare, None
        if not row:
            return None
        if row['key'] == key and row['expires'] > time.monotonic() and row['child'].poll() is None:
            return row['child'], row['dispose']
        row['dispose']()
        return None

    def arm(self, key, spawn):
        with self.lock:
            if self.arming or (self.spare and self.spare['key'] == key):
                return
            self.arming = True
            epoch = self.epoch
        def create():
            try:
                child, dispose = spawn()
                row = {'key':key,'child':child,'dispose':dispose,'expires':time.monotonic()+self.ttl}
                with self.lock:
                    if epoch != self.epoch:
                        dispose()
                        return
                    old, self.spare = self.spare, row
                if old:
                    old['dispose']()
                def expire():
                    with self.lock:
                        if self.spare is not row:
                            return
                        self.spare = None
                    row['dispose']()
                timer = threading.Timer(self.ttl, expire)
                timer.daemon = True
                timer.start()
            except Exception:
                pass  # A missing spare never changes request admission/error policy.
            finally:
                with self.lock:
                    self.arming = False
        threading.Thread(target=create, daemon=True).start()
