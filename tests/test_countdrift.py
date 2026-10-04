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


class SourceFailuresStayContained(InTempDir):
    """
    A source that fails is "non misurabile" for that claim only. It must not
    crash the run, lose the other claims' results, or exit 1 (drift).
    """

    def measure(self, truth, allow_exec=False):
        c = countdrift.Claim("t", r"(\d+)", truth, [])
        return c.measure(allow_exec), c.why

    def test_lines_invalid_match_regex(self):
        self.write("list.txt", "a\n")
        v, why = self.measure({"type": "lines", "file": "list.txt", "match": "["})
        self.assertIsNone(v)
        self.assertIn("invalid match", why)

    def test_files_absolute_glob(self):
        v, why = self.measure({"type": "files", "glob": "/tmp/*"})
        self.assertIsNone(v)
        self.assertIn("relative", why)

    def test_json_infinity_and_nan(self):
        self.write("d.json", '{"inf": 1e400, "nan": NaN}')
        for key in ("inf", "nan"):
            v, why = self.measure({"type": "json", "file": "d.json", "path": key})
            self.assertIsNone(v, key)
            self.assertIn("not a whole number", why)

    def test_json_fraction_is_not_truncated(self):
        # 16.7 used to become 16 and match a page that says 16.
        self.write("d.json", '{"n": 16.7, "m": 16.0}')
        v, why = self.measure({"type": "json", "file": "d.json", "path": "n"})
        self.assertIsNone(v)
        self.assertIn("not a whole number", why)
        self.assertEqual(self.measure({"type": "json", "file": "d.json",
                                       "path": "m"})[0], 16)

    def test_json_source_with_utf8_bom(self):
        Path("d.json").write_bytes(b'\xef\xbb\xbf{"n": 5}')
        self.assertEqual(self.measure({"type": "json", "file": "d.json",
                                       "path": "n"}), (5, ""))

    def test_files_directories_must_be_a_boolean(self):
        # "false" is a non-empty string, so it used to count directories.
        self.touch(2)
        Path("svc/d").mkdir()
        v, why = self.measure({"type": "files", "glob": "svc/*",
                               "directories": "false"})
        self.assertIsNone(v)
        self.assertIn("directories", why)

    def test_shell_timeout_must_be_a_number(self):
        v, why = self.measure({"type": "shell", "command": "echo 1",
                               "timeout": "5"}, allow_exec=True)
        self.assertIsNone(v)
        self.assertIn("timeout", why)

    def test_wrong_type_in_spec_is_unmeasurable(self):
        self.write("d.json", '{"n": 5}')
        v, why = self.measure({"type": "json", "file": "d.json", "path": 5})
        self.assertIsNone(v)
        self.assertTrue(why)

    def test_one_bad_source_does_not_lose_the_others(self):
        self.touch(16)
        self.write("page.md", "We run 22 services.\n")
        bad = {"name": "bad", "pattern": r"(\d+) services",
               "truth": {"type": "lines", "file": "page.md", "match": "("},
               "paths": ["page.md"]}
        code, data, err = self.run_json(self.config(files_claim(), bad))
        self.assertNotIn("Traceback", err)
        self.assertEqual(code, 2)
        self.assertEqual(data["divergenti"], 1)
        self.assertEqual(data["non_misurabili"], 1)


class WrittenSide(InTempDir):
    """Where the number is written: every place, once, at the right line."""

    def test_pattern_without_capture_group_is_a_config_error(self):
        # It used to find nothing, report OK and exit 0.
        self.touch(3)
        self.write("page.md", "We run 22 services.\n")
        cfg = self.config(files_claim(pattern=r"\d+ services"))
        code, out, err = self.run_cli(cfg)
        self.assertEqual(code, 2)
        self.assertIn("capture group", err)

    def test_paths_entry_that_matches_no_file_is_unmeasurable(self):
        # A typo in "paths" used to read as "written in 0 places", exit 0.
        self.touch(3)
        self.write("page.md", "We run 22 services.\n")
        code, data, _ = self.run_json(self.config(files_claim(paths=["pgae.md"])))
        self.assertEqual(code, 2)
        self.assertIn("pgae.md", data["claims"][0]["motivo"])

    def test_number_absent_from_existing_files_is_still_ok(self):
        self.touch(3)
        self.write("page.md", "No count here.\n")
        code, data, _ = self.run_json(self.config(files_claim()))
        self.assertEqual(code, 0)
        self.assertEqual(data["claims"][0]["occorrenze"], 0)

    def test_paths_must_be_a_list_of_relative_globs(self):
        for paths in ("page.md", ["/etc/*.conf"], [3]):
            claim = files_claim()
            claim["paths"] = paths
            code, _, err = self.run_cli(self.config(claim))
            self.assertEqual(code, 2, paths)
            self.assertIn("paths", err)
            self.assertNotIn("Traceback", err)

    def test_overlapping_paths_count_a_line_once(self):
        self.touch(3)
        self.write("page.md", "We run 22 services.\n")
        code, data, _ = self.run_json(
            self.config(files_claim(paths=["page.md", "*.md"])))
        self.assertEqual(code, 1)
        self.assertEqual(data["claims"][0]["occorrenze"], 1)
        self.assertEqual(len(data["claims"][0]["divergenti"]), 1)

    def test_optional_group_that_did_not_match_is_skipped(self):
        self.touch(3)
        self.write("page.md", "services\nWe run 3 services.\n")
        code, data, err = self.run_json(
            self.config(files_claim(pattern=r"(\d+)?\s*services")))
        self.assertNotIn("Traceback", err)
        self.assertEqual(code, 0)
        self.assertEqual(data["claims"][0]["occorrenze"], 1)

    def test_capture_that_is_not_a_number_is_unmeasurable(self):
        self.touch(3)
        self.write("page.md", "We run many services.\n")
        code, data, err = self.run_json(
            self.config(files_claim(pattern=r"(\w+) services")))
        self.assertNotIn("Traceback", err)
        self.assertEqual(code, 2)
        self.assertIn("many", data["claims"][0]["motivo"])

    def test_line_numbers_count_newlines_only(self):
        # str.splitlines() also splits on form feed, U+2028 and others, so
        # the reported line was wrong by one for each of them above it.
        self.touch(3)
        self.write("page.md", "intro\fpage two more\nWe run 22 services.\n")
        code, data, _ = self.run_json(self.config(files_claim()))
        self.assertEqual(code, 1)
        self.assertEqual(data["claims"][0]["divergenti"][0]["riga"], 2)

    def test_crlf_files_are_read(self):
        self.touch(3)
        Path("page.md").write_bytes(b"intro\r\nWe run 22 services.\r\n")
        code, data, _ = self.run_json(self.config(files_claim()))
        self.assertEqual(code, 1)
        self.assertEqual(data["claims"][0]["divergenti"][0]["riga"], 2)

    def test_lines_source_counts_newlines_only(self):
        self.write("list.txt", "a\fb\nc\n")
        c = countdrift.Claim("t", r"(\d+)", {"type": "lines", "file": "list.txt"}, [])
        self.assertEqual(c.measure(), 2)

    @unittest.skipIf(not hasattr(os, "geteuid") or os.geteuid() == 0,
                     "root can read a file with mode 000")
    def test_unreadable_file_is_unmeasurable_not_skipped(self):
        self.touch(3)
        self.write("a.md", "We run 22 services.\n")
        self.write("b.md", "We run 3 services.\n")
        os.chmod("a.md", 0)
        try:
            code, data, _ = self.run_json(self.config(files_claim(paths=["*.md"])))
        finally:
            os.chmod("a.md", 0o644)
        self.assertEqual(code, 2)
        self.assertIn("a.md", data["claims"][0]["motivo"])


class Output(InTempDir):

    def run_subprocess(self, *argv, encoding="ascii"):
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING=encoding)
        return subprocess.run([sys.executable, str(ROOT / "countdrift.py")]
                              + list(argv), capture_output=True, env=env)

    def test_narrow_console_encoding_does_not_turn_ok_into_drift(self):
        # A claim name or a line the console cannot encode used to raise
        # UnicodeEncodeError, which exits 1: the code for drift.
        self.touch(3)
        self.write("page.md", "Offriamo 3 servizi — 服务\n")
        claim = files_claim(name="servizi — 服务",
                            pattern=r"(\d+) servizi")
        cfg = self.config(claim)
        for extra in ((), ("--json",)):
            r = self.run_subprocess(cfg, *extra)
            self.assertEqual(r.returncode, 0, r.stderr.decode())
            self.assertNotIn(b"Traceback", r.stderr)

    def test_narrow_console_still_reports_drift_with_the_line(self):
        self.touch(3)
        self.write("page.md", "Offriamo 22 servizi — tutti\n")
        r = self.run_subprocess(self.config(files_claim(pattern=r"(\d+) servizi")))
        self.assertEqual(r.returncode, 1, r.stderr.decode())
        self.assertIn(b"page.md:1 dice 22", r.stdout)

    def test_json_output_keeps_non_ascii_on_a_utf8_console(self):
        self.touch(3)
        self.write("page.md", "Offriamo 22 servizi — tutti\n")
        r = self.run_subprocess(self.config(files_claim(pattern=r"(\d+) servizi")),
                                "--json", encoding="utf-8")
        data = json.loads(r.stdout.decode("utf-8"))
        self.assertIn("—", data["claims"][0]["divergenti"][0]["contesto"])
