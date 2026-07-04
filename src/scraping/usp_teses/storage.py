import json
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.scraping.usp_teses.models import ConcentrationArea, ThesisRecord

logger = logging.getLogger(__name__)


class ScraperStorage:
    """Persistência dos dados coletados."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_jsonl(self, records: List[ThesisRecord], filename: str = "theses.jsonl") -> Path:
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        logger.info("Salvos %d registros em %s", len(records), path)
        return path

    def save_parquet(self, records: List[ThesisRecord], filename: str = "theses.parquet") -> Path:
        path = self.output_dir / filename
        df = pd.DataFrame([r.to_dict() for r in records])
        if not df.empty:
            for col in ("palavras_chave_pt", "palavras_chave_en", "banca"):
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])
        df.to_parquet(path, index=False)
        logger.info("Parquet salvo: %s (%d rows)", path, len(df))
        return path

    def save_training_corpus(self, records: List[ThesisRecord], filename: str = "training_corpus.txt") -> Path:
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for i, record in enumerate(records):
                if not record.is_medicine_related or not record.texto_treino:
                    continue
                f.write(f"--- DOCUMENTO {i + 1} | {record.id} ---\n")
                f.write(record.texto_treino)
                f.write("\n\n")
        logger.info("Corpus de treino salvo: %s", path)
        return path

    def save_ontology(self, ontology: Dict, filename: str = "ontology.json") -> Path:
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ontology, f, indent=2, ensure_ascii=False)
        logger.info("Ontologia salva: %s", path)
        return path

    def save_areas(self, areas: List[ConcentrationArea], filename: str = "areas.json") -> Path:
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump([a.to_dict() for a in areas], f, indent=2, ensure_ascii=False)
        logger.info("Áreas salvas: %s (%d)", path, len(areas))
        return path

    def save_report(self, report: Dict, filename: str = "scrape_report.json") -> Path:
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return path