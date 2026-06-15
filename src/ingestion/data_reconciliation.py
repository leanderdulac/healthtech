import pandas as pd
from typing import Optional


def reconciliar_dados_biometricos(
    dados_sensores: pd.DataFrame,
    janela_tempo_segundos: int = 5
) -> pd.DataFrame:
    """
    Deduplica leituras de múltiplos sensores agrupando por janelas de tempo curtas.
    
    Args:
        dados_sensores: DataFrame com colunas ['timestamp', 'sensor_id', 'heart_rate']
        janela_tempo_segundos: Intervalo para considerar leituras como redundantes.
        
    Returns:
        DataFrame reconciliado com colunas ['timestamp', 'heart_rate_reconciliado', 'sensores_envolvidos']
        
    Raises:
        ValueError: Se o DataFrame estiver vazio ou faltar colunas obrigatórias.
    """
    if dados_sensores.empty:
        return dados_sensores
    
    # Validar colunas obrigatórias
    colunas_obrigatorias = {'timestamp', 'sensor_id', 'heart_rate'}
    if not colunas_obrigatorias.issubset(dados_sensores.columns):
        faltantes = colunas_obrigatorias - set(dados_sensores.columns)
        raise ValueError(f"Colunas obrigatórias ausentes: {faltantes}")
        
    # 1. Garantir o formato datetime
    df_trabalho = dados_sensores.copy()
    df_trabalho['timestamp'] = pd.to_datetime(df_trabalho['timestamp'], format='mixed')
    
    # 2. Ordenar cronologicamente
    df_ordenado = df_trabalho.sort_values('timestamp')
    
    # 3. Agrupar por janelas de tempo fixas e calcular a métrica reconciliada
    df_reconciliado = df_ordenado.groupby(
        pd.Grouper(key='timestamp', freq=f'{janela_tempo_segundos}s')
    ).agg(
        # Calcula a média se houver mais de uma leitura na janela
        heart_rate_reconciliado=('heart_rate', 'mean'),
        # Registra quais sensores participaram daquela janela
        sensores_envolvidos=('sensor_id', lambda x: sorted(set(x)))
    ).dropna().reset_index()
    
    # Arredondar a frequência cardíaca para int
    df_reconciliado['heart_rate_reconciliado'] = df_reconciliado['heart_rate_reconciliado'].round().astype(int)
    
    return df_reconciliado
