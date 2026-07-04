import pandas as pd

def reconciliar_dados_biometricos(dados_sensores: pd.DataFrame, janela_tempo_segundos: int = 5) -> pd.DataFrame:
    """
    Deduplica leituras de múltiplos sensores agrupando por janelas de tempo curtas.
    
    Args:
        dados_sensores: DataFrame com colunas ['timestamp', 'sensor_id', 'heart_rate']
        janela_tempo_segundos: Intervalo para considerar leituras como redundantes.
    """
    if dados_sensores.empty:
        return dados_sensores
        
    # 1. Garantir o formato datetime (otimizado)
    # Formato gerado pelo data_generator: '%Y-%m-%d %H:%M:%S' ou '%Y-%m-%d %H:%M:%S.%f'
    dados_sensores['timestamp'] = pd.to_datetime(dados_sensores['timestamp'], format='mixed')
    # 2. Ordenar cronologicamente
    df_ordenado = dados_sensores.sort_values('timestamp')
    
    # 3. Agrupar por janelas de tempo fixas e calcular a métrica reconciliada
    df_reconciliado = df_ordenado.groupby(
        pd.Grouper(key='timestamp', freq=f'{janela_tempo_segundos}s')
    ).agg(
        # Calcula a média se houver mais de uma leitura na janela
        heart_rate_reconciliado=('heart_rate', 'mean'),
        # Registra quais sensores participaram daquela janela
        sensores_envolvidos=('sensor_id', lambda x: list(set(x)))
    ).dropna().reset_index()
    
    # Arredondar a frequência cardíaca para int
    df_reconciliado['heart_rate_reconciliado'] = df_reconciliado['heart_rate_reconciliado'].round().astype(int)
    
    return df_reconciliado
