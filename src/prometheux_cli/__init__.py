"""prometheux_cli — the `px` CLI.

A thin, files-first layer over the prometheux_chain SDK. This package owns the
offline surface (schemas, `init`, `validate`) plus the `plan`/diff engine; all
platform I/O goes through prometheux_chain. The file tree itself is built by the
server, so `pull` only writes down what `/ontologies/export-tree` returns.
"""

__version__ = "0.4.0"
