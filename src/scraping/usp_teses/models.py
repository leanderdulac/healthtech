from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ThesisListing:
    titulo: str
    autor: str
    area: str
    tipo_documento: str
    unidade: str
    ano_defesa: str
    url: str
    url_absoluta: str
    search_query: str = ""
    pagina: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ThesisRecord:
    """Registro completo de tese/dissertação para treino e ontologia."""

    id: str
    titulo: str
    titulo_en: str = ""
    autor: str = ""
    orientador: str = ""
    area: str = ""
    programa: str = ""
    unidade: str = ""
    tipo_documento: str = ""
    ano_defesa: str = ""
    data_defesa: str = ""
    resumo_pt: str = ""
    resumo_en: str = ""
    palavras_chave_pt: List[str] = field(default_factory=list)
    palavras_chave_en: List[str] = field(default_factory=list)
    banca: List[str] = field(default_factory=list)
    doi: str = ""
    url: str = ""
    url_absoluta: str = ""
    search_query: str = ""
    is_medicine_related: bool = True
    texto_treino: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConcentrationArea:
    nome: str
    total_registros: int
    url_busca: str = ""
    is_medicine_related: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)