import html
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.scraping.usp_teses.config import MEDICINE_AREA_TERMS
from src.scraping.usp_teses.models import ConcentrationArea, ThesisListing, ThesisRecord

RESULTS_META_RE = re.compile(r"([\d\.]+)\s+documento", re.I)
AREA_META_RE = re.compile(r"([\d\.]+)\s+área", re.I)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _cell_link_text(cell) -> str:
    if cell is None:
        return ""
    link = cell.find("a")
    if link:
        return _clean_text(link.get_text(" ", strip=True))
    return _clean_text(cell.get_text(" ", strip=True))


def is_medicine_related(text: str, medicine_terms: Optional[List[str]] = None) -> bool:
    terms = medicine_terms or MEDICINE_AREA_TERMS
    normalized = _clean_text(text).lower()
    return any(term.lower() in normalized for term in terms)


def parse_search_results(
    html_content: str,
    base_url: str,
    search_query: str,
    page: int,
) -> Tuple[List[ThesisListing], int]:
    soup = BeautifulSoup(html_content, "html.parser")
    total = 0
    meta = soup.select_one(".results-meta")
    if meta:
        match = RESULTS_META_RE.search(meta.get_text(" ", strip=True))
        if match:
            total = int(match.group(1).replace(".", ""))

    listings: List[ThesisListing] = []
    rows = soup.select("section.results-panel table tbody tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue

        title_link = cells[0].find("a", href=True)
        if not title_link:
            continue

        rel_url = title_link["href"]
        listings.append(ThesisListing(
            titulo=_clean_text(title_link.get_text(" ", strip=True)),
            autor=_cell_link_text(cells[1]),
            area=_cell_link_text(cells[2]),
            tipo_documento=_cell_link_text(cells[3]),
            unidade=_cell_link_text(cells[4]),
            ano_defesa=_cell_link_text(cells[5]),
            url=rel_url,
            url_absoluta=urljoin(base_url, rel_url),
            search_query=search_query,
            pagina=page,
        ))

    return listings, total


def parse_area_list(html_content: str, base_url: str, medicine_terms: List[str]) -> List[ConcentrationArea]:
    soup = BeautifulSoup(html_content, "html.parser")
    areas: List[ConcentrationArea] = []
    rows = soup.select("section.results-panel table tbody tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a", href=True)
        nome = _cell_link_text(cells[0])
        total_text = _cell_link_text(cells[1])
        if not nome or not total_text.isdigit():
            continue
        href = link["href"] if link else ""
        areas.append(ConcentrationArea(
            nome=nome,
            total_registros=int(total_text),
            url_busca=urljoin(base_url, href) if href else "",
            is_medicine_related=is_medicine_related(nome, medicine_terms),
        ))

    return areas


def _meta_content(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    return _clean_text(tag["content"]) if tag and tag.get("content") else ""


def _meta_all(soup: BeautifulSoup, name: str) -> List[str]:
    return [_clean_text(tag["content"]) for tag in soup.find_all("meta", attrs={"name": name}) if tag.get("content")]


def _thesis_row_value(soup: BeautifulSoup, label: str) -> str:
    for row in soup.select(".thesis-row"):
        label_el = row.select_one(".thesis-label")
        value_el = row.select_one(".thesis-value")
        if not label_el or not value_el:
            continue
        if _clean_text(label_el.get_text()) == label:
            return _clean_text(value_el.get_text(" ", strip=True))
    return ""


def parse_thesis_detail(
    html_content: str,
    listing: ThesisListing,
    base_url: str,
    medicine_terms: List[str],
) -> ThesisRecord:
    soup = BeautifulSoup(html_content, "html.parser")

    titulo = _meta_content(soup, "dc.title") or listing.titulo
    titulo_en = _meta_content(soup, "dc.title.alternative")
    autor = _meta_content(soup, "dc.creator") or listing.autor
    orientador = _meta_content(soup, "dc.contributor.advisor1")
    area = _meta_content(soup, "dc.publisher.program") or listing.area
    unidade = _meta_content(soup, "dc.publisher.department") or listing.unidade
    tipo = _meta_content(soup, "dc.type") or listing.tipo_documento
    ano = _meta_content(soup, "dc.date") or listing.ano_defesa
    data_defesa = _meta_content(soup, "dc.date.issued")
    resumo_pt = _meta_content(soup, "dc.description.resumo") or _thesis_row_value(soup, "Resumo em português")
    resumo_en = _meta_content(soup, "dc.description.abstract") or _thesis_row_value(soup, "Abstract in English")
    doi = _meta_content(soup, "dc.identifier.doi")
    record_id = _meta_content(soup, "dc.identifier.uri") or listing.url.rstrip("/").split("/")[-1]

    keywords_pt = _meta_all(soup, "dc.subject")
    if not keywords_pt:
        raw_kw = _thesis_row_value(soup, "Palavras-chave em português")
        keywords_pt = [_clean_text(k) for k in raw_kw.split(";") if k.strip()]

    keywords_en = []
    raw_kw_en = _thesis_row_value(soup, "Keywords in English")
    if raw_kw_en:
        keywords_en = [_clean_text(k) for k in raw_kw_en.split(";") if k.strip()]

    banca = []
    for i in range(1, 10):
        referee = _meta_content(soup, f"dc.contributor.referee{i}")
        if referee:
            banca.append(referee)

    combined_text = " ".join(filter(None, [
        titulo, area, unidade, " ".join(keywords_pt), resumo_pt,
    ]))
    medicine_flag = is_medicine_related(combined_text, medicine_terms)

    texto_treino = "\n\n".join(filter(None, [
        f"TITULO: {titulo}",
        f"AREA: {area}",
        f"TIPO: {tipo}",
        f"PALAVRAS_CHAVE: {'; '.join(keywords_pt)}",
        f"RESUMO: {resumo_pt}",
    ]))

    return ThesisRecord(
        id=record_id,
        titulo=titulo,
        titulo_en=titulo_en,
        autor=autor,
        orientador=orientador,
        area=area,
        programa=area,
        unidade=unidade,
        tipo_documento=tipo,
        ano_defesa=ano,
        data_defesa=data_defesa,
        resumo_pt=resumo_pt,
        resumo_en=resumo_en,
        palavras_chave_pt=keywords_pt,
        palavras_chave_en=keywords_en,
        banca=banca,
        doi=doi,
        url=listing.url,
        url_absoluta=listing.url_absoluta,
        search_query=listing.search_query,
        is_medicine_related=medicine_flag,
        texto_treino=texto_treino,
    )


def detail_page_url(listing_url: str, lang: str = "pt-br") -> str:
    base = listing_url.rstrip("/")
    if base.endswith(".html"):
        return base
    return f"{base}/{lang}.html"