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


class Claim:
    """One number that is written down, and the command that knows the truth."""

    def __init__(self, name: str, pattern: str, truth: str,
                 paths: list[str], note: str = ""):
        self.name = name
        self.pattern = re.compile(pattern)
        self.truth = truth
        self.paths = paths
        self.note = note

    def measure(self) -> int | None:
        """Run the truth command. None when it could not run at all."""
        try:
            r = subprocess.run(self.truth, shell=True, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0:
            return None
        out = r.stdout.decode("utf-8", "replace").strip()
        m = re.search(r"-?\d+", out)
        return int(m.group(0)) if m else None

    def written(self) -> list[tuple[Path, int, int, str]]:
        """Every place the number is written. (file, line, value, context)"""
        trovati = []
        for p in self.paths:
            for f in sorted(Path().glob(p)):
                if not f.is_file():
                    continue
                try:
                    testo = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for n, riga in enumerate(testo.splitlines(), 1):
                    for m in self.pattern.finditer(riga):
                        if not m.groups():
                            continue
                        trovati.append((f, n, int(m.group(1)), riga.strip()[:90]))
        return trovati


def carica(config):
    dati = json.loads(config.read_text(encoding="utf-8"))
    return [Claim(c["name"], c["pattern"], c["truth"], c["paths"], c.get("note", ""))
            for c in dati["claims"]]


def controlla(claims, come_json=False):
    esiti, divergenti, ciechi = [], 0, 0
    for c in claims:
        vero = c.measure()
        punti = c.written()
        if vero is None:
            ciechi += 1
            esiti.append({"claim": c.name, "stato": "non misurabile",
                          "scritto_in": len(punti)})
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
        print(json.dumps({"claims": esiti, "divergenti": divergenti,
                          "non_misurabili": ciechi}, indent=2, ensure_ascii=False))
        return 2 if ciechi else (1 if divergenti else 0)
    for e in esiti:
        if e.get("stato") == "non misurabile":
            print("  ?  %-22s la fonte non ha dato un numero (in %d punti)"
                  % (e["claim"], e["scritto_in"]))
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

        sbagliato = Claim("servizi", r"\b(\d+)\s+servizi\b",
                          "ls svc_*.txt | wc -l", ["pagina.md"])
        giusto = Claim("network", r"\b(\d+)\s+network\b", "echo 5", ["pagina.md"])
        cieco = Claim("ignoto", r"\b(\d+)\s+servizi\b",
                      "comando-che-non-esiste-99", ["pagina.md"])

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
        print("  misura: %r (attesa None), exit sarebbe 2" % m3)
        ok &= m3 is None

        os.chdir(prima)
    print("\nselftest %s" % ("passato" if ok else "FALLITO"))
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="countdrift",
        description="Find numbers written by hand that no longer match their source.")
    p.add_argument("config", nargs="?", help="JSON file describing the claims")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--selftest", action="store_true",
                   help="run the built-in three-direction check and exit")
    p.add_argument("--version", action="version", version=__version__)
    a = p.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.config:
        p.error("serve un file di configurazione, oppure --selftest")
    return controlla(carica(Path(a.config)), a.json)


if __name__ == "__main__":
    sys.exit(main())
