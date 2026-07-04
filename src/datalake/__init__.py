"""
Datalake de Saúde — telemetria contínua 24h de wearables.

Arquitetura Medallion (Bronze → Silver → Gold) para ingestão,
qualidade, transformação e extração de dados biométricos.
"""

from src.datalake.config import LakehouseConfig

__all__ = ["LakehouseConfig"]