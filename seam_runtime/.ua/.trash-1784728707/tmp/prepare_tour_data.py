import json

arch_input_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/architecture-input.json"
layers_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/layers.json"
tour_input_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/tour-input.json"

with open(arch_input_path, "r", encoding="utf-8") as f:
    arch_input = json.load(f)

with open(layers_path, "r", encoding="utf-8") as f:
    layers = json.load(f)

# Omit nodeIds from layers to match the expected format: "list of {id, name, description} for each layer — omit nodeIds"
layers_omitted_node_ids = []
for l in layers:
    layers_omitted_node_ids.append({
        "id": l["id"],
        "name": l["name"],
        "description": l["description"]
    })

tour_input = {
    "nodes": arch_input["fileNodes"],
    "edges": arch_input["allEdges"],
    "layers": layers_omitted_node_ids
}

with open(tour_input_path, "w", encoding="utf-8") as f:
    json.dump(tour_input, f, indent=2, ensure_ascii=False)

print("tour-input.json prepared successfully.")
print(f"Nodes: {len(tour_input['nodes'])}")
print(f"Edges: {len(tour_input['edges'])}")
print(f"Layers: {len(tour_input['layers'])}")
