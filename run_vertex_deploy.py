#!/usr/bin/env python3
"""Deploy dos 3 TCNs no Vertex AI Endpoint (custom container).

Wrapper fino sobre src.integrations.vertex.deploy.deploy_tcn_custom.

Exemplos:
  python run_vertex_deploy.py --smoke-only
  python run_vertex_deploy.py --deploy --sync
  python run_vertex_deploy.py --deploy --skip-build   # reusa imagem latest
"""

from src.integrations.vertex.deploy.deploy_tcn_custom import main


if __name__ == "__main__":
    raise SystemExit(main())
