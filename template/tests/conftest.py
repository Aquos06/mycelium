import sys
from pathlib import Path

# make `import app.main` work no matter where pytest is launched from
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
