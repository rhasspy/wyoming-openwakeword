from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class State:
    custom_models: Dict[str, Path] = field(default_factory=dict)
