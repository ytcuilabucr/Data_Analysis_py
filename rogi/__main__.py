import sys
from pathlib import Path

# Support PyCharm's file run configuration as well as `python -m rogi`.
if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "rogi"

from .ui import main

if __name__ == "__main__":
    main()
