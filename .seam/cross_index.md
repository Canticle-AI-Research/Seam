# Cross-Index

schema: seam-cross-index/v1
source: streams/*/log.md (derived; do not hand-edit)
total_events: 382
hot_zone_max: 200
archive_pattern: cross_index_archive/<lo>-<hi>.cross.md

## Hot Zone (latest 200 events, oldest first)
| utc | stream:id:hash | kind | event | topics | refs |
|---|---|---|---|---|---|
| 2026-05-08T21:52:11Z | history:154:3246a284 | session-event | done | compile, search, roadmap, status, history | ROADMAP.md,HISTORY_INDEX.md,seam_runtime/server.py,pyproject.toml |
| 2026-05-08T21:57:50Z | history:155:f136dbff | session-event | done | roadmap, status, history, snapshot, verify, audit, protocol | ROADMAP.md,PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/snapshots,.cla... |
| 2026-05-08T22:01:15Z | history:156:59a944f1 | session-event | done | verify, history, snapshot, status, audit | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/snapshots |
| 2026-05-09T03:30:07Z | history:157:32f10cae | session-event | done | dashboard, roadmap, status, verify | ROADMAP.md#A-Web,experimental/webui/README.md,seam_runtime/server.py |
| 2026-05-09T04:00:18Z | history:158:99b6a799 | session-event | done | dashboard, verify, protocol, ledger, status, history | experimental/webui,experimental/webui/src/api/apiClient.ts,seam_runtime/serve... |
| 2026-05-09T04:17:11Z | history:159:3b6a7f68 | session-event | done | dashboard, verify, history, status | experimental/webui/src/App.tsx,experimental/webui/vite.config.ts,experimental... |
| 2026-05-09T04:26:07Z | history:160:034f2f3f | session-event | done | dashboard, verify, history, status | experimental/webui/prototype-backup/seam-dashboard-prototype.html,experimenta... |
| 2026-05-09T17:27:20Z | history:161:750a2c4b | session-event | done | dashboard, verify, history, status | experimental/webui/prototype-backup/seam-dashboard-prototype.html,experimenta... |
| 2026-05-10T00:00:00Z | roadmap:030:7522f63a | status-change | bootstrap | dashboard, webui, command | ROADMAP.md:181 |
| 2026-05-10T08:12:49Z | history:162:565a03ae | session-event | done | dashboard, verify, history, status | experimental/webui/prototype-backup/seam-dashboard-prototype.html,experimenta... |
| 2026-05-10T08:17:07Z | history:163:a80699bb | session-event | done | dashboard, verify, history, status | HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md |
| 2026-05-13T02:55:16Z | history:164:b3d6e2ef | session-event | done | status, history, snapshot, verify, audit, roadmap | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/snapshots |
| 2026-05-15T00:00:00Z | roadmap:031:81210641 | status-change | bootstrap | protocol, history, plan, roadmap | ROADMAP.md:1261 |
| 2026-05-15T00:00:00Z | roadmap:032:211f6c94 | status-change | bootstrap | protocol, retrieval, search | ROADMAP.md:1339 |
| 2026-05-15T00:00:00Z | roadmap:033:e7dd0d7a | status-change | bootstrap | protocol, retrieval, search, vector | ROADMAP.md:1363 |
| 2026-05-15T00:00:00Z | roadmap:034:85326313 | status-change | bootstrap | agent, compiler, skills | ROADMAP.md:1387 |
| 2026-05-15T00:00:00Z | roadmap:035:842b0cf6 | status-change | bootstrap | codec, compress, prompt, benchmark | ROADMAP.md:1450 |
| 2026-05-15T00:00:00Z | roadmap:036:e51d9c4c | status-change | bootstrap | security, audit, trust, benchmark | ROADMAP.md:1470 |
| 2026-05-15T06:50:47Z | history:165:89ff7e18 | session-event | done | roadmap, plan, protocol, history, status, audit, classifi... | docs/roadmap/CONTEXT_STREAMS.md,ROADMAP.md,PROJECT_STATUS.md,HISTORY.md,HISTO... |
| 2026-05-15T16:36:43Z | history:166:f324a81c | session-event | done | protocol, history, audit, classification, plan, snapshot,... | HISTORY.md,docs/roadmap/CONTEXT_STREAMS.md,ROADMAP.md,docs/howto/README.md,HI... |
| 2026-05-15T16:43:00Z | history:167:757a0270 | session-event | done | protocol, history, audit, classification, plan, verify, s... | .claude/settings.json,tools/claude/preflight_protocol.sh,tools/claude/session... |
| 2026-05-15T16:45:45Z | history:168:5df27e35 | session-event | done | protocol, history, audit, classification, plan, verify, s... | tools/claude/preflight_protocol.sh,tools/claude/session_start_brief.sh,REPO_L... |
| 2026-05-15T19:13:24Z | history:169:a06543fe | session-event | done | protocol, history, audit, classification, plan, verify, s... | tools/git-hooks/pre-commit,tools/git-hooks/install.sh,seam_runtime/doctor.py,... |
| 2026-05-15T19:59:46Z | history:170:941f2b6d | session-event | done | protocol, history, plan, verify, status, ledger, roadmap,... | tools/streams/__init__.py,tools/streams/streams_lib.py,tools/streams/history_... |
| 2026-05-15T21:15:18Z | history:171:65ae1a6a | session-event | done | protocol, history, plan, verify, status, ledger, roadmap,... | ROADMAP.md,tools/streams/build_context_pack.py,tools/streams/bloat_report.py,... |
| 2026-05-15T21:52:49Z | history:172:0cc3f09f | session-event | done | verify, history, audit, status, protocol | tools/history/recorded_fact_audit.py,tools/history/test_count_audit.py,tools/... |
| 2026-05-15T22:25:58Z | history:173:735e9a04 | session-event | done | installer, linux, verify, status, history, audit | .gitignore,experimental/webui/package.json,PROJECT_STATUS.md,HISTORY.md,HISTO... |
| 2026-05-16T00:15:17Z | history:174:aa43d093 | session-event | done | verify, history, audit, protocol, status | AGENTS.md,PROJECT_STATUS.md,REPO_LEDGER.md,tools/history/test_count_audit.py,... |
| 2026-05-16T00:22:59Z | history:175:a27d3a0a | session-event | done | verify, history, audit, protocol, status | PROJECT_STATUS.md,tools/history/test_count_audit.py,tools/history/test_histor... |
| 2026-05-16T00:29:22Z | history:176:96af49b3 | session-event | done | protocol, history, plan, verify, status, ledger, roadmap,... | HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md |
| 2026-05-16T04:58:56Z | history:177:65153fde | session-event | done | audit, security, verify, history, protocol, status, class... | docker-compose.yaml,.github/workflows/ci.yml,.gitignore,.rgignore,pyproject.t... |
| 2026-05-16T05:46:29Z | history:178:5d5cbd56 | session-event | done | benchmark, roadmap, registry, memory, protocol, verify, h... | benchmarks/registry/memory_benchmarks.json,seam_runtime/external_memory_bench... |
| 2026-05-16T05:58:30Z | history:179:e7611cad | session-event | done | docs, pgvector, benchmark, operator, salvage, protocol, v... | docs/PGVECTOR_LOCAL.md,docs/BENCHMARK_SOP.md,docs/SEAM_OPERATOR_GUIDE.md,docs... |
| 2026-05-16T06:01:05Z | history:180:2fe45947 | session-event | done | roadmap, plan, protocol, history, concepts | ROADMAP.md,docs/roadmap/MEMORY_BENCHMARKS.md,docs/roadmap/PROMPT_CODEC.md,doc... |
| 2026-05-16T06:16:00Z | history:181:3081e253 | session-event | done | persist, retrieval, search, vector, security, verify, his... | seam_runtime/storage.py,seam_runtime/vector.py,seam_runtime/server.py,seam_ru... |
| 2026-05-16T06:38:45Z | history:182:8affbd0f | session-event | done | harden, models, mcp, reconcile, memory, storage, vector, ... | seam_runtime/models.py,seam_runtime/mcp.py,seam_runtime/mcp_protocol.py,seam_... |
| 2026-05-16T07:31:59Z | history:183:93cfaec8 | session-event | done | mcp, pack, verify, history, audit | seam_runtime/mcp.py,seam_runtime/pack.py,test_seam_all/test_seam.py,HISTORY.m... |
| 2026-05-17 | history:185:ed014b41 | session-event | done | benchmark, command, protocol, verify | seam_runtime/cli.py,seam_runtime/external_memory_benchmarks.py,tools/run_exte... |
| 2026-05-17 | history:187:66289df0 | session-event | done | benchmark, fixture, retrieval, protocol | benchmarks/external/common/types.py,benchmarks/external/common/scoring.py,ben... |
| 2026-05-17 | history:188:a4e89290 | session-event | done | benchmark, retrieval, command, protocol | benchmarks/external/common/judge.py,benchmarks/external/common/runner.py,benc... |
| 2026-05-17 | history:189:054cfd3f | session-event | done | benchmark, retrieval, command, protocol | benchmarks/external/locomo/adapters/mem0.py,benchmarks/external/locomo/adapte... |
| 2026-05-17T00:00:00Z | roadmap:037:a49767b3 | status-change | bootstrap | benchmark, retrieval, comparator | ROADMAP.md:1419 |
| 2026-05-17T17:36:37Z | history:184:b8f6f1ed | session-event | done | audit, verify, history, status | HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md,.seam/cross_index.md |
| 2026-05-17T21:25:43Z | history:186:6dac80c8 | session-event | done | docs, handoff, protocol | docs/SOP_EXTERNAL_BENCH_LOCOMO_SEAM_ADAPTER.md,docs/SOP_EXTERNAL_BENCH_LLM_JU... |
| 2026-05-18 | history:190:8ecacfad | session-event | done | handoff, protocol, command | HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md |
| 2026-05-18 | history:199:6838df98 | session-event | done | vector, persist, verify, audit | seam_runtime/vector.py,tests/audit/__init__.py,tests/audit/test_vector_pragma... |
| 2026-05-18T00:00:00Z | roadmap:038:6ee5251d | status-change | bootstrap | tests, quality | ROADMAP.md:852 |
| 2026-05-18T00:00:00Z | roadmap:039:1ad3c112 | status-change | bootstrap | docs, security | ROADMAP.md:867 |
| 2026-05-18T00:00:00Z | roadmap:040:800f9062 | status-change | bootstrap | installer, linux | ROADMAP.md:878 |
| 2026-05-18T00:00:00Z | roadmap:041:39250734 | status-change | bootstrap | git-hooks, macos | ROADMAP.md:889 |
| 2026-05-18T00:00:00Z | roadmap:042:a278d768 | status-change | bootstrap | models, retry | ROADMAP.md:911 |
| 2026-05-18T00:00:00Z | roadmap:043:1fbb875c | status-change | bootstrap | pack, json | ROADMAP.md:922 |
| 2026-05-18T00:00:00Z | roadmap:044:d3465bb4 | status-change | bootstrap | scripts, windows | ROADMAP.md:933 |
| 2026-05-18T00:00:00Z | roadmap:045:7353eba3 | status-change | bootstrap | roadmap, docs | ROADMAP.md:955 |
| 2026-05-18T00:00:00Z | roadmap:046:baf1f8a9 | status-change | bootstrap | tests, judge | ROADMAP.md:966 |
| 2026-05-18T00:00:00Z | roadmap:047:4b8d1581 | status-change | bootstrap | verify, continuity, history | ROADMAP.md:977 |
| 2026-05-18T00:00:00Z | roadmap:048:3aca64b7 | status-change | bootstrap | verify, audit, retrieval | ROADMAP.md:1492 |
| 2026-05-18T00:00:00Z | roadmap:049:b181338c | status-change | bootstrap | verify, audit, provenance | ROADMAP.md:1510 |
| 2026-05-18T00:00:00Z | roadmap:050:6c50c0d9 | status-change | bootstrap | verify, command, audit | ROADMAP.md:1523 |
| 2026-05-18T00:00:00Z | roadmap:051:14b9746c | status-change | bootstrap | integrity, audit, snapshot | ROADMAP.md:1536 |
| 2026-05-18T00:00:00Z | roadmap:052:e84c2b0c | status-change | bootstrap | retrieval, rank, audit | ROADMAP.md:1549 |
| 2026-05-18T07:51:08Z | history:191:4007a129 | session-event | done | audit, verify, protocol, roadmap, tests, ci, security, hi... | PROJECT_STATUS.md,REPO_LEDGER.md,ROADMAP.md,seam_runtime/cli.py,seam_runtime/... |
| 2026-05-18T08:45:31Z | history:192:d3b2d91d | session-event | done | verify, streams, tests, protocol, continuity, history | tools/streams/verify_streams.py,tools/streams/test_streams.py,docs/SOP_PRODUC... |
| 2026-05-18T09:30:00Z | history:193:9b402292 | session-event | done | verify, continuity, roadmap, protocol | ROADMAP.md,docs/SOP_PRODUCTION_READINESS_REMEDIATION.md |
| 2026-05-18T10:26:40Z | history:194:33aefde3 | session-event | done | verify, history, protocol | tools/history/new_entry.py,tools/history/test_history_tools.py,PR#30 |
| 2026-05-18T10:33:00Z | history:195:bbc6e6d3 | session-event | done | verify, history, protocol | tools/history/new_entry.py,tools/history/test_history_tools.py,PR#30 |
| 2026-05-18T10:43:26Z | history:196:34581023 | session-event | done | roadmap, history, verify | ROADMAP.md,docs/roadmap/TRUST_SECURITY_AUDITABILITY.md,.seam/streams/roadmap/... |
| 2026-05-18T12:01:36Z | history:197:aadd22bd | session-event | done | security, verify, lx1, benchmark, dashboard | seam_runtime/server.py,seam_runtime/lx1.py,seam_runtime/dashboard.py,seam_run... |
| 2026-05-18T15:31:05Z | history:198:25e22fed | session-event | done | audit, verify, benchmark, docs, history, status | seam_runtime/storage.py,seam_runtime/mirl.py,tools/history/write_snapshot.py,... |
| 2026-05-19T00:02:24Z | history:200:f75ab478 | session-event | done | streams, security, verify, audit | tools/streams/streams_lib.py,tools/streams/test_streams.py |
| 2026-05-19T01:03:45Z | history:201:8b9ca2e1 | session-event | done | streams, security, verify, audit | tools/streams/rebuild_cross_index.py,tools/streams/rebuild_index.py,tools/str... |
| 2026-05-19T01:07:10Z | history:202:239b6a93 | session-event | done | streams, test, verify, audit | tools/streams/test_streams.py,PROJECT_STATUS.md |
| 2026-05-19T02:33:34Z | history:203:6685b7cf | session-event | done | dashboard, verify, status, docs | experimental/webui/public/dashboard.html,experimental/webui/public/seam-api.j... |
| 2026-05-19T02:42:56Z | history:204:b51b7e85 | session-event | done | audit, security, verify, history, installer, dashboard | seam_runtime/runtime.py,seam_runtime/installer.py,seam_runtime/dashboard.py,t... |
| 2026-05-19T03:11:04Z | history:205:b1523239 | session-event | done | audit, security, verify, docs, protocol | docs/SOP_DEEPSEEK_PARALLEL_AUDIT_EXECUTION.md,PROJECT_STATUS.md,REPO_LEDGER.md |
| 2026-05-19T03:45:45Z | history:206:9dcce7f9 | session-event | done | audit, verify, benchmark, lx1 | test_seam_all/test_seam.py,docs/SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md |
| 2026-05-19T04:01:03Z | history:207:cf297116 | session-event | done | audit, verify, history, status | test_seam_all/test_seam.py,HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md,.sea... |
| 2026-05-19T07:47:47Z | history:208:4857205d | session-event | done | audit, security, verify, multi-agent, protocol, docs, sur... | docs/SOP_WEBUI_BATCH_HARDENING_DEEPSEEK.md,docs/prompts/DEEPSEEK_WEBUI_BATCH_... |
| 2026-05-19T08:48:15Z | history:209:30392e3d | session-event | done | audit, verify, streams, integrity, security | tools/streams/streams_lib.py,.gitignore,tools/history/test_count_audit.py,too... |
| 2026-05-19T15:02:40Z | history:210:d8bccd3e | session-event | done | audit, verify, security, protocol, multi-agent, streams, mcp | .github/workflows/ci.yml,tests/audit/test_ci_verify_gates.py,tests/audit/test... |
| 2026-05-19T18:30:00Z | history:211:39fe0103 | session-event | done | audit, verify, benchmark, ci, pgvector, mcp | .github/workflows/ci.yml,tests/audit/test_sys_metrics_honesty.py,tests/audit/... |
| 2026-05-19T18:50:18Z | history:212:fb28c991 | session-event | done | audit, verify, benchmark, pgvector, mcp, persist, retriev... | tests/audit/test_pgvector_real_adapter.py,tests/audit/test_mcp_stdio_smoke.py... |
| 2026-05-19T18:54:10Z | history:213:2850402b | session-event | done | audit, verify, mcp, persist, protocol, history | seam_runtime/mcp.py,tests/audit/test_context_pack_persist_policy.py,PROJECT_S... |
| 2026-05-20T00:37:49Z | history:214:152513ad | session-event | done | benchmark, audit, verify, docs, plan, security, history | docs/SOP_TRACK_K_BIL_PHASE1_DEEPSEEK.md,docs/prompts/DEEPSEEK_TRACK_K_BIL_PHA... |
| 2026-05-20T02:15:17Z | history:215:9560b39d | session-event | done | benchmark, audit, verify, command, docs, status, history,... | seam_runtime/benchmark_integrity.py,seam_runtime/cli.py,test_seam_all/test_be... |
| 2026-05-20T03:12:17Z | history:216:45c3fc22 | session-event | done | benchmark, audit, verify, history, streams, command, docs... | seam_runtime/tokenization.py,tools/tokenization.py,seam_runtime/mirl.py,tools... |
| 2026-05-20T04:47:38Z | history:217:7eab9308 | session-event | done | benchmark, audit, verify, command, docs, status, history,... | seam_runtime/benchmark_integrity.py,seam_runtime/benchmark_baseline_policy.py... |
| 2026-05-20T07:34:43Z | history:218:bbeb7960 | session-event | done | security, audit, verify, mcp, persist, retrieval, vector,... | seam_runtime/server.py,seam_runtime/mcp.py,seam_runtime/mcp_protocol.py,seam_... |
| 2026-05-20T09:35:56Z | history:219:a514a615 | session-event | done | audit, verify, pgvector, test, docs, history, status, ben... | PROJECT_STATUS.md,test_seam_all/test_seam.py,docs/SOP_CRITICAL_BENCHMARKABILI... |
| 2026-05-21T02:47:05Z | history:220:a230b025 | session-event | done | benchmark, audit, verify, pgvector, vector, command, docs... | benchmarks/external/README.md,benchmarks/external/locomo/adapters/seam.py,ben... |
| 2026-05-21T03:53:02Z | history:221:a202dc65 | session-event | done | benchmark, audit, verify, command, docs, status, history | benchmarks/external/common/dataset.py,tests/audit/test_locomo_full_dataset_ro... |
| 2026-05-21T13:40:54Z | history:222:978c2fec | session-event | done | audit, verify, mcp, security, test, retrieval, history, p... | experimental/retrieval_orchestrator/adapters.py,tests/audit/test_chroma_sync_... |
| 2026-05-21T14:37:12Z | history:223:d5a079a6 | session-event | done | benchmark, locomo, longmemeval, beam, retrieval, vector, ... | seam_runtime/vector.py,tests/audit/test_raw_vector_indexable.py,seam_runtime/... |
| 2026-05-21T17:07:38Z | history:224:1586813e | session-event | done | protocol, history, multi-agent, verify, docs, handoff | tools/git/scan_stale_branches.py,tools/git/__init__.py,AGENTS.md |
| 2026-05-21T18:21:11Z | history:225:29d04ffc | session-event | in-progress | audit, security, benchmark, verify, history, snapshot, da... | benchmarks/external/common/judge.py,benchmarks/external/common/runner.py,seam... |
| 2026-05-21T18:22:19Z | history:226:cff72e64 | session-event | done | status, history, snapshot, verify, audit, security, bench... | PROJECT_STATUS.md,docs/SOP_DEEPSEEK_SECURITY_BENCHMARK_REMEDIATION.md,HISTORY... |
| 2026-05-21T18:22:55Z | history:227:8ad73efe | session-event | done | status, history, snapshot, verify, audit, security, bench... | PROJECT_STATUS.md,docs/SOP_DEEPSEEK_SECURITY_BENCHMARK_REMEDIATION.md,HISTORY... |
| 2026-05-21T23:38:48Z | history:228:0ffdb776 | session-event | done | docs, handoff, benchmark, locomo, retrieval, vector, prot... | docs/SOP_TRACK_M_P4_SCORE_IMPROVEMENTS_AND_MEASUREMENT.md |
| 2026-05-22T06:25:30Z | history:229:cd21a37f | session-event | done | audit, history, snapshot, verify, security, benchmark, ha... | HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md,.seam/streams/history/log.md,.s... |
| 2026-05-22T07:46:11Z | history:230:db816fc2 | session-event | done | docs, ledger, protocol, multi-agent, history, verify | docs/SOP_ADVISOR_EXECUTOR_LOOP.md,docs/prompts/DEEPSEEK_ADVISED_EXECUTOR_PROM... |
| 2026-05-22T07:56:51Z | history:231:bccee17e | session-event | done | docs, protocol, multi-agent, benchmark, history, verify | docs/prompts/DEEPSEEK_TRACK_M_BATCH_JUDGE_ADVISED_PROMPT.md,PROJECT_STATUS.md |
| 2026-05-22T08:50:21Z | history:232:cf622b5f | session-event | done | benchmark, verify, command, history, status | benchmarks/external/common/judge.py,benchmarks/external/common/runner.py,benc... |
| 2026-05-22T09:38:42Z | history:233:563a0f5c | session-event | done | benchmark, retrieval, verify, history, status | seam_runtime/temporal.py,seam_runtime/retrieval.py,seam_runtime/runtime.py,be... |
| 2026-05-22T12:52:58Z | history:234:c7001cf4 | session-event | done | benchmark, bugfix, locomo, verify, history, status | benchmarks/external/locomo/adapters/seam.py,PROJECT_STATUS.md |
| 2026-05-23T03:58:36Z | history:235:66be1596 | session-event | done | benchmark, retrieval, verify, history, status | benchmarks/external/locomo/rerank.py,benchmarks/external/locomo/run.py,benchm... |
| 2026-05-24T06:20:32Z | history:236:cd41a03c | session-event | done | benchmark, retrieval, verify, history, status | benchmarks/external/common/runner.py,benchmarks/external/locomo/adapters/seam... |
| 2026-05-24T16:42:58Z | history:237:d1e9036b | session-event | done | benchmark, retrieval, verify, history | benchmarks/external/common/types.py,benchmarks/external/common/runner.py,benc... |
| 2026-05-24T21:01:24Z | history:238:8633cd12 | session-event | done | retrieval, verify, bundle, history, status | /tmp/seam-track-m/step0b_locomo_gpt5mini_gpt5nano_save_context.json,/tmp/seam... |
| 2026-05-24T21:10:00Z | history:239:57a615b2 | session-event | done | verify, history, snapshot, status | HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md,.seam/streams/history/log.md,.s... |
| 2026-05-24T21:59:02Z | history:240:395c3322 | session-event | done | benchmark, retrieval, search, rank, verify, history, status | benchmarks/external/locomo/adapters/seam.py,benchmarks/external/common/types.... |
| 2026-05-24T23:39:52Z | history:241:ff3c9fc6 | session-event | done | benchmark, command, verify, history, status | benchmarks/external/locomo/adapters/seam.py,benchmarks/external/locomo/run.py... |
| 2026-05-25T00:00:00Z | roadmap:053:b5337aac | status-change | bootstrap | retrieval, benchmark | ROADMAP.md:900 |
| 2026-05-25T00:00:00Z | roadmap:054:4b2f3d54 | status-change | bootstrap | experience, protocol | ROADMAP.md:944 |
| 2026-05-25T00:00:00Z | roadmap:055:2bde78b6 | status-change | bootstrap | protocol, history, plan | ROADMAP.md:1294 |
| 2026-05-25T02:50:25Z | history:242:e6d10168 | session-event | done | benchmark, retrieval, search, rank, verify, history, status | seam_runtime/storage.py,tests/audit/test_sqlite_load_order.py,PROJECT_STATUS.md |
| 2026-05-25T08:02:25Z | history:243:ba34a614 | session-event | done | roadmap, plan, retrieval, rank, history, status | ROADMAP.md,docs/roadmap/CONTEXT_STREAMS.md,PROJECT_STATUS.md |
| 2026-05-25T08:49:55Z | history:244:7fe45cf1 | session-event | done | persist, retrieval, verify, history, audit | seam_runtime/storage.py,tests/audit/test_retrieval_event_store.py,PROJECT_STA... |
| 2026-05-25T12:22:20Z | history:245:93877919 | session-event | done | benchmark, bundle, verify, security, protocol | .github/workflows/ci.yml,.github/pull_request_template.md,tools/ci/chroma_rea... |
| 2026-05-25T12:33:37Z | history:246:8a53e31a | session-event | done | security, protocol, verify, history, status | PROJECT_STATUS.md,REPO_LEDGER.md,GitHub-ruleset:15143368 |
| 2026-05-25T12:37:57Z | history:247:bb5fbd5f | session-event | in-progress | security, protocol, verify, history, status | PROJECT_STATUS.md,.github/workflows/repository-maintenance.yml,tools/ci/githu... |
| 2026-05-25T12:45:28Z | history:248:19849f93 | session-event | done | security, protocol, verify, history, status | PROJECT_STATUS.md,.github/workflows/repository-maintenance.yml,tools/ci/githu... |
| 2026-05-25T12:59:52Z | history:249:edf07639 | session-event | done | protocol, security, verify, history, status | AGENTS.md,REPO_LEDGER.md,PROJECT_STATUS.md,GitHub-PR:32 |
| 2026-05-25T13:51:15Z | history:250:d76f57b7 | session-event | done | protocol, verify, history, status, security | PROJECT_STATUS.md,GitHub-PR:31,GitHub-PR:32,GitHub-branch:main |
| 2026-05-25T17:37:36Z | history:251:2938605e | session-event | done | persist, retrieval, benchmark, command, verify, history, ... | benchmarks/external/locomo/adapters/seam.py,benchmarks/external/locomo/run.py... |
| 2026-05-25T17:39:47Z | history:252:f6bcabd9 | session-event | done | protocol, verify, history, status | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/streams/history/log.md,.s... |
| 2026-05-25T19:28:36Z | history:253:2e18e819 | session-event | done | security, protocol, verify, history, status | tools/ci/github_maintenance_report.py,tests/audit/test_github_maintenance_rep... |
| 2026-05-25T20:20:47Z | history:254:d1a59a90 | session-event | done | verify, benchmark, protocol, history, status | .github/workflows/ci.yml,tests/audit/test_github_pr_gates.py,tests/audit/test... |
| 2026-05-25T20:36:15Z | history:255:dba3e5e7 | session-event | done | verify, windows, protocol, history, status | test_seam_all/test_git_hooks.py,tools/streams/streams_lib.py,PROJECT_STATUS.m... |
| 2026-05-25T20:45:46Z | history:256:d310e523 | session-event | done | verify, windows, protocol, history, status | tools/streams/test_streams.py,PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.... |
| 2026-05-25T20:54:52Z | history:257:b4959999 | session-event | done | verify, windows, protocol, history, status | tools/streams/streams_lib.py,tools/streams/test_streams.py,PROJECT_STATUS.md,... |
| 2026-05-25T21:05:09Z | history:258:73267294 | session-event | done | verify, windows, protocol, history, status | tools/streams/streams_lib.py,PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.s... |
| 2026-05-25T21:14:05Z | history:259:e2b36892 | session-event | done | verify, windows, protocol, history, status | .gitattributes,PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/streams/hi... |
| 2026-05-25T21:24:33Z | history:260:3af70289 | session-event | done | verify, windows, protocol, history, status | .github/workflows/ci.yml,tests/audit/test_github_pr_gates.py,PROJECT_STATUS.m... |
| 2026-05-25T21:35:57Z | history:261:9d37437e | session-event | done | verify, windows, protocol, history, status | tests/audit/test_ci_verify_gates.py,PROJECT_STATUS.md,HISTORY.md,HISTORY_INDE... |
| 2026-05-26T05:42:57Z | history:262:7d02e345 | session-event | done | retrieval, benchmark, bundle, verify, history, protocol | tools/h2/__init__.py,tools/h2/backfill_bundle.py,tests/audit/test_h2_backfill... |
| 2026-05-26T11:34:45Z | history:263:e16bf8c8 | session-event | done | security, protocol, verify, history, status | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,experimental/retrieval_orchestr... |
| 2026-05-26T11:47:25Z | history:264:4ddd19ed | session-event | done | security, protocol, verify, history, status | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/streams/history/log.md,.s... |
| 2026-05-26T17:30:36Z | history:265:38c7f5ed | session-event | done | retrieval, benchmark, fixture, verify, history, protocol | tools/h2/holdout_split.py,tests/audit/test_h2_holdout_split.py,PROJECT_STATUS.md |
| 2026-05-26T22:06:52Z | history:266:55f1f930 | session-event | done | protocol, history, verify, benchmark, retrieval | seam_runtime/storage.py,seam_runtime/improvement.py,tools/h2/improvement_revi... |
| 2026-05-27T13:27:37Z | history:267:853c5503 | session-event | done | bugfix, storage, retrieval, docs, pyproject, ci, webui, h... | seam_runtime/storage.py,seam_runtime/temporal.py,seam_runtime/mirl.py,seam_ru... |
| 2026-05-28T05:22:24Z | history:268:d817ea8f | session-event | done | bugfix, hardening, security, storage, multi-agent, protoc... | seam_runtime/storage.py,seam_runtime/server.py,seam_runtime/dashboard.py,seam... |
| 2026-05-29T00:42:30Z | history:269:4b1818d8 | session-event | done | bugfix, storage, benchmark, security, retrieval, audit, v... | seam_runtime/pool.py,seam_runtime/benchmark_integrity.py,seam_runtime/cli.py,... |
| 2026-05-29T07:28:25Z | history:270:9ef6f8de | session-event | done | bugfix, storage, security, audit, verify | seam_runtime/pool.py,seam_runtime/storage.py,tests/audit/test_pool_concurrenc... |
| 2026-05-29T15:52:57Z | history:271:c925b3b4 | session-event | done | benchmark, locomo, recovery, infra, verify, audit | benchmarks/external/locomo/data/locomo10.json,benchmarks/external/locomo/data... |
| 2026-05-29T20:10:02Z | history:272:8826bb65 | session-event | done | security, dashboard, audit, bugfix, verify | seam_runtime/dashboard.py,tests/audit/test_shell_security.py,docs/audits/2026... |
| 2026-05-30T07:57:40Z | history:273:95ed7b6f | session-event | done | retrieval, benchmark, locomo, audit, experiment, verify | seam_runtime/retrieval.py,seam_runtime/runtime.py,tests/audit/test_retrieval_... |
| 2026-05-30T13:48:08Z | history:274:6c12c07b | session-event | done | retrieval, memory, isolation, security, benchmark, locomo... | seam_runtime/retrieval.py,seam_runtime/vector.py,seam_runtime/vector_adapters... |
| 2026-05-31T00:00:00Z | roadmap:056:659e2ea6 | status-change | bootstrap | surface, search, verify, integrity | ROADMAP.md:1204 |
| 2026-05-31T13:12:09Z | history:275:1ab79a91 | session-event | done | retrieval, memory, isolation, bugfix, verify, benchmark | test_seam_all/test_seam.py |
| 2026-05-31T23:56:01Z | history:276:aa84a2f6 | session-event | done | roadmap, surface, verify, integrity, search, streams, his... | ROADMAP.md,PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md,.seam/streams/roadma... |
| 2026-06-01T19:23:53Z | history:277:cb90f2da | session-event | done | audit, benchmark, retrieval, locomo, docs, verify, histor... | docs/audits/2026-05-31-cat4-single-hop-attribution.md,.gitignore,PROJECT_STAT... |
| 2026-06-01T22:59:38Z | history:278:8ddb1b38 | session-event | done | retrieval, benchmark, locomo, audit, docs, verify, histor... | benchmarks/external/locomo/adapters/seam.py,benchmarks/external/locomo/run.py... |
| 2026-06-02T00:00:00Z | roadmap:057:fd920cab | status-change | bootstrap | packaging, release, distribution | ROADMAP.md:1572 |
| 2026-06-02T03:23:37Z | history:279:d613fd79 | session-event | done | retrieval, benchmark, locomo, audit, docs, verify, histor... | docs/audits/2026-06-01-paid-locomo-slice-validation.md,PROJECT_STATUS.md,HIST... |
| 2026-06-02T13:32:10Z | history:280:a329f272 | session-event | done | test, pgvector, bugfix, protocol, branch, audit, verify, ... | tests/conftest.py,tests/audit/test_pgvector_real_adapter.py,PROJECT_STATUS.md... |
| 2026-06-02T15:11:26Z | history:281:cecfeea7 | session-event | done | benchmark, bugfix, integrity, locomo, retrieval, ci, veri... | benchmarks/external/common/runner.py,PROJECT_STATUS.md,HISTORY.md,HISTORY_IND... |
| 2026-06-02T15:59:58Z | history:282:72dedfd2 | session-event | done | bugfix, windows, storage, benchmark, locomo, ci, verify, ... | seam_runtime/runtime.py,seam_runtime/benchmarks.py,benchmarks/external/mem0_h... |
| 2026-06-02T16:12:06Z | history:283:d46e609b | session-event | done | bugfix, windows, storage, locking, ci, verify, history, s... | tests/audit/test_pool_concurrency.py,PROJECT_STATUS.md,HISTORY.md,HISTORY_IND... |
| 2026-06-02T16:46:11Z | history:284:782b83c2 | session-event | done | refactor, structure, retrieval, roadmap, packaging, verif... | seam_runtime/retrieval_orchestrator/,seam_runtime/cli.py,seam_runtime/mcp.py,... |
| 2026-06-02T18:22:53Z | history:285:c8699092 | session-event | done | dashboard, webui, server, cli, structure, verify, history... | seam_runtime/webui/,webui/,seam_runtime/server.py,seam_runtime/cli.py,seam_ru... |
| 2026-06-04T04:41:57Z | history:286:d89b0879 | session-event | done | dashboard, webui, server, chat, memory, bugfix, verify, h... | seam_runtime/server.py,seam_runtime/webui/dashboard.html,seam_runtime/webui/s... |
| 2026-06-05T05:13:34Z | history:287:2d859afb | session-event | done | doctor, streams, cli, bugfix, packaging, test, verify, hi... | seam_runtime/doctor.py,test_seam_all/test_cli_import_isolation.py,HISTORY.md,... |
| 2026-06-06T14:22:16Z | history:288:76706d50 | session-event | done | security, audit, retrieval, holographic, lossless, server... | seam_runtime/dashboard.py,seam_runtime/holographic.py,seam_runtime/lossless.p... |
| 2026-06-08T07:30:36Z | history:289:bbf7ccaa | session-event | done | retrieval, self-improvement, h2, loop, benchmark, test, v... | seam_runtime/retrieval.py,seam_runtime/runtime.py,seam_runtime/storage.py,too... |
| 2026-06-08T08:57:59Z | history:290:3f3c4870 | session-event | done | retrieval, self-improvement, h2, loop, benchmark, locomo,... | seam_runtime/self_improve.py,seam_runtime/retrieval.py,seam_runtime/runtime.p... |
| 2026-06-08T11:10:38Z | history:291:4d966326 | session-event | done | retrieval, self-improvement, h2, loop, proposer, ratchet,... | seam_runtime/self_improve.py,tools/h2/improvement_loop.py,tests/audit/test_im... |
| 2026-06-09T00:30:25Z | history:292:6a03a252 | session-event | done | retrieval, self-improvement, h2, loop, benchmark, locomo,... | benchmarks/external/locomo/recall_scorer.py,seam_runtime/self_improve.py,test... |
| 2026-06-09T01:01:07Z | history:293:ce085961 | session-event | done | cli, self-improvement, h2, loop, packaging, chroma, depen... | seam_runtime/cli.py,pyproject.toml,.github/workflows/ci.yml,tests/audit/test_... |
| 2026-06-09T13:53:04Z | history:294:9c04649a | session-event | done | test, ci, protocol, skip, pgvector, enforcement, verify, ... | tests/conftest.py,tests/audit/test_pgvector_pk_composite.py,tests/audit/test_... |
| 2026-06-09T14:09:49Z | history:295:cb32e58d | session-event | done | ci, test, bugfix, chroma, dependencies, pgvector, verify,... | .github/workflows/ci.yml,tests/audit/test_github_pr_gates.py,HISTORY.md,HISTO... |
| 2026-06-09T20:30:51Z | history:296:e269f04f | session-event | done | security, chroma, dependencies, vulnerability, packaging,... | requirements.txt,pyproject.toml,tests/audit/test_chroma_optional.py,REPO_LEDG... |
| 2026-06-09T21:06:59Z | history:297:eda068d9 | session-event | done | retrieval, self-improvement, h2, loop, locomo, dev-gate, ... | benchmarks/external/locomo/recall_scorer.py,seam_runtime/cli.py,tests/audit/t... |
| 2026-06-09T22:42:26Z | history:298:70e871a8 | session-event | done | security, codeql, redos, clear-text-logging, workflow-per... | .github/workflows/external-memory-benchmarks.yml,seam_runtime/dsl.py,seam_run... |
| 2026-06-10T01:39:24Z | history:299:f461b4ea | session-event | done | security, codeql, clear-text-logging, dashboard, correcti... | seam_runtime/dashboard.py,HISTORY.md,HISTORY_INDEX.md |
| 2026-06-10T05:12:03Z | history:300:071ef6f0 | session-event | done | security, ssrf, dns-rebinding, chat-endpoint, server, all... | seam_runtime/server.py,tests/audit/test_audit_2026_06_05.py,HISTORY.md,HISTOR... |
| 2026-06-11T09:14:32Z | history:301:f168a4a1 | session-event | done | maintenance, security, codeql, dependabot, dependencies, ... | .github/dependabot.yml,webui/package.json,HISTORY.md,HISTORY_INDEX.md,PROJECT... |
| 2026-06-11T10:00:24Z | history:302:9ceec2f6 | session-event | done | self-improvement, benchmark, locomo, judge, paid-validati... | benchmarks/external/locomo/judged_scorer.py,tools/h2/paid_validation.py,seam_... |
| 2026-06-13T03:32:40Z | history:303:89226734 | session-event | done | mirl, compiler, nl, fidelity, contract, ingest, bug, harn... | benchmarks/fidelity/__init__.py,benchmarks/fidelity/contract.py,benchmarks/fi... |
| 2026-06-13T04:32:49Z | history:304:6a29f16d | session-event | done | protocol, agents, repo-ledger, spec, governing-contract, ... | AGENTS.md,REPO_LEDGER.md,SEAM_SPEC_V0.1.md,docs/MIRL_V1.md,HISTORY.md,HISTORY... |
| 2026-06-13T04:54:03Z | history:305:852d5e86 | session-event | done | mirl, compiler, fidelity, spec, metrics, reconciliation, ... | benchmarks/fidelity/spec_metrics.py,benchmarks/fidelity/golden.py,benchmarks/... |
| 2026-06-13T08:31:06Z | history:306:119fc10b | session-event | done | handoff, consolidation, branches, session-end, mirl, comp... | docs/handoffs/2026-06-13-mirl-compiler-fidelity-handoff.md,HISTORY.md,HISTORY... |
| 2026-06-13T09:23:12Z | history:307:627093bb | session-event | done | mirl, compiler, fidelity, spec, metrics, qr, retrieval, t... | benchmarks/fidelity/spec_metrics.py,benchmarks/fidelity/golden.py,tests/fidel... |
| 2026-06-13T10:11:44Z | history:308:add55806 | session-event | done | mirl, compiler, nl, fidelity, floor, retrieval, test, ver... | seam_runtime/nl.py,benchmarks/fidelity/golden.py,tests/fidelity/test_spec_met... |
| 2026-06-13T17:45:05Z | history:309:0994fba1 | session-event | done | security, redos, codeql, mirl, compiler, nl, test, symbol... | seam_runtime/nl.py,test_seam_all/test_seam.py,HISTORY.md,HISTORY_INDEX.md,PRO... |
| 2026-06-13T17:58:01Z | history:310:9c0ba7e3 | session-event | done | protocol, history, status, verify, continuity, docs | PROJECT_STATUS.md,HISTORY.md,HISTORY_INDEX.md |
| 2026-06-14T05:06:38Z | history:311:cbcce34e | session-event | done | mirl, compiler, nl, unify, conversation, locomo, benchmar... | seam_runtime/nl.py,seam_runtime/runtime.py,tests/audit/test_conversation_turn... |
| 2026-06-14T06:56:46Z | history:312:d81f92ae | session-event | done | self-improvement, loop, self-probe, retrieval, locomo, be... | seam_runtime/self_improve.py,tests/audit/test_self_probe_scorer.py,HISTORY.md... |
| 2026-06-14T08:03:31Z | history:313:105bd107 | session-event | done | mirl, compiler, nl, ollama, extractor, fidelity, llm, tes... | seam_runtime/nl_extract.py,seam_runtime/nl.py,tests/fidelity/test_nl_extract.... |
| 2026-06-14T11:04:31Z | history:314:bcd1c824 | session-event | done | pack, density, compression, context, retrieval, cr, verif... | seam_runtime/pack.py,seam_runtime/context_views.py,test_seam_all/test_seam.py... |
| 2026-06-14T12:27:24Z | history:315:1824fb06 | session-event | done | pack, density, compression, context, retrieval, cr, verif... | seam_runtime/pack.py,test_seam_all/test_seam.py,HISTORY.md,HISTORY_INDEX.md,P... |
| 2026-06-14T13:26:00Z | history:316:a45c14d0 | session-event | done | pack, density, compression, context, symbols, prov, evide... | seam_runtime/pack.py,test_seam_all/test_seam.py,HISTORY.md,HISTORY_INDEX.md,P... |
| 2026-06-14T23:53:15Z | history:317:8008e5f4 | session-event | done | nl, compiler, ingest, enrichment, regex, locomo, benchmar... | seam_runtime/nl.py,tests/audit/test_conversation_turn_compile.py,test_seam_al... |
| 2026-06-15T01:01:25Z | history:318:986aa846 | session-event | done | retrieval, multihop, locomo, benchmark, scope, query, sql... | docs/audits/2026-06-15-cat1-cat3-multihop-scope.md,docs/roadmap/SEAM_QUERY_EN... |
| 2026-06-15T01:17:23Z | history:319:4081a094 | session-event | done | roadmap, query, sql, bird, benchmark, retrieval, multihop... | ROADMAP.md,HISTORY.md,HISTORY_INDEX.md,PROJECT_STATUS.md |
| 2026-06-15T03:39:08Z | history:320:25494450 | session-event | done | retrieval, budget, topk, locomo, benchmark, judge, recall... | seam_runtime/retrieval.py,seam_runtime/runtime.py,benchmarks/external/locomo/... |
| 2026-06-15T04:42:47Z | history:321:8f340dc0 | session-event | done | retrieval, answerer, reasoning, locomo, benchmark, judge,... | benchmarks/external/locomo/adapters/seam.py,HISTORY.md,HISTORY_INDEX.md,PROJE... |
| 2026-06-15T12:01:01Z | history:322:e08eb1a6 | session-event | done | test, pgvector, protocol, docs, history | AGENTS.md,REPO_LEDGER.md,docs/CODE_LAYOUT.md,tests/docs/README.md,tests/docs/... |
| 2026-06-15T14:29:51Z | history:323:427968af | session-event | done | retrieval, locomo, cat1, coreference, entity-aggregation,... | benchmarks/external/locomo/adapters/seam.py,tests/audit/test_locomo_entity_ag... |
| 2026-06-17T22:49:30Z | history:324:e8d2acce | session-event | done | doctor, stash, git, hygiene, tooling, protocol, history | seam_runtime/doctor.py,seam_runtime/cli.py,tests/audit/test_doctor_stashes.py... |
| 2026-06-18T01:26:35Z | history:325:13dd6b94 | session-event | done | calibration, abstention, benchmark, locomo, scorer, epist... | benchmarks/external/locomo/calibration_scorer.py,benchmarks/external/common/d... |


## Archive Pointers

| chunk | utc_range | event_count | streams | top_topics |
|---|---|---|---|---|
| 0001-0182.cross.md | 2026-04-15T00:00:00Z..2026-05-08T21:52:11Z | 182 | (multi) | (multi) |
