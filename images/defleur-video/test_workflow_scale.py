"""Opt-in capacity test, not creative or original-footage acceptance.

Use VIDEO_RUN_SCALE=1 inside the image (bundled helpers at /opt/defleur).
Generates 184 seconds of tiny synthetic frames/tone and pads an ISO free box to
270 MiB. Exercises real HTTP streaming admission, decode and original PCM helper.
"""
import json
import os
from pathlib import Path
import resource
import secrets
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import wave

import service
from client import Client


@unittest.skipUnless(os.environ.get('VIDEO_RUN_SCALE') == '1', 'opt-in capacity measurement')
class ScaleTests(unittest.TestCase):
    def test_original_fixture_duration_and_byte_scale(self):
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='video-scale-', dir=os.environ.get('TMPDIR')) as temp:
            root = Path(temp)
            source = root / 'source.mp4'
            subprocess.run(['/usr/bin/ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=navy:s=160x90:r=5',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '184', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-threads', '1', '-c:a', 'aac', '-ac', '2', '-movflags', '+faststart', str(source)], check=True, timeout=90)
            target_bytes = 270 * 1024 * 1024
            padding = target_bytes - source.stat().st_size
            with source.open('ab') as f:
                f.write(struct.pack('>I4s', padding, b'free'))
                f.truncate(target_bytes)
            token = secrets.token_hex(24)
            server = service.make_server(root / 'state', token, port=0)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                client = Client(f'http://127.0.0.1:{server.server_port}', token)
                project = client.upload(source)
                self.assertAlmostEqual(project['duration'], 184, places=1)
                src = client.wait(client.request('POST', f"/v1/projects/{project['id']}/stages/source-audio", '{}')['id'], True)
                self.assertEqual(src['state'], 'needs_review', src.get('error'))
                job = client.request('POST', f"/v1/projects/{project['id']}/stages/pcm-assemble",
                    json.dumps({'audio_job': src['id'], 'segments': [{'start_s': 0, 'end_s': 184, 'reason': 'Capacity fixture, not a creative edit'}]}))
                job = client.wait(job['id'], True)
                self.assertEqual(job['state'], 'needs_review', job.get('error'))
                folder = server.store.path(project['id']) / (job['id'] + '.stage')
                ledger = json.loads((folder / 'edit-map.json').read_text())
                self.assertEqual(ledger['frames'], 920)
                self.assertEqual(ledger['samples'], 8832000)
                self.assertEqual(ledger['channels'], 2)
                with wave.open(str(folder / 'edited.wav')) as f:
                    self.assertEqual(f.getnframes(), 8832000)
                report = {'test': 'capacity only; padded synthetic source, not original creative fixture',
                    'source_bytes': target_bytes, 'source_seconds': project['duration'], 'source_dimensions': [160, 90],
                    'frames': ledger['frames'], 'samples': ledger['samples'], 'channels': ledger['channels'],
                    'stage_wall_seconds': job['result']['elapsed_s'], 'total_wall_seconds': round(time.monotonic() - started, 3),
                    'python_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    'helpers': job['result']['helpers'], 'delivery_approved': False}
                for name in ('memory.peak', 'memory.max', 'memory.swap.max', 'cpu.max'):
                    file = Path('/sys/fs/cgroup') / name
                    if file.is_file():
                        report[name] = file.read_text().strip()
                print(json.dumps(report, sort_keys=True), flush=True)
                client.request('DELETE', f"/v1/projects/{project['id']}")
                self.assertIsNone(client.request('GET', f"/v1/projects/{project['id']}", missing_ok=True))
            finally:
                server.shutdown(); server.store.close(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
