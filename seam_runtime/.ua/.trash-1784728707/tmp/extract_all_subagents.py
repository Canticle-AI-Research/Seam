import json
import os
import re

batches_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/batches.json"
subagents = [
    "a1e35102-6048-47a4-92a4-27e2b9dab275",
    "2742bb83-2615-4aa1-9899-106bf9e8851f",
    "243a6d58-938e-4208-bc88-cea777ab07c4",
    "f9491cde-82fa-4064-adee-0880062b6514",
    "0f5ea029-951c-4954-aab5-62cf424ef377"
]

# Load batches mappings
with open(batches_path) as f:
    batches_data = json.load(f)
batches_list = batches_data["batches"]

file_to_batch = {}
for idx, b in enumerate(batches_list):
    b_idx = b["batchIndex"]
    for f_info in b["files"]:
        file_to_batch[f_info["path"]] = b_idx

recovered = {}

def process_text(text, source_desc):
    # Find all json blocks
    blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    for b_idx, block in enumerate(blocks):
        try:
            g = json.loads(block)
            if "nodes" in g and isinstance(g["nodes"], list) and len(g["nodes"]) > 0:
                file_path = None
                for node in g["nodes"]:
                    if node.get("type") == "file":
                        file_path = node.get("filePath")
                        if file_path:
                            break
                if file_path:
                    b_num = file_to_batch.get(file_path)
                    if b_num:
                        print(f"Matched block in {source_desc} to batch-{b_num} (filePath: {file_path})")
                        recovered[b_num] = g
                    else:
                        print(f"Warning: filePath {file_path} in {source_desc} not found in batch mapping")
                else:
                    # Try to fall back to first node if no type=file is found
                    first_id = g["nodes"][0].get("id", "")
                    if first_id.startswith("file:"):
                        f_name = first_id.split(":", 1)[1]
                        b_num = file_to_batch.get(f_name)
                        if b_num:
                            print(f"Matched block in {source_desc} via fallback to batch-{b_num} (fileName: {f_name})")
                            recovered[b_num] = g
                        else:
                            print(f"Warning: fallback fileName {f_name} not found in batch mapping")
                    else:
                        print(f"Could not determine batch index for block in {source_desc} (first node: {g['nodes'][0]})")
        except Exception as e:
            pass

for sub_id in subagents:
    sub_log_path = f"/home/terrabyte/.gemini/antigravity-cli/brain/{sub_id}/.system_generated/logs/transcript_full.jsonl"
    if not os.path.exists(sub_log_path):
        print(f"Log path for subagent {sub_id} does not exist: {sub_log_path}")
        continue
    
    with open(sub_log_path) as f:
        for idx, line in enumerate(f):
            try:
                data = json.loads(line)
                
                # Check planner response content
                content = data.get("content", "")
                if content:
                    process_text(content, f"subagent {sub_id} line {idx} content")
                
                # Check tool calls
                tool_calls = data.get("tool_calls", [])
                if tool_calls and isinstance(tool_calls, list):
                    for tc_idx, tc in enumerate(tool_calls):
                        args = tc.get("args") or tc.get("Arguments")
                        if args:
                            if isinstance(args, str):
                                try:
                                    args_dict = json.loads(args)
                                except:
                                    args_dict = {}
                            else:
                                args_dict = args
                            
                            msg = args_dict.get("Message") or args_dict.get("message")
                            if msg:
                                process_text(msg, f"subagent {sub_id} line {idx} tool call {tc_idx} Message")
            except Exception as e:
                pass

print(f"Successfully recovered batches: {sorted(list(recovered.keys()))} (Total: {len(recovered)})")

# Write to disk
for b_num, g in recovered.items():
    out_path = f"/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/batch-{b_num}.json"
    with open(out_path, "w") as out_f:
        json.dump(g, out_f, indent=2)
    print(f"Wrote batch-{b_num}.json")
