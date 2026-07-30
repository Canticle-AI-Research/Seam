import json
import os
import subprocess

project_root = "/home/terrabyte/Documents/Projects/Seam/seam_runtime"
ua_dir = "/home/terrabyte/Documents/Projects/Seam/seam_runtime/.ua"
tmp_dir = os.path.join(ua_dir, "tmp")
batches_path = os.path.join(ua_dir, "intermediate/batches.json")
extractor_path = "/home/terrabyte/.gemini/config/plugins/understand-anything/skills/understand/extract-structure.mjs"

with open(batches_path, "r") as f:
    batches_data = json.load(f)

batches = batches_data["batches"]
print(f"Loaded {len(batches)} batches.")

for idx, b in enumerate(batches):
    input_data = {
        "projectRoot": project_root,
        "batchFiles": b["files"],
        "batchImportData": b.get("batchImportData", {})
    }
    
    # Save as both idx and idx + 1 to handle different agent indexing conventions
    indices = [idx, idx + 1]
    for index in indices:
        input_filename = f"ua-file-analyzer-input-{index}.json"
        input_path = os.path.join(tmp_dir, input_filename)
        with open(input_path, "w") as out_f:
            json.dump(input_data, out_f, indent=2)
            
        output_filename = f"ua-file-extract-results-{index}.json"
        output_path = os.path.join(tmp_dir, output_filename)
        
        # Run node extract-structure.mjs
        cmd = ["node", extractor_path, input_path, output_path]
        print(f"Running: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error running batch {index}: {res.stderr}")
        else:
            print(f"Batch {index} completed successfully.")
