import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scrape_usp_theses(base_url, max_pages=2, output_file='teses_usp_saude.csv'):
    """
    Realiza o scraping de teses do portal da USP.
    """
    logger.info(f"Iniciando scraping de teses USP (Max pages: {max_pages})")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    theses_data = []
    
    for page in range(1, max_pages + 1):
        url = f"{base_url}&page={page}"
        logger.info(f"Buscando página {page}...")
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Os links para as teses parecem estar em divs ou a tags específicas. 
            # A partir da URL fornecida, os resultados tem links como /teses/disponiveis/
            links = soup.find_all('a', href=True)
            thesis_links = []
            for a in links:
                href = a['href']
                if '/teses/disponiveis/' in href:
                    # O site usa meta refresh HTML para redirecionar para pt-br.html
                    if not href.endswith('.html'):
                        if not href.endswith('/'):
                            href += '/'
                        href += 'pt-br.html'
                        
                    if href.startswith('http'):
                        thesis_links.append(href)
                    else:
                        # Trata URL relativa
                        base = "https://teses.usp.br"
                        if href.startswith('/'):
                            thesis_links.append(base + href)
                        else:
                            thesis_links.append(base + '/' + href)
            
            # Remove duplicatas preservando a ordem
            thesis_links = list(dict.fromkeys(thesis_links))
            
            logger.info(f"Encontrados {len(thesis_links)} links de teses na página {page}.")
            
            for link in thesis_links:
                try:
                    logger.info(f"Extraindo dados de: {link}")
                    t_resp = requests.get(link, headers=headers, timeout=30)
                    t_resp.raise_for_status()
                    t_soup = BeautifulSoup(t_resp.text, 'html.parser')
                    
                    # No HTML da USP, os metadados estão em tags <meta name="dc.*">
                    title_meta = t_soup.find('meta', attrs={'name': 'dc.title'})
                    title = title_meta['content'].strip() if title_meta else "N/A"
                    
                    author_meta = t_soup.find('meta', attrs={'name': 'dc.creator'})
                    author = author_meta['content'].strip() if author_meta else "N/A"
                    
                    resumo_meta = t_soup.find('meta', attrs={'name': 'dc.description.resumo'})
                    resumo = resumo_meta['content'].strip() if resumo_meta else "N/A"
                    
                    # Extraindo palavras-chave se houver
                    keywords_meta = t_soup.find('meta', attrs={'name': 'dc.subject'})
                    keywords = keywords_meta['content'].strip() if keywords_meta else ""
                    
                    if resumo != "N/A":
                        theses_data.append({
                            'titulo': title,
                            'autor': author,
                            'resumo': resumo,
                            'palavras_chave': keywords,
                            'url': link
                        })
                    
                    time.sleep(0.5) # Pausa amigável
                except Exception as e:
                    logger.error(f"Erro ao extrair tese {link}: {e}")
                    
        except Exception as e:
            logger.error(f"Erro na página {page}: {e}")
            break
            
    df = pd.DataFrame(theses_data)
    df.to_csv(output_file, index=False, encoding='utf-8')
    logger.info(f"Scraping concluído! Foram extraídas {len(df)} teses e salvas em {output_file}.")
    return df

if __name__ == "__main__":
    BASE_URL = "https://teses.usp.br/?lang=pt-br&operadores%5B%5D=AND&campos%5B%5D=resumo&termos%5B%5D=Sa%C3%BAde%2C+medicina%2C+telemedicina+&termos_exatos%5B%5D=0"
    # Rodamos com 1 página para teste inicial
    scrape_usp_theses(BASE_URL, max_pages=1, output_file='teses_usp_saude.csv')
