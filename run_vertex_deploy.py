#!/usr/bin/env python3
"""Deploy dos 3 TCNs no Vertex AI Endpoint."""

import argparse
import json
import logging

from src.integrations.vertex.deploy.endpoint_manager import VertexTCNEndpointManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Deploy TCN temporal no Vertex AI")
    parser.add_argument("--smoke-only", action="store_true", help="Apenas teste local")
    parser.add_argument("--upload-only", action="store_true", help="Upload GCS sem deploy")
    parser.add_argument("--deploy", action="store_true", help="Deploy completo no Vertex")
    parser.add_argument("--sync", action="store_true", help="Aguardar conclusão do deploy")
    args = parser.parse_args()

    manager = VertexTCNEndpointManager()
    validation = manager.validate_artifacts()
    print("Artefatos:", json.dumps(validation, indent=2))

    if not validation["valid"]:
        print("ERRO: modelos TCN ausentes. Execute: python run_temporal_training.py")
        return

    if args.smoke_only or (not args.upload_only and not args.deploy):
        result = manager.smoke_test_local()
        print(json.dumps(result, indent=2))
        return

    if args.upload_only:
        uri = manager.upload_to_gcs()
        print(f"Upload concluído: {uri}")
        return

    result = manager.deploy_to_vertex(sync=args.sync)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()