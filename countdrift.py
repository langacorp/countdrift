#!/usr/bin/env python3
"""
countdrift — find numbers written by hand that no longer match their source.

A count typed into a page, a README or a rulebook does not change when the
thing it counts does. It stays plausible, passes every review, and is wrong.

This tool takes pairs: a literal to look for, and a command that produces the
true number. It reports where they disagree. It never edits anything.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

__version__ = "1.0.0"



# --------------------------------------------------------------------------
# TRUST BOUNDARY
#
# A claims file says where the truth lives. Historically that meant a shell
# command, which makes the file as dangerous as the machine running it: in CI,
# whoever can edit claims.json can run anything.
#
# So the default is that nothing executes. The sources below read; they do not
# run. A shell command is still available, but it has to be asked for twice:
# `{"type": "shell", ...}` in the file AND --allow-exec on the command line.
# --------------------------------------------------------------------------


class SourceError(RuntimeError):
    """The truth could not be read. Never the same as 'the number is zero'."""


class ConfigError(ValueError):
    """The claims file cannot be used. Nothing was compared."""


def _righe(testo):
    """
    The lines of a text, split on newlines only. Path.read_text() already
    turns \r\n and \r into \n. str.splitlines() would also split on form
    feed, U+2028 and other separators, which miscounts lines and shifts every
    line number reported below them.
    """
    righe = testo.split("\n")
    if righe and righe[-1] == "":
        righe.pop()
    return righe


def _src_files(spec, allow_exec):
    """How many paths match a glob. Reads the filesystem, runs nothing."""
    pattern = spec["glob"]
    if not isinstance(pattern, str) or not pattern:
        raise SourceError("glob must be a non-empty string")
    if Path(pattern).is_absolute():
        raise SourceError("glob must be relative to the working directory: %s"
                          % pattern)
    only_dirs = spec.get("directories", False)
    if not isinstance(only_dirs, bool):
        # "false" is a non-empty string and would have meant True.
        raise SourceError("directories must be true or false, not %r" % only_dirs)
    n = 0
    for p in Path().glob(pattern):
        if only_dirs and not p.is_dir():
            continue
        if not only_dirs and not p.is_file():
            continue
        n += 1
    return n


def _src_lines(spec, allow_exec):
    """How many lines in a file match a regular expression."""
    f = Path(spec["file"])
    if not f.is_file():
        raise SourceError("file not found: %s" % f)
    try:
        rx = re.compile(spec["match"]) if spec.get("match") else None
    except (re.error, TypeError) as e:
        raise SourceError("invalid match pattern %r: %s" % (spec.get("match"), e))
    n = 0
    for line in _righe(f.read_text(encoding="utf-8", errors="replace")):
        if rx is None or rx.search(line):
            n += 1
    return n


def _src_json(spec, allow_exec):
    """A number inside a JSON file, addressed by a dotted path."""
    f = Path(spec["file"])
    if not f.is_file():
        raise SourceError("file not found: %s" % f)
    try:
        node = json.loads(f.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise SourceError("not valid JSON: %s (%s)" % (f, e))
    for key in [k for k in spec["path"].split(".") if k]:
        if isinstance(node, list) and key == "length":
            return len(node)
        if not isinstance(node, dict) or key not in node:
            raise SourceError("no such key in %s: %s" % (f, spec["path"]))
        node = node[key]
    if isinstance(node, list):
        return len(node)
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        raise SourceError("%s is not a number" % spec["path"])
    if isinstance(node, float):
        # int() would turn 16.7 into 16 and call it a match; it would crash on
        # Infinity and NaN, which json.loads accepts.
        if not node.is_integer():
            raise SourceError("%s is not a whole number: %r" % (spec["path"], node))
        node = int(node)
    return node


def _src_shell(spec, allow_exec):
    """
    The escape hatch. Asked for twice on purpose: once in the file, once on
    the command line. A claims file that can run commands is as trusted as
    the machine it runs on, and that has to be a decision, not a default.
    """
    if not allow_exec:
        raise SourceError(
            "this claim runs a shell command; pass --allow-exec to permit it")
    timeout = spec.get("timeout", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
            or timeout <= 0:
        raise SourceError("timeout must be a positive number of seconds, not %r"
                          % (timeout,))
    try:
        r = subprocess.run(spec["command"], shell=True,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SourceError("command timed out")
    if r.returncode != 0:
        raise SourceError("command exited %d" % r.returncode)
    m = re.search(r"-?\d+", r.stdout.decode("utf-8", "replace"))
    if not m:
        raise SourceError("command produced no number")
    return int(m.group(0))


SOURCES = {"files": _src_files, "lines": _src_lines,
           "json": _src_json, "shell": _src_shell}


class Claim:
    """One number that is written down, and the source that knows the truth."""

    def __init__(self, name, pattern, truth, paths, note=""):
        self.name = name
        try:
            self.pattern = re.compile(pattern)
        except (re.error, TypeError) as e:
            raise ConfigError("claim %r: invalid pattern: %s" % (name, e))
        if self.pattern.groups < 1:
            # Without a group there is no number to read: every line would be
            # skipped and the claim would report OK, written in 0 places.
            raise ConfigError("claim %r: pattern needs one capture group "
                              "around the number" % name)
        self.paths = paths
        self.note = note
        self.why = ""
        # A bare string is the old shape: a shell command. It keeps working,
        # still behind --allow-exec, so an old claims file does not quietly
        # become a way to run things.
        self.truth = ({"type": "shell", "command": truth}
                      if isinstance(truth, str) else truth)
        if not isinstance(self.truth, dict):
            raise ConfigError("claim %r: truth must be an object or a string"
                              % name)
        if self.truth.get("type") not in SOURCES:
            raise ConfigError("claim %r: unknown source type: %r"
                              % (name, self.truth.get("type")))

    def measure(self, allow_exec=False):
        """The true number, or None when it could not be read at all."""
        try:
            return SOURCES[self.truth["type"]](self.truth, allow_exec)
        except SourceError as e:
            self.why = str(e)
            return None
        except Exception as e:
            # Any other failure is still "the source did not answer" for this
            # claim: reported with its type and message, exit 2. Letting it
            # escape would crash the run, lose every other claim's result and
            # exit 1, which is the code for drift.
            self.why = "%s: %s" % (type(e).__name__, e)
            return None

    def written(self) -> list[tuple[Path, int, int, str]]:
        """
        Every place the number is written. (file, line, value, context)

        Raises SourceError when the written side cannot be read in full: a
        paths entry that matches no file, a file that cannot be read, or a
        capture that is not a number. Each of those used to be skipped, and
        a claim with nothing to compare reported OK.
        """
        trovati, visti = [], set()
        for p in self.paths:
            corrisponde = False
            for f in sorted(Path().glob(p)):
                if not f.is_file():
                    continue
                corrisponde = True
                chiave = f.resolve()
                if chiave in visti:
                    # Two entries in "paths" can match the same file; it is
                    # still one place where the number is written.
                    continue
                visti.add(chiave)
                try:
                    testo = f.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    raise SourceError("cannot read %s: %s" % (f, e))
                for n, riga in enumerate(_righe(testo), 1):
                    for m in self.pattern.finditer(riga):
                        v = m.group(1)
                        if v is None:
                            continue
                        try:
                            valore = int(v)
                        except ValueError:
                            raise SourceError(
                                "%s:%d: pattern captured %r, which is not a "
                                "whole number" % (f, n, v))
                        trovati.append((f, n, valore, riga.strip()[:90]))
            if not corrisponde:
                raise SourceError("paths entry matches no file: %s" % p)
        return trovati


def carica(config):
    """
    Read the claims file. Anything wrong with it is a ConfigError: a file that
    cannot be read must not look like a drift (exit 1) or a crash.
    """
    try:
        testo = config.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError("cannot read %s: %s" % (config, e))
    try:
        dati = json.loads(testo)
    except ValueError as e:
        raise ConfigError("not valid JSON: %s (%s)" % (config, e))
    if not isinstance(dati, dict) or not isinstance(dati.get("claims"), list):
        raise ConfigError('%s: expected an object with a "claims" list' % config)
    claims = []
    for i, c in enumerate(dati["claims"]):
        if not isinstance(c, dict):
            raise ConfigError("claim #%d is not an object" % (i + 1))
        for key in ("name", "pattern", "truth", "paths"):
            if key not in c:
                raise ConfigError("claim #%d: missing key %r" % (i + 1, key))
        paths = c["paths"]
        if not isinstance(paths, list) or not paths or not all(
                isinstance(x, str) and x and not Path(x).is_absolute()
                for x in paths):
            # A bare string used to be globbed character by character.
            raise ConfigError("claim %r: paths must be a non-empty list of "
                              "globs relative to the working directory"
                              % c["name"])
        claims.append(Claim(c["name"], c["pattern"], c["truth"], c["paths"],
                            c.get("note", "")))
    return claims


def controlla(claims, come_json=False, allow_exec=False):
    esiti, divergenti, ciechi = [], 0, 0
    for c in claims:
        vero = c.measure(allow_exec)
        try:
            punti = c.written()
        except SourceError as e:
            # The written side could not be read in full: comparing what was
            # read would be a partial answer presented as a whole one.
            ciechi += 1
            esiti.append({"claim": c.name, "stato": "non misurabile",
                          "motivo": c.why or str(e), "scritto_in": 0})
            continue
        if vero is None:
            ciechi += 1
            esiti.append({"claim": c.name, "stato": "non misurabile",
                          "motivo": c.why, "scritto_in": len(punti)})
            continue
        sbagliati = [p for p in punti if p[2] != vero]
        if sbagliati:
            divergenti += 1
        esiti.append({"claim": c.name, "misurato": vero,
                      "occorrenze": len(punti),
                      "divergenti": [{"file": str(f), "riga": n, "scritto": v,
                                      "contesto": x} for f, n, v, x in sbagliati]})
    return _stampa(esiti, divergenti, ciechi, come_json)


def _stampa(esiti, divergenti, ciechi, come_json):
    if come_json:
        # On a console that is not UTF-8, escape non-ASCII as \uXXXX: still
        # valid JSON with the same content, instead of an encoding error.
        utf = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
        print(json.dumps({"claims": esiti, "divergenti": divergenti,
                          "non_misurabili": ciechi}, indent=2,
                         ensure_ascii=not utf.startswith("utf")))
        return 2 if ciechi else (1 if divergenti else 0)
    for e in esiti:
        if e.get("stato") == "non misurabile":
            print("  ?  %-22s %s (written in %d place(s))"
                  % (e["claim"], e.get("motivo") or "source did not answer",
                     e["scritto_in"]))
            continue
        d = e["divergenti"]
        print("  %s %-22s fonte: %-5d scritto in %d punti"
              % ("OK" if not d else "!!", e["claim"], e["misurato"], e["occorrenze"]))
        for x in d:
            print("       %s:%d dice %d | %s"
                  % (x["file"], x["riga"], x["scritto"], x["contesto"]))
    print("\nclaim divergenti: %d | non misurabili: %d" % (divergenti, ciechi))
    return 2 if ciechi else (1 if divergenti else 0)


def selftest() -> int:
    """
    Due versi, piu' il terzo che gli altri strumenti hanno insegnato:
    deve trovare una divergenza vera, tacere su un numero giusto, e NON
    dichiarare verde quando la fonte non ha risposto.
    """
    import tempfile, os
    ok = True
    with tempfile.TemporaryDirectory() as d:
        prima = Path.cwd()
        os.chdir(d)
        Path("pagina.md").write_text(
            "Offriamo 22 servizi ai clienti.\nCon 5 network attivi.\n", encoding="utf-8")
        for i in range(16):
            Path("svc_%02d.txt" % i).write_text("x", encoding="utf-8")

        Path("n.json").write_text('{"networks": 5}', encoding="utf-8")

        sbagliato = Claim("services", r"\b(\d+)\s+servizi\b",
                          {"type": "files", "glob": "svc_*.txt"}, ["pagina.md"])
        giusto = Claim("networks", r"\b(\d+)\s+network\b",
                       {"type": "json", "file": "n.json", "path": "networks"},
                       ["pagina.md"])
        cieco = Claim("unknown", r"\b(\d+)\s+servizi\b",
                      {"type": "json", "file": "assente.json", "path": "x"},
                      ["pagina.md"])
        esecutivo = Claim("legacy", r"\b(\d+)\s+servizi\b",
                          "echo 16", ["pagina.md"])

        print("verso 1 - deve trovare la divergenza: la pagina dice 22, i file sono 16")
        d1 = [p for p in sbagliato.written() if p[2] != sbagliato.measure()]
        print("  divergenze trovate: %d (attesa 1)" % len(d1))
        ok &= len(d1) == 1

        print("verso 2 - deve tacere su un numero che coincide")
        d2 = [p for p in giusto.written() if p[2] != giusto.measure()]
        print("  divergenze trovate: %d (attesa 0)" % len(d2))
        ok &= len(d2) == 0

        print("verso 3 - una fonte che non risponde non e' un verde")
        m3 = cieco.measure()
        print("  misura: %r (attesa None) | motivo: %s" % (m3, cieco.why))
        ok &= m3 is None and bool(cieco.why)

        print("verso 4 - un comando NON si esegue senza --allow-exec")
        m4 = esecutivo.measure(allow_exec=False)
        print("  misura: %r (attesa None) | motivo: %s" % (m4, esecutivo.why))
        ok &= m4 is None

        print("verso 5 - con --allow-exec lo stesso comando si esegue")
        m5 = esecutivo.measure(allow_exec=True)
        print("  misura: %r (attesa 16)" % m5)
        ok &= m5 == 16

        os.chdir(prima)
    print("\nselftest %s" % ("passato" if ok else "FALLITO"))
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="countdrift",
        description="Find numbers written by hand that no longer match their source.")
    p.add_argument("config", nargs="?", help="JSON file describing the claims")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--allow-exec", action="store_true",
                   help="permit claims whose source is a shell command. "
                        "Only for a claims file you trust as much as this machine.")
    p.add_argument("--selftest", action="store_true",
                   help="run the built-in three-direction check and exit")
    p.add_argument("--version", action="version", version=__version__)
    a = p.parse_args(argv)
    # A character the console cannot encode used to raise UnicodeEncodeError,
    # which exits 1: the code for drift. Write it escaped instead.
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    if a.selftest:
        return selftest()
    if not a.config:
        p.error("serve un file di configurazione, oppure --selftest")
    try:
        claims = carica(Path(a.config))
    except ConfigError as e:
        # Exit 2, like a source that did not answer: nothing was compared.
        print("countdrift: %s" % e, file=sys.stderr)
        return 2
    return controlla(claims, a.json, a.allow_exec)


if __name__ == "__main__":
    sys.exit(main())
