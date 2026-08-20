# Modelos locais

Os pesos (`.pkl`, `.pt`, `.joblib`) **não são versionados**. São gerados no treino:

```bash
python run_alert_matrix_training.py
python run_temporal_training.py
```

A matriz de alertas funciona só com regras se o classificador não estiver neste diretório.

JSON de metadados (`*_meta.json`, `alert_matrix_rules.json`, `temporal_scaler.json`) permanece no git.
