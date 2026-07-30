import json
import os

graph_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/assembled-graph.json"
review_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/assemble-review.json"

import_map = {
  "__init__.py": [
    "mirl.py",
    "runtime.py"
  ],
  "agent_memory.py": [
    "mirl.py"
  ],
  "benchmark_baseline_policy.py": [],
  "benchmark_integrity.py": [],
  "benchmarks.py": [
    "context_views.py",
    "dsl.py",
    "evals.py",
    "holographic.py",
    "lossless.py",
    "models.py",
    "storage.py",
    "surface_adapters.py",
    "vector.py"
  ],
  "bm25.py": [],
  "cli.py": [
    "agent_memory.py",
    "benchmark_baseline_policy.py",
    "benchmark_integrity.py",
    "benchmarks.py",
    "context_views.py",
    "dashboard.py",
    "doctor.py",
    "external_memory_benchmarks.py",
    "holographic.py",
    "installer.py",
    "lossless.py",
    "lx1.py",
    "mirl.py",
    "runtime.py",
    "surface_adapters.py"
  ],
  "context_views.py": [],
  "conversation.py": [],
  "dashboard.py": [
    "context_views.py",
    "installer.py",
    "lossless.py",
    "mirl.py",
    "models.py",
    "runtime.py",
    "ui/__init__.py"
  ],
  "derived_fact_context.py": [
    "mirl.py",
    "multi_speaker_facts.py",
    "nl_extract.py",
    "sentence_grounded_facts.py"
  ],
  "doctor.py": [
    "installer.py",
    "lossless.py",
    "runtime.py"
  ],
  "dsl.py": [
    "mirl.py"
  ],
  "evals.py": [
    "dsl.py",
    "lossless.py",
    "models.py",
    "pack.py",
    "retrieval.py",
    "vector.py"
  ],
  "event_count_context.py": [],
  "external_memory_benchmarks.py": [],
  "holographic.py": [
    "lossless.py",
    "mirl.py",
    "pack.py",
    "retrieval.py"
  ],
  "improvement.py": [],
  "installer.py": [],
  "jspace.py": [],
  "knowledge_graph.py": [
    "mirl.py"
  ],
  "lossless.py": [],
  "lx1.py": [
    "mirl.py"
  ],
  "mcp.py": [
    "doctor.py",
    "holographic.py",
    "runtime.py"
  ],
  "mcp_protocol.py": [
    "installer.py",
    "mcp.py",
    "pgvector_bootstrap.py",
    "runtime.py"
  ],
  "mirl.py": [],
  "models.py": [],
  "multi_scope_pack.py": [],
  "multi_speaker_facts.py": [
    "sentence_grounded_facts.py"
  ],
  "nl.py": [
    "derived_fact_context.py",
    "mirl.py"
  ],
  "nl_extract.py": [],
  "pack.py": [
    "mirl.py",
    "symbols.py"
  ],
  "pgvector_bootstrap.py": [],
  "pool.py": [],
  "reconcile.py": [
    "mirl.py"
  ],
  "retrieval.py": [
    "bm25.py",
    "mirl.py",
    "symbols.py",
    "temporal.py"
  ],
  "retrieval_orchestrator/README.md": [],
  "retrieval_orchestrator/__init__.py": [
    "retrieval_orchestrator/adapters.py",
    "retrieval_orchestrator/orchestrator.py",
    "retrieval_orchestrator/types.py"
  ],
  "retrieval_orchestrator/adapters.py": [
    "mirl.py",
    "models.py",
    "retrieval_orchestrator/types.py",
    "storage.py",
    "vector.py",
    "vector_adapters.py"
  ],
  "retrieval_orchestrator/merger.py": [
    "retrieval_orchestrator/types.py"
  ],
  "retrieval_orchestrator/orchestrator.py": [
    "pack.py",
    "retrieval_orchestrator/adapters.py",
    "retrieval_orchestrator/merger.py",
    "retrieval_orchestrator/planner.py",
    "retrieval_orchestrator/types.py",
    "runtime.py"
  ],
  "retrieval_orchestrator/planner.py": [
    "retrieval_orchestrator/types.py"
  ],
  "retrieval_orchestrator/types.py": [
    "mirl.py"
  ],
  "retry.py": [],
  "runtime.py": [
    "agent_memory.py",
    "benchmarks.py",
    "dsl.py",
    "evals.py",
    "mirl.py",
    "models.py",
    "nl.py",
    "pack.py",
    "reconcile.py",
    "retrieval.py",
    "storage.py",
    "symbols.py",
    "transpile.py",
    "vector_adapters.py",
    "verify.py"
  ],
  "second_hop_context.py": [],
  "self_improve.py": [
    "mirl.py",
    "retrieval.py"
  ],
  "sentence_grounded_facts.py": [
    "nl_extract.py"
  ],
  "server.py": [
    "installer.py",
    "jspace.py",
    "mirl.py",
    "runtime.py",
    "workspace.py"
  ],
  "skills/__init__.py": [
    "skills/factory.py",
    "skills/skill_ir.py"
  ],
  "skills/factory.py": [],
  "skills/skill_ir.py": [],
  "storage.py": [
    "knowledge_graph.py",
    "mirl.py",
    "pool.py",
    "retry.py",
    "workspace.py"
  ],
  "surface_adapters.py": [],
  "symbols.py": [
    "mirl.py"
  ],
  "temporal.py": [],
  "temporal_instance_context.py": [],
  "tokenization.py": [],
  "transpile.py": [
    "mirl.py"
  ],
  "ui/__init__.py": [],
  "ui/animations.py": [
    "ui/bars.py",
    "ui/theme.py"
  ],
  "ui/bars.py": [
    "ui/theme.py"
  ],
  "ui/logo.py": [
    "ui/theme.py"
  ],
  "ui/theme.py": [],
  "vector.py": [
    "mirl.py",
    "models.py"
  ],
  "vector_adapters.py": [
    "mirl.py",
    "models.py",
    "vector.py"
  ],
  "verify.py": [
    "mirl.py"
  ],
  "webui/dashboard.html": [],
  "webui/seam-api.js": [],
  "webui/tweaks-panel.jsx": [],
  "workspace.py": [
    "mirl.py"
  ]
}

with open(graph_path, "r", encoding="utf-8") as f:
    data = json.load(f)

nodes = data.get("nodes", [])
edges = data.get("edges", [])

unique_types = set(n.get("type") for n in nodes)
unique_complexities = set(n.get("complexity") for n in nodes)
print("Initial unique types:", unique_types)
print("Initial unique complexities:", unique_complexities)

no_id_nodes = [n for n in nodes if "id" not in n]
print("Nodes with no id:", len(no_id_nodes))

has_is_count_question = any(n.get("id") == "function:event_count_context.py:is_count_question" for n in nodes)
nodes_recovered = 0
edges_restored = 0
types_remapped = 0
complexity_remapped = 0

if not has_is_count_question:
    new_node = {
      "id": "function:event_count_context.py:is_count_question",
      "type": "function",
      "name": "is_count_question",
      "filePath": "event_count_context.py",
      "lineRange": [
        412,
        416
      ],
      "summary": "Checks if the provided query or question represents a distinct event or item count request.",
      "tags": [
        "utility",
        "validation",
        "helper"
      ],
      "complexity": "simple"
    }
    nodes.append(new_node)
    nodes_recovered += 1
    print("Recovered node: function:event_count_context.py:is_count_question")

contains_edge = {
  "source": "file:event_count_context.py",
  "target": "function:event_count_context.py:is_count_question",
  "type": "contains",
  "direction": "forward",
  "weight": 1.0
}
calls_edge = {
  "source": "function:event_count_context.py:build_count_context_projection",
  "target": "function:event_count_context.py:is_count_question",
  "type": "calls",
  "direction": "forward",
  "weight": 0.8
}

has_contains = any(e.get("source") == contains_edge["source"] and e.get("target") == contains_edge["target"] and e.get("type") == contains_edge["type"] for e in edges)
if not has_contains:
    edges.append(contains_edge)
    edges_restored += 1

has_calls = any(e.get("source") == calls_edge["source"] and e.get("target") == calls_edge["target"] and e.get("type") == calls_edge["type"] for e in edges)
if not has_calls:
    edges.append(calls_edge)
    edges_restored += 1

node_id_map = {n["id"]: n for n in nodes if "id" in n}
cross_batch_edges_added = 0

for source_file, targets in import_map.items():
    source_id = f"file:{source_file}"
    if source_id not in node_id_map:
        continue
    for target_file in targets:
        target_id = f"file:{target_file}"
        if target_id not in node_id_map:
            continue
        
        has_import_edge = any(
            e.get("source") == source_id and 
            e.get("target") == target_id and 
            e.get("type") == "imports" 
            for e in edges
        )
        if not has_import_edge:
            edges.append({
                "source": source_id,
                "target": target_id,
                "type": "imports",
                "direction": "forward",
                "weight": 0.7
            })
            cross_batch_edges_added += 1

print(f"Added {cross_batch_edges_added} cross-batch import edges.")

# Type and complexity validation mappings
# Check if any complexity or type needs mapping
for n in nodes:
    t = n.get("type")
    c = n.get("complexity")
    
    # Types validation (e.g. func -> function, etc.)
    if t == "func":
        n["type"] = "function"
        types_remapped += 1
    elif t == "doc":
        n["type"] = "document"
        types_remapped += 1
    elif t == "svc":
        n["type"] = "service"
        types_remapped += 1
        
    # Complexity validation
    if c not in ["simple", "moderate", "complex", None]:
        # map to closest
        if c in ["very low", "trivial", "easy"]:
            n["complexity"] = "simple"
            complexity_remapped += 1
        elif c in ["medium", "normal"]:
            n["complexity"] = "moderate"
            complexity_remapped += 1
        elif c in ["very high", "hard"]:
            n["complexity"] = "complex"
            complexity_remapped += 1

data["nodes"] = nodes
data["edges"] = edges
with open(graph_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

review_data = {
  "fixedSectionOk": True,
  "nodesRecovered": nodes_recovered,
  "edgesRestored": edges_restored,
  "crossBatchEdgesAdded": cross_batch_edges_added,
  "typesRemapped": types_remapped,
  "complexityRemapped": complexity_remapped,
  "notes": [
    "Recovered function:event_count_context.py:is_count_question node and its calls/contains edges.",
    "Added missing cross-batch imports edges using the provided import map."
  ]
}

with open(review_path, "w", encoding="utf-8") as f:
    json.dump(review_data, f, indent=2, ensure_ascii=False)

print("Process completed successfully. typesRemapped:", types_remapped, "complexityRemapped:", complexity_remapped)
