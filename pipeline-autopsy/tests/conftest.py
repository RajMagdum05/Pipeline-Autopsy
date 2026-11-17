import sys
import os
from pathlib import Path

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

TEST_API_KEY = "autopsy-test-static-key"
os.environ["AUTOPSY_API_KEY"] = TEST_API_KEY
os.environ.setdefault("AUTOPSY_DATABASE_URL", "sqlite:///./test.db")
