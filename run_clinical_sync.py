#!/usr/bin/env python3
"""Sincronização de dados clínicos reais via FHIR Server."""

import argparse
import json
import logging

from src.integrations.clinical.clinical_bridge import ClinicalDataBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Sync clínico FHIR → PatientBaseline")
    parser.add_argument("--patient-ids", nargs="+", required=True)
    parser.add_argument("--fhir-patient-id", default=None)
    args = parser.parse_args()

    bridge = ClinicalDataBridge()
    print(f"FHIR Server live: {bridge.client.is_live}")

    for pid in args.patient_ids:
        baseline = bridge.sync_patient(pid, fhir_patient_id=args.fhir_patient_id)
        events = bridge.get_clinical_events(pid)
        print(f"\n{pid}:")
        print(f"  Condições: {baseline.clinical_conditions}")
        print(f"  Medicações: {baseline.medications}")
        print(f"  Risk factor: {baseline.risk_factor:.3f}")
        print(f"  Eventos FHIR: {len(events)}")


if __name__ == "__main__":
    main()