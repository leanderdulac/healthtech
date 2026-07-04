import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://teses.usp.br"

MEDICINE_AREA_TERMS = [
    "medicina",
    "saúde",
    "saude",
    "clínica",
    "clinica",
    "biomédic",
    "biomedic",
    "enfermagem",
    "odontologia",
    "farmácia",
    "farmacia",
    "fisioterapia",
    "nutrição",
    "nutricao",
    "psiquiatria",
    "cirurgia",
    "pediatria",
    "cardiologia",
    "oncologia",
    "neurologia",
    "radiologia",
    "patologia",
    "epidemiologia",
    "farmacologia",
    "imunologia",
    "ginecologia",
    "obstetrícia",
    "obstetricia",
    "anestesiologia",
    "ortopedia",
    "dermatologia",
    "oftalmologia",
    "urologia",
    "gastroenterologia",
    "pneumologia",
    "endocrinologia",
    "hematologia",
    "bioética",
    "bioetica",
    "telemedicina",
    "monitoramento",
    "wearable",
    "sinais vitais",
    "cardiologia",
    "enfermaria",
    "hospitalar",
]

DEFAULT_SEARCH_QUERIES = [
    {"field": "area", "term": "medicina"},
    {"field": "area", "term": "saúde"},
    {"field": "palavra_chave", "term": "medicina"},
    {"field": "resumo", "term": "telemedicina"},
    {"field": "resumo", "term": "wearable"},
    {"field": "resumo", "term": "monitoramento cardíaco"},
]


@dataclass
class ScraperConfig:
    base_url: str = BASE_URL
    lang: str = "pt-br"
    output_dir: Path = field(default_factory=lambda: Path("data/scraping/usp_teses"))
    request_delay: float = 1.5
    request_timeout: int = 120
    max_retries: int = 3
    page_size: int = 50
    max_pages_per_query: int = 0
    max_details: int = 0
    fetch_details: bool = True
    search_queries: List[dict] = field(default_factory=lambda: list(DEFAULT_SEARCH_QUERIES))
    medicine_terms: List[str] = field(default_factory=lambda: list(MEDICINE_AREA_TERMS))
    user_agent: str = (
        "HealthtechBot/1.0 (+https://github.com/leanderdulac/healthtech; academic research)"
    )

    def __post_init__(self):
        self.output_dir = Path(self.output_dir)
        delay = os.getenv("SCRAPER_DELAY")
        if delay:
            self.request_delay = float(delay)
        max_pages = os.getenv("SCRAPER_MAX_PAGES")
        if max_pages:
            self.max_pages_per_query = int(max_pages)
        max_details = os.getenv("SCRAPER_MAX_DETAILS")
        if max_details:
            self.max_details = int(max_details)