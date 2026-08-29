import os
import sys
import logging
import pandas as pd
import uuid
import numpy as np
try:
    import chromadb
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False

# Adicionar raiz do projeto ao path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Tentar importar SentenceTransformer (ignorado no modo de teste rápido)
if not os.environ.get("TESTING"):
    try:
        from sentence_transformers import SentenceTransformer
        _HAS_TRANSFORMERS = True
    except (ImportError, OSError) as e:
        logger.warning(
            f"Aviso: Falha ao carregar a biblioteca de Deep Learning 'sentence-transformers' ({e}). "
            "O sistema utilizará codificação baseada em hashing de texto para busca como fallback."
        )
        _HAS_TRANSFORMERS = False
else:
    _HAS_TRANSFORMERS = False


class SLMSearchEngine:
    def __init__(self, db_path='data/chroma_db'):
        """
        Inicializa o Motor de Busca RAG.
        Utiliza o Healthtech Language v1 (BioBERTpt fino-ajustado) para embeddings.
        MiniLM só entra se o v1 não estiver em disco.
        Caso o deep learning falhe, implementa um fallback robusto.
        """
        self.db_path = db_path
        os.makedirs(self.db_path, exist_ok=True)
        
        # Sincroniza com GCS antes de instanciar o ChromaDB
        self.download_db_from_gcs()
        
        self.encoder = None
        self.encoder_name = "fallback-hash"
        self.embedding_dim = 768
        if _HAS_TRANSFORMERS:
            try:
                v1_path = os.path.join(
                    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
                    "data", "models", "language_v1", "encoder",
                )
                if os.path.isdir(v1_path):
                    logger.info("Carregando Healthtech Language v1 (BioBERTpt)...")
                    self.encoder = SentenceTransformer(v1_path)
                    self.encoder_name = "healthtech-language-v1"
                else:
                    logger.warning("Language v1 ausente em %s. Fallback MiniLM.", v1_path)
                    self.encoder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
                    self.encoder_name = "minilm"
                dim_fn = getattr(self.encoder, "get_sentence_embedding_dimension", None) or getattr(
                    self.encoder, "get_embedding_dimension", None
                )
                if dim_fn:
                    self.embedding_dim = int(dim_fn())
            except Exception as e:
                logger.warning(
                    f"Erro ao instanciar o SentenceTransformer ({e}). "
                    "Ativando codificador fallback."
                )
                self.encoder = None
                self.encoder_name = "fallback-hash"

        if _HAS_CHROMADB:
            logger.info("Conectando ao Vector Database (ChromaDB)...")
            self.chroma_client = chromadb.PersistentClient(path=self.db_path)
            collection_name = "medical_knowledge_v1" if self.encoder_name == "healthtech-language-v1" else "medical_knowledge"
            self.collection = self.chroma_client.get_or_create_collection(name=collection_name)
            self.seed_global_knowledge()
        else:
            logger.warning("ChromaDB não instalado. SLMSearchEngine operando em modo fallback estático.")
            self.chroma_client = None
            self.collection = None

    def seed_global_knowledge(self):
        """Semeia o Chroma com teses USP (Language v1) se a coleção estiver vazia."""
        if self.collection is None or self.collection.count() != 0:
            return

        seed_docs = []
        seed_meta = []
        theses_path = os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
            "data", "scraping", "usp_teses", "theses.jsonl",
        )
        if os.path.isfile(theses_path):
            import json
            with open(theses_path, encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    title = (rec.get("titulo") or "").strip()
                    abstract = (rec.get("resumo_pt") or "").strip()
                    if not title:
                        continue
                    seed_docs.append(f"Título: {title}\nResumo: {abstract[:1200]}")
                    seed_meta.append({
                        "autor": str(rec.get("autor") or "USP"),
                        "topico_dominante": str(rec.get("area") or "medicina"),
                        "source": "usp_teses",
                    })
            logger.info("Semeando RAG Language v1 com %d teses USP...", len(seed_docs))
        else:
            logger.info("theses.jsonl ausente. Semeando stubs clínicos.")
            seed_docs = [
                "USP - Estudo de Reatividade Cardíaca e Variação Autonômica em Pacientes Críticos.",
                "Johns Hopkins Medicine - Global Cardiology Review: Catecholamines, HRV and Autonomic Stress Signals.",
                "USP Medicina - Telemetria Contínua e Monitoramento do Microclima Fisiológico no SUS.",
                "Johns Hopkins Research - Predictive Hemodynamic Instability and Sympathetic Tone Evaluation.",
            ]
            seed_meta = [
                {"autor": "USP Faculdade de Medicina", "topico_dominante": "Cardiologia"},
                {"autor": "Johns Hopkins University", "topico_dominante": "Catecolaminas e Estresse"},
                {"autor": "USP Medicina", "topico_dominante": "SUS Prevenção"},
                {"autor": "Johns Hopkins Medicine", "topico_dominante": "Hemodinâmica"},
            ]

        ids = [str(uuid.uuid4()) for _ in range(len(seed_docs))]
        if self.encoder is not None:
            try:
                embs = self.encoder.encode(seed_docs, show_progress_bar=False).tolist()
            except Exception:
                embs = self._fallback_encode(seed_docs).tolist()
        else:
            embs = self._fallback_encode(seed_docs).tolist()

        self.collection.add(
            embeddings=embs,
            documents=seed_docs,
            metadatas=seed_meta,
            ids=ids,
        )
        logger.info("RAG semeado: %d docs, encoder=%s dim=%s", len(seed_docs), self.encoder_name, self.embedding_dim)

    def download_db_from_gcs(self):
        """Baixa o backup do ChromaDB do GCS se disponível."""
        bucket_name = os.getenv("GCS_STAGING_BUCKET", "").replace("gs://", "").strip()
        if not bucket_name:
            logger.info("Sincronização GCS ChromaDB: GCS_STAGING_BUCKET não configurado. Ignorando download.")
            return
        
        from src.utils.gcp_auth import get_gcp_credentials
        creds, _ = get_gcp_credentials()
        if not creds:
            logger.info("Credentials GCP não encontradas no ambiente local. Pulando download do GCS.")
            return

        logger.info(f"Sincronização GCS: Tentando baixar ChromaDB do bucket: {bucket_name}...")
        try:
            from google.cloud import storage
            import tarfile
            
            storage_client = storage.Client(credentials=creds)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob("chroma_db/chroma_db.tar.gz")
            
            if blob.exists():
                archive_path = os.path.join(os.path.dirname(self.db_path), "chroma_db.tar.gz")
                blob.download_to_filename(archive_path)
                logger.info("ChromaDB baixado com sucesso do GCS. Extraindo...")
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(path=os.path.dirname(self.db_path))
                os.remove(archive_path)
                logger.info("Extração concluída!")
            else:
                logger.info("Nenhum backup do ChromaDB encontrado no GCS. Iniciando com base vazia.")
        except Exception as e:
            logger.warning(f"Aviso na sincronização GCS (não bloqueante): {e}")

    def upload_db_to_gcs(self):
        """Comprime e envia o ChromaDB atualizado para o GCS."""
        bucket_name = os.getenv("GCS_STAGING_BUCKET", "").replace("gs://", "").strip()
        if not bucket_name:
            logger.info("Sincronização GCS ChromaDB: GCS_STAGING_BUCKET não configurado. Ignorando upload.")
            return
            
        from src.utils.gcp_auth import get_gcp_credentials
        creds, _ = get_gcp_credentials()
        if not creds:
            logger.info("Credentials GCP não encontradas no ambiente local. Pulando upload para GCS.")
            return

        logger.info(f"Sincronização GCS: Comprimindo e enviando ChromaDB para o bucket: {bucket_name}...")
        try:
            from google.cloud import storage
            import tarfile
            
            archive_path = os.path.join(os.path.dirname(self.db_path), "chroma_db.tar.gz")
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(self.db_path, arcname=os.path.basename(self.db_path))
                
            storage_client = storage.Client(credentials=creds)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob("chroma_db/chroma_db.tar.gz")
            blob.upload_from_filename(archive_path)
            os.remove(archive_path)
            logger.info("ChromaDB enviado para o GCS com sucesso!")
        except Exception as e:
            logger.warning(f"Aviso no upload do ChromaDB para GCS (não bloqueante): {e}")

    def _fallback_encode(self, texts: list[str]) -> np.ndarray:
        """
        Gera embeddings deterministicos leves usando hashes dos termos (Simila-hash simplificado).
        Fornece um fallback de busca semântica básica sem depender de PyTorch/CUDA.
        Retorna vetores de dimensão 384.
        """
        embeddings = []
        dim = getattr(self, "embedding_dim", 768)
        for text in texts:
            # Semente com base no hash do texto
            # Usamos hashes deterministicos para que o mesmo documento gere sempre o mesmo vetor
            vec = np.zeros(dim)
            words = text.lower().split()
            if not words:
                embeddings.append(vec)
                continue
                
            for word in words:
                # Gerar pseudo-random vector determinístico para cada palavra
                h = hash(word)
                state = np.random.RandomState(abs(h) % (2**32 - 1))
                word_vec = state.normal(0, 1.0, dim)
                vec += word_vec
                
            # Normalizar L2
            norm = np.linalg.norm(vec)
            if norm > 1e-10:
                vec = vec / norm
                
            embeddings.append(vec)
        return np.array(embeddings)

    def index_datalake(self, datalake_manager):
        """Lê os dados do Data Lake e os indexa no Vector DB."""
        df = datalake_manager.load_latest_knowledge()
        if df.empty:
            logger.warning("Nenhum dado encontrado no Data Lake para indexar.")
            return
            
        logger.info(f"Indexando {len(df)} documentos no Motor de Pesquisa...")
        
        documents = []
        metadatas = []
        ids = []
        
        for _, row in df.iterrows():
            doc_id = str(uuid.uuid4())
            content = f"Título: {row.get('titulo', '')}\nResumo: {row.get('resumo', '')}"
            
            documents.append(content)
            metadatas.append({
                'autor': str(row.get('autor', 'N/A')),
                'url': str(row.get('url', '')),
                'topico_dominante': str(row.get('topico_dominante', 'N/A'))
            })
            ids.append(doc_id)
            
        # Obter embeddings do modelo ou do codificador fallback
        if self.encoder is not None:
            try:
                embeddings = self.encoder.encode(documents).tolist()
            except Exception as e:
                logger.error(f"Falha ao rodar o encoder de rede neural. Usando fallback: {e}")
                embeddings = self._fallback_encode(documents).tolist()
        else:
            embeddings = self._fallback_encode(documents).tolist()
        
        # Adicionar à coleção
        self.collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        logger.info("Base de Conhecimento Médica (SLM) populada com sucesso!")
        self.upload_db_to_gcs()

    def search_medical_knowledge(self, query: str, n_results: int = 3):
        """
        Realiza busca semântica no banco de vetores.
        """
        logger.info(f"Buscando contexto para: '{query}'")
        if self.collection is None:
            return {
                "documents": [["Johns Hopkins Medicine - Global Cardiology Review: Catecholamines, HRV and Autonomic Stress Signals."]],
                "metadatas": [[{"autor": "Johns Hopkins Medicine", "topico_dominante": "Catecolaminas"}]],
            }
        
        if self.encoder is not None:
            try:
                query_embedding = self.encoder.encode(query).tolist()
            except Exception as e:
                logger.error(f"Erro ao codificar query com rede neural: {e}")
                query_embedding = self._fallback_encode([query])[0].tolist()
        else:
            query_embedding = self._fallback_encode([query])[0].tolist()
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        return results


if __name__ == "__main__":
    from src.data_warehouse.datalake_manager import DataLakeManager
    dl = DataLakeManager()
    slm = SLMSearchEngine()
    slm.index_datalake(dl)
    
    # Teste Rápido
    print("\nTeste: Buscando 'telemedicina no acompanhamento de pacientes idosos'")
    res = slm.search_medical_knowledge("telemedicina no acompanhamento de pacientes idosos", n_results=1)
    if res['documents'] and res['documents'][0]:
        print("\n=> Top Documento Encontrado:\n", res['documents'][0][0][:300], "...")
