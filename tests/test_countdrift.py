"""
Unit tests for countdrift.

Every verdict is exercised in both directions: a case where it must fire and a
case where it must stay silent. Each test works in its own temporary directory
and needs no network. Run with:

    python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import countdrift  # noqa: E402


class InTempDir(unittest.TestCase):
    """Each test runs in a fresh directory, which is also the cwd."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.getcwd()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()

    @staticmethod
    def write(name, text):
        p = Path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    @staticmethod
    def touch(n, prefix="svc/s"):
        for i in range(n):
            p = Path("%s%02d.txt" % (prefix, i))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")

    def config(self, *claims):
        self.write("claims.json", json.dumps({"claims": list(claims)}))
        return "claims.json"

    def run_cli(self, *argv):
        """Run main() and return (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = countdrift.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def run_json(self, *argv):
        code, out, err = self.run_cli(*argv, "--json")
        return code, json.loads(out), err


def files_claim(name="services", glob="svc/*", paths=("page.md",),
                pattern=r"\b(\d+)\s+services\b", **extra):
    truth = {"type": "files", "glob": glob}
    truth.update(extra)
    return {"name": name, "pattern": pattern, "truth": truth,
            "paths": list(paths)}


class Verdicts(InTempDir):
    """The three outcomes, each in the direction where it must fire and not."""

    def test_match_exits_0(self):
        self.touch(16)
        self.write("page.md", "We run 16 services.\n")
        code, data, _ = self.run_json(self.config(files_claim()))
        self.assertEqual(code, 0)
        self.assertEqual(data["divergenti"], 0)
        self.assertEqual(data["non_misurabili"], 0)
        self.assertEqual(data["claims"][0]["misurato"], 16)
        self.assertEqual(data["claims"][0]["occorrenze"], 1)
        self.assertEqual(data["claims"][0]["divergenti"], [])

    def test_drift_exits_1_and_names_the_line(self):
        self.touch(16)
        self.write("page.md", "intro\nWe run 22 services.\n")
        code, data, _ = self.run_json(self.config(files_claim()))
        self.assertEqual(code, 1)
        self.assertEqual(data["divergenti"], 1)
        d = data["claims"][0]["divergenti"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["file"], "page.md")
        self.assertEqual(d[0]["riga"], 2)
        self.assertEqual(d[0]["scritto"], 22)
        self.assertEqual(d[0]["contesto"], "We run 22 services.")

    def test_only_the_wrong_occurrences_are_listed(self):
        self.touch(16)
        self.write("page.md", "16 services here\n22 services there\n")
        code, data, _ = self.run_json(self.config(files_claim()))
        self.assertEqual(code, 1)
        self.assertEqual(data["claims"][0]["occorrenze"], 2)
        self.assertEqual([x["riga"] for x in data["claims"][0]["divergenti"]], [2])

    def test_source_that_does_not_answer_exits_2_not_0(self):
        self.write("page.md", "We run 16 services.\n")
        claim = {"name": "x", "pattern": r"(\d+) services",
                 "truth": {"type": "json", "file": "missing.json", "path": "n"},
                 "paths": ["page.md"]}
        code, data, _ = self.run_json(self.config(claim))
        self.assertEqual(code, 2)
        self.assertEqual(data["non_misurabili"], 1)
        e = data["claims"][0]
        self.assertEqual(e["stato"], "non misurabile")
        self.assertIn("missing.json", e["motivo"])
        self.assertEqual(e["scritto_in"], 1)

    def test_unanswered_source_outranks_drift(self):
        self.touch(16)
        self.write("page.md", "We run 22 services.\n")
        blind = {"name": "blind", "pattern": r"(\d+) services",
                 "truth": {"type": "lines", "file": "nope.txt"},
                 "paths": ["page.md"]}
        code, data, _ = self.run_json(self.config(files_claim(), blind))
        self.assertEqual(code, 2)
        self.assertEqual(data["divergenti"], 1)
        self.assertEqual(data["non_misurabili"], 1)

    def test_text_output_marks_each_outcome(self):
        self.touch(16)
        self.write("page.md", "We run 22 services.\n")
        blind = {"name": "blind", "pattern": r"(\d+) services",
                 "truth": {"type": "lines", "file": "nope.txt"},
                 "paths": ["page.md"]}
        ok = files_claim(name="fine", glob="svc/*",
                         pattern=r"(\d+) things")
        code, out, _ = self.run_cli(self.config(files_claim(), blind, ok))
        self.assertEqual(code, 2)
        self.assertRegex(out, r"(?m)^  !! services ")
        self.assertIn("page.md:1 dice 22", out)
        self.assertRegex(out, r"(?m)^  \?  blind .*file not found")
        self.assertRegex(out, r"(?m)^  OK fine ")
        self.assertIn("claim divergenti: 1 | non misurabili: 1", out)


class Sources(InTempDir):

    def measure(self, truth, allow_exec=False):
        c = countdrift.Claim("t", r"(\d+)", truth, [])
        return c.measure(allow_exec), c.why

    def test_files_counts_files_not_directories(self):
        self.touch(3)
        Path("svc/sub").mkdir()
        self.assertEqual(self.measure({"type": "files", "glob": "svc/*"})[0], 3)

    def test_files_directories_counts_directories_only(self):
        self.touch(3)
        Path("svc/a").mkdir()
        Path("svc/b").mkdir()
        v, _ = self.measure({"type": "files", "glob": "svc/*",
                             "directories": True})
        self.assertEqual(v, 2)

    def test_files_zero_is_a_number(self):
        Path("svc").mkdir()
        self.assertEqual(self.measure({"type": "files", "glob": "svc/*"}), (0, ""))

    def test_lines_counts_all_or_matching(self):
        self.write("list.txt", "a\nb\n# c\nd\n")
        self.assertEqual(self.measure({"type": "lines", "file": "list.txt"})[0], 4)
        v, _ = self.measure({"type": "lines", "file": "list.txt",
                             "match": "^[^#]"})
        self.assertEqual(v, 3)

    def test_lines_missing_file_is_not_zero(self):
        v, why = self.measure({"type": "lines", "file": "nope.txt"})
        self.assertIsNone(v)
        self.assertIn("file not found", why)

    def test_json_dotted_path_and_length(self):
        self.write("d.json", json.dumps({"a": {"b": 7, "items": [1, 2, 3]}}))
        self.assertEqual(self.measure({"type": "json", "file": "d.json",
                                       "path": "a.b"})[0], 7)
        self.assertEqual(self.measure({"type": "json", "file": "d.json",
                                       "path": "a.items"})[0], 3)
        self.assertEqual(self.measure({"type": "json", "file": "d.json",
                                       "path": "a.items.length"})[0], 3)

    def test_json_rejects_what_is_not_a_number(self):
        self.write("d.json", json.dumps({"s": "12", "t": True, "n": None}))
        for key in ("s", "t", "n"):
            v, why = self.measure({"type": "json", "file": "d.json", "path": key})
            self.assertIsNone(v, key)
            self.assertIn("not a number", why)

    def test_json_missing_key_and_invalid_file(self):
        self.write("d.json", json.dumps({"a": 1}))
        v, why = self.measure({"type": "json", "file": "d.json", "path": "b"})
        self.assertIsNone(v)
        self.assertIn("no such key", why)
        self.write("bad.json", "{not json")
        v, why = self.measure({"type": "json", "file": "bad.json", "path": "a"})
        self.assertIsNone(v)
        self.assertIn("not valid JSON", why)

    def test_spec_without_its_key_is_unmeasurable(self):
        v, why = self.measure({"type": "files"})
        self.assertIsNone(v)
        self.assertIn("KeyError", why)


class TrustBoundary(InTempDir):

    def test_shell_does_not_run_without_allow_exec(self):
        c = countdrift.Claim("t", r"(\d+)",
                             {"type": "shell", "command": "touch ran"}, [])
        self.assertIsNone(c.measure(allow_exec=False))
        self.assertIn("--allow-exec", c.why)
        self.assertFalse(Path("ran").exists())

    def test_shell_runs_with_allow_exec(self):
        c = countdrift.Claim("t", r"(\d+)",
                             {"type": "shell", "command": "echo 16"}, [])
        self.assertEqual(c.measure(allow_exec=True), 16)

    def test_bare_string_is_shell_and_stays_gated(self):
        c = countdrift.Claim("t", r"(\d+)", "echo 16", [])
        self.assertEqual(c.truth, {"type": "shell", "command": "echo 16"})
        self.assertIsNone(c.measure(allow_exec=False))
        self.assertEqual(c.measure(allow_exec=True), 16)

    def test_shell_failure_modes_are_unmeasurable(self):
        cases = [
            ({"type": "shell", "command": "exit 3"}, "exited 3"),
            ({"type": "shell", "command": "echo none"}, "no number"),
            ({"type": "shell", "command": "sleep 5", "timeout": 0.2},
             "timed out"),
        ]
        for truth, why in cases:
            c = countdrift.Claim("t", r"(\d+)", truth, [])
            self.assertIsNone(c.measure(allow_exec=True), truth)
            self.assertIn(why, c.why)

    def test_cli_flag_is_needed(self):
        self.write("page.md", "We run 16 services.\n")
        claim = {"name": "legacy", "pattern": r"(\d+) services",
                 "truth": "echo 16", "paths": ["page.md"]}
        cfg = self.config(claim)
        self.assertEqual(self.run_cli(cfg)[0], 2)
        self.assertEqual(self.run_cli(cfg, "--allow-exec")[0], 0)


class Cli(InTempDir):

    def test_selftest_passes(self):
        code, out, _ = self.run_cli("--selftest")
        self.assertEqual(code, 0)
        self.assertIn("selftest passato", out)

    def test_version_prints_the_constant(self):
        code, out, _ = self.run_cli("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), countdrift.__version__)

    def test_no_config_is_a_usage_error(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("--selftest", err)

    def test_example_config_loads(self):
        claims = countdrift.carica(ROOT / "example.json")
        self.assertEqual([c.name for c in claims], ["services", "agents"])

    def test_note_is_optional_and_kept(self):
        self.write("c.json", json.dumps({"claims": [
            dict(files_claim(), note="why"), files_claim(name="b")]}))
        a, b = countdrift.carica(Path("c.json"))
        self.assertEqual((a.note, b.note), ("why", ""))


if __name__ == "__main__":
    unittest.main()


class ConfigErrors(InTempDir):
    """A claims file that cannot be used is not a drift: exit 2, no traceback."""

    def assert_config_error(self, text, needle):
        self.write("c.json", text)
        code, out, err = self.run_cli("c.json")
        self.assertEqual(code, 2, err)
        self.assertNotIn("Traceback", err)
        self.assertIn(needle, err)
        self.assertEqual(out, "")

    def test_missing_config_file(self):
        code, _, err = self.run_cli("nope.json")
        self.assertEqual(code, 2)
        self.assertIn("nope.json", err)

    def test_invalid_json(self):
        self.assert_config_error("{claims: ", "not valid JSON")

    def test_no_claims_list(self):
        self.assert_config_error('{"claim": []}', "claims")

    def test_missing_key(self):
        self.assert_config_error(json.dumps({"claims": [
            {"name": "a", "truth": {"type": "files", "glob": "*"},
             "paths": ["x"]}]}), "pattern")

    def test_invalid_regex(self):
        self.assert_config_error(json.dumps({"claims": [
            files_claim(pattern=r"(\d+ services")]}), "invalid pattern")

    def test_unknown_source_type(self):
        self.assert_config_error(json.dumps({"claims": [
            {"name": "a", "pattern": r"(\d+)", "truth": {"type": "sql"},
             "paths": ["x"]}]}), "unknown source type")

    def test_config_with_utf8_bom_is_read(self):
        self.touch(16)
        self.write("page.md", "We run 16 services.\n")
        Path("c.json").write_bytes(
            b"\xef\xbb\xbf" + json.dumps({"claims": [files_claim()]}).encode())
        self.assertEqual(self.run_cli("c.json")[0], 0)
