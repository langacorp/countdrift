# countdrift

[![self-test](https://github.com/langacorp/countdrift/actions/workflows/selftest.yml/badge.svg)](https://github.com/langacorp/countdrift/actions/workflows/selftest.yml)

Find numbers written by hand that no longer match their source.

A count typed into a page, a README or a rulebook does not change when the
thing it counts does. It stays plausible, it passes every review, and it is
wrong. Nothing flags it, because nothing is empty.

## The defect it was born from

**2026-08-30.** A rulebook of ours had a line reading *"AI agents in production
(32 total)"*. The registry it describes returned **72**.

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
countdrift claims.json
countdrift claims.json --json
countdrift --selftest
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

## Configuration

```json
{
  "claims": [
    {
      "name": "services",
      "pattern": "\\b(\\d+)\\s+services\\b",
      "truth": "ls -d site/services/*/ | wc -l",
      "paths": ["site/**/*.php", "README.md"]
    }
  ]
}
```

`pattern` needs one capture group: the number. `truth` is any command whose
output contains one. See `example.json`.

## What it is not

It does not fix anything, and it never picks a winner. When a page says 22 and
the directory says 16, one of the two may still be the right answer — maybe
the pages are missing, not the claim. Choosing is a decision; this only says
where to look.

Python 3.9+, no dependencies.

## Where this comes from

LANGA runs 16 digital services across 5 networks on its own infrastructure.
This tool came out of a rule we had to correct in our own rulebook: **the
number does not get written here, it gets read from the source.**

- [LANGA](https://langa.tv) — the ecosystem
- [LANGA Studios](https://studios.langa.tv) — strategy, branding, platforms
- [easy LANGA](https://easy.langa.tv) — client management, reports, support
- [eFruit](https://efruit.langa.tv) — food marketplace for local producers

See [How we work](https://about.langa.tv/how-we-work/).

## Licence

MIT — see LICENSE. Copyright LANGA Corporation S.r.l.
