# Cross-Index

schema: seam-cross-index/v1
source: streams/*/log.md (derived; do not hand-edit)
total_events: 1
hot_zone_max: 200
archive_pattern: cross_index_archive/<lo>-<hi>.cross.md

## Hot Zone (latest 1 events, oldest first)
| utc | stream:id:hash | kind | event | topics | refs |
|---|---|---|---|---|---|
| 2026-07-06T03:07:19Z | history:001:e3983308 | session-event | done | protocol, release, public-core | docs/PROTECTION_MODEL.md,tools/release/public_manifest.py |
