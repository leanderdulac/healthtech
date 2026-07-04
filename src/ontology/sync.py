"""
Sincroniza ontologia do scraper para o registro canônico do projeto.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Optional

from src.ontology.registry import DEFAULT_ONTOLOGY_PATH, SCRAPER_ONTOLOGY_PATH

logger = logging.getLogger(__name__)


def sync_ontology_to_project(
    source: Optional[Path] = None,
    target: Optional[Path] = None,
) -> Dict:
    src = Path(source) if source else SCRAPER_ONTOLOGY_PATH
    dst = Path(target) if target else DEFAULT_ONTOLOGY_PATH

    if not src.exists():
        return {"status": "NOT_FOUND", "source": str(src)}

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    with open(dst, encoding="utf-8") as f:
        data = json.load(f)

    stats = data.get("ontology", {}).get("statistics", {})
    logger.info("Ontologia sincronizada: %s → %s", src, dst)

    return {
        "status": "SYNCED",
        "source": str(src),
        "target": str(dst),
        "statistics": stats,
    }