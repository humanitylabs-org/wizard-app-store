"""Registry guard policy tests; never contact a registry or use credentials."""
import importlib.util
import io
from email.message import Message
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location('release_guard', Path(__file__).with_name('release_guard.py'))
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
DIGEST = 'sha256:' + 'a' * 64

class GuardTests(unittest.TestCase):
    def test_only_404_is_absence(self):
        for code in (401, 403, 404, 429, 500):
            error = urllib.error.HTTPError('https://ghcr.io', code, 'test', Message(), None)
            with patch.object(guard.urllib.request, 'urlopen', side_effect=error):
                if code == 404: self.assertIsNone(guard.manifest('test', 'synthetic'))
                else:
                    with self.assertRaises(RuntimeError): guard.manifest('test', 'synthetic')

    def check_policy(self, release, values, expected=None, rejected=False):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            env={'GITHUB_ACTOR':'test','GH_TOKEN':'synthetic','GITHUB_SHA':'b'*40,'GITHUB_OUTPUT':str(output),'RELEASE_VERSION':release}
            with patch.dict(os.environ, env, clear=True), patch.object(guard.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"token":"synthetic"}')), patch.object(guard, 'manifest', side_effect=values):
                if rejected:
                    with self.assertRaises(RuntimeError): guard.main()
                else: guard.main()
            self.assertEqual(output.read_text() if output.exists() else None, expected)

    def test_fresh_version_and_source(self): self.check_policy('0.1.0', [None, None])
    def test_same_source_release_is_reused_not_pushed(self): self.check_policy('0.1.0', [DIGEST, DIGEST], 'digest='+DIGEST+'\n')
    def test_existing_version_with_other_source_is_refused(self): self.check_policy('0.1.0', [DIGEST, None], rejected=True)
    def test_existing_source_does_not_backfill_a_version(self): self.check_policy('0.1.0', [None, DIGEST], rejected=True)
    def test_main_sha_only_fresh(self): self.check_policy('', [None])
    def test_main_sha_only_reuse(self): self.check_policy('', [DIGEST], 'digest='+DIGEST+'\n')
    def test_unknown_version_is_refused(self): self.check_policy('latest', [], rejected=True)

if __name__ == '__main__': unittest.main()
