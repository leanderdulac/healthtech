"""Admin: search + reindex (stubs seguros quando RAG não está montado)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.schemas import SearchQuery
from app.security.auth import require_scope
from app.services import telemetry_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


def _try_slm_search(query: str, n_results: int) -> List[Dict[str, Any]]:
    try:
        from src.ml_pipeline.slm_search_engine import SLMSearchEngine  # type: ignore

        engine = SLMSearchEngine()
        results = engine.search_medical_knowledge(query, n_results=n_results)
        parsed: List[Dict[str, Any]] = []
        if results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                meta = results["metadatas"][0][i]
                dist = 0.0
                if results.get("distances") and results["distances"]:
                    dist = float(results["distances"][0][i])
                parsed.append(
                    {
                        "document": results["documents"][0][i],
                        "url": meta.get("url", ""),
                        "autor": meta.get("autor", "Desconhecido"),
                        "topico_dominante": meta.get("topico_dominante", "N/A"),
                        "distance_l2": dist,
                    }
                )
        return parsed
    except Exception as exc:
        logger.info("SLM indisponível no modo secure standalone: %s", exc)
        return []


@router.post("/api/search")
def search_literature(
    search: SearchQuery,
    request: Request,
    _api_key: str = Depends(require_scope("wearables:read")),
):
    """Busca semântica em literatura (se SLM/parent disponível)."""
    _ = request
    if not search.query.strip():
        raise HTTPException(status_code=400, detail="A consulta (query) não pode estar vazia.")
    docs = _try_slm_search(search.query, search.n_results)
    return {
        "results": docs,
        "query": search.query,
        "engine": "slm" if docs else "unavailable",
    }


@router.post("/api/v1/admin/reindex")
@router.post("/api/reindex")
def reindex_data_lake(
    request: Request,
    _api_key: str = Depends(require_scope("admin")),
):
    """Reindexação do data lake no ChromaDB (admin)."""
    _ = request
    try:
        from src.data_warehouse.datalake_manager import DataLakeManager  # type: ignore
        from src.ml_pipeline.slm_search_engine import SLMSearchEngine  # type: ignore

        engine = SLMSearchEngine()
        engine.index_datalake(DataLakeManager())
        return {"status": "success", "message": "Data lake reindexado com sucesso."}
    except Exception as exc:
        logger.warning("Reindex standalone sem monólito: %s", exc)
        s = telemetry_store.stats()
        return {
            "status": "success",
            "message": (
                "Reindex solicitado. Motor RAG do monólito não montado; "
                "telemetria em memória preservada."
            ),
            "patients_tracked": s["patients_tracked"],
            "mode": "standalone",
        }
