# Cross-Index

schema: seam-cross-index/v1
source: streams/*/log.md (derived; do not hand-edit)
total_events: 571
hot_zone_max: 200
archive_pattern: cross_index_archive/<lo>-<hi>.cross.md

## Hot Zone (latest 200 events, oldest first)
| utc | stream:id:hash | kind | event | topics | refs |
|---|---|---|---|---|---|
| 2026-06-14T13:26:00Z | history:316:a45c14d0 | session-event | done | pack, density, compression, context, symbols, prov, evide... | seam_runtime/pack.py,test_seam_all/test_seam.py,HISTORY.md,HISTORY_INDEX.md,P... |
| 2026-06-14T23:53:15Z | history:317:8008e5f4 | session-event | done | nl, compiler, ingest, enrichment, regex, locomo, benchmar... | seam_runtime/nl.py,tests/audit/test_conversation_turn_compile.py,test_seam_al... |
| 2026-06-15T00:00:00Z | roadmap:057:3277f475 | status-change | bootstrap | query, sql, retrieval, benchmark, bird | ROADMAP.md:1707 |
| 2026-06-15T01:01:25Z | history:318:986aa846 | session-event | done | retrieval, multihop, locomo, benchmark, scope, query, sql... | docs/audits/2026-06-15-cat1-cat3-multihop-scope.md,docs/roadmap/SEAM_QUERY_EN... |
| 2026-06-15T01:17:23Z | history:319:4081a094 | session-event | done | roadmap, query, sql, bird, benchmark, retrieval, multihop... | ROADMAP.md,HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md |
| 2026-06-15T03:39:08Z | history:320:25494450 | session-event | done | retrieval, budget, topk, locomo, benchmark, judge, recall... | seam_runtime/retrieval.py,seam_runtime/runtime.py,benchmarks/external/locomo/... |
| 2026-06-15T04:42:47Z | history:321:8f340dc0 | session-event | done | retrieval, answerer, reasoning, locomo, benchmark, judge,... | benchmarks/external/locomo/adapters/seam.py,HISTORY.md,HISTORY_INDEX.md,PROJE... |
| 2026-06-15T12:01:01Z | history:322:e08eb1a6 | session-event | done | test, pgvector, protocol, docs, history | AGENTS.md,REPO_LEDGER.md,docs/CODE_LAYOUT.md,tests/docs/README.md,tests/docs/... |
| 2026-06-15T14:29:51Z | history:323:427968af | session-event | done | retrieval, locomo, cat1, coreference, entity-aggregation,... | benchmarks/external/locomo/adapters/seam.py,tests/audit/test_locomo_entity_ag... |
| 2026-06-17T22:49:30Z | history:324:e8d2acce | session-event | done | doctor, stash, git, hygiene, tooling, protocol, history | seam_runtime/doctor.py,seam_runtime/cli.py,tests/audit/test_doctor_stashes.py... |
| 2026-06-18T01:26:35Z | history:325:13dd6b94 | session-event | done | calibration, abstention, benchmark, locomo, scorer, epist... | benchmarks/external/locomo/calibration_scorer.py,benchmarks/external/common/d... |
| 2026-06-18T05:27:21Z | history:326:cd345e8f | session-event | done | webui, dashboard, cleanup, structure, docs, dependabot, a... | docs/CODE_LAYOUT.md,.github/dependabot.yml,archive/webui-vite-source/ARCHIVED... |
| 2026-06-19T00:46:44Z | history:327:52811e9b | session-event | done | judge, benchmark, locomo, openai, reasoning, bugfix, gpt5... | benchmarks/external/common/judge.py,tests/audit/test_openai_judge_gpt5.py,HIS... |
| 2026-06-19T02:47:17Z | history:328:f5702bd8 | session-event | done | retrieval, profile, retrievalflags, core, locomo, cat1, a... | seam_runtime/retrieval.py,seam_runtime/runtime.py,tests/audit/test_retrieval_... |
| 2026-06-19T08:20:53Z | history:329:475ed601 | session-event | done | docs, test, benchmark, status, history | docs/progress_tables/README.md,docs/progress_tables/test_runs.csv,docs/progre... |
| 2026-06-20T08:34:57Z | history:330:7e2c1696 | session-event | done | security, codeql, test, tempfile | tests/audit/test_retrieval_flags.py |
| 2026-06-20T14:58:16Z | history:331:7cbe5ba6 | session-event | done | docs, engineering, manual, skill, templates | docs/engineering/README.md,docs/engineering/templates/README.md,skills/seam-e... |
| 2026-06-21T17:33:37Z | history:332:b9cbb8ff | session-event | done | retrieval, self-improvement, loop, profile, locomo | benchmarks/external/locomo/answer_quality_scorer.py,seam_runtime/self_improve... |
| 2026-06-26T08:22:49Z | history:333:98c0f0f0 | session-event | done | benchmark, locomo, mem0, answerer, harness, comparison, f... | benchmarks/external/common/answerer.py,benchmarks/external/locomo/run.py,benc... |
| 2026-06-26T22:11:10Z | history:334:4a535172 | session-event | done | benchmark, locomo, mem0, judge, retrieval, profile, confo... | benchmarks/external/locomo/judged_scorer.py,tests/audit/test_judged_scorer.py |
| 2026-06-26T23:08:35Z | history:335:7b74fc23 | session-event | done | benchmark, locomo, mem0, adapter, bugfix, test, history | benchmarks/external/locomo/adapters/mem0.py,test_seam_all/test_locomo_mem0_ad... |
| 2026-06-27T00:00:00Z | history:336:3a688abd | session-event | done | benchmark, locomo, mem0, retry, judge, bugfix, test, history | benchmarks/external/common/provider_retry.py,benchmarks/external/common/answe... |
| 2026-06-27T00:00:00Z | history:337:1071f2ca | session-event | done | installer, macos, docs, test, history | installers/install_seam_macos.sh,seam_runtime/installer.py,installers/install... |
| 2026-06-27T00:00:00Z | history:338:5ed0d240 | session-event | done | benchmark, locomo, mem0, retrieval, test, docs, history | benchmarks/external/locomo/adapters/mem0.py,benchmarks/external/locomo/run.py... |
| 2026-06-27T15:16:28Z | history:339:7ca998d1 | session-event | done | pyproject, readme, ci, test, docs, history | pyproject.toml,README.md,MANIFEST.in,.github/workflows/ci.yml,tests/audit/tes... |
| 2026-06-27T17:52:01Z | history:340:2681bb08 | session-event | done | readme, docs, prompt, memory, operator, webui, test, history | README.md,docs/README.md,docs/errors.md,tests/audit/test_github_package_metad... |
| 2026-06-27T18:03:10Z | history:341:1c9841e7 | session-event | done | readme, docs, test, history | README.md,tests/audit/test_github_package_metadata.py |
| 2026-06-28T03:58:48Z | history:342:fff85ad5 | session-event | done | chat, dashboard, webui, memory, persist, test, history | seam_runtime/server.py,seam_runtime/webui/seam-api.js,seam_runtime/webui/dash... |
| 2026-06-29T06:15:22Z | history:343:125c00fc | session-event | done | benchmark, locomo, mem0, scripts, handoff, test, history | tools/benchmarks/rung_c_paid.py,tests/audit/test_rung_c_paid_runner.py,docs/h... |
| 2026-07-03T14:36:09Z | history:344:19f81224 | session-event | done | git-hooks, security, verify, test, docs | tools/release/verify_public_safe.py,tools/release/__init__.py,tools/git-hooks... |
| 2026-07-03T15:15:01Z | history:345:677aea14 | session-event | done | readme, prompt, docs | README.md |
| 2026-07-03T16:21:14Z | history:346:8e76711d | session-event | done | readme, ledger, roadmap, protocol | LICENSE,NOTICE,COMMERCIAL_LICENSE.md,CONTRIBUTING.md,README.md,REPO_LEDGER.md... |
| 2026-07-03T23:54:27Z | history:347:029e01d2 | session-event | done | mcp, pyproject, readme, registry | pyproject.toml,README.md,server.json,seam_runtime/mcp_protocol.py |
| 2026-07-04T00:04:38Z | history:348:a3175bc2 | session-event | done | registry, mcp | server.json |
| 2026-07-04T00:16:21Z | history:349:25a779c8 | session-event | changed | protocol, git-hooks, security | PR#115 |
| 2026-07-06T01:01:48Z | history:350:4f4608dd | session-event | done | mcp, registry, pypi, release | pyproject.toml,server.json,README.md,seam_runtime/mcp_protocol.py |
| 2026-07-06T01:12:39Z | history:351:a07a4103 | session-event | changed | protocol, git-hooks, security | PR#117 |
| 2026-07-06T02:07:42Z | history:352:71dbffca | session-event | done | docs, macos, installer, readme | docs/MACOS.md,docs/setup.md,docs/README.md,docs/errors.md,docs/howto/README.m... |
| 2026-07-06T02:10:27Z | history:353:162c9fc2 | session-event | done | docs, macos, operator, readme | docs/SEAM_OPERATOR_GUIDE.md,docs/MACOS.md,docs/README.md,README.md |
| 2026-07-06T02:20:59Z | history:354:e3857106 | session-event | done | docs, macos, pgvector, correction | docs/MACOS.md,docs/SEAM_OPERATOR_GUIDE.md,docs/PGVECTOR_LOCAL.md |
| 2026-07-06T03:16:22Z | history:355:3e6365ea | session-event | changed | protocol, security, release, routing | tools/release/public_manifest.py,tools/release/sync_public_mirror.py,tools/re... |
| 2026-07-06T12:37:09Z | history:356:2b504aaf | session-event | done | protocol, security, release | tools/release/sync_public_mirror.py |
| 2026-07-06T19:38:33Z | history:357:78e26de9 | session-event | done | lint, tooling, docs, tests | pyproject.toml,REPO_LEDGER.md,docs/CODE_LAYOUT.md,seam.py,tools/history/write... |
| 2026-07-06T23:21:18Z | history:358:2eb9586d | session-event | done | retrieval, coreference, entity-aggregation, locomo, cat1,... | seam_runtime/storage.py,seam_runtime/nl.py,seam_runtime/retrieval.py,tests/au... |
| 2026-07-07T18:59:07Z | history:359:951ab6e8 | session-event | done | ci, tests, git-hooks, pr, merge, security, vector-adapter... | tests/audit/test_sync_public_mirror.py,seam_runtime/vector_adapters.py |
| 2026-07-07T19:33:26Z | history:360:4d15dbbe | session-event | done | ci, tests, windows, installer, git, mirror-sync, cross-pl... | tools/release/sync_public_mirror.py,test_seam_all/test_seam.py,seam_runtime/i... |
| 2026-07-07T20:31:43Z | history:361:5b9cb577 | session-event | done | ci, tests, windows, ssrf, flaky, skip-policy | tests/audit/test_audit_2026_06_05.py |
| 2026-07-08T03:44:02Z | history:362:f93632fb | session-event | done | handoff, locomo, cat1, cat3, retrieval, performance, prof... | docs/handoffs/2026-07-07-cat1-cat3-scoping-handoff.md |
| 2026-07-08T04:31:56Z | history:363:00e4e5ea | session-event | done | ci, performance, retrieval, numpy, cosine, disk-space, de... | .github/workflows/ci.yml, seam_runtime/models.py, tests/audit/test_cosine_num... |
| 2026-07-08T16:08:52Z | history:364:50aeef5f | session-event | done | performance, retrieval, vector, sqlite, cache, numpy, ben... | seam_runtime/vector.py, tests/audit/test_vector_cache_parity.py, test_seam_al... |
| 2026-07-08T16:36:07Z | history:365:9de60364 | session-event | done | locomo, cat1, cat3, benchmark, paid, diagnostic, generati... | docs/audits/2026-07-08-cat13-generation-side-paid-confirmation.md |
| 2026-07-08T22:50:21Z | history:366:fe1cd501 | session-event | done | benchmark, telemetry, run-record, cost, reasoning, cot, t... | benchmarks/external/common/run_record.py, benchmarks/external/common/pricing.... |
| 2026-07-09T00:09:26Z | history:367:2278b41a | session-event | done | benchmark, deepseek, answerer, reasoning, cot, run-record... | benchmarks/external/locomo/adapters/seam.py, benchmarks/external/common/answe... |
| 2026-07-09T13:11:14Z | history:368:f6b7058a | session-event | done | deepseek, pricing, answerer, model-selection, correctness... | benchmarks/external/locomo/adapters/seam.py, benchmarks/external/common/prici... |
| 2026-07-09T22:06:19Z | history:369:466ae477 | session-event | done | locomo, cat1, cat3, deepseek, benchmark, handoff, gold-no... | docs/handoffs/2026-07-09-cat1-cat3-deepseek-fixes-handoff.md |
| 2026-07-09T22:40:39Z | history:370:fe908a9e | session-event | done | ci, tests, deepseek, benchmark, windows, bugfix | tests/audit/test_run_record.py |
| 2026-07-10T00:58:27Z | history:371:64d25145 | session-event | done | benchmark, locomo, audit, quality, tests | benchmarks/external/common/scoring.py, benchmarks/external/common/run_record.... |
| 2026-07-10T01:52:55Z | history:372:db3b41ad | session-event | done | benchmark, locomo, judge, tests | benchmarks/external/common/judge.py, tools/h2/rejudge_record.py, tests/audit/... |
| 2026-07-10T02:13:52Z | history:373:7fc68391 | session-event | done | benchmark, locomo, judge, tests, provenance | tools/h2/rejudge_record.py, tests/audit/test_rejudge_record.py |
| 2026-07-10T12:38:26Z | history:374:d9ca53b9 | session-event | done | bugfix, judge, benchmark, tests, verify, history | benchmarks/external/common/judge.py, test_seam_all/test_locomo_judge.py, test... |
| 2026-07-11T10:19:44Z | history:375:37cbccba | session-event | done | benchmark, locomo, handoff, evidence, judge | docs/handoffs/2026-07-11-cat1-cat3-pr1-pr2-pr3-handoff.md |
| 2026-07-11T11:00:41Z | history:376:73a04b3c | session-event | done | benchmark, locomo, judge, audit, quality, verify | docs/audits/2026-07-11-cat13-judge2-paid-rejudge.md, tools/h2/rejudge_record.... |
| 2026-07-11T15:32:11Z | history:377:761edaec | session-event | done | benchmark, locomo, audit, judge, retrieval, quality | docs/audits/2026-07-11-cat13-private-offline-adjudication.md, PROJECT_STATUS.md |
| 2026-07-11T17:17:35Z | history:378:f77e4b36 | session-event | done | handoff, protocol, continuity, multi-agent, ci, docs, ver... | docs/handoffs/INDEX.md,docs/handoffs/2026-07-11-cat1-cat3-success-contract-ha... |
| 2026-07-11T17:18:09Z | history:379:4c759d1c | session-event | changed | history, handoff, bugfix, continuity, verify | docs/handoffs/INDEX.md,docs/handoffs/2026-07-11-cat1-cat3-success-contract-ha... |
| 2026-07-11T18:01:34Z | history:380:8b3fadc7 | session-event | changed | ci, handoff, bugfix, protocol, verify, tests, history | .github/workflows/ci.yml,tests/audit/test_ci_verify_gates.py,PR#141 |
| 2026-07-11T22:58:00Z | history:381:e34c302b | session-event | in-progress | benchmark, locomo, retrieval, answerer, quality, handoff,... | docs/handoffs/2026-07-11-cat13-semantic-conversation-adapter-in-progress.md,.... |
| 2026-07-12T00:03:58Z | history:382:32666036 | session-event | done | benchmark, locomo, retrieval, prompt, quality, handoff, c... | seam_runtime/conversation.py,seam_runtime/retrieval.py,seam_runtime/self_impr... |
| 2026-07-12T05:39:56Z | history:383:6b2cac1d | session-event | done | benchmark, locomo, quality, retrieval, merge, verify, pai... | HISTORY.md,PROJECT_STATUS.md,HISTORY_INDEX.md |
| 2026-07-12T21:22:48Z | history:384:096e1844 | session-event | done | benchmark, locomo, competitors, zep, mem0, paid-validatio... | benchmarks/external/locomo/run.py,benchmarks/external/locomo/adapters/zep.py,... |
| 2026-07-13T03:25:35Z | history:385:4f2a7c73 | session-event | done | benchmark, locomo, retrieval, quality, paid-validation, v... | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md |
| 2026-07-13T23:21:38Z | history:386:1c619b66 | session-event | done | benchmark, locomo, retrieval, quality, command, tests, ha... | seam_runtime/cli.py,tests/audit/test_judged_scorer.py,test_seam_all/test_loco... |
| 2026-07-13T23:45:23Z | history:387:1d31ef23 | session-event | changed | history, handoff, status, verify, ci | PROJECT_STATUS.md,docs/handoffs/INDEX.md,docs/handoffs/2026-07-13-improve-val... |
| 2026-07-14T01:43:37Z | history:388:1e8e9de6 | session-event | done | review, ci, merge, history, status, verify | seam_runtime/cli.py,tests/audit/test_judged_scorer.py,test_seam_all/test_loco... |
| 2026-07-14T03:41:21Z | history:389:a8b788fe | session-event | done | benchmark, locomo, retrieval, quality, command, tests, ve... | seam_runtime/conversation.py,seam_runtime/retrieval.py,seam_runtime/self_impr... |
| 2026-07-15T01:05:17Z | history:390:5136df2c | session-event | done | benchmark, locomo, retrieval, quality, paid-validation, b... | benchmarks/external/locomo/judged_scorer.py,tests/audit/test_judged_scorer.py... |
| 2026-07-15T03:19:09Z | history:391:aa60db95 | session-event | done | benchmark, locomo, quality, audit, verify | docs/audits/2026-07-14-post-temporal-per-case-review.md,PROJECT_STATUS.md |
| 2026-07-15T11:14:21Z | history:392:212b18cf | session-event | done | benchmark, locomo, quality, paid-validation, negative-res... | seam_runtime/conversation.py,tools/h2/rejudge_record.py,tests/audit/test_sema... |
| 2026-07-15T11:29:48Z | history:393:765c2d9f | session-event | done | benchmark, mem0, harness, command, tests, verify | benchmarks/external/mem0_harness/seam_mem0_server.py,tests/audit/test_seam_me... |
| 2026-07-15T11:35:53Z | history:394:f348135d | session-event | done | benchmark, mem0, harness, cleanup | benchmarks/external/mem0_harness/README.md,benchmarks/external/mem0_harness/s... |
| 2026-07-15T11:49:56Z | history:395:de5bf982 | session-event | done | benchmark, locomo, mem0, harness, retrieval, quality, tes... | seam_runtime/conversation.py,seam_runtime/self_improve.py,tests/audit/test_se... |
| 2026-07-15T12:08:08Z | history:396:6f876cc6 | session-event | done | benchmark, locomo, quality, audit | docs/audits/2026-07-15-champion-problem-scan.md,PROJECT_STATUS.md |
| 2026-07-15T12:24:16Z | history:397:c5ff6b8a | session-event | done | benchmark, locomo, quality, handoff, continuity, verify | seam_runtime/conversation.py,seam_runtime/self_improve.py,tests/audit/test_se... |
| 2026-07-15T14:14:56Z | history:398:07f4efb0 | session-event | done | benchmark, locomo, judge, quality, audit, handoff, verify... | PROJECT_STATUS.md,docs/audits/2026-07-15-c4-and-mem0-cat13-score.md,docs/hand... |
| 2026-07-15T14:17:19Z | history:399:008c723c | session-event | changed | history, continuity, verify, handoff, benchmark, locomo | PROJECT_STATUS.md,docs/audits/2026-07-15-c4-and-mem0-cat13-score.md,docs/hand... |
| 2026-07-15T14:24:23Z | history:400:2d638e36 | session-event | done | bugfix, benchmark, locomo, retrieval, temporal, tests, ci... | benchmarks/external/mem0_harness/seam_mem0_server.py,tests/audit/test_seam_me... |
| 2026-07-16T00:00:00Z | roadmap:058:9e33f50a | status-change | bootstrap | agent, openclaw, namespaces, profiles, console | ROADMAP.md:1771 |
| 2026-07-16T00:00:00Z | roadmap:059:8ddd7075 | status-change | bootstrap | android, mobile, small-models, memory-loop | ROADMAP.md:1831 |
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
| 2026-07-22T00:00:00Z | roadmap:060:50daaaa2 | status-change | bootstrap | graph, memory, retrieval, benchmark, comparator, provenance | ROADMAP.md:1868 |
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
| 2026-07-28T00:00:00Z | roadmap:062:f3f25c18 | status-change | bootstrap | packaging, selfhost, distribution, mcp, cli | ROADMAP.md:1634 |
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


## Archive Pointers

| chunk | utc_range | event_count | streams | top_topics |
|---|---|---|---|---|
| 0001-0371.cross.md | 2026-04-15T00:00:00Z..2026-06-14T12:27:24Z | 371 | (multi) | (multi) |
