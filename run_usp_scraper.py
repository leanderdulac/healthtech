#!/usr/bin/env python3
"""
Scraper de Teses e Dissertações da USP — área de Medicina.

Fonte: https://teses.usp.br/area?lang=pt-br

Coleta metadados (título, resumo, palavras-chave, área, orientador)
para treino de modelos NLP e construção de ontologia do projeto Healthtech.
"""

import argparse
import logging
from pathlib import Path

from src.scraping.usp_teses.config import ScraperConfig
from src.scraping.usp_teses.scraper import UspTesesScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Scraper USP Teses — Medicina")
    parser.add_argument("--max-pages", type=int, default=2, help="Máx. páginas por query")
    parser.add_argument("--max-details", type=int, default=20, help="Máx. detalhes a coletar")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay entre requests (s)")
    parser.add_argument("--discover-areas", action="store_true", help="Descobrir áreas de concentração")
    parser.add_argument("--no-details", action="store_true", help="Apenas listagens, sem páginas de detalhe")
    parser.add_argument("--output", type=str, default="data/scraping/usp_teses", help="Diretório de saída")
    args = parser.parse_args()

    print_section("USP TESES — SCRAPER DE MEDICINA")

    config = ScraperConfig(
        output_dir=Path(args.output),
        max_pages_per_query=args.max_pages,
        max_details=args.max_details,
        request_delay=args.delay,
        fetch_details=not args.no_details,
    )

    print(f"\n  Fonte                : https://teses.usp.br/area?lang=pt-br")
    print(f"  Queries              : {len(config.search_queries)}")
    print(f"  Max páginas/query    : {config.max_pages_per_query}")
    print(f"  Max detalhes         : {config.max_details}")
    print(f"  Delay entre requests : {config.request_delay}s")
    print(f"  Saída                : {config.output_dir}")

    scraper = UspTesesScraper(config)

    print_section("EXECUTANDO COLETA")
    report = scraper.run(discover_areas=args.discover_areas)

    print_section("RESULTADO")
    print(f"\n  Queries executadas    : {len(report['queries_executed'])}")
    for q in report["queries_executed"]:
        print(f"    • {q['field']}={q['term']} → {q['results']} resultados")
    print(f"  Listagens coletadas   : {report['listings_collected']}")
    print(f"  Registros completos   : {report['records_collected']}")
    print(f"  Registros medicina    : {report['medicine_records']}")

    if report.get("output_paths"):
        print(f"\n  Artefatos:")
        for key, path in report["output_paths"].items():
            print(f"    {key:12s}: {path}")

    print_section("COLETA CONCLUÍDA")
    print(f"  Próximo passo: usar training_corpus.txt e ontology.json para treino NLP")


if __name__ == "__main__":
    main()