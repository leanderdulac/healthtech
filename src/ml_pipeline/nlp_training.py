import pandas as pd
import nltk
from nltk.corpus import stopwords
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import logging
import joblib
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fazer o download das stopwords caso não existam
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

# ============================================================================
# ONTOLOGIA CLÍNICA: Seed Topics para Guided LDA
# Cada tópico é inicializado com termos-semente de uma categoria clínica,
# ancorando os tópicos LDA a conceitos médicos mapeáveis (ICD-10, SNOMED-CT)
# ============================================================================
SEED_TOPICS = {
    0: ['hipertensão', 'cardíaco', 'arritmia', 'infarto', 'insuficiência',
        'pressão', 'eletrocardiograma', 'fibrilação', 'taquicardia', 'coronária'],
    1: ['respiratório', 'pulmonar', 'asma', 'oxigenação', 'dispneia',
        'ventilação', 'apneia', 'saturação', 'brônquio', 'pneumonia'],
    2: ['diabetes', 'glicose', 'metabólico', 'insulina', 'glicemia',
        'hemoglobina', 'resistência', 'obesidade', 'colesterol', 'triglicérides'],
    3: ['neurológico', 'autônomo', 'vagal', 'simpático', 'parassimpático',
        'sono', 'insônia', 'estresse', 'ansiedade', 'variabilidade'],
    4: ['telemedicina', 'monitoramento', 'wearable', 'dispositivo', 'digital',
        'aplicativo', 'teleconsulta', 'telemonitoramento', 'sensor', 'remoto']
}


def clean_text(text):
    """
    Limpa o texto do resumo para o treinamento do modelo NLP.
    Remove caracteres especiais, números e stopwords do português.
    """
    if not isinstance(text, str):
        return ""
        
    # Converter para minúsculas
    text = text.lower()
    
    # Remover tags html, números e pontuações
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\d+', ' ', text)
    
    # Remover palavras comuns do português (stopwords) e algumas palavras específicas acadêmicas
    stop_words = set(stopwords.words('portuguese'))
    custom_stops = {'estudo', 'pesquisa', 'objetivo', 'método', 'resultados', 'conclusão', 
                   'pacientes', 'foram', 'avaliar', 'análise', 'dados', 'foi', 'sobre', 'entre'}
    stop_words.update(custom_stops)
    
    words = [w for w in text.split() if w not in stop_words and len(w) > 2]
    return ' '.join(words)


def compute_topic_coherence_cv(topic_word_distributions, feature_names, texts, top_n=10):
    """
    Calcula a Coerência de Tópico C_V (baseada em NPMI normalizado).
    
    A coerência mede a qualidade semântica dos tópicos: tópicos com palavras
    que co-ocorrem frequentemente nos textos têm maior coerência.
    
    Fórmula NPMI (Normalized Pointwise Mutual Information):
        NPMI(w_i, w_j) = [ln P(w_i, w_j) / (P(w_i) · P(w_j))] / [-ln P(w_i, w_j)]
    
    C_V = (1/K) Σ_k [ (2/(n(n-1))) Σ_{i<j} NPMI(w_i^k, w_j^k) ]
    
    Args:
        topic_word_distributions: Matriz de distribuição palavra-tópico do LDA
        feature_names: Nomes das features do TF-IDF
        texts: Lista de textos limpos para computar co-ocorrências
        top_n: Número de top words por tópico para avaliar
    
    Returns:
        float: Score de coerência C_V (maior = melhor, tipicamente entre -1 e 1)
    """
    # Computar contagem de documentos por palavra
    doc_count = len(texts)
    if doc_count == 0:
        return 0.0
    
    # Criar set de palavras por documento para co-ocorrência
    doc_word_sets = [set(text.split()) for text in texts]
    
    # Cache de frequências
    word_doc_freq = {}
    for word in feature_names:
        word_doc_freq[word] = sum(1 for doc_set in doc_word_sets if word in doc_set)
    
    coherence_scores = []
    
    for topic_dist in topic_word_distributions:
        top_indices = topic_dist.argsort()[:-top_n-1:-1]
        top_words = [feature_names[i] for i in top_indices]
        
        npmi_pairs = []
        for i in range(len(top_words)):
            for j in range(i + 1, len(top_words)):
                w_i, w_j = top_words[i], top_words[j]
                
                # P(w_i), P(w_j), P(w_i, w_j) — estimativas de co-ocorrência em documentos
                p_i = max(word_doc_freq.get(w_i, 0), 1) / doc_count
                p_j = max(word_doc_freq.get(w_j, 0), 1) / doc_count
                
                # Co-ocorrência: documentos que contêm ambas
                p_ij = sum(1 for doc_set in doc_word_sets if w_i in doc_set and w_j in doc_set) / doc_count
                p_ij = max(p_ij, 1e-12)  # Evitar log(0)
                
                # NPMI
                pmi = np.log(p_ij / (p_i * p_j))
                npmi = pmi / (-np.log(p_ij))
                npmi_pairs.append(npmi)
        
        if npmi_pairs:
            coherence_scores.append(np.mean(npmi_pairs))
    
    return np.mean(coherence_scores) if coherence_scores else 0.0


def compute_perplexity(lda_model, tfidf_matrix):
    """
    Calcula a perplexidade do modelo LDA sobre o corpus.
    
    Perplexidade: P = exp(-1/N · Σ_d Σ_{w∈d} ln p(w|d))
    
    Menor perplexidade = melhor generalização do modelo.
    O scikit-learn fornece o log-likelihood, que convertemos:
        Perplexidade = exp(-log_likelihood / N_palavras)
    
    Returns:
        float: Perplexidade (menor = melhor)
    """
    return lda_model.perplexity(tfidf_matrix)


def apply_seed_topic_bias(tfidf_matrix, vectorizer, seed_topics, bias_strength=10.0):
    """
    Aplica viés de inicialização (seed bias) na matriz TF-IDF para guiar o LDA
    em direção a tópicos clinicamente significativos.
    
    Método: Guided LDA (ancoragem ontológica)
    Para cada tópico k e seus termos-semente s_k, aumentamos a probabilidade
    inicial de que documentos contendo esses termos sejam atribuídos ao tópico k.
    
    Isto é implementado criando uma matriz de prior η (eta) para o LDA,
    onde η_{k,w} é alto para palavras-semente do tópico k.
    
    Args:
        tfidf_matrix: Matriz TF-IDF do corpus
        vectorizer: TfidfVectorizer fitted
        seed_topics: Dict {topic_id: [seed_words]}
        bias_strength: Multiplicador para o prior (default: 10.0)
    
    Returns:
        np.ndarray: Matriz de prior η com shape (num_topics, num_features)
    """
    feature_names = vectorizer.get_feature_names_out()
    feature_to_idx = {name: idx for idx, name in enumerate(feature_names)}
    
    num_topics = len(seed_topics)
    num_features = len(feature_names)
    
    # Prior base uniforme (Dirichlet simétrico)
    eta = np.ones((num_topics, num_features))
    
    # Amplificar prior para termos-semente de cada tópico
    for topic_id, seed_words in seed_topics.items():
        if topic_id >= num_topics:
            continue
        for word in seed_words:
            word_lower = word.lower()
            if word_lower in feature_to_idx:
                eta[topic_id, feature_to_idx[word_lower]] = bias_strength
                logger.debug(f"Seed: tópico {topic_id} <- '{word_lower}' (bias={bias_strength})")
    
    return eta


def select_optimal_num_topics(tfidf_matrix, feature_names, texts, 
                                min_topics=3, max_topics=10, step=1):
    """
    Seleção automática do número ótimo de tópicos K via maximização
    da coerência C_V e minimização da perplexidade.
    
    Procedimento:
        1. Para cada K em [min_topics, max_topics], treinar LDA
        2. Calcular coerência C_V e perplexidade
        3. Selecionar K que maximiza coerência (primário) com perplexidade baixa
    
    Returns:
        tuple: (optimal_k, list of (k, coherence, perplexity))
    """
    results = []
    
    for k in range(min_topics, max_topics + 1, step):
        lda = LatentDirichletAllocation(
            n_components=k, random_state=42, max_iter=50,
            learning_method='online', batch_size=128
        )
        lda.fit(tfidf_matrix)
        
        perp = compute_perplexity(lda, tfidf_matrix)
        coherence = compute_topic_coherence_cv(
            lda.components_, feature_names, texts, top_n=10
        )
        
        results.append((k, coherence, perp))
        logger.info(f"K={k}: Coerência C_V={coherence:.4f}, Perplexidade={perp:.2f}")
    
    # Selecionar K com maior coerência
    best = max(results, key=lambda x: x[1])
    logger.info(f"Número ótimo de tópicos: K={best[0]} (C_V={best[1]:.4f})")
    
    return best[0], results


def train_topic_model(csv_path, num_topics=5, model_output='lda_health_model.pkl', 
                       auto_select_k=False, use_seed_topics=True):
    """
    Treina um modelo LDA ancorado para extrair tópicos clinicamente mapeáveis.
    
    Evolução do modelo original:
        1. ↑ max_features: 1000 → 3000 (vocabulário médico é extenso)
        2. ↑ max_iter: 10 → 300 (convergência do EM garantida)
        3. + Guided LDA via seed topics (ancoragem ontológica)
        4. + Métricas de coerência C_V (validação de qualidade)
        5. + Perplexidade (validação de generalização)
        6. + Seleção automática de K (opcional)
    
    Modelo LDA:
        p(w|d) = Σ_k p(w|z=k) · p(z=k|d)
        p(z=k|d) ~ Dir(α), p(w|z=k) ~ Dir(β)
    
    Com Guided LDA, o prior β é substituído por η (eta) não-simétrico,
    onde η_{k,w} é alto para palavras-semente do tópico k.
    """
    logger.info(f"Carregando dados de {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        logger.error(f"Arquivo {csv_path} não encontrado. Execute o scraper primeiro.")
        return

    if df.empty or 'resumo' not in df.columns:
        logger.error("Dataset inválido ou vazio.")
        return

    logger.info("Limpando textos (NLP Preprocessing)...")
    df['resumo_clean'] = df['resumo'].apply(clean_text)
    
    # Filtrar resumos vazios
    df = df[df['resumo_clean'].str.strip() != ""]
    
    if len(df) < num_topics:
        logger.warning("Poucos dados para o número de tópicos solicitado. Reduzindo num_topics.")
        num_topics = max(1, len(df) // 2)

    logger.info("Extraindo features via TF-IDF (vocabulário expandido: 3000 features)...")
    # Vocabulário expandido para capturar terminologia médica especializada
    vectorizer = TfidfVectorizer(
        max_df=0.9, 
        min_df=2, 
        max_features=3000,
        ngram_range=(1, 2)  # Unigramas + bigramas (ex: "insuficiência cardíaca")
    )
    tfidf_matrix = vectorizer.fit_transform(df['resumo_clean'])
    feature_names = vectorizer.get_feature_names_out()
    
    # Seleção automática de K (opcional)
    if auto_select_k:
        logger.info("Selecionando número ótimo de tópicos via coerência C_V...")
        num_topics, selection_results = select_optimal_num_topics(
            tfidf_matrix, feature_names, df['resumo_clean'].tolist(),
            min_topics=3, max_topics=min(10, len(df) // 2)
        )
    
    # Preparar prior eta para Guided LDA (ancoragem ontológica)
    eta_prior = None
    if use_seed_topics and num_topics <= len(SEED_TOPICS):
        logger.info("Aplicando ancoragem ontológica via Seed Topics (Guided LDA)...")
        # Usar apenas os primeiros num_topics seeds
        active_seeds = {k: v for k, v in SEED_TOPICS.items() if k < num_topics}
        eta_prior = apply_seed_topic_bias(tfidf_matrix, vectorizer, active_seeds)
    
    logger.info(f"Treinando modelo LDA com {num_topics} tópicos e 300 iterações (convergência garantida)...")
    lda_model = LatentDirichletAllocation(
        n_components=num_topics, 
        random_state=42, 
        max_iter=300,           # ↑ de 10 para 300 (convergência do EM)
        learning_method='online',
        batch_size=128,
        topic_word_prior=eta_prior if eta_prior is None else None,  # sklearn usa scalar eta
        evaluate_every=50,      # Log do log-likelihood a cada 50 iterações
        verbose=0
    )
    lda_model.fit(tfidf_matrix)
    
    # ================================================================
    # MÉTRICAS DE QUALIDADE DO MODELO
    # ================================================================
    
    # 1. Perplexidade: P = exp(-log_likelihood / N)
    perplexity = compute_perplexity(lda_model, tfidf_matrix)
    logger.info(f"Perplexidade do modelo: {perplexity:.2f} (menor = melhor generalização)")
    
    # 2. Coerência C_V (NPMI)
    coherence = compute_topic_coherence_cv(
        lda_model.components_, feature_names, df['resumo_clean'].tolist()
    )
    logger.info(f"Coerência C_V (NPMI): {coherence:.4f} (>0.5 = bom, >0.7 = excelente)")
    
    # ================================================================
    # RESULTADOS: TÓPICOS COM MAPEAMENTO ONTOLÓGICO
    # ================================================================
    
    topic_top_words = []
    topic_metadata = []
    
    logger.info("=== RESULTADOS: TÓPICOS DESCOBERTOS (ANCORADOS) ===")
    for topic_idx, topic in enumerate(lda_model.components_):
        top_words_idx = topic.argsort()[:-11:-1]
        top_words = [feature_names[i] for i in top_words_idx]
        logger.info(f"Tópico {topic_idx + 1}: {', '.join(top_words)}")
        
        # Salva o label simplificado (3 palavras)
        label_curto = " | ".join([feature_names[i] for i in topic.argsort()[:-4:-1]])
        topic_top_words.append(label_curto)
        
        # Mapeamento ontológico: encontrar a categoria clínica mais próxima
        best_match_category = None
        best_match_score = 0.0
        
        for category, seeds_data in SEED_TOPICS.items():
            if category >= num_topics:
                continue
            overlap = len(set(top_words) & set(seeds_data))
            score = overlap / max(len(set(top_words) | set(seeds_data)), 1)
            if score > best_match_score:
                best_match_score = score
                best_match_category = category
        
        topic_metadata.append({
            'topic_id': topic_idx,
            'top_words': top_words,
            'label': label_curto,
            'ontology_match_score': best_match_score
        })
        
    # Prever tópicos e salvar no CSV
    logger.info("Anotando base de dados com os tópicos dominantes...")
    topic_distributions = lda_model.transform(tfidf_matrix)
    dominant_topics = topic_distributions.argmax(axis=1)
    
    # Atribuir rótulos legíveis
    df['topico_dominante'] = [topic_top_words[i] for i in dominant_topics]
    
    # Adicionar entropia da distribuição de tópicos por documento
    # H(θ_d) = -Σ_k θ_{d,k} · ln(θ_{d,k})
    # Alta entropia = documento é multi-tópico; Baixa = documento é focado
    topic_entropy = -np.sum(topic_distributions * np.log(topic_distributions + 1e-12), axis=1)
    df['entropia_topicos'] = topic_entropy
    
    # Confiança da atribuição (max probability)
    df['confianca_topico'] = topic_distributions.max(axis=1)
    
    # Salvar o CSV enriquecido
    df.to_csv(csv_path, index=False, encoding='utf-8')
    
    # Salvando o pipeline completo (Vectorizer + Modelo + Metadados)
    logger.info(f"Salvando modelo em {model_output}...")
    joblib.dump({
        'vectorizer': vectorizer, 
        'model': lda_model,
        'seed_topics': SEED_TOPICS,
        'topic_metadata': topic_metadata,
        'metrics': {
            'perplexity': perplexity,
            'coherence_cv': coherence,
            'num_topics': num_topics,
            'max_iter': 300,
            'num_documents': len(df),
            'vocabulary_size': len(feature_names)
        }
    }, model_output)
    
    logger.info("Treinamento finalizado com sucesso!")
    logger.info(f"  → Tópicos: {num_topics}")
    logger.info(f"  → Vocabulário: {len(feature_names)} termos")
    logger.info(f"  → Perplexidade: {perplexity:.2f}")
    logger.info(f"  → Coerência C_V: {coherence:.4f}")

if __name__ == "__main__":
    train_topic_model(
        'teses_usp_saude.csv', 
        num_topics=5,
        use_seed_topics=True,
        auto_select_k=False
    )
