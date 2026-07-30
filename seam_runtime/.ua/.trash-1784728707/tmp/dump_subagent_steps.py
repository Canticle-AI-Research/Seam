import json

sub_log_path = "/home/terrabyte/.gemini/antigravity-cli/brain/a1e35102-6048-47a4-92a4-27e2b9dab275/.system_generated/logs/transcript_full.jsonl"
with open(sub_log_path) as f:
    for idx, line in enumerate(f):
        try:
            data = json.loads(line)
            step_type = data.get("type", "")
            source = data.get("source", "")
            content = data.get("content", "")
            print(f"Line {idx}: type={step_type}, source={source}, len={len(content) if content else 0}")
        except Exception as e:
            print(f"Line {idx}: failed to parse JSON: {e}")
