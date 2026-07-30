import json
import re

sub_log_path = "/home/terrabyte/.gemini/antigravity-cli/brain/a1e35102-6048-47a4-92a4-27e2b9dab275/.system_generated/logs/transcript_full.jsonl"
with open(sub_log_path) as f:
    for idx, line in enumerate(f):
        try:
            data = json.loads(line)
            content = data.get("content", "")
            if not content:
                continue
            code_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            for b_idx, cb in enumerate(code_blocks):
                try:
                    g = json.loads(cb)
                    if "nodes" in g and "edges" in g:
                        print(f"Line {idx} block {b_idx}: VALID JSON! Nodes: {len(g['nodes'])}, Edges: {len(g['edges'])}")
                except Exception as e:
                    pass
        except Exception as e:
            pass
