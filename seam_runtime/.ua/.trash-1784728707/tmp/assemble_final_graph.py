import json
from datetime import datetime

graph_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/assembled-graph.json"
layers_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/layers.json"
tour_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/tour.json"

with open(graph_path, "r", encoding="utf-8") as f:
    graph = json.load(f)

with open(layers_path, "r", encoding="utf-8") as f:
    layers = json.load(f)

with open(tour_path, "r", encoding="utf-8") as f:
    tour = json.load(f)

# Validate node IDs existence
node_ids = {n["id"] for n in graph.get("nodes", [])}

# Normalize/validate layers
validated_layers = []
for layer in layers:
    layer_id = layer.get("id")
    name = layer.get("name")
    description = layer.get("description")
    node_ids_in_layer = layer.get("nodeIds", [])
    
    # Filter out dangling refs
    valid_node_ids = [nid for nid in node_ids_in_layer if nid in node_ids]
    
    if len(valid_node_ids) > 0:
        validated_layers.append({
            "id": layer_id,
            "name": name,
            "description": description,
            "nodeIds": valid_node_ids
        })

# Normalize/validate tour steps
validated_tour = []
for step in tour:
    order = step.get("order")
    title = step.get("title")
    description = step.get("description")
    node_ids_in_step = step.get("nodeIds", [])
    lang_lesson = step.get("languageLesson")
    
    # Filter out dangling refs
    valid_node_ids = [nid for nid in node_ids_in_step if nid in node_ids]
    
    step_obj = {
        "order": order,
        "title": title,
        "description": description,
        "nodeIds": valid_node_ids
    }
    if lang_lesson:
        step_obj["languageLesson"] = lang_lesson
        
    validated_tour.append(step_obj)

# Assemble final object
final_graph = {
    "version": "1.0.0",
    "project": {
        "name": "seam-runtime",
        "languages": ["html", "javascript", "markdown", "python"],
        "frameworks": ["FastAPI", "Uvicorn"],
        "description": "SEAM memory runtime and glassbox operator tooling for AI agents",
        "analyzedAt": "2026-07-22T02:32:00-05:00",
        "gitCommitHash": "cdbb3fdb711080da9a12e341fbaa31cdf5b18dd6"
    },
    "nodes": graph.get("nodes", []),
    "edges": graph.get("edges", []),
    "layers": validated_layers,
    "tour": validated_tour
}

with open(graph_path, "w", encoding="utf-8") as f:
    json.dump(final_graph, f, indent=2, ensure_ascii=False)

print("Full knowledge graph assembled successfully in assembled-graph.json.")
print(f"Nodes: {len(final_graph['nodes'])}")
print(f"Edges: {len(final_graph['edges'])}")
print(f"Layers: {len(final_graph['layers'])}")
print(f"Tour steps: {len(final_graph['tour'])}")
