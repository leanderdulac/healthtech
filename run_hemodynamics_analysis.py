#!/usr/bin/env python3
"""
Análise hemodinâmica com gradiente, divergência e curl.

Modela padrões de circulação sanguínea e detecta irregularidades vasculares.
Integra com ontologia cardiovascular e alertas FHIR.
"""

import logging

from src.hemodynamics.alerts import HemodynamicsAlertGenerator
from src.hemodynamics.analyzer import VascularFlowAnalyzer
from src.hemodynamics.simulator import VascularFlowSimulator
from src.hemodynamics.storage import HemodynamicsStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    print_section("HEMODINÂMICA — GRAD · DIV · CURL")

    simulator = VascularFlowSimulator(nx=40, ny=24, nz=24, spacing=0.5)
    analyzer = VascularFlowAnalyzer()
    alert_gen = HemodynamicsAlertGenerator()
    storage = HemodynamicsStorage()

    scenarios = ["normal", "stenosis", "aneurysm", "turbulent"]
    all_summaries = []

    for scenario in scenarios:
        print_section(f"CENÁRIO: {scenario.upper()}")
        pressure, velocity = simulator.simulate(scenario)
        result = analyzer.analyze(
            pressure=pressure,
            velocity=velocity,
            patient_id=f"PAT-HEMO-{scenario[:4].upper()}",
            scenario=scenario,
        )
        summary = alert_gen.summary(result)
        flags = alert_gen.generate_fhir_flags(result)
        paths = storage.save_analysis(result, summary)
        fhir_path = storage.save_fhir_flags(flags, scenario)

        print(f"\n  Gradiente max |∇p|  : {summary['operators']['gradient_max']:.2f}")
        print(f"  Divergência   : [{summary['operators']['divergence_range'][0]:.1f}, "
              f"{summary['operators']['divergence_range'][1]:.1f}]")
        print(f"  Curl max |∇×v|  : {summary['operators']['curl_max']:.2f}")
        print(f"  Irregularidades : {summary['irregularities']}")
        print(f"  Por operador    : {summary['by_operator']}")
        print(f"  Ontologia       : {summary['ontology_domains']}")

        if result.irregularities:
            print(f"\n  Alertas:")
            for ir in result.irregularities:
                print(f"    • [{ir.severity}] {ir.description}")

        print(f"\n  Artefatos       : {paths['analysis']}")
        print(f"  FHIR Flags      : {fhir_path}")
        all_summaries.append(summary)

    print_section("RESUMO COMPARATIVO")
    print(f"\n  {'Cenário':<12} {'|∇p|':>8} {'div_max':>8} {'|curl|':>8} {'Alertas':>8}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for s in all_summaries:
        print(f"  {s['scenario']:<12} "
              f"{s['operators']['gradient_max']:>8.1f} "
              f"{max(abs(v) for v in s['operators']['divergence_range']):>8.1f} "
              f"{s['operators']['curl_max']:>8.1f} "
              f"{s['irregularities']:>8}")

    print_section("ANÁLISE CONCLUÍDA")
    print("  Operadores: gradient (pressão), divergence (fontes/sumidouros), curl (rotação)")
    print("  Integração: ontologia cardiovascular + FHIR Flags")
    print("  Dados em   : data/hemodynamics/")


if __name__ == "__main__":
    main()