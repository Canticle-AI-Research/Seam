# 2026-10-02 Documentation drift audit (repo docs, GitHub surfaces, canticle.cc)

Scope: whole-repository documentation health, the GitHub-facing surfaces of
`Canticle-AI-Research/Seam`, and the public site `canticle.cc`, audited against
code/config sources of truth (`pyproject.toml`, `seam_runtime/cli.py`,
`seam_runtime/installer.py`, `seam_runtime/migrations.py`,
`seam_runtime/server.py`, `seam_runtime/config.py`, `docker-compose.yaml`,
`.env.example`, `.github/workflows/ci.yml`, git history) and the repo's
temporal chain (`docs/handoffs/INDEX.md` supersession chain, `HISTORY_INDEX.md`
entry dates, `docs/status/*` streams). Method: a deterministic link/CLI/tag
checker, five parallel audit passes, an adversarial falsification round over
every applied correction, and a dedicated duplication map. Ground rules: dated
records (`HISTORY.md`, handoffs, audits, archives, ledgers, DeepSeek-era task
packets) are records and were never "corrected"; a superseded handoff is never
current truth; the `latest` handoff plus the status streams win.

At authoring time the operator had frozen `HISTORY.md`, `ROADMAP.md`, and the
`docs/roadmap/` collection for this session against modification; the
closeout entry `HISTORY#653` was appended append-only at session end, and the
frozen authored files remain untouched.

## Corrected in this pass (all verified against source; falsifier round passed)

- **Stale Track S state** — REPO_LEDGER.md ("S8 is the next stage"), and
  docs/status/operations.md + surfaces.md ("R2 remains before S8 freeze")
  still described pre-freeze state; corrected to the landed record: R2 exact
  backend parity qualified S8 and the protected S8 freeze merged through
  PR #254 at `2f9a96b9` (HISTORY#641); S9/S10 remain open.
- **Falsified retrieval premise kept as justification** — REPO_LEDGER.md still
  cited HISTORY#503's confounded 0.755616 canonical figure as the reason to
  freeze legacy ranking; rewritten to the matched four-arm ablation record
  (canonical mix/hybrid 0.776048 vs legacy 0.766420, legacy arm reproducing
  #503 exactly, zero admissible semantic relations in the default-ingest
  corpus, cat3 gate open, `legacy-weighted/1` default until S9), matching
  docs/status/retrieval.md.
- **Dead repository coordinate** — `BlackhatShiftey/Seam_Runtime` no longer
  resolves publicly (no redirect; deleted or made private). README.md had a
  live hyperlink to it, as does/do CONTRIBUTING.md, docs/PROTECTION_MODEL.md
  (which also presented the removed private-to-public mirror-sync utility as a
  live "disabled" control), docs/CODE_LAYOUT.md, and REPO_LEDGER.md. All now
  describe the coordinate as unreachable with the frozen head `0f4b40a` +
  `LICENSES/Apache-2.0.txt` as provenance. The frozen snapshot survives as a
  dangling commit object in this checkout.
- **README current-state rot** — "unpublished Track S S6 candidate ... merge
  remain[s]" rewritten to the published record (S6 PR #223, agent-turn
  lifecycle PR #231, deliberate-memory governance PR #233; source-publication,
  not deployment); stale "naming candidate is not on `main`" clause removed
  (seam-suite 2.4.1rc1 landed via commit 8cf669f); untracked-operator Gemini
  config claim generalized.
- **Operator guides** (docs/MACOS.md, docs/SEAM_OPERATOR_GUIDE.md,
  docs/setup.md, installers/README.md, docs/PGVECTOR_LOCAL.md,
  docs/BENCHMARK_SOP.md, docs/errors.md): compose service name `seam-pgvector`
  → `pgvector` in 10 command instances (the container name `seam-pgvector` is
  correct and unchanged); clone owner → `Canticle-AI-Research/Seam` (11
  instances); Python floor 3.10+ → 3.11+ (`requires-python`); install
  coordinates `seam-runtime[...] @ git+ssh://...BlackhatShiftey...` and
  `pip install seam[...]` (the PyPI `seam` package is an unrelated SDK) →
  checkout-extras installs (`pip install -e ".[...]"`); MCP client config
  pointed at a nonexistent `~/.local/bin/seam-mcp` shim → the real `seam` shim
  with `["mcp", "stdio"]`, with `seam-mcp --ensure-pgvector` located in the
  runtime venv (installer writes exactly `seam`, `seam-benchmark`, `seam-dash`);
  `~/.config/seam/.env` mislabeled as the credentials location → split into
  the runtime-managed `seam.env` (mode 0600) vs the compose env file; DSN
  example `user=postgres` → `user=$env:POSTGRES_USER` (compose default `seam`);
  compose default port 5432 → 55432 in errors.md; `webui/` Vite-project
  references dropped (tree removed in HISTORY#285); extras version bounds
  aligned to pyproject (textual >=8.0,<9.0; psycopg <4.0;
  sentence-transformers <3.0); all-extras marked as excluding `chroma`.
- **Reference docs** — docs/IMPROVEMENT_EXPERIMENTS.md core projection
  `core-storage/3` → `core-storage/4` (S6 handle projection);
  docs/status/compression-visual.md missing `rgba64` surface mode;
  docs/status/operations.md runner name → label `seam-box` (ci.yml runs-on);
  docs/status/workspace.md decision-map main SHA refreshed and the 2026-08-30
  deep-audit branch row resolved (lineage preserved, superseded by PR #247);
  docs/RAG_ARCHITECTURE.md MCP tool list completed (+`seam_knowledge_graph`,
  `seam_knowledge_node`, `seam_identity_merges`); docs/BENCHMARK_SOP.md
  success-check keys and per-fixture field names aligned to
  `seam_runtime/evals.py` (`hybrid_beats_vector_on_relation`; no
  `rejected_ids`/`rejection_rate` fields exist);
  docs/SOP_CI_BENCH_GATE_PREP_DEEPSEEK.md pgvector tag 0.8.2 → 0.8.6.
- **SOP-era correctness** — the three external-bench comparator SOPs now
  install real extras instead of the foreign PyPI `seam` package;
  docs/SOP_INDEX.md gained an era note covering the DeepSeek/Track K-M packets
  whose `experimental/webui/` instructions predate HISTORY#285;
  docs/SOP_PRODUCTION_READINESS_REMEDIATION.md's dead-code phase now records
  the HISTORY#284 promotion + HISTORY#285 removal instead of instructing an
  audit of a nonexistent tree.
- **SECURITY.md / SECURITY intake** — fallback contact now names the private
  advisory URL instead of "release notes".

## Found, intentionally not changed

- **Operator-frozen this session**: `HISTORY.md` (reference only),
  `ROADMAP.md`, `docs/roadmap/` collection — ROADMAP still carries
  `experimental/` references at lines 594, 600, 2031 and
  docs/roadmap/MEMORY_BENCHMARKS.md:65 still proposes `pip install seam[bench]`
  (a coordinate that would install an unrelated package if executed); flagged
  for a later session.
- **SEAM_SPEC_V0.1.md §27** lists a "suggested command surface" (`seam canon`,
  `seam recall`, `seam evolve`, ...) that never shipped; the spec is the
  governing contract and was not edited. Flag for a spec-process decision.
- **Dated records** (HISTORY, status archive, DeepSeek packets, historical
  banners) left verbatim per protocol.

## Operator action required (outside repo reach this session)

Resolution status as of the same day's cleanup pass (HISTORY#657): the
canticle.cc badge/hosted/benchmarks/demo/help/console items and the
GitHub org-profile framing, wiki placeholders, repo description, and
dead Pages config are fixed — see below. Still open for the owner:
the Lab Notes catalog superlative (site protocol forbids in-place
report edits), the Discussions enabled-or-not decision, the published
v2.4.0 release body, and a live-site deploy check (the live downloads
page still shows pre-fix content that main's source no longer contains).

1. **canticle.cc — HIGH**: "APACHE-2.0 CORE" badge and "open-source runtime"
   copy conflict with the BUSL-1.1 runtime license (Apache-2.0 covers only
   legacy/seam-client artifacts); `brew install canticle/tap/seam` points at a
   nonexistent tap (and homebrew-core has an unrelated `seam`); downloads page
   advertises .dmg/.exe/Linux binaries that do not exist in release v2.4.0
   (wheel + sdist only); the public benchmarks board shows figures absent from
   `benchmarks/RESULTS.md` (including an unauthorized "graph 0.86" while the
   matched arms tie with zero admissible graph relations); the demo dashboard
   presents simulated metrics with no disclaimer. MEDIUM: landing page
   present-tense "hosted plans exist" vs the repo's blocked-deployment state;
   help page's "SEAM vs Mem0 / Zep" board description; lab-notes "0.733
   highest measured" unverifiable from committed records;
   documentation.html's CLI reference lists `seam init`, which does not exist
   in `seam_runtime/cli.py`. Confirmed-correct on documentation.html: the
   pipeline/four-layer model, retrieval modes, first-flow and doctor commands,
   pgvector port/container, MCP config (`python -m seam_runtime.mcp_protocol
   --ensure-pgvector`), HS/1 modes and JPEG rejection, MIRL record kinds, the
   12-tool MCP list (a subset of the real 19), all other CLI names sampled
   (including multi-line parsers `readable-compress`, `readable-query`,
   `reindex`, `shell`/`chat`, `webui`), SQLite `vector_index`, and the
   waitlist-only hosted posture.
2. **GitHub org surfaces**: the org profile README (Canticle-AI-Research/.github)
   brands the whole enterprise "open-source AI research", the same
   license-family mislabel as the site, while the public Ghost README
   correctly states "PolyForm Shield is not an OSI-approved open-source
   license" with layered licensing — align the org profile with that layered
   framing. The org blog field points at canticle.cc/sign-up (fine); the
   other org repos' descriptions are consistent (Ghost public and
   carefully worded; Seam_SDK private/BUSL; the rest private placeholders).
   Repo-level settings from the earlier pass: wiki placeholder pages (one
   titled with the wrong product expansion, "Semantically" vs "Surface"
   Encoded Agent Memory), GitHub Pages enabled but serving 404, Discussions
   enabled but undocumented, placeholder repo description.
3. **Future release notes**: the v2.4.0 body's "Private proprietary" wording
   sits on a publicly readable repo (report-only; published release untouched).

## Duplication map (pointer-card refactor backlog)

14 clusters, ~52 duplicated passages across 12 active files, all currently
AGREE except one divergence fixed this pass (extras version bounds). Top
maintenance burdens: (1) BUSL self-host grant restated across 7 files;
(2) seam-suite/TestPyPI facts in 6 copies including a PROJECT_STATUS router
violation; (3) seam.env credential handling with no designated owner and 3
in-README copies; (4) MCP/`--ensure-pgvector` mechanism in 4 docs;
(5) WebUI-prototype warning 4x inside README alone. Recommended consolidation:
REPO_LEDGER.md / docs/status/<area>.md / docs/SEAM_OPERATOR_GUIDE.md own their
concerns; README and guides collapse to pointer cards — left as a scoped
follow-up because mass prose removal needs its own review.

## Verification

- All six continuity gates pass after corrections: verify_integrity,
  verify_routing, verify_handoffs, verify_continuity, verify_streams,
  verify_wiki (278 active pages reachable, safe links).
- Deterministic drift checker: zero findings on active paths (remaining hits
  are inside the deliberately frozen `docs/status_archive/` record).
- Adversarial falsification round: every applied correction re-attacked against
  code/config/git evidence; all survived after two minor fix-ups (era-note date
  decoupling; a nonexistent `bench` extra in a reverted roadmap doc).

## Evidence manifest

Raw artifacts: none

All evidence is repository content at the audited working tree: the cited
code/config files and line-level claims above, plus git facts reproducible
from this checkout — the PR #254 merge commit 2f9a96b9 (see the git log), the
dangling legacy frozen commit 0f4b40aab7fda643ce776e597f0b430faa465ca8 (a
reachable object via git cat-file), and the legacy repository coordinate
returning "could not resolve" from the GitHub API on 2026-10-02.
