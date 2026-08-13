"""prometheux_cli — the `px` CLI.

A thin, files-first layer over the prometheux_chain SDK. This package owns the
offline surface (schemas, `init`, `validate`) plus the `plan`/diff engine and
`pull` file-tree reshaping; all platform I/O goes through prometheux_chain.
"""

__version__ = "0.2.0"
