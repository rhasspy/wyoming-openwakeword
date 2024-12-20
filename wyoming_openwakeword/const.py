
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class Settings:
    builtin_models_dir: Path
    custom_model_dirs: List[Path]
    detection_threshold: float
    vad_threshold: float
    refractory_seconds: float
    output_dir: Optional[Path]
    debug_probability: bool
