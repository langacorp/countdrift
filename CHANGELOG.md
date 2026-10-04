# Changelog

All notable changes to this project are recorded here.
Each entry is a release. The heading carries the tag and the date the release
was published. Work that is tagged but never released says so.

## Unreleased

Fixes. Each one was reproduced first, and each has a test that fails on the
previous code and passes now.

- **A claims file that cannot be used exits 2, not 1.** A missing file,
  invalid JSON, a missing key, an invalid regular expression or an unknown
  source type ended in a traceback, and Python exits 1 on that: the code for
  drift. They are now one line on stderr and exit 2. A claims file with a
  UTF-8 byte order mark is read.
- **A source that fails no longer ends the run.** Any exception in a source
  now makes that claim unmeasurable. Before, an invalid `match` regex, an
  absolute `glob`, Infinity in a JSON file or a `timeout` written as a string
  crashed the run, lost every other claim's result and exited 1.
- **`json` no longer truncates.** 16.7 was read as 16 and matched a page that
  says 16. A value with a fractional part is now unmeasurable; 16.0 is 16.
  A JSON source with a UTF-8 byte order mark is read.
- **`files`: `directories` must be true or false.** `"false"` is a non-empty
  string and used to count directories.
- **A claim with nothing it could read is no longer OK.** A pattern without
  a capture group, or a `paths` entry that matches no file, used to report
  "written in 0 places" and exit 0. The first is now an error in the claims
  file, the second makes the claim unmeasurable. A file on the written side
  that cannot be read used to be skipped; it now makes the claim
  unmeasurable too. `paths` must be a list.
- A capture that is not a number makes the claim unmeasurable, instead of a
  traceback. An optional group that did not take part is skipped.
- A line matched by two `paths` entries is counted and reported once.
- Line numbers, and the `lines` source, split on newlines only. Form feed
  and U+2028 used to count as line breaks and shift every line below them.
- On a console that is not UTF-8, output that cannot be encoded is escaped
  instead of raising an error that exited 1. JSON output is ASCII-escaped
  there: the same content once parsed.

- `--version` printed 1.0.0 through v1.1.0 and v1.1.1: the constant was
  never changed. A test now compares it with CITATION.cff. Both say 1.2.0,
  prepared for the next release and not tagged.

Exit codes keep their meaning. Some inputs that used to exit 0 or 1 by
mistake now exit 2, which is what that code already meant: nothing was
compared.

Added:

- A unit test suite in `tests/`, stdlib `unittest`, no network:
  `python -m unittest discover -s tests -v`.
- `pyproject.toml`: install with pip or pipx from git, run as `countdrift`.
  `python countdrift.py` keeps working unchanged.
- CI runs the unit tests and the installed command on 3.9, 3.11 and 3.13.

Earlier, not yet released:

- Add CITATION.cff: make this tool citable in a bibliography
- README: drop both figures, keep the case, and show an invocation that works
- README: stop writing counts that will change

## v1.1.0 — 2026-08-30

- **Nothing executes by default.** A claims file used to mean shell commands,
  which made it as dangerous as the machine running it: in CI, whoever could
  edit it could run anything. Added `files`, `lines` and `json` sources that
  read without running, and they cover most claims.
- A shell command now has to be asked for twice: `{"type": "shell"}` in the
  file and `--allow-exec` on the command line.
- A source that fails now says why, instead of only saying it failed.
- Self-test grows from three directions to five.

## v1.0.0 — 2026-08-30

First release.

- Declare pairs of a written number and the command that knows the truth
- Report where they disagree; never edit, never pick a winner
- Three outcomes: matched, drifted, or **the source did not answer**
- Self-test in three directions, run on every push
