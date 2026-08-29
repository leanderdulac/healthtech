#!/usr/bin/env python3
"""Healthtech Language v1 — encoder clínico PT (BioBERTpt) fine-tuned no corpus USP.

Não entra no caminho de decisão clínica. Substitui o MiniLM genérico do RAG.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from sentence_transformers import InputExample, SentenceTransformer, losses, models

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("language_v1")

ROOT = Path(__file__).resolve().parent
THESES = ROOT / "data/scraping/usp_teses/theses.jsonl"
OUT_DIR = ROOT / "data/models/language_v1"
BACKBONE = "pucpr/biobertpt-all"
FALLBACK = "neuralmind/bert-base-portuguese-cased"
BRT = timezone(timedelta(hours=-3))


def load_theses() -> list[dict]:
    rows = []
    with THESES.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_pairs(theses: list[dict]) -> list[InputExample]:
    examples: list[InputExample] = []
    for rec in theses:
        title = (rec.get("titulo") or "").strip()
        abstract = (rec.get("resumo_pt") or "").strip()
        if title and abstract:
            examples.append(InputExample(texts=[title, abstract[:1200]]))
        kws = rec.get("palavras_chave_pt") or []
        for kw in kws[:8]:
            kw = (kw or "").strip()
            if kw and title:
                examples.append(InputExample(texts=[kw, title]))
            if kw and abstract:
                examples.append(InputExample(texts=[kw, abstract[:400]]))
        area = (rec.get("area") or "").strip()
        if area and title:
            examples.append(InputExample(texts=[area, title]))
    random.shuffle(examples)
    logger.info("Pares de treino: %d", len(examples))
    return examples


def make_model(name: str) -> SentenceTransformer:
    logger.info("Carregando backbone %s", name)
    word = models.Transformer(name, max_seq_length=256)
    pool = models.Pooling(word.get_word_embedding_dimension(), pooling_mode="mean")
    model = SentenceTransformer(modules=[word, pool])
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)
    logger.info("Device: %s", device)
    return model


def retrieval_acc(model: SentenceTransformer, theses: list[dict], n: int = 80) -> dict:
    subset = theses[:n]
    titles = [r["titulo"] for r in subset]
    abstracts = [(r.get("resumo_pt") or "")[:1200] for r in subset]
    t_emb = model.encode(titles, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
    a_emb = model.encode(abstracts, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
    t_emb = np.nan_to_num(t_emb, nan=0.0, posinf=0.0, neginf=0.0)
    a_emb = np.nan_to_num(a_emb, nan=0.0, posinf=0.0, neginf=0.0)
    sims = t_emb @ a_emb.T
    ranks = []
    for i in range(len(subset)):
        order = np.argsort(-sims[i])
        ranks.append(int(np.where(order == i)[0][0]) + 1)
    ranks = np.array(ranks)
    return {
        "n": int(len(subset)),
        "top1": round(float((ranks == 1).mean()), 4),
        "top5": round(float((ranks <= 5).mean()), 4),
        "mrr": round(float((1.0 / ranks).mean()), 4),
    }


def main() -> None:
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    theses = load_theses()
    logger.info("Teses: %d", len(theses))
    examples = build_pairs(theses)
    if len(examples) < 50:
        raise SystemExit("Corpus pequeno demais para treinar")

    try:
        backbone = BACKBONE
        model = make_model(backbone)
    except Exception as e:
        logger.warning("Falha em %s (%s). Fallback %s", BACKBONE, e, FALLBACK)
        backbone = FALLBACK
        model = make_model(backbone)

    baseline = retrieval_acc(model, theses)
    logger.info("Baseline retrieval: %s", baseline)

    loader = DataLoader(examples, shuffle=True, batch_size=8)
    loss = losses.MultipleNegativesRankingLoss(model)
    warmup = max(10, int(0.1 * len(loader) * 2))
    model.fit(
        train_objectives=[(loader, loss)],
        epochs=2,
        warmup_steps=warmup,
        optimizer_params={"lr": 2e-5},
        output_path=str(OUT_DIR / "encoder"),
        save_best_model=True,
        show_progress_bar=True,
        use_amp=False,
    )

    trained = SentenceTransformer(str(OUT_DIR / "encoder"))
    after = retrieval_acc(trained, theses)
    logger.info("After retrieval: %s", after)

    meta = {
        "name": "Healthtech Language v1",
        "backbone": backbone,
        "trained_at": datetime.now(BRT).isoformat(),
        "theses": len(theses),
        "train_pairs": len(examples),
        "epochs": 2,
        "max_seq_length": 256,
        "task": "sentence embedding (title/abstract/keyword), RAG only",
        "not_used_for": "clinical decision path",
        "baseline_retrieval": baseline,
        "trained_retrieval": after,
    }
    (OUT_DIR / "language_v1_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    logger.info("Salvo em %s", OUT_DIR)


if __name__ == "__main__":
    main()
