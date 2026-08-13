# Security Policy

## Reporting a vulnerability

Please report suspected security vulnerabilities **privately** — do not open a
public GitHub issue for them.

- Preferred: use GitHub's [private vulnerability reporting](https://github.com/prometheuxresearch/prometheux-cli/security/advisories/new)
  ("Report a vulnerability" under the repository's **Security** tab).
- Or email **security@prometheux.co.uk**.

Please include enough detail to reproduce: the `px` version (`px --version`), your
OS and Python version, the command run, and what happened versus what you expected.

We aim to acknowledge a report within **3 business days** and to provide a remediation
timeline after triage. Please give us a reasonable window to release a fix before any
public disclosure.

## Supported versions

`px` is pre-1.0. Security fixes land on the latest released `0.x` line; please
upgrade to the newest version before reporting.

## Scope

`px` is a thin, files-first client over the Prometheux platform SDK
(`prometheux_chain`). Vulnerabilities in the CLI itself — credential handling,
local file writes, dependency issues, TLS/CA handling — are in scope here.
Issues in the hosted platform or backend belong to the platform's own disclosure
channel, not this repository.
