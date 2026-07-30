import json
import re

log_path = "/home/terrabyte/.gemini/antigravity-cli/brain/3bee8bf4-dbc3-44f5-a4ac-d905a53fb3d2/.system_generated/logs/transcript_full.jsonl"
batches_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/batches.json"

with open(batches_path) as f:
    batches_data = json.load(f)
batches_list = batches_data["batches"]

# Map file path to batch index
file_to_batch = {}
for idx, b in enumerate(batches_list):
    b_idx = b["batchIndex"]
    for f_info in b["files"]:
        file_to_batch[f_info["path"]] = b_idx

print("Sample file mappings:")
for k, v in list(file_to_batch.items())[:5]:
    print(f"  {k} -> batch-{v}")

subagents_data = {}
with open(log_path) as f:
    for idx, line in enumerate(f):
        if "content" in line:
            try:
                data = json.loads(line)
                content = data.get("content", "")
                if not content:
                    continue
                # Find all JSON code blocks
                code_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
                for cb in code_blocks:
                    try:
                        g = json.loads(cb)
                        if "nodes" in g and isinstance(g["nodes"], list) and len(g["nodes"]) > 0:
                            # Try to identify file path from any node
                            file_path = None
                            for node in g["nodes"]:
                                if node.get("type") == "file":
                                    file_path = node.get("filePath")
                                    # Normalize path
                                    if file_path:
                                        break
                            if file_path:
                                b_num = file_to_batch.get(file_path)
                                if b_num:
                                    print(f"Found batch data for batch-{b_num} (line {idx}) with {len(g['nodes'])} nodes")
                                    subagents_data[b_num] = g
                                else:
                                    print(f"Warning: file {file_path} not found in batch mapping")
                            else:
                                print("Could not find file node in block")
                    except Exception as e:
                        pass
            except Exception as e:
                pass

print(f"Total unique batches found: {len(subagents_data)}: {sorted(list(subagents_data.keys()))}")
