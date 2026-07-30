import json
import os
import re

log_path = "/home/terrabyte/.gemini/antigravity-cli/brain/3bee8bf4-dbc3-44f5-a4ac-d905a53fb3d2/.system_generated/logs/transcript_full.jsonl"
sender_id = "a1e35102-6048-47a4-92a4-27e2b9dab275"

with open(log_path, "r") as f:
    for line in f:
        if sender_id in line:
            data = json.loads(line)
            content = data.get("content", "")
            if "batch-2.json" in content:
                # Find all JSON code blocks
                code_blocks = re.findall(r"```json\s*(.*?)\s*```", content, re.DOTALL)
                if len(code_blocks) >= 2:
                    batch_1_content = code_blocks[0]
                    batch_2_content = code_blocks[1]
                    
                    # Parse to verify valid JSON
                    b1 = json.loads(batch_1_content)
                    b2 = json.loads(batch_2_content)
                    
                    # Write to files
                    b1_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/batch-1.json"
                    b2_path = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua/intermediate/batch-2.json"
                    
                    with open(b1_path, "w") as out:
                        json.dump(b1, out, indent=2)
                    print(f"Wrote batch-1.json ({len(b1['nodes'])} nodes, {len(b1['edges'])} edges)")
                    
                    with open(b2_path, "w") as out:
                        json.dump(b2, out, indent=2)
                    print(f"Wrote batch-2.json ({len(b2['nodes'])} nodes, {len(b2['edges'])} edges)")
                    break
                else:
                    print(f"Error: Found only {len(code_blocks)} code blocks.")
