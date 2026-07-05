from src.integrations.vertex.config import VertexConfig

__all__ = ["VertexConfig", "VertexIntegrationOrchestrator"]


def __getattr__(name: str):
    if name == "VertexIntegrationOrchestrator":
        from src.integrations.vertex.orchestrator import VertexIntegrationOrchestrator
        return VertexIntegrationOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")