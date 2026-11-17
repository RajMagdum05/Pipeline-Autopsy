import re
import subprocess
import sys
from pathlib import Path


def test_core_imports_without_application_dependencies():
    script = """
import sys
import autopsy.core
forbidden = ("autopsy.api", "autopsy.db", "autopsy.services", "autopsy.explain")
loaded = [name for name in sys.modules for prefix in forbidden
          if name == prefix or name.startswith(prefix + ".")]
assert not loaded, loaded
"""
    project_root = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, "-c", script], cwd=project_root, check=True)


def test_core_source_uses_only_domain_neutral_terms():
    root = Path(__file__).resolve().parents[2] / "autopsy" / "core"
    forbidden = re.compile(r"\b(claim|policy|ocr|gemini|insurance)\b", re.IGNORECASE)
    for path in root.glob("*.py"):
        assert forbidden.search(path.read_text(encoding="utf-8")) is None, path.name

