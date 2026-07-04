import sys
from pathlib import Path

# Add project root to sys.path immediately when conftest is loaded
_project_root = Path(__file__).parent
_project_root_str = str(_project_root)
if _project_root_str not in sys.path:
    sys.path.insert(0, _project_root_str)
