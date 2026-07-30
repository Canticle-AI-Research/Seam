import json

graph_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/assembled-graph.json"
output_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/architecture-input.json"

with open(graph_path, "r", encoding="utf-8") as f:
    graph = json.load(f)

file_level_types = {"file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"}

# Filter nodes
file_nodes = []
file_node_ids = set()
for n in graph.get("nodes", []):
    ntype = n.get("type")
    if ntype in file_level_types:
        node_id = n.get("id")
        file_node_ids.add(node_id)
        # Construct {id, type, name, filePath, summary, tags}
        file_nodes.append({
            "id": node_id,
            "type": ntype,
            "name": n.get("name"),
            "filePath": n.get("filePath"),
            "summary": n.get("summary", ""),
            "tags": n.get("tags", [])
        })

# Filter edges (both source and target must be file-level nodes)
import_edges = []
all_edges = []

for e in graph.get("edges", []):
    src = e.get("source")
    tgt = e.get("target")
    etype = e.get("type")
    
    if src in file_node_ids and tgt in file_node_ids:
        edge_obj = {
            "source": src,
            "target": tgt,
            "type": etype
        }
        all_edges.append(edge_obj)
        if etype == "imports":
            import_edges.append(edge_obj)

output_data = {
    "fileNodes": file_nodes,
    "importEdges": import_edges,
    "allEdges": all_edges
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output_data, f, indent=2, ensure_ascii=False)

print(f"Extraction complete.")
print(f"Total file nodes: {len(file_nodes)}")
print(f"Total import edges: {len(import_edges)}")
print(f"Total all edges: {len(all_edges)}")
