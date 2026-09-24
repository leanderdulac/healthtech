"""Contrato de status online da frota (servidor + painel).

Selecionar/focar uma linha NUNCA marca o device como online.
Só um frame de ingestão WebSocket genuinamente recente (ou o campo
`online` vindo do servidor) pode fazê-lo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from src.ops.timestamps import ONLINE_WITHIN_SECONDS, is_online


def resolve_fleet_online(
    existing: Optional[Mapping[str, Any]],
    incoming: Mapping[str, Any],
    from_live_ingest: bool,
    now: Optional[datetime] = None,
) -> bool:
    """Decide o flag `online` ao mesclar um frame no cliente.

    - `from_live_ingest=True`: usa a recência do timestamp do frame WS.
    - caso contrário: usa `incoming.online` (servidor) ou o valor já conhecido;
      nunca assume True só porque a linha foi focada.
    """
    if from_live_ingest:
        stamp = incoming.get("received_at") or incoming.get("last_seen") or incoming.get("timestamp")
        return is_online(stamp, now=now, window=ONLINE_WITHIN_SECONDS)
    if isinstance(incoming.get("online"), bool):
        return bool(incoming.get("online"))
    if existing is not None and isinstance(existing.get("online"), bool):
        return bool(existing.get("online"))
    return False
