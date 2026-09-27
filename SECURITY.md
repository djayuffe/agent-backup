# Security policy

## Supported versions

The latest release is supported. This is a 0.x project: fixes land on `main` and
go out in the next release rather than as patches to older tags.

## Reporting a vulnerability

Please report privately through GitHub:
[open a security advisory](https://github.com/djayuffe/agent-backup/security/advisories/new).
That keeps the report between you and the maintainer until a fix exists. Please
do not open a public issue for a vulnerability.

An initial response should take a few days. If a report is accepted, the fix and
an advisory go out together.

## What is in scope

This tool reads an agent's session state and writes copies of it. The
interesting risks are therefore about *your data*, not about a service:

- Writing outside the directory you asked for, or into the agent's own state
  (the tool only ever reads there).
- Destroying data it was meant to protect: overwriting an existing archive,
  deleting a mirrored chat, or dropping files from a backup while reporting
  success.
- Path traversal through a crafted session file name or a crafted profile, for
  example escaping the output directory when an archive is written.
- Leaking session content into somewhere it does not belong — the record-shape
  profile in a backup, for instance, is meant to contain shapes and never message
  text.

## What is not in scope

- The agents themselves, and whatever they choose to write to disk.
- A profile you wrote pointing the tool at a directory it should not read; the
  tool runs with your permissions, by design.
- The contents of your backups once written. They are as readable as the
  filesystem you put them on: if that matters, put them on an encrypted volume.

## A note on what this tool copies

Backups and exports contain your full session transcripts, which routinely
include source code, file paths, credentials you pasted, and anything else you
said to an agent. Treat an archive as being exactly as sensitive as the
conversations inside it.
