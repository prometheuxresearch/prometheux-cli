# Changelog

All notable changes to `prometheux` (the `px` CLI) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Because the public contract is the command-line surface (commands, flags, output),
a breaking change is a removed/renamed command or flag, or an output change that
would break a script.

## [Unreleased]

<!-- Add entries here as you merge. On release, rename this heading to the new
     version and open a fresh [Unreleased] section above it. The release workflow
     publishes the matching section as the GitHub Release notes. -->

### Added
- `px list` — list ontologies, apps, datasources, context, and concepts.
- MCP-parity commands so the CLI is a full alternative to the MCP connection:
  - `px snapshot` — list / create / restore / delete ontology snapshots.
  - `px policy` — list / get / create / update / delete / trigger / runs (schedules).
  - `px template` — list / import catalogue templates.
  - `px datasource` — preview / delete (disconnect) a data source.
  - `px app` — publish / unpublish an app.
  - `px query` — read-only SQL SELECT over a populated concept.
  - `px search concepts|company` — semantic concept search + company knowledge base.
  - `px context search` — semantic search over context notes.
  - `px playbook` — list / show the platform's skill playbooks.
  - `px compute catalog|provision|remove` — machine lifecycle beyond start/stop.
  - `px validate --online` — server-side Vadalog validation of each concept body.

### Changed
- Renamed the top-level `project` concept to `ontology` throughout the CLI
  (commands, output, on-disk `ontologies/` layout, `ontology:` manifest key,
  `ontology.schema.json`). Backend-wire terms (`project_id`, context scope
  `project`) unchanged.

## [0.1.0] - 2026-08-12

Initial public release.

### Added
- `px init` / `px validate` — scaffold a workspace and validate it **fully
  offline** (no platform, no SDK).
- Platform verbs over REST: `px login`, `px pull`, `px plan`, `px apply`,
  `px run`, `px status`, `px delete`, `px context apply`.
- Files-first workspace model: concepts, datasources, ontologies, apps, and the
  context/notes layer authored as files with JSON Schema `$schema` references.
- `px skill install` — installs the authoring skill from the bundled schemas +
  curated prose (targets: Claude global, Claude project, Cursor rule); no repo to
  clone and always matches the installed `px`.
- Generated `AGENTS.md` authoring reference (schema-derived).
- Install scripts: `install.sh` (uv → pipx → pip) and `install.ps1` (native
  Windows), plus a hashed `requirements.lock`.

### Security
- Proxy/CA aware: OpenLineage emit honours `REQUESTS_CA_BUNDLE` /
  `CURL_CA_BUNDLE` / `SSL_CERT_FILE`.
- Release supply-chain: CycloneDX SBOM, SHA256 checksums, and Sigstore
  build-provenance attestation published with every release; PyPI publishing via
  Trusted Publishing (OIDC), no stored token.

[Unreleased]: https://github.com/prometheuxresearch/prometheux-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/prometheuxresearch/prometheux-cli/releases/tag/v0.1.0
