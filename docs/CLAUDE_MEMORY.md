# Claude auto memory for Seam

The root `.claude/settings.json` pins auto memory to
`~/.claude/memory-shared/seam`. Independent checkouts containing that setting
share one directory on the same machine after workspace trust. This is
operator memory, separate from SEAM runtime databases and the separate SDK.
The SDK must not adopt this setting. Other machines start with their own
directory; this is not synchronization or a backup service.

Claude Code 2.1.266 was tested with a local HTTP stub: the first request from
a fresh project loaded its configured memory directory and index. Its embedded
schema description still says project scope is ignored, but its resolver and
the [current memory documentation](https://code.claude.com/docs/en/memory)
honor trusted project settings. A SessionStart hook writing this setting was
too late for the first request and must not be used as the routing mechanism.

## Existing checkouts

Before updating a checkout that has a local `.claude/settings.json`, preserve
that file and merge its hooks and individual settings into ignored
`.claude/settings.local.json`. Do not replace local hook arrays or permission
lists with a fresh minimal file. Put only the tracked memory pin in
`.claude/settings.json`; remove any conflicting local memory-directory
override only after reviewing where its data lives. Update older worktrees
individually. Old revisions and clones that have not acquired this commit do
not inherit the new setting automatically.

Before moving memory, compare bytes and fingerprint every source file. Copy
into a private staging directory, verify preservation, and check the source
fingerprints again before activation. Keep conflicting originals in an
external dated archive, outside the active memory directory. Do not load
superseded instructions as equally authoritative `.variant.md` files.
Archive the original indexes too. Rebuild the active index with one entry per
memory, repaired links, and explicit historical status for old project facts.
Stay below both startup limits: 200 lines and 25 KB.

Preserve the original directories before replacing their paths. Where local
filesystem support is verified, compatibility directory symlinks to the shared
directory let sessions caching the old path keep using the same files. They
are a migration bridge; the tracked setting is the route for new clones.
Claude may ask permission before writing through a legacy symlink in manual
mode. Do not weaken permissions to suppress that prompt; start a fresh session
that resolves the configured shared directory directly.
Do not archive entire Claude project directories: those contain session state
unrelated to auto memory. Do not place source archives beneath the active
shared directory, where Claude could rediscover superseded instructions.

## Verification and operating limits

Use a new trusted session and `/memory` to inspect the effective directory.
Check an independent clone, a linked worktree, and an SDK checkout as a negative
control. Verify actual index loading, not just JSON syntax. User/local/policy
settings and explicit `--settings` can alter precedence; restricted or bare
sessions intentionally disable normal settings or memory. Resumed sessions
may retain their earlier system prompt until compaction; begin a new session
after migration. Never bypass workspace trust to make the pin work.

Sharing a directory does not add transactional concurrency. Before editing a
memory, reread it; use targeted edits and coordinate changes to the index.
Two independent whole-file writes can still overwrite each other. Keep the
dated migration archive and compare both sides before rollback; restoring old
snapshots blindly would discard post-migration memories. Memory instructions
also do not enforce spending or deletion policy: existing hooks and operator
approval remain necessary.

The scope validator rejects additional tracked settings and validates staged
content at commit time. Run `python -m tools.git.verify_agent_config` for a
checkout check or add `--staged` to check the Git index.
