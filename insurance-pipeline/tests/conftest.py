import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure enterprise-pipeline root is on sys.path
pipeline_root = Path(__file__).resolve().parents[1]
if str(pipeline_root) not in sys.path:
    sys.path.insert(0, str(pipeline_root))

# Also ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Load .env
load_dotenv(pipeline_root / ".env")
load_dotenv(repo_root / ".env")
