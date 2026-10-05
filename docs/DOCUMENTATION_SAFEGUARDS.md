# Documentation safeguards

The maintained references use the actual CLI parser and a shared link registry.
They reduce mechanical drift while preserving authored explanations for review.
The full documentation audit, licensing decisions and website reconciliation
remain separate work. A passing check does not certify the full wiki.

## Update and check

Use the repository's base and `lint` dependencies in your development
environment. From the repository root:

```bash
python -m tools.docs.sync_references --update
python -m tools.docs.sync_references --check
python -m tools.docs.verify_wiki
```

`--update` regenerates the registered command pages, command catalog, review
state and marked shared-link definitions. It does not run CLI commands, open a
SEAM database, fetch updates, install SEAM, call a provider or publish anything.
It can regenerate safe references while returning failure for pending prose
reviews. Inspect that output before relying on the result.

For local polling while editing:

```bash
python -m tools.docs.sync_references --watch --interval 5
```

Each cycle starts a fresh Python process so changed definitions are reloaded.
Stop it with Ctrl+C. The watcher never acknowledges a prose review. This is a
local documentation watcher; application installation and update behavior are
outside its scope.

## Canonical references

[reference_config.json](../tools/docs/reference_config.json) registers shared
link IDs, pages with marked definition blocks, and whole generated CLI pages.
Pages using Markdown reference links with the `seam:` prefix must be registered
and contain exactly one managed definition block; unregistered consumers fail.
Change a target in
the registry, then regenerate; every registered definition block is updated
with a path relative to its own page. Other inline links remain authored prose
and can enter the review queue when the old target is detected.

The [CLI definition reference](reference/CLI_REFERENCE.md) and
[command catalog](reference/command_catalog.json) come from `build_parser()`.
The catalog reuses the command palette's traversal helpers with strict failure
handling and records root options, parent options, aliases, arity, defaults,
constants, metavars, groups and defining scopes. The database default records
its source resolver expression instead of a developer's local path. Changed
resolver expressions require review before regeneration.

Source files carry Git blob identities and SHA-256 hashes. Identical source
and metadata produce identical outputs without moving HEAD hashes or
timestamps. The catalog names its exact source scope; it does not fingerprint
every runtime implementation, dependency or release artifact.

## Review authored prose

[reference_state.json](reference/reference_state.json) records active Markdown
identities, unmanaged pages, pending reviews and explicit acknowledgements.
The initial baseline records identity, not approval of existing claims.
Changes to the parser contract or recorded source revisions queue active prose
containing CLI mentions. Every added or changed active authored Markdown page
enters the queue, including prose without CLI mentions. Canonical link changes
queue canonical-ID consumers as well as detected old-target inline references.

Read each pending page and review the change named in its reasons. Verify
affected examples and behavior against the exact code and relevant evidence,
and make any justified correction before recording the review. Name only pages
whose flagged change was actually reviewed:

```bash
python -m tools.docs.sync_references --update --acknowledge docs/setup.md
python -m tools.docs.sync_references --check
```

Acknowledgement records the current prose and command-contract hashes and its
limited change-review scope. It is an explicit maintainer assertion, not a
whole-page audit, licensing approval or automatic semantic verifier. The CLI
mention and link detectors are conservative heuristics; indirect claims,
non-Markdown formats and unregistered website copies still need audit.
Removing an authored page queues its removal and retains its last saved prose
hash. Deletion does not clear earlier review reasons. A deliberate removal needs
an explicit acknowledgement of the removed path after reviewing the change.

## Enforcement and boundaries

The existing `repo-hygiene` job runs the read-only check. The tracked canonical
pre-commit hook checks the exact Git index, so an unstaged repair cannot hide
staged drift. The closeout and Claude preflight sources run the same working
tree check. Existing hook installation remains a separate local setup step;
editing hook source does not install it on another checkout.

[documentation-check.yml](../.github/workflows/documentation-check.yml) proposes
a daily and manually dispatchable check on the existing self-hosted runner.
It has read-only repository permissions and does not regenerate, commit,
deploy or publish outputs. It becomes active only after the workflow reaches
the repository's default branch.

Generation rejects missing metadata, unresolved IDs, missing local targets or
anchors, unsafe paths, unmarked authored command pages and empty command
fallbacks. Whole generated pages stay under `docs/reference/`. Licensing and
notice documents cannot be registered for automated rewriting. Historical
records and archives are preserved; dated records and archive paths remain
outside this maintenance scope and inside the separate full audit inventory.

All output and recovery bytes are prepared before replacement. Recoverable
write errors restore prior files and clean temporary files. If recovery also
fails, the command fails and retains recovery files for explicit restoration.
Process termination is not a filesystem-wide atomic transaction; rerun the
read-only check after an interruption and restore a failed baseline before
continuing. Existing file modes are preserved.
The saved state binds the complete catalog hash, including source identities,
so an interrupted catalog advance fails even when parser metadata is unchanged.
Missing saved fields or unsupported state versions require explicit restoration
or a reviewed migration; regeneration never invents a replacement baseline.

Generated payloads are checked by the repository's content-free secret/session
scanner before writes. This detects its defined credential patterns, not every
possible confidential value. The generated CLI page is a local review candidate;
no public export exists here. Public/private placement and redistribution rights
must be reviewed explicitly before publication. Legal pages cannot be rewritten.

External URL availability, live website equivalence, licensing authority,
runtime behavior, release readiness and the full documentation corpus require
their own evidence. No owner licensing answer is inferred by this tool.
