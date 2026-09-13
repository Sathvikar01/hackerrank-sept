import sys
from pathlib import Path

CODE_DIR = str(Path(__file__).resolve().parent / "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)
