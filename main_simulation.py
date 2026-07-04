"""
Ponto de entrada unificado do projeto Healthtech.

Executa o pipeline completo:
  Datalake 24h → BigQuery → Vertex AI (treino + online + batch)
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    print("=" * 70)
    print(" HEALTHTECH — Pipeline Completo (Datalake + BigQuery + Vertex AI)")
    print("=" * 70)
    print("\nRedirecionando para run_vertex_integration.py ...\n")

    from run_vertex_integration import main as run_integration
    run_integration()


if __name__ == "__main__":
    main()