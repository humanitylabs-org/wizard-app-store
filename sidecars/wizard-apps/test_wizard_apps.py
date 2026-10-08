"""Unit tests: deterministic core, idempotent Hermes adapter. Run: python3 -m unittest discover -s sidecars/wizard-apps"""
import json
import random
import tempfile
import unittest
from pathlib import Path

import hermes_adapter as adapter
import wizard_core as core

STORE = [
    {"id": "transcriber", "name": "Transcriber", "port": 8000, "short_desc": "Service: Local speech-to-text."},
    {"id": "defleur-video", "name": "DeFleur Video (Testing)", "port": 8787, "mcp_path": "/mcp",
     "short_desc": "Service: Edit videos."},
    {"id": "secret-drop", "name": "Secret Drop", "port": 8792, "short_desc": "Service: Secrets."},
    {"id": "browser", "name": "Browser", "port": 9222, "short_desc": "Service: Chromium."},
]
UP = {"defleur-video", "transcriber", "secret-drop"}
VIDEO_URL = "http://defleur-video:8787/mcp"


def refresh(state_dir, store, up=UP, fetch_fails=False, now=1000):
    def fetch(repo, ref):
        if fetch_fails:
            raise OSError("offline")
        return [dict(a) for a in store]
    return core.refresh(state_dir, "o/r", "main", now, fetch=fetch, tcp=lambda host, port: host in up,
                        mcp=lambda url: (True, ""))


class FakeHermes(adapter.Hermes):
    """Hermes with an in-memory config; run() mimics `hermes config set|unset` and records every call."""

    def __init__(self, home, servers=None):
        super().__init__(home, "hermes")
        self.data = dict(servers or {})
        (self.home / "skills").mkdir(parents=True, exist_ok=True)
        self.config.write_text("x: 1\n")

    def servers(self):
        return json.loads(json.dumps(self.data))

    def run(self, *args):
        self.calls.append(args)
        key = args[2].split(".", 1)[1]
        if args[1] == "set":
            self.data[key] = json.loads(args[3])
        else:
            self.data.pop(key, None)
        return True


class CoreTest(unittest.TestCase):
    def test_same_inputs_give_byte_identical_apps_json(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            refresh(a, STORE)
            first = (Path(a) / "apps.json").read_bytes()
            _, changed = refresh(a, STORE, now=1001)
            self.assertFalse(changed, "second run with the same inputs must not rewrite apps.json")
            self.assertEqual((Path(a) / "apps.json").read_bytes(), first)
            shuffled = STORE[:]
            random.Random(7).shuffle(shuffled)
            refresh(b, list(reversed(shuffled)), now=5000)
            self.assertEqual((Path(b) / "apps.json").read_bytes(), first, "store order and time must not matter")
        apps = json.loads(first)["apps"]
        self.assertEqual([a["id"] for a in apps], ["defleur-video", "secret-drop", "transcriber"])
        self.assertEqual(apps[0], {"id": "defleur-video", "name": "DeFleur Video (Testing)", "description": "Service: Edit videos.",
                                   "type": "mcp", "url": "http://defleur-video:8787", "mcp_url": VIDEO_URL,
                                   "mcp_ready": True, "note": ""})
        self.assertEqual((apps[2]["type"], apps[2]["mcp_url"]), ("http", None))

    def test_offline_falls_back_to_cache_then_builtin(self):
        with tempfile.TemporaryDirectory() as d:
            refresh(d, STORE[:1], up={"transcriber"})
            apps, _ = refresh(d, STORE, up={"transcriber", "defleur-video"}, fetch_fails=True, now=999999)
            self.assertEqual([a["id"] for a in apps], ["transcriber"], "offline: cached store list")
        with tempfile.TemporaryDirectory() as d:
            apps, _ = refresh(d, STORE, fetch_fails=True)
            self.assertEqual([a["id"] for a in apps], ["defleur-video", "secret-drop", "transcriber"], "built-in list")

    def test_parse_app_reads_mcp_path_and_internal_port(self):
        compose = {"services": {"x-app": {"x-runtipi": {"is_main": True, "internal_port": 8123}}}}
        self.assertEqual(core.parse_app({"id": "x-app", "name": "X", "wizard_type": "service", "wizard_mcp_path": "/mcp"}, compose),
                         {"id": "x-app", "name": "X", "short_desc": "", "port": 8123, "mcp_path": "/mcp"})
        self.assertIsNone(core.parse_app({"id": "x-app", "wizard_type": "agent"}, compose))
        self.assertNotIn("mcp_path", core.parse_app({"id": "x-app", "wizard_type": "service", "wizard_mcp_path": "mcp;rm"}, compose))


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.user = {"my-tools": {"url": "http://elsewhere:9/mcp", "enabled": False}}
        self.hermes = FakeHermes(Path(self.tmp.name) / "home", self.user)
        self.state = {}

    def tearDown(self):
        self.tmp.cleanup()

    def cycle(self, up=UP, now=1000):
        apps, _ = refresh(self.state_dir, STORE, up=up, now=now)
        self.hermes.calls = []
        adapter.apply(apps, self.hermes, self.state, now, grace_s=600)
        return self.hermes.calls

    def test_connects_once_then_no_writes_when_nothing_changed(self):
        self.assertEqual(self.cycle(), [("config", "set", "mcp_servers.defleur-video", json.dumps({"url": VIDEO_URL, "enabled": True}))])
        skill = self.hermes.skill.read_text()
        mtime = self.hermes.skill.stat().st_mtime_ns
        self.assertIn("mcp__defleur_video__*", skill)
        self.assertIn("workflow_guide", skill)
        self.assertIn("http://secret-drop:8792/SKILL.md", skill)
        for now in (1030, 1060):
            self.assertEqual(self.cycle(now=now), [], "no config write when nothing changed")
        self.assertEqual(self.hermes.skill.stat().st_mtime_ns, mtime, "no skill rewrite when nothing changed")
        self.assertEqual(self.hermes.data["my-tools"], self.user["my-tools"])

    def test_grace_period_removal_and_return(self):
        self.cycle()
        self.assertEqual(self.cycle(up={"transcriber"}, now=1100), [], "still inside the grace period")
        self.assertEqual(self.cycle(up={"transcriber"}, now=1700), [("config", "unset", "mcp_servers.defleur-video")])
        self.assertNotIn("defleur-video", self.hermes.data)
        self.assertEqual(self.cycle(up={"transcriber"}, now=1800), [])
        self.assertEqual(len(self.cycle(now=1900)), 1, "comes back when the app is up again")
        self.assertIn("defleur-video", self.hermes.data)

    def test_never_touches_owner_entries(self):
        self.hermes.data["defleur-video"] = {"url": "http://custom:1/mcp", "enabled": True, "headers": {"A": "b"}}
        self.assertEqual(self.cycle(), [], "an owner's entry with the same name is left alone")
        self.hermes.data.pop("defleur-video")
        self.hermes.data["video"] = {"url": VIDEO_URL}
        self.assertEqual(self.cycle(now=1030), [], "already connected under another name")
        self.assertIn("mcp__video__*", self.hermes.skill.read_text())
        self.hermes.data.pop("video")
        self.cycle(now=1060)
        self.hermes.data["defleur-video"]["enabled"] = False  # owner turns ours off: released for good
        self.assertEqual(self.cycle(up={"transcriber"}, now=99999), [])
        self.assertEqual(self.hermes.data["defleur-video"]["enabled"], False)
        self.assertEqual(self.state["owned"]["defleur-video"], {"state": "released"})

    def test_skill_render_is_deterministic_and_respects_owner_skill(self):
        apps, _ = refresh(self.state_dir, STORE)
        self.assertEqual(adapter.render_skill(apps, {}), adapter.render_skill(json.loads(json.dumps(apps)), {}))
        self.hermes.skill.parent.mkdir(parents=True)
        self.hermes.skill.write_text("---\nname: wizard-apps\n---\nmine\n")
        self.cycle()
        self.assertEqual(self.hermes.skill.read_text(), "---\nname: wizard-apps\n---\nmine\n")

    def test_disable_removes_only_own(self):
        self.cycle()
        adapter.disable(self.hermes, self.state)
        self.assertEqual(self.hermes.data, self.user)
        self.assertFalse(self.hermes.skill.exists())


if __name__ == "__main__":
    unittest.main()
