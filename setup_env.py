#!/usr/bin/env python3
import os
from pathlib import Path

# Copy DeepSeek API key from Hermes config
hermes_env = Path.home() / ".hermes" / ".env"
target_env = Path(__file__).resolve().parent / "backend" / ".env"

if hermes_env.exists() and not target_env.exists():
    key = None
    for line in hermes_env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY=") or line.startswith("OPENAI_API_KEY="):
            key = line
            break
    if key:
        target_env.write_text(f"{key}\n# video2blog configuration\nFLASK_PORT=5000\nWHISPER_MODEL=base\n")
        print(f"✅ Created {target_env} with API key")
    else:
        print("⚠️  No API key found in ~/.hermes/.env")
else:
    print(f"{'✅' if target_env.exists() else '⚠️'} {target_env}")
