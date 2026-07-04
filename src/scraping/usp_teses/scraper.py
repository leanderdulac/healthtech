import logging
import math
from typing import Dict, List, Optional, Set

from src.scraping.usp_teses.client import UspTesesClient
from src.scraping.usp_teses.config import ScraperConfig
from src.scraping.usp_teses.models import ConcentrationArea, ThesisListing, ThesisRecord
from src.scraping.usp_teses.ontology import OntologyBuilder
from src.scraping.usp_teses.parsers import (
    detail_page_url,
    is_medicine_related,
    parse_area_list,
    parse_search_results,
    parse_thesis_detail,
)
from src.scraping.usp_teses.storage import ScraperStorage
from src.ontology.sync import sync_ontology_to_project

logger = logging.getLogger(__name__)


class UspTesesScraper:
    """
    Scraper da Biblioteca Digital de Teses e Dissertações da USP.

    Fluxo:
      1. Descobre áreas de concentração relacionadas à medicina
      2. Busca e pagina resultados por query
      3. Coleta metadados completos (resumo, palavras-chave, orientador)
      4. Constrói ontologia e corpus de treino
    """

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self.client = UspTesesClient(self.config)
        self.storage = ScraperStorage(self.config.output_dir)
        self.ontology_builder = OntologyBuilder()

    def discover_medicine_areas(self) -> List[ConcentrationArea]:
        logger.info("Descobrindo áreas de concentração (buscar_todos=1)...")
        html = self.client.get(self.client.build_area_list_url())
        areas = parse_area_list(html, self.config.base_url, self.config.medicine_terms)
        medicine_areas = [a for a in areas if a.is_medicine_related]
        logger.info(
            "Áreas encontradas: %d total, %d relacionadas à medicina",
            len(areas), len(medicine_areas),
        )
        self.storage.save_areas(areas, "areas_all.json")
        self.storage.save_areas(medicine_areas, "areas_medicine.json")
        return medicine_areas

    def search_listings(self, field: str, term: str) -> List[ThesisListing]:
        query_label = f"{field}={term}"
        all_listings: List[ThesisListing] = []
        page = 1
        total = 0

        while True:
            path = self.client.build_search_url(field, term, page=page)
            logger.info("Buscando [%s] página %d ...", query_label, page)
            html = self.client.get(path)
            listings, total = parse_search_results(
                html, self.config.base_url, query_label, page,
            )

            if not listings:
                break

            for listing in listings:
                if is_medicine_related(
                    f"{listing.titulo} {listing.area} {listing.unidade}",
                    self.config.medicine_terms,
                ):
                    all_listings.append(listing)

            if self.config.max_pages_per_query and page >= self.config.max_pages_per_query:
                break

            total_pages = max(1, math.ceil(total / self.config.page_size))
            if page >= total_pages:
                break
            page += 1

        logger.info(
            "Query [%s]: %d resultados medicina de %d totais",
            query_label, len(all_listings), total,
        )
        return all_listings

    def fetch_details(self, listings: List[ThesisListing]) -> List[ThesisRecord]:
        records: List[ThesisRecord] = []
        limit = self.config.max_details or len(listings)

        for i, listing in enumerate(listings[:limit]):
            detail_url = detail_page_url(listing.url, self.config.lang)
            logger.info(
                "Detalhe %d/%d: %s",
                i + 1, min(limit, len(listings)), listing.titulo[:60],
            )
            try:
                html = self.client.get(detail_url)
                record = parse_thesis_detail(
                    html, listing, self.config.base_url, self.config.medicine_terms,
                )
                if record.is_medicine_related:
                    records.append(record)
            except Exception as e:
                logger.warning("Falha ao coletar %s: %s", listing.url_absoluta, e)

        return records

    def run(
        self,
        discover_areas: bool = False,
        queries: Optional[List[dict]] = None,
    ) -> Dict:
        report = {
            "queries_executed": [],
            "areas_discovered": 0,
            "listings_collected": 0,
            "records_collected": 0,
            "medicine_records": 0,
        }

        if discover_areas:
            areas = self.discover_medicine_areas()
            report["areas_discovered"] = len(areas)

        search_queries = queries or self.config.search_queries
        seen_urls: Set[str] = set()
        unique_listings: List[ThesisListing] = []

        for query in search_queries:
            field = query["field"]
            term = query["term"]
            listings = self.search_listings(field, term)
            report["queries_executed"].append({
                "field": field,
                "term": term,
                "results": len(listings),
            })
            for listing in listings:
                if listing.url_absoluta not in seen_urls:
                    seen_urls.add(listing.url_absoluta)
                    unique_listings.append(listing)

        report["listings_collected"] = len(unique_listings)

        records: List[ThesisRecord] = []
        if self.config.fetch_details and unique_listings:
            records = self.fetch_details(unique_listings)
        else:
            records = [
                ThesisRecord(
                    id=lst.url.rstrip("/").split("/")[-1],
                    titulo=lst.titulo,
                    autor=lst.autor,
                    area=lst.area,
                    unidade=lst.unidade,
                    tipo_documento=lst.tipo_documento,
                    ano_defesa=lst.ano_defesa,
                    url=lst.url,
                    url_absoluta=lst.url_absoluta,
                    search_query=lst.search_query,
                    is_medicine_related=True,
                    texto_treino=f"TITULO: {lst.titulo}\nAREA: {lst.area}",
                )
                for lst in unique_listings
            ]

        medicine_records = [r for r in records if r.is_medicine_related]
        report["records_collected"] = len(records)
        report["medicine_records"] = len(medicine_records)

        ontology = self.ontology_builder.build(medicine_records)

        paths = {
            "jsonl": str(self.storage.save_jsonl(medicine_records)),
            "parquet": str(self.storage.save_parquet(medicine_records)),
            "corpus": str(self.storage.save_training_corpus(medicine_records)),
            "ontology": str(self.storage.save_ontology(ontology)),
            "report": str(self.storage.save_report(report)),
        }

        sync_result = sync_ontology_to_project()
        paths["ontology_canonical"] = sync_result.get("target", "")
        report["ontology_sync"] = sync_result
        report["output_paths"] = paths

        logger.info(
            "Scraping concluído: %d teses medicina, ontologia com %d keywords",
            len(medicine_records),
            ontology["ontology"]["statistics"]["unique_keywords"],
        )
        return report