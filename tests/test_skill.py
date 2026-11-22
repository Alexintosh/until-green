import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1] / "skills" / "until-green"
REV = "a" * 40


class SkillTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.db = self.home / "milestones" / "test" / "dispatch.sqlite"
        self.env = dict(os.environ, HOME=temp.name, XDG_CONFIG_HOME=str(self.home / "cfg"))
        self.env.pop("UNTIL_GREEN_PROFILE", None)

    def ledger(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SKILL / "scripts/dispatch.py"),
                                 "--db", str(self.db), *args], env=self.env, capture_output=True, text=True)
        if not ok:
            self.assertNotEqual(result.returncode, 0)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_presets_and_immutable_overrides(self):
        profile = self.ledger("init", "--profile", "alpi", "--writer", "local:max", "--reviewer", "sol2:high")
        self.assertEqual(profile["dispatcher"]["providerInstanceId"], "codex_tensorfold")
        self.assertEqual(profile["writerLevels"][0]["options"], {"reasoningEffort": "max"})
        self.env["UNTIL_GREEN_PROFILE"] = "codex"
        self.assertEqual(self.ledger("routes"), profile)
        self.assertIn("frozen", self.ledger("init", "--profile", "codex", ok=False))
        self.assertEqual(self.ledger("review-start", "component", REV)["model"], "gpt-6.2-sol")

    def test_custom_provider_and_telemetry(self):
        override = self.home / "override.json"
        trial = dict(driverKind="custom", providerInstanceId="trial-instance",
                     model="trial-model", effortOption="thinking")
        override.write_text(json.dumps({"agents": {"trial": trial}}))
        self.ledger("init", "--profile", "codex", "--override", str(override),
                    "--dispatcher", "trial:-", "--writer", "trial:deeper", "--reviewer", "trial:deeper")
        self.assertEqual(self.ledger("routes")["dispatcher"]["options"], {})
        worker = self.ledger("reserve", "parser", "fixture", "--kind", "repair", "--cohort", "suite", "--base", REV)
        self.assertEqual(worker["options"], {"thinking": "deeper"})
        self.ledger("bind", worker["token"], "synthetic-writer")
        self.ledger("measure", worker["token"], "--input-tokens", "100", "--cached-tokens", "30")
        self.ledger("finish", worker["token"], "candidate", "private-log", "--revision", REV)
        for scope in ("component", "final"):
            reviewer = self.ledger("review-start", scope, REV)
            self.assertEqual(reviewer, self.ledger("review-start", scope, REV))
            self.ledger("review-bind", reviewer["token"], scope)
            self.ledger("review-finish", reviewer["token"], "private-log", "--scores", "10", "10", "10", "10",
                        "--blockers", "0", "--checks", "pass")
        output = subprocess.check_output([sys.executable, str(SKILL / "scripts/model_report.py"),
            "--root", str(self.db.parent.parent), "--ledger-only", "--format", "json"], env=self.env, text=True)
        report = json.loads(output)
        self.assertEqual(report["milestones"][0]["accepted_sha"], REV)
        self.assertTrue(all(g["model"] == "trial-model" and g["effort"] == "deeper" for g in report["groups"]))
        self.assertEqual(report["groups"][0]["uncached_input_tokens"]["sum"], 70)
        self.assertNotIn("private-log", output)

    def test_short_ladder_infra_retry_review_promotion_and_takeover(self):
        file = self.home / "short.json"
        file.write_text(json.dumps(dict(attemptsPerLevel=1, writers=[
            dict(agent="sol1", levels=["low"]), dict(agent="sol2", levels=["max"])])))
        self.ledger("init", "--profile", "codex", "--override", str(file))
        t = self.ledger("reserve", "x", "one")["token"]
        self.ledger("finish", t, "infra", "offline")
        self.assertEqual(self.ledger("resume", t)["slot"], 1)
        t = self.ledger("reserve", "x", "two")["token"]
        self.ledger("bind", t, "w1")
        self.ledger("finish", t, "candidate", "result", "--revision", REV)
        v = self.ledger("review-start", "component", REV)["token"]
        self.ledger("review-bind", v, "reviewer")
        self.ledger("review-finish", v, "finding", "--scores", "9.5", "9.5", "9.5", "9.5",
                    "--blockers", "0", "--checks", "pass")
        self.assertEqual(self.ledger("status", "another")["slot"], 2)
        repair = self.ledger("reserve", "x", "three")
        self.assertEqual(repair["model"], "gpt-6.2-sol")
        self.ledger("bind", repair["token"], "w2")
        self.assertEqual(self.ledger("finish", repair["token"], "technical", "evidence")["state"], "takeover")

    def test_defaults_and_invalid_configuration(self):
        pref = self.home / "cfg/until-green/profile.json"
        pref.parent.mkdir(parents=True)
        pref.write_text((SKILL / "profiles/codex.json").read_text())
        self.assertIn("unknown agent", self.ledger("init", "--reviewer", "typo:high", ok=False))
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM milestone_config").fetchone()[0], 0)
        self.assertEqual(self.ledger("init")["dispatcher"]["driverKind"], "codex")
        self.db = self.home / "other.sqlite"
        self.env["UNTIL_GREEN_PROFILE"] = "alpi"
        self.assertEqual(self.ledger("init")["dispatcher"]["model"], "GLM-5.3-Flash")
        self.db = self.home / "explicit.sqlite"
        self.assertEqual(self.ledger("init", "--profile", "default")["dispatcher"]["driverKind"], "opencode")


if __name__ == "__main__":
    unittest.main()
