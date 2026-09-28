import json
import os
from datetime import datetime, timezone

from .config import DEBUG_DUMP_DIR
def dump_debug_run(payload: dict, dump_dir: str = DEBUG_DUMP_DIR) -> str:
    """
    Writes the whole run to debug_runs/<timestamp>.json so prompt iterations can be
    compared run over run. Returns the path written, or "" on failure.
    """
    try:
        os.makedirs(dump_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path  = os.path.join(dump_dir, f"run_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        return path
    except Exception as e:
        print(f"  [WARNING] Could not write debug dump: {e}")
        return ""

