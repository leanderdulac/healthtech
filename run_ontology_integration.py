#!/usr/bin/env python3
"""
Integração da ontologia médica USP com FHIR e pipeline ML.
"""

import json
import logging
from pathlib import Path

from src.ontology.fhir_bridge import OntologyFhirBridge
from src.ontology.registry import MedicalOntologyRegistry
from src.ontology.sync import sync_ontology_to_project

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    print_section("INTEGRAÇÃO ONTOLOGIA MÉDICA")

    sync = sync_ontology_to_project()
    print(f"\n  Sync status          : {sync.get('status')}")
    print(f"  Fonte                : {sync.get('source', 'N/A')}")
    print(f"  Destino canônico     : {sync.get('target', 'N/A')}")

    registry = MedicalOntologyRegistry()
    if not registry.load():
        print("\n  Ontologia não disponível. Execute: python run_usp_scraper.py")
        return

    stats = registry.statistics
    print(f"\n  Teses na ontologia   : {stats.get('total_theses', 0)}")
    print(f"  Keywords únicas      : {stats.get('unique_keywords', 0)}")
    print(f"  Áreas únicas         : {stats.get('unique_areas', 0)}")

    print_section("TOP KEYWORDS")
    for item in registry.get_top_keywords(15):
        print(f"    • {item['keyword']} ({item['count']})")

    print_section("DOMÍNIOS (exemplo: telemedicina + cardiovascular)")
    sample_text = "telemedicina wearable monitoramento cardíaco spo2"
    domains = registry.domain_scores(sample_text)
    for domain, score in sorted(domains.items(), key=lambda x: x[1], reverse=True):
        print(f"    • {domain}: {score}")

    bridge = OntologyFhirBridge(registry)
    codesystem = bridge.build_codesystem()
    cs_path = Path("data/ontology/fhir_codesystem.json")
    cs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cs_path, "w", encoding="utf-8") as f:
        json.dump(codesystem, f, indent=2, ensure_ascii=False)

    print_section("FHIR CODESYSTEM")
    print(f"  Conceitos exportados : {len(codesystem.get('concept', []))}")
    print(f"  Arquivo              : {cs_path}")
    print(f"  URL                  : {codesystem.get('url')}")

    print_section("INTEGRAÇÃO CONCLUÍDA")
    print("  A ontologia está ativa em:")
    print("    • DatalakeFeatureBuilder (features ont_*)")
    print("    • FHIR Flags (extensões ontology-keyword)")
    print("    • VertexIntegrationOrchestrator (Fase 6)")


if __name__ == "__main__":
    main()