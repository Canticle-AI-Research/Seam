# Cross-Index

schema: seam-cross-index/v1
source: streams/*/log.md (derived; do not hand-edit)
total_events: 650
hot_zone_max: 200
archive_pattern: cross_index_archive/<lo>-<hi>.cross.md

## Hot Zone (latest 200 events, oldest first)
| utc | stream:id:hash | kind | event | topics | refs |
|---|---|---|---|---|---|
| 2026-07-15T11:35:53Z | history:394:f348135d | session-event | done | benchmark, mem0, harness, cleanup | benchmarks/external/mem0_harness/README.md,benchmarks/external/mem0_harness/s... |
| 2026-07-15T11:49:56Z | history:395:de5bf982 | session-event | done | benchmark, locomo, mem0, harness, retrieval, quality, tes... | seam_runtime/conversation.py,seam_runtime/self_improve.py,tests/audit/test_se... |
| 2026-07-15T12:08:08Z | history:396:6f876cc6 | session-event | done | benchmark, locomo, quality, audit | docs/audits/2026-07-15-champion-problem-scan.md,PROJECT_STATUS.md |
| 2026-07-15T12:24:16Z | history:397:c5ff6b8a | session-event | done | benchmark, locomo, quality, handoff, continuity, verify | seam_runtime/conversation.py,seam_runtime/self_improve.py,tests/audit/test_se... |
| 2026-07-15T14:14:56Z | history:398:07f4efb0 | session-event | done | benchmark, locomo, judge, quality, audit, handoff, verify... | PROJECT_STATUS.md,docs/audits/2026-07-15-c4-and-mem0-cat13-score.md,docs/hand... |
| 2026-07-15T14:17:19Z | history:399:008c723c | session-event | changed | history, continuity, verify, handoff, benchmark, locomo | PROJECT_STATUS.md,docs/audits/2026-07-15-c4-and-mem0-cat13-score.md,docs/hand... |
| 2026-07-15T14:24:23Z | history:400:2d638e36 | session-event | done | bugfix, benchmark, locomo, retrieval, temporal, tests, ci... | benchmarks/external/mem0_harness/seam_mem0_server.py,tests/audit/test_seam_me... |
| 2026-07-16T00:00:00Z | roadmap:058:d10da061 | status-change | bootstrap | agent, openclaw, namespaces, profiles, console | ROADMAP.md:1726 |
| 2026-07-16T00:00:00Z | roadmap:059:d7fe472b | status-change | bootstrap | android, mobile, small-models, memory-loop | ROADMAP.md:1786 |
| 2026-07-16T12:38:06Z | history:401:ae65e22b | session-event | done | bugfix, benchmark, locomo, persist, tests, ci, handoff, v... | benchmarks/external/mem0_harness/seam_mem0_server.py,tests/audit/test_seam_me... |
| 2026-07-16T13:46:22Z | history:402:90136fda | session-event | in-progress | graph, memory, provenance, dashboard, webui, retrieval, a... | seam_runtime/knowledge_graph.py,seam_runtime/storage.py,seam_runtime/runtime.... |
| 2026-07-16T19:01:09Z | history:403:11d8ecbd | session-event | done | graph, memory, trust, provenance, webui, dashboard, retri... | seam_runtime/knowledge_graph.py,seam_runtime/nl.py,seam_runtime/nl_extract.py... |
| 2026-07-16T21:24:03Z | history:404:f1d35210 | session-event | done | bugfix, webui, dashboard, persist, graph, security, tests... | seam_runtime/webui/dashboard.html,tests/audit/test_webui_auto_ingest.py,PROJE... |
| 2026-07-16T23:08:58Z | history:405:465cd643 | session-event | done | benchmark, locomo, merge, pgvector, analysis, levers, rec... | PROJECT_STATUS.md,HISTORY.md,seam_runtime/conversation.py,seam_runtime/vector... |
| 2026-07-17T04:04:48Z | history:406:ed2e5617 | session-event | done | hygiene, gitignore, worktree, artifacts | .gitignore |
| 2026-07-17T04:52:38Z | history:407:2a544db0 | session-event | done | roadmap, agent, openclaw, android, namespaces, planning | ROADMAP.md,PROJECT_STATUS.md |
| 2026-07-17T04:59:20Z | history:408:324140f0 | session-event | done | benchmark, locomo, levers, answer-contract, exact-answer,... | seam_runtime/conversation.py,seam_runtime/retrieval.py,seam_runtime/self_impr... |
| 2026-07-17T09:27:04Z | history:409:144ab2d9 | session-event | done | handoff, registry, exact-answer, closeout | docs/handoffs/2026-07-17-exact-answer-contract-handoff.md,docs/handoffs/INDEX.md |
| 2026-07-17T09:39:49Z | history:410:97eaf38f | session-event | done | benchmark, results, proof, provenance, locomo, mem0, publish | benchmarks/RESULTS.md,benchmarks/BENCHMARK_LOG.md |
| 2026-07-17T17:48:07Z | history:411:e9c275f8 | session-event | done | benchmark, results, reproduce, fix, cli | benchmarks/RESULTS.md |
| 2026-07-17T19:11:22Z | history:412:626d3dcc | session-event | done | benchmark, locomo, exact-answer, negative-result, paid, p... | seam_runtime/conversation.py |
| 2026-07-17T19:32:03Z | history:413:a74254d9 | session-event | done | benchmark, locomo, cat3, open-domain, inference, lever, h... | seam_runtime/conversation.py,seam_runtime/self_improve.py,tests/audit/test_se... |
| 2026-07-17T19:52:56Z | history:414:96038f7d | session-event | planned | roadmap, benchmark, graph, memory, retrieval, comparator,... | ROADMAP.md,PROJECT_STATUS.md,benchmarks/RESULTS.md,docs/KNOWLEDGE_GRAPH.md |
| 2026-07-17T19:55:01Z | history:415:4f266a98 | session-event | changed | roadmap, benchmark, graph, memory, retrieval, comparator,... | ROADMAP.md,PROJECT_STATUS.md,benchmarks/RESULTS.md |
| 2026-07-17T20:50:51Z | history:416:2c227cbc | session-event | done | benchmark, locomo, memory, retrieval, pack, provenance, q... | seam_runtime/event_count_context.py,seam_runtime/retrieval.py,benchmarks/exte... |
| 2026-07-18T01:03:48Z | history:417:5760e59a | session-event | done | benchmark, locomo, memory, retrieval, quality, test, hand... | benchmarks/external/mem0_harness/microgate_event_count_context.py,tests/audit... |
| 2026-07-18T04:00:00Z | history:418:caca6117 | session-event | done | roadmap, docs, agent, memory |  |
| 2026-07-18T11:21:47Z | history:419:3f64d78d | session-event | done | benchmark, locomo, retrieval, quality, verify | docs/handoffs/2026-07-17-hc3-open-domain-cat3-handoff.md,PROJECT_STATUS.md |
| 2026-07-18T11:28:05Z | history:420:cf6c4060 | session-event | done | benchmark, locomo, retrieval, memory, quality, plan | docs/audits/2026-07-18-mem0-cat1-noncount-miss-mining.md,PROJECT_STATUS.md |
| 2026-07-18T20:13:22Z | history:421:95bef19b | session-event | done | benchmark, locomo, retrieval, verify, quality | docs/audits/2026-07-18-mem0-cat1-noncount-miss-mining.md,PROJECT_STATUS.md |
| 2026-07-18T21:24:25Z | history:422:b54c82e6 | session-event | done | benchmark, locomo, handoff, test, plan | benchmarks/external/mem0_harness/parity_probe_answerer.py,tests/audit/test_pa... |
| 2026-07-19T05:20:46Z | history:423:22ed4a4c | session-event | done | benchmark, locomo, paid-run, handoff, test | docs/handoffs/2026-07-19-matched-answerer-full-run-handoff.md,docs/handoffs/2... |
| 2026-07-19T13:48:23Z | history:424:43ca0434 | session-event | done | benchmark, locomo, paid-run, mem0-harness, ops | benchmarks/external/mem0_harness/seam_mem0_server.py,docs/handoffs/2026-07-19... |
| 2026-07-19T15:01:35Z | history:425:9d000c10 | session-event | done | ci, ops, infra, cost | .github/workflows/ci.yml,.github/workflows/ci-windows.yml |
| 2026-07-19T16:04:15Z | history:426:f3bd1e40 | session-event | done | benchmark, locomo, ci, ops | .github/workflows/ci.yml |
| 2026-07-19T19:47:29Z | history:427:8872a7d3 | session-event | done | benchmark, locomo, paid-run, handoff, retrieval, ci | seam_runtime/temporal_instance_context.py,benchmarks/external/mem0_harness/se... |
| 2026-07-19T21:02:19Z | history:428:bf0ea168 | session-event | done | ops, cost, benchmark, tooling | benchmarks/external/common/cost_report.py,tests/audit/test_cost_report.py |
| 2026-07-19T21:18:24Z | history:429:121a6292 | session-event | done | benchmark, locomo, paid-run, negative-result | benchmarks/external/common/cost_report.py,docs/handoffs/2026-07-19-matched-ru... |
| 2026-07-20T00:26:26Z | history:430:8b5c726f | session-event | done | bugfix, benchmark, locomo, handoff, verify, audit, contin... | seam_runtime/temporal_instance_context.py,benchmarks/external/common/cost_rep... |
| 2026-07-20T01:39:34Z | history:431:c0a57164 | session-event | done | retrieval, benchmark, mem0-harness, lever | seam_runtime/second_hop_context.py,benchmarks/external/mem0_harness/seam_mem0... |
| 2026-07-20T01:52:14Z | history:432:99068044 | session-event | done | retrieval, benchmark, negative-result, plan | seam_runtime/second_hop_context.py,tests/audit/test_second_hop_context.py |
| 2026-07-20T02:46:05Z | history:433:c3150c72 | session-event | done | retrieval, benchmark, mem0-harness, lever, recovery | seam_runtime/event_count_context.py,seam_runtime/retrieval.py,benchmarks/exte... |
| 2026-07-20T09:48:51Z | history:434:291b0956 | session-event | done | benchmark, locomo, paid-run, negative-result, mem0-harness | benchmarks/external/mem0_harness/microgate_event_count_context.py,tests/audit... |
| 2026-07-20T13:40:00Z | history:435:ec698280 | session-event | done | benchmark, locomo, mirl, retrieval, compile, provenance, ... | seam_runtime/derived_fact_context.py,seam_runtime/nl_extract.py,seam_runtime/... |
| 2026-07-20T14:03:53Z | history:436:1394218c | session-event | done | handoff, benchmark, retrieval, derived-facts, plan | docs/handoffs/2026-07-20-derived-facts-landed-and-kb-scaffold.md,docs/handoff... |
| 2026-07-20T14:09:56Z | history:437:d729f0ca | session-event | done | kb, docs, retrieval, benchmark, reference, plan | docs/kb/README.md,docs/kb/eval-methodology/benchmark-traps.md,docs/kb/eval-me... |
| 2026-07-20T22:26:20Z | history:438:2d0eac31 | session-event | done | derived-facts, grounded-clm, retrieval, benchmark, compil... | seam_runtime/nl_extract.py,seam_runtime/nl.py,seam_runtime/derived_fact_conte... |
| 2026-07-21T01:17:20Z | history:439:f81b36f6 | session-event | done | benchmark,locomo,memory,retrieval,compile,provenance,audi... | docs/audits/2026-07-20-memory-competitor-ratchet.md,seam_runtime/sentence_gro... |
| 2026-07-21T03:37:52Z | history:440:c44f9f60 | session-event | in-progress | benchmark,longmemeval,beam,memory,audit,bugfix,protocol,t... | benchmarks/external/mem0_harness/upstream_runner.py,benchmarks/external/commo... |
| 2026-07-21T04:38:43Z | history:441:ea8c3fb0 | session-event | done | benchmark,longmemeval,beam,memory,temporal,graph,audit,bu... | benchmarks/external/mem0_harness/upstream_runner.py,benchmarks/external/commo... |
| 2026-07-21T07:08:50Z | history:442:4d879e77 | session-event | done | graph, memory, retrieval, benchmark, audit, bugfix, test,... | benchmarks/external/mem0_harness/preflight_graph_memory.py,benchmarks/externa... |
| 2026-07-21T07:20:56Z | history:443:dc33c3b0 | session-event | done | history, verify, audit, benchmark, handoff | HISTORY.md,PROJECT_STATUS.md,docs/handoffs/2026-07-21-canonical-graph-fill-fr... |
| 2026-07-21T11:08:11Z | history:444:f50aee8b | session-event | changed | graph, memory, retrieval, benchmark, audit, bugfix, test,... | benchmarks/external/mem0_harness/preflight_graph_memory.py,benchmarks/externa... |
| 2026-07-21T19:47:21Z | history:445:3c8a382d | session-event | in-progress | benchmark, beam, pack, retrieval, audit, test, handoff, v... | seam_runtime/multi_scope_pack.py,benchmarks/external/mem0_harness/seam_mem0_s... |
| 2026-07-21T20:24:11Z | history:446:365a3c98 | session-event | done | benchmark, beam, pack, retrieval, audit, test, handoff, v... | seam_runtime/multi_scope_pack.py,benchmarks/external/mem0_harness/seam_mem0_s... |
| 2026-07-21T21:26:08Z | history:447:c51ad1e0 | session-event | done | ci, test, benchmark, bugfix, performance, verify, continuity | .github/workflows/ci.yml,seam_runtime/models.py,test_seam_all/test_locomo_run... |
| 2026-07-21T23:48:47Z | history:448:8fa1aac6 | session-event | done | benchmark, locomo, retrieval, compile, provenance, audit,... | seam_runtime/multi_speaker_facts.py,seam_runtime/derived_fact_context.py,seam... |
| 2026-07-21T23:50:13Z | history:449:3656720f | session-event | changed | test, verify, history, continuity, audit | HISTORY.md,HISTORY_INDEX.md,.seam/streams/history/log.md,.seam/streams/histor... |
| 2026-07-22T00:00:00Z | roadmap:060:2a5a9591 | status-change | bootstrap | graph, memory, retrieval, benchmark, comparator, provenance | ROADMAP.md:1823 |
| 2026-07-22T03:34:11Z | history:450:2b21583d | session-event | done | benchmark, locomo, retrieval, pack, graph, models, audit,... | seam_runtime/multi_scope_pack.py,benchmarks/external/mem0_harness/preflight_n... |
| 2026-07-22T03:38:17Z | history:451:1236931e | session-event | changed | test, verify, history, continuity, audit | HISTORY.md,HISTORY_INDEX.md,.seam/streams/history/log.md,.seam/streams/histor... |
| 2026-07-22T05:03:16Z | history:452:92876be2 | session-event | changed | benchmark, retrieval, derived-facts, non-displacing-pack,... | seam_runtime/multi_scope_pack.py,benchmarks/external/mem0_harness/preflight_f... |
| 2026-07-22T06:23:10Z | history:453:5dd3c7e3 | session-event | changed | retrieval, graph, knowledge-graph, non-displacing-pack, m... | seam_runtime/graph_source_selector.py,benchmarks/external/mem0_harness/seam_m... |
| 2026-07-22T07:28:54Z | history:454:74725c05 | session-event | done | graph, memory, retrieval, provenance, compile, roadmap, b... | seam_runtime/knowledge_graph.py,seam_runtime/graph_source_selector.py,seam_ru... |
| 2026-07-22T08:10:43Z | history:455:133e97d5 | session-event | done | graph, identity, resolution, knowledge-graph, verify, tes... | docs/roadmap/GRAPH_MEMORY_MATURITY.md |
| 2026-07-22T08:31:29Z | history:456:c5d91902 | session-event | done | graph, identity, resolution, candidate, knowledge-graph, ... | docs/roadmap/GRAPH_MEMORY_MATURITY.md |
| 2026-07-22T08:47:52Z | history:457:2a4d73af | session-event | done | graph, identity, resolution, mcp, cli, rest, server, know... | docs/roadmap/GRAPH_MEMORY_MATURITY.md |
| 2026-07-22T11:15:01Z | history:458:e7f532c2 | session-event | done | graph, identity, resolution, retrieval, vector, knowledge... | docs/roadmap/GRAPH_MEMORY_MATURITY.md |
| 2026-07-22T13:59:43Z | history:459:a7cf1232 | session-event | done | graph, identity, resolution, measurement, tooling, protoc... | docs/kb/seam-internals/lever-graveyard.md |
| 2026-07-22T14:59:22Z | history:460:f3d5ac63 | session-event | done | graph, bugfix, verify, history, continuity, retrieval, pa... | seam_runtime/identity_resolution.py,seam_runtime/cli.py,seam_runtime/pack.py,... |
| 2026-07-22T15:21:34Z | history:461:d0e59411 | session-event | done | graph, memory, agent, protocol, storage, workspace, atomi... | seam_runtime/reasoning_graph.py,seam_runtime/sdk.py,seam_runtime/storage.py,s... |
| 2026-07-22T16:50:30Z | history:462:2b05af6b | session-event | done | graph, retrieval, memory, agent, verify, vector | docs/REASONING_GRAPH.md,docs/roadmap/GRAPH_MEMORY_MATURITY.md,docs/handoffs/2... |
| 2026-07-23T02:46:46Z | history:463:3c16da17 | session-event | done | vector, retrieval, memory, verify | docs/RAG_ARCHITECTURE.md,tests/audit/test_pgvector_boundary_resync.py |
| 2026-07-23T08:59:28Z | history:464:5d53be0e | session-event | done | vector, retrieval, bugfix, verify, test | seam_runtime/runtime.py,tests/audit/test_pgvector_boundary_resync.py,docs/RAG... |
| 2026-07-23T09:34:00Z | history:465:f120ba7d | session-event | done | vector, retrieval, memory, verify, test | seam_runtime/vector.py,seam_runtime/vector_adapters.py,seam_runtime/retrieval... |
| 2026-07-23T16:42:06Z | history:466:dfaafd98 | session-event | done | graph, memory, agent, verify, test, provenance, atomicity... | seam_runtime/reasoning_graph.py,seam_runtime/sdk.py,seam_runtime/storage.py,t... |
| 2026-07-24T00:00:00Z | roadmap:061:f52ecd5e | status-change | bootstrap | packaging, release, distribution | ROADMAP.md:1572 |
| 2026-07-24T10:21:50Z | history:467:9e9791e2 | session-event | changed | security, mirl, surface, pyproject, ci, docs, verify, han... | LICENSE,LICENSES/Apache-2.0.txt,NOTICE,COMMERCIAL_LICENSE.md,CONTRIBUTING.md,... |
| 2026-07-24T10:24:48Z | history:468:e8590966 | session-event | done | ci, security, pyproject, verify, handoff, status | .github/workflows/package-release.yml,PROJECT_STATUS.md,REPO_LEDGER.md,ROADMA... |
| 2026-07-24T12:53:45Z | history:469:3b2e4a9a | session-event | done | agent, surface, pyproject, security, test, handoff, docs | seam_runtime/public_api.py,seam_runtime/server.py,tests/audit/test_public_sdk... |
| 2026-07-24T15:52:53Z | history:470:31703e92 | session-event | done | agent, ci, pyproject, verify, handoff, status | docs/PUBLIC_SDK_API.md,docs/handoffs/2026-07-24-seam-client-0-1-0-live.md,REA... |
| 2026-07-27T17:21:39Z | history:471:d5f50357 | session-event | done | docker, mirl, security, bundle, agent, verify, handoff | seam_runtime/selfhost.py,seam_runtime/selfhost_entitlement.py,selfhost/Docker... |
| 2026-07-27T20:02:02Z | history:472:94271e65 | session-event | done | ci, bugfix, test, verify, history | .github/workflows/ci.yml,tests/audit/test_github_pr_gates.py,PR#169 |
| 2026-07-27T20:12:57Z | history:473:2366f295 | session-event | done | ci, bugfix, test, verify, history | tests/audit/test_selfhost_edition.py,PR#169,run#30300943888 |
| 2026-07-28T04:15:42Z | history:474:82fb3cc3 | session-event | changed | licensing, busl, distribution, docs | LICENSE,LICENSES/BUSL-1.1.txt,NOTICE,COMMERCIAL_LICENSE.md,README.md,CONTRIBU... |
| 2026-07-28T04:15:54Z | history:475:f30d3857 | session-event | changed | pricing, docs, licensing | docs/pricing-tiers.md |
| 2026-07-28T04:16:06Z | history:476:d2c2881a | session-event | changed | release, licensing, distribution-boundary, ci | public_pkg/pyproject.toml,public_pkg/README.md,public_pkg/seam.py,public_pkg/... |
| 2026-07-28T05:52:28Z | history:477:cd1540ba | session-event | changed | selfhost, licensing, busl, security, verify, docker | selfhost/Dockerfile,pyproject.toml,tools/release/build_selfhost.py,tools/rele... |
| 2026-07-28T14:55:22Z | history:478:e836d773 | session-event | done | graph, retrieval, provenance, history, handoff, verify, t... | seam_runtime/retrieval_orchestrator/adapters.py,seam_runtime/retrieval_orches... |
| 2026-07-28T14:55:30Z | history:479:450b261e | session-event | done | graph, retrieval, rank, provenance, test, verify, handoff... | seam_runtime/retrieval_policy.py,seam_runtime/retrieval_orchestrator/merger.p... |
| 2026-07-28T15:26:55Z | history:480:14d762d7 | session-event | changed | selfhost, security, verify, graph, docker | tools/release/verify_selfhost_artifact.py,tests/audit/test_selfhost_edition.p... |
| 2026-07-28T16:32:58Z | history:481:89070f00 | session-event | changed | roadmap, selfhost, packaging, mcp | ROADMAP.md |
| 2026-07-28T17:43:24Z | history:482:e8f54f77 | session-event | changed | selfhost, licensing, busl, entitlement, security, docker | seam_runtime/selfhost.py,seam_runtime/selfhost_entitlement.py,selfhost/compos... |
| 2026-07-28T22:11:37Z | history:483:9b437667 | session-event | done | selfhost, mcp, security, packaging, bundle, verify, test,... | seam_runtime/selfhost_mcp.py,tools/release/build_node_wheel.py,tests/audit/te... |
| 2026-07-28T22:42:05Z | history:484:8cef3b6f | session-event | changed | selfhost, packaging, release, pypi, naming, test, verify | selfhost_pkg/pyproject.toml,tools/release/build_selfhost_wheel.py,tools/relea... |
| 2026-07-28T23:20:55Z | history:485:f42d2568 | session-event | done | selfhost, release, pypi, packaging, busl, verify | .github/workflows/selfhost-release.yml,selfhost_pkg/pyproject.toml |
| 2026-07-28T23:51:04Z | history:486:55291525 | session-event | changed | selfhost, pgvector, embeddings, docs, packaging, release,... | seam_runtime/selfhost.py,selfhost_pkg/pyproject.toml,selfhost_pkg/README.md,t... |
| 2026-07-29T02:15:43Z | history:487:1d877009 | session-event | done | bugfix, bundle, ci, docs, graph, handoff, mcp, pgvector, ... | .github/workflows/package-release.yml,PROJECT_STATUS.md,REPO_LEDGER.md,docs/P... |
| 2026-07-29T02:58:28Z | history:488:18f55355 | session-event | changed | bugfix, bundle, graph, handoff, pgvector, retrieval, secu... | PROJECT_STATUS.md,docs/handoffs/2026-07-29-package-stability-release-candidat... |
| 2026-07-29T03:09:09Z | history:489:d0314671 | session-event | done | bugfix, bundle, ci, graph, handoff, pgvector, retrieval, ... | PROJECT_STATUS.md,docs/handoffs/2026-07-29-package-stability-release-candidat... |
| 2026-07-29T03:31:27Z | history:490:387b5f03 | session-event | done | bundle, ci, graph, handoff, pgvector, retrieval, security... | PROJECT_STATUS.md,REPO_LEDGER.md,docs/handoffs/2026-07-29-stable-packages-liv... |
| 2026-07-29T04:50:58Z | history:491:e00dcf50 | session-event | changed | graph, g3, node-vectors, retrieval, mcp | docs/roadmap/GRAPH_MEMORY_MATURITY.md,docs/REASONING_GRAPH.md |
| 2026-07-29T05:39:28Z | history:492:d051142c | session-event | changed | graph, g3, node-vectors, semantic-seeding, retrieval | docs/roadmap/GRAPH_MEMORY_MATURITY.md |
| 2026-07-29T06:21:50Z | history:493:3a2ced3b | session-event | changed | extraction, derived-facts, benchmarks, ollama | docs/kb/seam-internals/derived-facts-grounded-clm.md |
| 2026-07-29T08:07:06Z | history:494:638f4a69 | session-event | done | graph, retrieval, rank, provenance, verify, benchmark, me... | seam_runtime/reasoning_patterns.py, seam_runtime/reasoning_graph.py, seam_run... |
| 2026-07-29T09:34:17Z | history:495:6171d8cd | session-event | done | graph, reasoning, provenance, storage, mirl, audit, verif... | PROJECT_STATUS.md,REPO_LEDGER.md,docs/CODE_LAYOUT.md,docs/REASONING_GRAPH.md,... |
| 2026-07-29T10:37:47Z | history:496:69f0bf33 | session-event | done | graph, retrieval, pack, storage, persist, retry, benchmar... | PROJECT_STATUS.md,REPO_LEDGER.md,docs/CODE_LAYOUT.md,docs/REASONING_GRAPH.md,... |
| 2026-07-29T15:08:37Z | history:497:c921e841 | session-event | done | handoff, status, graph, reasoning, benchmark, verify | PROJECT_STATUS.md,docs/handoffs/INDEX.md,docs/handoffs/2026-07-29-g5-g7-r6-pr... |
| 2026-07-29T20:57:28Z | history:498:5b00f63c | session-event | done | retrieval, graph, benchmark, reasoning, bugfix, provenanc... | PROJECT_STATUS.md,docs/handoffs/INDEX.md,docs/handoffs/2026-07-29-semantic-re... |
| 2026-07-30T00:34:40Z | history:499:cac73724 | session-event | done | retrieval, graph, reasoning, promotion, benchmark, sdk, v... | seam_runtime/sdk.py,benchmarks/external/mem0_harness/seam_mem0_server.py,test... |
| 2026-07-30T12:36:38Z | history:500:377e4029 | session-event | changed | history, audit, classification, verify | AGENTS.md,HISTORY.md,HISTORY_INDEX.md |
| 2026-07-30T13:19:48Z | history:501:de6bd3e6 | session-event | changed | packaging, consolidation, distribution, licensing, workflows | REPO_LEDGER.md,docs/CODE_LAYOUT.md,ROADMAP.md |
| 2026-07-30T15:22:13Z | history:502:e3a0799e | session-event | changed | retrieval, graph, locomo, surface, vector, tests, verify,... | PROJECT_STATUS.md,REPO_LEDGER.md,docs/CODE_LAYOUT.md,docs/handoffs/2026-07-30... |
| 2026-07-30T16:33:26Z | history:503:1b3130cb | session-event | changed | retrieval, benchmark, locomo, rank, graph, verify, handof... | PROJECT_STATUS.md,REPO_LEDGER.md,docs/handoffs/2026-07-30-full-retrieval-ab-n... |
| 2026-07-30T17:09:40Z | history:504:41987004 | session-event | in-progress | retrieval, benchmark, locomo, rank, graph, verify, handof... | seam_runtime/runtime.py,seam_runtime/retrieval_orchestrator,benchmarks/extern... |
| 2026-07-30T21:07:58Z | history:505:5673f963 | session-event | changed | retrieval, benchmark, wandr, trace, status, locomo, verify | PROJECT_STATUS.md,docs/status/index.md,docs/handoffs/2026-07-30-wandr-zero-ne... |
| 2026-07-31T19:32:14Z | history:506:cfcf42ff | session-event | done | tests, sqlite, test-artifacts, cleanup, windows, verify | none |
| 2026-07-31T22:28:32Z | history:507:7d3ad352 | session-event | done | benchmarks, locomo, operations, huggingface, docs, verify | none |
| 2026-07-31T22:48:26Z | history:508:cac65cb0 | session-event | done | retrieval, graph, fusion, locomo, benchmarks, verify | none |
| 2026-07-31T23:29:44Z | history:509:0389549c | session-event | done | retrieval, graph, fusion, locomo, benchmarks, ablation, v... | none |
| 2026-08-01T00:00:00Z | roadmap:062:d5499fc4 | status-change | bootstrap | packaging, selfhost, distribution, mcp, cli | ROADMAP.md:1634 |
| 2026-08-01T00:00:00Z | roadmap:063:c23e87bf | status-change | bootstrap | audit, storage, retrieval, security, graph, provenance, b... | ROADMAP.md:1909 |
| 2026-08-01T01:48:32Z | history:510:ff1c7a29 | session-event | done | provenance, retrieval, graph, mirl, fusion, verify | none |
| 2026-08-01T09:22:35Z | history:511:71bf65cc | session-event | in-progress | audit, roadmap, plan, status, retrieval, storage, securit... | docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,ROADMAP.md,PROJECT_STATUS.md,docs/... |
| 2026-08-01T10:47:10Z | history:512:6eafc7b3 | session-event | done | fixture, test, wandr, bugfix, verify, continuity | .gitignore,benchmarks/fixtures/wandr/smoke.replay.jsonl,benchmarks/fixtures/w... |
| 2026-08-01T11:52:41Z | history:513:44291c44 | session-event | done | audit, bugfix, benchmark, retrieval, provenance, verify, ... | docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,docs/handoffs/2026-08-01-track-s-s... |
| 2026-08-01T11:56:23Z | history:514:a963e0c4 | session-event | done | history, streams, roadmap, bugfix, verify, test, continuity | tools/history/closeout.py,tests/audit/test_history_closeout.py,.seam/streams/... |
| 2026-08-01T12:29:04Z | history:515:6060ff3a | session-event | done | security, audit, bugfix, bundle, verify, test, history, s... | seam_runtime/ui/logo.py,test_seam_all/test_artifact_hygiene.py,tools/relation... |
| 2026-08-01T13:51:35Z | history:516:6579b20f | session-event | changed | ci, bugfix, security, huggingface, benchmark, verify, his... | .github/workflows/ci.yml,tests/audit/test_locomo_adapter_real_embedding.py,PR... |
| 2026-08-01T14:03:59Z | history:517:533dac16 | session-event | changed | ci, bugfix, huggingface, benchmark, verify, history, streams | .github/workflows/ci.yml,tests/audit/test_locomo_adapter_real_embedding.py,PR... |
| 2026-08-01T14:23:53Z | history:518:838eb489 | session-event | changed | ci, bugfix, huggingface, benchmark, verify, history, streams | .github/workflows/ci.yml,tests/audit/test_locomo_adapter_real_embedding.py,PR... |
| 2026-08-01T14:27:13Z | history:519:b61e9310 | session-event | changed | ci, bugfix, huggingface, benchmark, verify, history, streams | .github/workflows/ci.yml,tests/audit/test_locomo_adapter_real_embedding.py,PR... |
| 2026-08-01T17:00:04Z | history:520:2f7705d1 | session-event | done | audit, bugfix, retrieval, storage, security, server, mcp,... | docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,docs/handoffs/2026-08-01-track-s-s... |
| 2026-08-01T17:59:57Z | history:521:ce1156ed | session-event | done | audit, bugfix, retrieval, rank, test, storage, linux, verify | .gitignore,tests/audit/test_fusion_leg_weights.py |
| 2026-08-01T21:10:17Z | history:522:67e4bfc5 | session-event | done | storage, persist, atomicity, integrity, retry, test, veri... | seam_runtime/migrations.py,seam_runtime/storage.py,tests/audit/test_sqlite_mi... |
| 2026-08-01T21:12:16Z | history:523:3657d08b | session-event | changed | audit, docs, verify, history, handoff, streams | PROJECT_STATUS.md,docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md,docs/handoffs/20... |
| 2026-08-01T22:59:30Z | history:524:101c505c | session-event | done | bugfix, doctor, chroma, security, pyproject, test, verify... | seam_runtime/doctor.py,tests/audit/test_chroma_optional.py,test_seam_all/test... |
| 2026-08-02T00:03:13Z | history:525:2ccd78dc | session-event | done | audit, ci, docs, security, test, verify, history | docs/audits/2026-08-01-full-repo-audit.md,docs/audits/INDEX.md,.github/workfl... |
| 2026-08-02T07:35:40Z | history:526:2da969f0 | session-event | done | bugfix, security, storage, persist, atomicity, locking, r... | seam_runtime/storage.py,seam_runtime/server.py,seam_runtime/migrations.py,sea... |
| 2026-08-03T02:45:03Z | history:527:cad44901 | session-event | done | audit, security, harden, bugfix, graph, retrieval, ci, do... | seam_runtime/server.py,seam_runtime/knowledge_graph.py,seam_runtime/retrieval... |
| 2026-08-03T04:36:20Z | history:528:0055347b | session-event | done | handoff, docs, protocol, continuity, status, verify | docs/handoffs/2026-08-03-audit-repairs-merged.md,docs/handoffs/INDEX.md |
| 2026-08-03T05:21:41Z | history:529:0d3883bb | session-event | done | storage, persist, graph, provenance, integrity, atomicity... | seam_runtime/knowledge_graph.py,seam_runtime/migrations.py,tests/audit/test_k... |
| 2026-08-03T22:05:58Z | history:530:cbfcfc5f | session-event | done | storage, persist, mirl, graph, integrity, atomicity, prov... | seam_runtime/reference_contracts.py,seam_runtime/knowledge_graph.py,seam_runt... |
| 2026-08-03T22:53:54Z | history:531:8d46796b | session-event | done | history, handoff, streams, protocol, git-hooks, tests, bu... | tools/history/new_entry.py,tools/history/test_history_tools.py,docs/handoffs/... |
| 2026-08-04T01:00:04Z | history:532:665c9106 | session-event | changed | track-s, retrieval, storage, vector, durability, operations | seam_runtime/read_snapshot.py,seam_runtime/vector_outbox.py,seam_runtime/pool... |
| 2026-08-04T03:28:40Z | history:533:ec47c306 | session-event | done | track-s, operations, retrieval, storage, vector, publication | PROJECT_STATUS.md,docs/status/operations.md,docs/roadmap/MEMORY_GUARANTEES_CA... |
| 2026-08-04T23:33:39Z | history:534:aa584b09 | session-event | done | ci, hygiene, worktree, protocol, enforcement, verify | tools/ci/github_maintenance_report.py,.github/workflows/repository-maintenanc... |
| 2026-08-05T00:18:21Z | history:535:8e413826 | session-event | done | test, api, security, audit, tenancy | tests/audit/test_public_api_v1_http.py,docs/audits/2026-08-01-full-repo-audit.md |
| 2026-08-05T04:21:46Z | history:536:0413b88a | session-event | done | protocol, verify, ci, audit, history | tools/claude/preflight_protocol.sh,tools/git-hooks/pre-commit,tools/history/c... |
| 2026-08-05T15:26:42Z | history:537:ae51741b | session-event | done | tui, cli, surfaces, dashboard, config, verify | seam_runtime/tui/app.py,seam_runtime/tui/settings_screen.py,seam_runtime/conf... |
| 2026-08-05T16:01:09Z | history:538:cdcdba92 | session-event | done | benchmarks, mem0, positioning, roadmap, correction, tenancy | docs/kb/memory-systems/mem0.md,docs/kb/memory-systems/seam-positioning.md,doc... |
| 2026-08-05T16:31:24Z | history:539:b6845b76 | session-event | done | ci, tests, tui, verify, gates | .github/workflows/ci.yml,.github/workflows/ci-windows.yml,tests/audit/test_tu... |
| 2026-08-06T22:44:45Z | history:540:4a989fbc | session-event | done | tui, surfaces, dashboard, provenance, roadmap, verify | seam_runtime/tui/panels.py,seam_runtime/tui/app.py,seam_runtime/tui/theme.tcs... |
| 2026-08-06T23:29:00Z | history:541:591dd697 | session-event | done | tui, palette, cli, api, sdk, surfaces, verify | seam_runtime/server.py,seam_runtime/sdk.py,seam_runtime/tui/commands.py,seam_... |
| 2026-08-07T04:39:51Z | history:542:c9a1de0d | session-event | done | tui, modes, shell, chat, security, navigation, verify | seam_runtime/tui/shell.py,seam_runtime/tui/app.py,seam_runtime/tui/commands.p... |
| 2026-08-10T06:39:24Z | history:543:e3d23a4c | session-event | done | animation, bugfix, memory, security, surface, test, textu... | .gitattributes,branding/kit,branding/README.md,branding/assets/mature/seam-te... |
| 2026-08-10T19:39:31Z | history:544:958270f4 | session-event | done | animation, dashboard, graph, surface, test, verify, webui | seam_runtime/webui/dashboard.html,tests/audit/test_knowledge_graph.py,docs/KN... |
| 2026-08-10T19:41:07Z | history:545:3e106537 | session-event | done | continuity, graph, history, surface, verify, webui | HISTORY#544,seam_runtime/webui/dashboard.html,tests/audit/test_knowledge_grap... |
| 2026-08-10T19:41:20Z | history:546:e2258ccb | session-event | done | continuity, history, verify | HISTORY#544,HISTORY#545 |
| 2026-08-10T22:08:49Z | history:547:b6fbe0d6 | session-event | done | graph, retrieval, benchmark, persist, integrity, verify | seam_runtime/improvement_experiments.py,seam_runtime/storage.py,seam_runtime/... |
| 2026-08-10T22:39:55Z | history:548:07f48d67 | session-event | done | continuity, history, verify, test | .seam/cross_index.md,.seam/cross_index_archive/0001-0411.cross.md,.seam/strea... |
| 2026-08-10T23:39:47Z | history:549:5716f02a | session-event | done | surface, animation, docs, test, verify | .gitattributes,branding/README.md,branding/canticle-cosmic-kit,docs/CODE_LAYO... |
| 2026-08-11T00:00:06Z | history:550:2436f418 | session-event | done | bugfix, security, surface, test, verify | branding/canticle-cosmic-kit/css/canticle-cosmic.css,branding/canticle-cosmic... |
| 2026-08-11T05:00:08Z | history:551:820a6b22 | session-event | done | status, roadmap, audit, docs, continuity, verify | docs/audits/2026-08-10-track-s-visual-status-report.md,docs/audits/INDEX.md,d... |
| 2026-08-11T05:47:41Z | history:552:ed81ddc7 | session-event | done | audit, docs, history, continuity, verify, status | HISTORY#551,docs/audits/2026-08-10-track-s-visual-status-report.md,docs/audit... |
| 2026-08-11T05:56:03Z | history:553:2793e88a | session-event | done | audit, docs, history, continuity, verify, status, retriev... | HISTORY#552,HISTORY#509,docs/audits/2026-08-10-track-s-visual-status-report.m... |
| 2026-08-11T15:43:16Z | history:554:968ea4e4 | session-event | done | tui, keyboard, textual, defect, config, docs, tests | HISTORY#542,seam_runtime/tui/keys.py,seam_runtime/tui/app.py,seam_runtime/tui... |
| 2026-08-11T15:45:32Z | history:555:55a38b1f | session-event | done | history, correction, gates, worktree, verify | HISTORY#554,tools/git-hooks/pre-push,tests/audit/test_public_safe_gate.py |
| 2026-08-11T16:44:27Z | history:556:f5b7c69a | session-event | done | docs, wiki, navigation, commonmark, gates, ci, parity, ve... | HISTORY#553,tools/docs/verify_wiki.py,tests/audit/test_wiki_navigation.py,doc... |
| 2026-08-11T16:50:52Z | history:557:40a8ec3b | session-event | done | history, correction, verify, wiki, gates | HISTORY#556,HISTORY#555,tests/audit/test_public_safe_gate.py,tools/git-hooks/... |
| 2026-08-12T23:31:08Z | history:558:104d9e3e | session-event | changed | docs, audit, security, history, ci, tests, verify, correc... | HISTORY#557,PR#214,tools/docs/verify_wiki.py,tests/audit/test_wiki_navigation... |
| 2026-08-12T23:43:12Z | history:559:901e2567 | session-event | done | tui, config, bugfix, test, verify, history | HISTORY#558,HISTORY#555,PR#216,seam_runtime/tui/app.py,seam_runtime/tui/setti... |
| 2026-08-13T04:45:00Z | history:560:e9ee3b51 | session-event | done | audit, docs, history, continuity, verify, status, roadmap... | HISTORY#559,HISTORY#538,HISTORY#535,HISTORY#533,docs/audits/2026-08-12-full-r... |
| 2026-08-14T03:47:18Z | history:561:42852c09 | session-event | done | security, provenance, signing, hooks, git, verify, histor... | HISTORY#560,tools/git-hooks/pre-push,.seam/cross_index.md,.seam/streams/histo... |
| 2026-08-14T04:05:15Z | history:562:e2761c1e | session-event | done | security, provenance, git-hooks, verify, history, bugfix,... | HISTORY#561,HISTORY#560,HISTORY#355,PR#217,tools/git-hooks/pre-push,docs/audi... |
| 2026-08-14T06:13:24Z | history:563:4dcc3530 | session-event | done | audit, docs, verify, history, protocol, test, continuity | HISTORY#562,HISTORY#561,HISTORY#560,tools/docs/verify_audit_claims.py,tests/a... |
| 2026-08-14T18:57:30Z | history:564:4e6b4b23 | session-event | done | branding, docs, verify, test, history, protocol | HISTORY#563,branding/kit/tokens.json,tools/branding/assets.py,tests/audit/tes... |
| 2026-08-14T20:36:47Z | history:565:754e7f51 | session-event | done | branding, docs, verify, bugfix, history | HISTORY#564,HISTORY#563,tools/branding/assets.py,branding/kit/tokens.json |
| 2026-08-15T23:23:49Z | history:566:af03d830 | session-event | done | branding, docs, test, verify | HISTORY#565,HISTORY#564,tools/branding/assets.py,tests/audit/test_branding_as... |
| 2026-08-17T11:51:21Z | history:567:06d54ca3 | session-event | done | status, worktree, reconcile, audit, docs, continuity | docs/status/workspace.md,PROJECT_STATUS.md,REPO_LEDGER.md,PR#207,PR#213 |
| 2026-08-17T11:53:16Z | history:568:4ae87616 | session-event | done | verify, status, worktree, docs, continuity, test | HISTORY#567,docs/status/workspace.md,tests/audit/test_wiki_navigation.py,tool... |
| 2026-08-17T11:58:12Z | history:569:68651609 | session-event | changed | status, worktree, reconcile, audit, docs, continuity | docs/status/workspace.md,REPO_LEDGER.md,HISTORY#568 |
| 2026-08-17T12:11:09Z | history:570:78018fef | session-event | changed | correction, audit, history, status, reconcile, verify | HISTORY#566,HISTORY#568,HISTORY#569,docs/status/workspace.md,PR#220 |
| 2026-08-19T04:06:43Z | history:571:ead7bf1e | session-event | done | audit, benchmark, bugfix, graph, harden, operator, persis... | HISTORY#570,PROJECT_STATUS.md,REPO_LEDGER.md,docs/audits/2026-08-18-track-s-d... |
| 2026-08-19T04:11:06Z | history:572:0b3a3ad6 | session-event | done | bugfix, git-hooks, test, verify, worktree | HISTORY#571,tools/git-hooks/pre-push,tests/audit/test_public_safe_gate.py |
| 2026-08-19T04:13:50Z | history:573:3744fd57 | session-event | changed | bugfix, correction, git-hooks, verify, worktree | HISTORY#572,tools/git-hooks/pre-push,tests/audit/test_public_safe_gate.py,doc... |
| 2026-08-19T09:47:52Z | history:574:bbc227ed | session-event | in-progress | audit, continuity, handoff, harden, lifecycle, migration,... | HISTORY#573,docs/handoffs/2026-08-19-track-s-s6-in-progress.md,docs/audits/20... |
| 2026-08-22T08:42:39Z | history:575:4278e8b9 | session-event | changed | audit, bugfix, continuity, handoff, harden, lifecycle, mi... | HISTORY#574,docs/handoffs/2026-08-22-track-s-s6-locally-qualified.md,docs/aud... |
| 2026-08-22T08:47:54Z | history:576:9eb10e23 | session-event | changed | correction, audit, continuity, docs, verify | HISTORY#575,docs/audits/2026-08-19-track-s-s6-principal-tenancy-threat-model.... |
| 2026-08-22T11:32:21Z | history:580:e79d1fe9 | session-event | done | ci, docs, gates, operator, registry, security, tests, verify | HISTORY#579,.github/ISSUE_TEMPLATE,.github/workflows/package-release.yml,.git... |
| 2026-08-22T11:39:49Z | history:581:ac6688b9 | session-event | changed | bugfix, ci, correction, gates, pyproject, tests, verify | HISTORY#580,PR#224,.github/workflows/package-release.yml,tools/ci/verify_depe... |
| 2026-08-23T03:02:53Z | history:577:00ea6abf | session-event | changed | bugfix, security, surface, storage, test, verify, continu... | HISTORY#576,PR#223,seam_runtime/public_memory_handles.py,seam_runtime/public_... |
| 2026-08-23T03:35:00Z | history:578:a71f9112 | session-event | changed | bugfix, security, surface, storage, test, verify, continu... | HISTORY#577,PR#223,seam_runtime/public_memory_handles.py,seam_runtime/lifecyc... |
| 2026-08-23T04:00:04Z | history:579:becfc7bc | session-event | changed | atomicity, bugfix, locking, security, surface, storage, t... | HISTORY#578,PR#223,seam_runtime/runtime.py,seam_runtime/server.py,seam_runtim... |
| 2026-08-23T04:15:43Z | history:582:c8609f49 | session-event | changed | ci, docs, gates, handoff, history, operator, registry, se... | HISTORY#581,PR#223,PR#224,docs/handoffs/2026-08-22-github-operations-restacke... |
| 2026-08-23T04:31:22Z | history:583:ab9783a4 | session-event | changed | bugfix, ci, docs, gates, handoff, security, status, test,... | HISTORY#582,PR#224,tools/release/verify_private_artifacts.py,.github/workflow... |
| 2026-08-23T04:35:27Z | history:584:67598c4b | session-event | changed | bugfix, ci, docs, gates, handoff, security, test, verify | HISTORY#583,PR#224,.github/workflows/package-release.yml,tests/audit/test_git... |
| 2026-08-23T04:49:40Z | history:585:b1224212 | session-event | changed | bugfix, ci, docs, gates, handoff, security, status, test,... | HISTORY#584,PR#224,tools/release/verify_private_artifacts.py,.github/workflow... |
| 2026-08-23T04:57:49Z | history:586:dbb95462 | session-event | changed | audit, ci, correction, docs, handoff, provenance, test, v... | HISTORY#585,PR#224,tests/audit/test_github_issue_release_config.py,.seam/cros... |
| 2026-08-23T04:58:37Z | history:587:b4188469 | session-event | changed | correction, history, integrity, provenance, verify | HISTORY#586,tests/audit/test_github_issue_release_config.py,docs/handoffs/202... |


## Archive Pointers

| chunk | utc_range | event_count | streams | top_topics |
|---|---|---|---|---|
| 0001-0450.cross.md | 2026-04-15T00:00:00Z..2026-07-15T11:29:48Z | 450 | (multi) | (multi) |
