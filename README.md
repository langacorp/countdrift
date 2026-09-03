# countdrift

[![self-test](https://github.com/langacorp/countdrift/actions/workflows/selftest.yml/badge.svg)](https://github.com/langacorp/countdrift/actions/workflows/selftest.yml)

Find numbers written by hand that no longer match their source.

A count typed into a page, a README or a rulebook does not change when the
thing it counts does. It stays plausible, it passes every review, and it is
wrong. Nothing flags it, because nothing is empty.

## The defect it was born from

**2026-08-30.** A rulebook of ours declared, as a plain figure, how many AI agents
were in production. The registry it describes returned a different number — and the
two were not even counting the same kind of thing.

The number had been typed once and never read again. From that line it had
spread: into two public articles, and into the markup of a status panel that
declared a constant while the query behind it had grown.

The same day, in the same estate, a service count appeared as **22** in seven
published articles, **16** in the approved figure, **17** in one theme and
**24** in a code comment. Four numbers, one thing, nobody wrong on purpose.

## What it does

You declare pairs: a number as it is **written**, and a command that knows the
**truth**. It reports where they disagree, and it never edits anything — which
one is right is a decision, and decisions are not a tool's job.

```bash
curl -O https://raw.githubusercontent.com/langacorp/countdrift/main/countdrift.py
python3 countdrift.py claims.json
python3 countdrift.py claims.json --json
python3 countdrift.py --selftest
```

```
  OK networks       fonte: 5     scritto in 12 punti
  !! services       fonte: 16    scritto in 9 punti
       site/about/index.php:41 dice 22 | Con 22 servizi distribuiti su 5 network
  ?  agents         la fonte non ha dato un numero (in 2 punti)
```

## Three outcomes, not two

| exit | meaning |
|---|---|
| `0` | every written number matches its source |
| `1` | at least one has drifted |
| `2` | **a source did not answer** — nothing was compared |

The third one is the point. A check that could not read its source and reports
green is worse than no check: it is a green that means *nothing was measured*.

## Trust boundary

A claims file says where the truth lives. If that means *a shell command*, the
file is as dangerous as the machine that runs it: in CI, whoever can edit
`claims.json` can run anything.

So **nothing executes by default.** The `files`, `lines` and `json` sources
read; they do not run, and they cover most claims. A shell command has to be
asked for **twice** — `{"type": "shell"}` in the file *and* `--allow-exec` on
the command line — because that is a decision, not a default.

```
  ?  legacy   this claim runs a shell command; pass --allow-exec to permit it
```

A claims file that arrives in a pull request should never be run with
`--allow-exec`.

## Configuration

```json
{
  "claims": [
    {
      "name": "services",
      "pattern": "\\b(\\d+)\\s+services\\b",
      "truth": { "type": "files", "glob": "site/services/*", "directories": true },
      "paths": ["site/**/*.php", "README.md"]
    }
  ]
}
```

`pattern` needs one capture group: the number.

| `truth.type` | reads | keys |
|---|---|---|
| `files` | how many paths match a glob | `glob`, `directories` |
| `lines` | how many lines of a file match | `file`, `match` |
| `json` | a number at a dotted path | `file`, `path` |
| `shell` | **runs a command** — needs `--allow-exec` | `command`, `timeout` |

A plain string instead of an object still works and is treated as `shell`, so
older files keep running — behind `--allow-exec`, never silently.

## What it is not

It does not fix anything, and it never picks a winner. When a page says 22 and
the directory says 16, one of the two may still be the right answer — maybe
the pages are missing, not the claim. Choosing is a decision; this only says
where to look.

Python 3.9+, no dependencies.

## The other tools

Each came out of a defect measured on our own estate. Each one is standalone
and depends on none of the others.

- **[realroute](https://github.com/langacorp/realroute)** — checks that a route
  really exists, by content and not by status code.
- **[leakform](https://github.com/langacorp/leakform)** — finds secrets in a git
  repository by shape, across every ref.
- **[samecheck](https://github.com/langacorp/samecheck)** — measures whether the
  copies that should be identical still are, and never says which one is right.
- **[provenreal](https://github.com/langacorp/provenreal)** — compares what a
  system claims with what can be measured, from independent sources.
- **[kemproof](https://github.com/langacorp/kemproof)** — attests that an
  ML-KEM-768 key exchange really happened. It does not encrypt anything.

The set is kept on the [organisation profile](https://github.com/langacorp).
It is not written here as a count, because a number typed by hand is the thing
countdrift exists to find.

## Where this comes from

LANGA runs an ecosystem of digital services on its own infrastructure.
This tool came out of a rule we had to correct in our own rulebook: **the
number does not get written here, it gets read from the source.**

- [LANGA](https://langa.tv) — the ecosystem
- [LANGA Studios](https://studios.langa.tv) — strategy, branding, platforms
- [easy LANGA](https://easy.langa.tv) — client management, reports, support
- [eFruit](https://efruit.langa.tv) — food marketplace for local producers

See [How we work](https://about.langa.tv/how-we-work/).

## Licence

MIT — see LICENSE. Copyright LANGA Corporation S.r.l.
