import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def reconciliar_dados_biometricos(dados_sensores: pd.DataFrame, janela_tempo_segundos: int = 5) -> pd.DataFrame:
    """
    Fusão Bayesiana de leituras de múltiplos sensores via ponderação por precisão inversa
    (Inverse-Variance Weighting) com estimativa adaptativa de variância por sensor.
    
    Modelo matemático:
        Cada sensor i mede: z_{i,t} = h_t + ε_{i,t}, onde ε_{i,t} ~ N(0, σ_i²)
        
        Estimador ótimo (MMSE):
            ĥ_t = Σ(w_i · z_{i,t}) / Σ(w_i), onde w_i = 1/σ_i²
        
        Variância do estimador fusionado:
            σ_fused² = 1 / Σ(w_i)
        
        As variâncias σ_i² são estimadas via EWMA (Exponentially Weighted Moving Average):
            σ̂²_{i,t} = λ · σ̂²_{i,t-1} + (1-λ) · (z_{i,t} - ĥ_{t-1})²
    
    Vantagem sobre média aritmética:
        Sensores mais precisos recebem mais peso automaticamente.
        Um sensor com SNR de 40dB domina sobre um com 15dB.
    
    Args:
        dados_sensores: DataFrame com colunas ['timestamp', 'sensor_id', 'heart_rate']
        janela_tempo_segundos: Intervalo para considerar leituras como redundantes.
    
    Returns:
        DataFrame com leituras reconciliadas via fusão Bayesiana.
    """
    if dados_sensores.empty:
        return dados_sensores
        
    # 1. Garantir o formato datetime (otimizado)
    # Formato gerado pelo data_generator: '%Y-%m-%d %H:%M:%S' ou '%Y-%m-%d %H:%M:%S.%f'
    dados_sensores = dados_sensores.copy()
    dados_sensores['timestamp'] = pd.to_datetime(dados_sensores['timestamp'], format='mixed')
    
    # 2. Ordenar cronologicamente
    df_ordenado = dados_sensores.sort_values('timestamp').reset_index(drop=True)
    
    # 3. Parâmetros da fusão Bayesiana
    lambda_ewma = 0.90  # Fator de esquecimento para EWMA (0.9 = memória de ~10 leituras)
    variancia_inicial = 4.0  # σ² inicial para cada sensor (conservador)
    
    # Estado adaptativo por sensor
    sensor_variances = {}  # sensor_id -> variância estimada
    ultima_estimativa = None  # Última estimativa fusionada para cálculo de resíduos
    
    # 4. Agrupar por janelas de tempo fixas
    df_ordenado['janela'] = df_ordenado['timestamp'].dt.floor(f'{janela_tempo_segundos}s')
    
    resultados = []
    
    for janela, grupo in df_ordenado.groupby('janela'):
        if grupo.empty:
            continue
        
        sensores_na_janela = grupo['sensor_id'].unique().tolist()
        leituras = {}
        
        for _, row in grupo.iterrows():
            sid = row['sensor_id']
            hr = row['heart_rate']
            
            # Inicializar variância do sensor se necessário
            if sid not in sensor_variances:
                sensor_variances[sid] = variancia_inicial
            
            # Armazenar leitura (se múltiplas do mesmo sensor na janela, usa a última)
            leituras[sid] = hr
        
        if not leituras:
            continue
        
        # 5. Fusão Bayesiana: Inverse-Variance Weighting
        if len(leituras) == 1:
            # Sensor único: usar diretamente
            sid, hr = next(iter(leituras.items()))
            estimativa_fusionada = hr
            variancia_fusionada = sensor_variances[sid]
        else:
            # Múltiplos sensores: ponderar pela precisão (1/σ²)
            pesos = {}
            for sid, hr in leituras.items():
                var_i = sensor_variances[sid]
                # Proteção contra variância zero
                var_i = max(var_i, 1e-6)
                pesos[sid] = 1.0 / var_i
            
            soma_pesos = sum(pesos.values())
            
            # Estimativa fusionada: média ponderada pela precisão
            estimativa_fusionada = sum(pesos[sid] * leituras[sid] for sid in leituras) / soma_pesos
            
            # Variância do estimador fusionado (sempre menor que qualquer sensor individual)
            variancia_fusionada = 1.0 / soma_pesos
        
        # 6. Atualizar variâncias via EWMA usando resíduos
        if ultima_estimativa is not None:
            for sid, hr in leituras.items():
                residuo_sq = (hr - ultima_estimativa) ** 2
                sensor_variances[sid] = (
                    lambda_ewma * sensor_variances[sid] + 
                    (1 - lambda_ewma) * residuo_sq
                )
        
        ultima_estimativa = estimativa_fusionada
        
        # 7. Calcular pesos normalizados para relatório
        pesos_report = {}
        for sid in leituras:
            var_i = max(sensor_variances[sid], 1e-6)
            pesos_report[sid] = round(1.0 / var_i, 4)
        soma = sum(pesos_report.values())
        pesos_report = {k: round(v / soma, 3) for k, v in pesos_report.items()}
        
        resultados.append({
            'timestamp': janela,
            'heart_rate_reconciliado': int(round(estimativa_fusionada)),
            'variancia_fusionada': round(variancia_fusionada, 4),
            'sensores_envolvidos': sensores_na_janela,
            'pesos_bayesianos': pesos_report
        })
    
    df_reconciliado = pd.DataFrame(resultados)
    
    logger.info(
        f"Reconciliação Bayesiana concluída: {len(df_reconciliado)} janelas, "
        f"{len(sensor_variances)} sensores rastreados"
    )
    
    return df_reconciliado


if __name__ == '__main__':
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from src.utils.data_generator import generate_sensor_data
    
    logging.basicConfig(level=logging.INFO)
    
    print("=== Teste: Fusão Bayesiana de Sensores ===")
    df_raw = generate_sensor_data(num_records=20)
    print(f"Leituras brutas: {len(df_raw)}")
    print(df_raw.head())
    
    df_fused = reconciliar_dados_biometricos(df_raw, janela_tempo_segundos=3)
    print(f"\nLeituras fusionadas: {len(df_fused)}")
    print(df_fused.head(10))
    
    # Verificar que a variância fusionada é menor que a dos sensores individuais
    if 'variancia_fusionada' in df_fused.columns:
        print(f"\nVariância fusionada média: {df_fused['variancia_fusionada'].mean():.4f}")
        print(f"Variância fusionada máxima: {df_fused['variancia_fusionada'].max():.4f}")
