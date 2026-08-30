# Changelog

All notable changes to this project are recorded here.
Dates are the date of the commit, not of a release.

## v1.1.0 - 2026-08-30

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
