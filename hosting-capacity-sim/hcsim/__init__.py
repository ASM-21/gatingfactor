"""Distribution feeder DER hosting capacity screening.

Educational / illustrative model. The feeders here are synthetic archetypes
built from typical US overhead distribution parameters. They are NOT calibrated
to any real circuit and must not be used for actual interconnection decisions.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
