# Authoring a Prometheux workspace — guide for humans and agents

This repo is a **Prometheux workspace as code**: the lineage (concepts, datasources,
ontology, apps) and the context layer (notes) live as files you author locally and apply
to the platform with the `px` CLI. This file is the canonical guide; `CLAUDE.md` and
`.cursor/rules/` just point here.

Every YAML/manifest carries a `$schema` reference to a file under `.px/schemas/`, so a
language server gives you autocomplete and validation with zero guesswork. When in doubt,
read the schema — it is the single source of truth. The **Schema reference** at the end of
this guide is generated from those same schemas, so it never drifts from what `px validate`
enforces.
