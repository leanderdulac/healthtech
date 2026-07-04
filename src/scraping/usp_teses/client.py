import logging
import time
from typing import Dict, Optional
from urllib.parse import urlencode, urljoin

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.scraping.usp_teses.config import ScraperConfig

logger = logging.getLogger(__name__)


class UspTesesClient:
    """Cliente HTTP para teses.usp.br com rate limiting e retries."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        })
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < self.config.request_delay:
            time.sleep(self.config.request_delay - elapsed)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def get(self, path: str, params: Optional[Dict] = None) -> str:
        self._throttle()
        url = path if path.startswith("http") else urljoin(self.config.base_url, path)
        response = self.session.get(url, params=params, timeout=self.config.request_timeout)
        self._last_request_at = time.time()
        response.raise_for_status()
        return response.text

    def build_search_url(self, field: str, term: str, page: int = 1) -> str:
        params = {
            "lang": self.config.lang,
            "operadores[]": "AND",
            "campos[]": field,
            "termos[]": term,
            "termos_exatos[]": "0",
            "page": page,
            "page_size": self.config.page_size,
        }
        return f"/?{urlencode(params, doseq=True)}"

    def build_area_list_url(self) -> str:
        return f"/area?lang={self.config.lang}&buscar_todos=1"