"""
HealthCausal-Engine: Sistema Enterprise de IA Médica com Especialistas por Domínio
e Motor de Inferência Causal para Previsão de Eventos em Cascata.

Autor: Engenheiro de Dados & ML Specialist (GCP HealthTech)
Arquitetura: Multi-Model Ensemble + Causal Graph Inference
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from datetime import datetime, timedelta
import logging
from scipy import stats
from collections import deque

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("HealthCausalEngine")

# ==============================================================================
# 1. DEFINIÇÕES DE DOMÍNIO E ESTRUTURAS DE DADOS
# ==============================================================================

class VitalSignType(Enum):
    HEART_RATE = "heart_rate"
    BLOOD_PRESSURE_SYS = "bp_sys"
    BLOOD_PRESSURE_DIA = "bp_dia"
    GLUCOSE = "glucose"
    SPO2 = "spo2"
    RESPIRATORY_RATE = "resp_rate"
    TEMPERATURE = "temperature"
    ECG_RHYTHM = "ecg_rhythm"

class AlertSeverity(Enum):
    NORMAL = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    LIFE_THREATENING = 5

@dataclass
class PatientContext:
    patient_id: str
    age: int
    gender: str
    history: Dict[str, bool] = field(default_factory=dict)  # ex: {"diabetes": True, "hypertension": False}
    baseline_metrics: Dict[str, float] = field(default_factory=dict)
    
@dataclass
class ClinicalEvent:
    timestamp: datetime
    patient_id: str
    source_module: str
    severity: AlertSeverity
    prediction: str
    confidence: float
    contributing_factors: Dict[str, float]
    causal_chain: List[str] = field(default_factory=list)

# ==============================================================================
# 2. ALGORITMOS ESPECIALISTAS (ONE-ALGORITHM-PER-METRIC)
# ==============================================================================

class BaseSpecialist:
    """Classe base para todos os especialistas médicos."""
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"Specialist.{name}")

    def analyze(self, current_value: float, history: deque, context: PatientContext) -> Tuple[float, str, Dict]:
        raise NotImplementedError

class CardiacSpecialist(BaseSpecialist):
    """
    Algoritmo especializado em Batimento Cardíaco e Infarto.
    Usa HRV (Heart Rate Variability), detecção de taquicardia/bradicardia e padrões de ischemia.
    """
    def __init__(self):
        super().__init__("Cardiac_Infarct_Proxy")
        self.hr_threshold_high = 100
        self.hr_threshold_low = 50
        self.hrv_window = 20

    def analyze(self, current_hr: float, history: deque, context: PatientContext) -> Tuple[float, str, Dict]:
        if len(history) < 5:
            return 0.0, "NORMAL", {}

        hist_arr = np.array(list(history))
        
        # 1. Detecção de Extremos Absolutos
        risk_score = 0.0
        factors = {}
        
        if current_hr > 140:
            risk_score += 0.4
            factors["tachycardia_extreme"] = 1.0
        elif current_hr > 110:
            risk_score += 0.2
            factors["tachycardia_moderate"] = 1.0
            
        if current_hr < 40:
            risk_score += 0.5
            factors["bradycardia_critical"] = 1.0

        # 2. Análise de HRV (Desvio Padrão dos NN intervals - proxy simplificado)
        hrv = np.std(hist_arr[-self.hrv_window:]) if len(hist_arr) >= self.hrv_window else 0
        if hrv < 10: # Baixa variabilidade indica estresse ou infarto iminente
            risk_score += 0.3
            factors["low_hrv"] = 1.0
        
        # 3. Tendência súbita (Slope detection)
        if len(hist_arr) > 3:
            slope = hist_arr[-1] - hist_arr[-4]
            if slope > 30: # Aumento de 30bpm em pouco tempo
                risk_score += 0.3
                factors["rapid_onset"] = 1.0

        # Normalização do score (0-1)
        final_score = min(risk_score, 1.0)
        
        diagnosis = "NORMAL"
        if final_score > 0.7:
            diagnosis = "ACUTE_MI_RISK" # Infarto Agudo do Miocárdio
        elif final_score > 0.4:
            diagnosis = "ARRHYTHMIA_DETECTED"
            
        return final_score, diagnosis, factors

class HemodynamicSpecialist(BaseSpecialist):
    """
    Algoritmo especializado em Pressão Arterial.
    Detecta crise hipertensiva, hipotensão ortostática e risco de choque.
    """
    def __init__(self):
        super().__init__("Hemodynamic_Pressure_Proxy")

    def analyze(self, sys: float, dia: float, history_sys: deque, context: PatientContext) -> Tuple[float, str, Dict]:
        risk_score = 0.0
        factors = {}

        # 1. Crise Hipertensiva (MAP e Valores Absolutos)
        map_val = dia + (sys - dia) / 3 # Pressão Arterial Média
        
        if sys > 180 or dia > 120:
            risk_score += 0.5
            factors["hypertensive_crisis"] = 1.0
        elif sys > 160:
            risk_score += 0.2
            factors["stage2_hypertension"] = 1.0

        # 2. Hipotensão de Choque
        if sys < 90 or map_val < 65:
            risk_score += 0.6
            factors["shock_risk"] = 1.0

        # 3. Pressão de Pulso Estreita (Indicador de tamponamento ou perda sanguínea)
        pulse_pressure = sys - dia
        if pulse_pressure < 25:
            risk_score += 0.3
            factors["narrow_pulse_pressure"] = 1.0

        final_score = min(risk_score, 1.0)
        diagnosis = "NORMAL"
        if final_score > 0.6:
            diagnosis = "HEMODYNAMIC_INSTABILITY"
        elif final_score > 0.3:
            diagnosis = "BP_ANOMALY"

        return final_score, diagnosis, factors

class MetabolicSpecialist(BaseSpecialist):
    """
    Algoritmo especializado em Diabetes e Glicose.
    Prevê hipoglicemia severa e cetoacidose baseada em tendências.
    """
    def __init__(self):
        super().__init__("Metabolic_Diabetes_Proxy")

    def analyze(self, glucose: float, history: deque, context: PatientContext) -> Tuple[float, str, Dict]:
        risk_score = 0.0
        factors = {}

        # 1. Hipoglicemia Crítica
        if glucose < 50:
            risk_score += 0.8
            factors["severe_hypoglycemia"] = 1.0
        elif glucose < 70:
            risk_score += 0.4
            factors["hypoglycemia"] = 1.0

        # 2. Hiperglicemia / Cetoacidose Risk
        if glucose > 400:
            risk_score += 0.7
            factors["hyperglycemic_crisis"] = 1.0
        elif glucose > 250:
            risk_score += 0.3
            factors["hyperglycemia"] = 1.0

        # 3. Volatilidade (Rate of Change)
        if len(history) > 2:
            hist_arr = np.array(list(history))
            roc = (hist_arr[-1] - hist_arr[-2]) / 15 # mg/dL por minuto (assumindo 15min)
            if roc < -3.0: # Queda rápida
                risk_score += 0.3
                factors["rapid_glucose_drop"] = 1.0
        
        final_score = min(risk_score, 1.0)
        diagnosis = "NORMAL"
        if final_score > 0.6:
            diagnosis = "METABOLIC_EMERGENCY"
        elif final_score > 0.3:
            diagnosis = "GLUCOSE_INSTABILITY"

        return final_score, diagnosis, factors

class NeurovascularSpecialist(BaseSpecialist):
    """
    Algoritmo Proxy para AVC (Stroke).
    Combina PA, irregularidade cardíaca (FA) e sinais neurológicos (simulados).
    """
    def __init__(self):
        super().__init__("Neuro_Stroke_Proxy")

    def analyze(self, inputs: Dict[str, float], context: PatientContext) -> Tuple[float, str, Dict]:
        risk_score = 0.0
        factors = {}
        
        sys = inputs.get('bp_sys', 120)
        hr = inputs.get('heart_rate', 80)
        irregular_hr = inputs.get('hr_irregularity', 0.0) # 0 a 1

        # 1. Hipertensão Severa + Idade
        if sys > 160 and context.age > 60:
            risk_score += 0.3
            factors["htn_age_factor"] = 1.0

        # 2. Fibrilação Atrial Proxy (HR irregular)
        if irregular_hr > 0.6:
            risk_score += 0.4
            factors["afib_proxy"] = irregular_hr

        # 3. Histórico de AVC
        if context.history.get('prior_stroke', False):
            risk_score += 0.2
            factors["history_factor"] = 1.0

        final_score = min(risk_score, 1.0)
        diagnosis = "NORMAL"
        if final_score > 0.6:
            diagnosis = "HIGH_STROKE_PROBABILITY"
        elif final_score > 0.3:
            diagnosis = "STROKE_WATCH"

        return final_score, diagnosis, factors

# ==============================================================================
# 3. PROXY DE VALIDAÇÃO CRUZADA (ANTI-FALSE POSITIVE)
# ==============================================================================

class CrossValidationProxy:
    """
    Atua como um filtro de ruído. Verifica se os sinais vitais são fisiologicamente coerentes.
    Ex: HR alto deveria baixar SpO2 ou aumentar RR. Se não, é ruído do sensor.
    """
    def __init__(self):
        self.logger = logging.getLogger("CrossValidationProxy")

    def validate_coherence(self, vitals: Dict[str, float]) -> Tuple[bool, float, List[str]]:
        """
        Retorna: (Is_Valid, Confidence_Score, List_of_Incoherences)
        """
        incoherences = []
        penalty = 0.0

        hr = vitals.get('heart_rate', 80)
        spo2 = vitals.get('spo2', 98)
        rr = vitals.get('resp_rate', 16)
        bp_sys = vitals.get('bp_sys', 120)

        # Regra 1: Taquicardia extrema sem dessaturação ou taquipneia é suspeita
        if hr > 150 and spo2 > 95 and rr < 20:
            incoherences.append("Tachycardia without hypoxia/tachypnea")
            penalty += 0.4

        # Regra 2: Hipotensão severa sem taquicardia compensatória (exceto em beta-bloqueados)
        if bp_sys < 80 and hr < 90:
            # Pode ser choque neurogênico ou erro, mas reduz confiança se não houver contexto
            incoherences.append("Hypotension without compensatory tachycardia")
            penalty += 0.3

        # Regra 3: SpO2 baixo (<80%) com FC normal é fisicamente improvável a longo prazo
        if spo2 < 80 and 60 < hr < 100:
            incoherences.append("Severe hypoxia with normal HR")
            penalty += 0.5

        confidence = max(0.0, 1.0 - penalty)
        is_valid = confidence > 0.6

        if not is_valid:
            self.logger.warning(f"Incoherence detected: {incoherences}. Confidence reduced to {confidence:.2f}")

        return is_valid, confidence, incoherences

# ==============================================================================
# 4. MOTOR DE INFERÊNCIA CAUSAL (THE MERGER)
# ==============================================================================

class CausalInferenceEngine:
    """
    O 'Cérebro' do sistema. Mescla os outputs dos especialistas e calcula efeitos em cascata.
    Usa uma matriz de adjacência ponderada para simular a fisiologia humana.
    """
    def __init__(self):
        self.logger = logging.getLogger("CausalEngine")
        # Matriz de impacto: [Origem] -> [Destino] = Peso do impacto (0-1)
        # Ex: Se Pressão sobe, impacta Risco AVC em 0.8 e Risco Infarto em 0.6
        self.causal_graph = {
            'bp_sys': {'stroke_risk': 0.8, 'cardiac_risk': 0.6, 'renal_risk': 0.5},
            'heart_rate': {'cardiac_risk': 0.9, 'stroke_risk': 0.4, 'metabolic_demand': 0.7},
            'glucose': {'neuro_risk': 0.7, 'cardiac_risk': 0.3, 'infection_risk': 0.4},
            'spo2': {'cardiac_risk': 0.8, 'neuro_risk': 0.9, 'organ_failure': 0.8}
        }
        
        # Limiares de ativação de cascata
        self.cascade_threshold = 0.5

    def predict_cascade(self, current_vitals: Dict[str, float], specialist_scores: Dict[str, float]) -> Dict[str, Any]:
        """
        Calcula o efeito dominó. Se um item sobe, o que acontece com os outros?
        """
        cascade_effects = {}
        critical_path = []

        # 1. Identificar gatilhos atuais
        triggers = {k: v for k, v in specialist_scores.items() if v > self.cascade_threshold}

        if not triggers:
            return {"status": "STABLE", "effects": {}, "path": [], "predicted_next_event": None}

        # 2. Propagação no Grafo
        total_risk_accumulation = 0.0
        
        for trigger_metric, score in triggers.items():
            if trigger_metric in self.causal_graph:
                impacts = self.causal_graph[trigger_metric]
                for target, weight in impacts.items():
                    impact_value = score * weight
                    if target not in cascade_effects:
                        cascade_effects[target] = 0.0
                    
                    # Acumula risco se múltiplos fatores afetam o mesmo alvo
                    cascade_effects[target] = max(cascade_effects[target], impact_value)
                    
                    if impact_value > 0.6:
                        critical_path.append(f"{trigger_metric} ↑ → {target} CRITICAL ({impact_value:.2f})")

        # 3. Determinar o pior cenário provável
        max_risk_target = max(cascade_effects, key=cascade_effects.get) if cascade_effects else None
        max_risk_val = cascade_effects.get(max_risk_target, 0)

        result = {
            "status": "CRITICAL_CHAIN" if max_risk_val > 0.7 else "WATCH",
            "primary_trigger": list(triggers.keys())[0],
            "predicted_next_event": max_risk_target,
            "probability": max_risk_val,
            "causal_chain": critical_path,
            "recommendation": self._generate_recommendation(max_risk_target, max_risk_val) if max_risk_target else "MONITORAR CONTINUAMENTE"
        }
        
        return result

    def _generate_recommendation(self, target: str, risk: float) -> str:
        recs = {
            'stroke_risk': "ADMINISTER ANTIHYPERTENSIVES IMMEDIATELY. PREPARE CT SCAN.",
            'cardiac_risk': "PERFORM 12-LEAD ECG. CHECK TROPONIN. PREPARE CATH LAB.",
            'neuro_risk': "CHECK GLUCOSE. AIRWAY MANAGEMENT. NEURO CONSULT.",
            'organ_failure': "INITIATE SEPSIS PROTOCOL. SUPPORTIVE CARE."
        }
        return recs.get(target, "CONTINUE MONITORING. REASSESS IN 5 MIN.")

# ==============================================================================
# 5. ORQUESTRADOR PRINCIPAL (FACADE PATTERN)
# ==============================================================================

class HealthCausalOrchestrator:
    def __init__(self):
        self.logger = logging.getLogger("HealthCausalOrchestrator")
        self.cardiac = CardiacSpecialist()
        self.hemo = HemodynamicSpecialist()
        self.metabolic = MetabolicSpecialist()
        self.neuro = NeurovascularSpecialist()
        
        self.validator = CrossValidationProxy()
        self.causal_engine = CausalInferenceEngine()
        
        # Buffers de histórico por paciente
        self.patient_history: Dict[str, Dict[str, deque]] = {}
        self.max_history_len = 50

    def get_patient_buffer(self, pid: str) -> Dict[str, deque]:
        if pid not in self.patient_history:
            self.patient_history[pid] = {
                'hr': deque(maxlen=self.max_history_len),
                'bp_sys': deque(maxlen=self.max_history_len),
                'bp_dia': deque(maxlen=self.max_history_len),
                'glucose': deque(maxlen=self.max_history_len),
                'spo2': deque(maxlen=self.max_history_len)
            }
        return self.patient_history[pid]

    def process_stream(self, patient: PatientContext, vitals: Dict[str, float]) -> Optional[ClinicalEvent]:
        """
        Fluxo principal de ingestão e decisão.
        """
        pid = patient.patient_id
        buffers = self.get_patient_buffer(pid)
        
        # 1. Atualizar Buffers
        for k, v in vitals.items():
            if k in buffers:
                buffers[k].append(v)

        # 2. Validação Cruzada (Filtro de Ruído)
        is_valid, coherence_conf, incoherences = self.validator.validate_coherence(vitals)
        if not is_valid:
            logger.warning(f"[{pid}] Dados incoerentes detectados. Alertas suprimidos parcialmente.")
            # Não paramos o processo, mas reduzimos a confiança dos alertas

        # 3. Executar Especialistas
        scores = {}
        diagnoses = {}
        all_factors = {}

        # Cardíaco
        s, d, f = self.cardiac.analyze(vitals['heart_rate'], buffers['hr'], patient)
        scores['cardiac_risk'] = s * coherence_conf
        diagnoses['cardiac'] = d
        all_factors.update(f)

        # Hemodinâmico
        s, d, f = self.hemo.analyze(vitals['bp_sys'], vitals['bp_dia'], buffers['bp_sys'], patient)
        scores['hemodynamic_risk'] = s * coherence_conf
        diagnoses['hemodynamic'] = d
        all_factors.update(f)

        # Metabólico
        if 'glucose' in vitals:
            s, d, f = self.metabolic.analyze(vitals['glucose'], buffers['glucose'], patient)
            scores['metabolic_risk'] = s * coherence_conf
            diagnoses['metabolic'] = d
            all_factors.update(f)

        # Neuro (AVC) - Requer inputs compostos
        neuro_inputs = {
            'bp_sys': vitals['bp_sys'],
            'heart_rate': vitals['heart_rate'],
            'hr_irregularity': np.std(list(buffers['hr'])) / (np.mean(buffers['hr']) + 1e-5) if len(buffers['hr']) > 5 else 0
        }
        s, d, f = self.neuro.analyze(neuro_inputs, patient)
        scores['stroke_risk'] = s * coherence_conf
        diagnoses['neuro'] = d
        all_factors.update(f)

        # 4. Inferência Causal (O "Merger")
        causal_result = self.causal_engine.predict_cascade(vitals, scores)

        # 5. Decisão Final e Geração de Evento
        max_score = max(scores.values()) if scores else 0
        severity = AlertSeverity.NORMAL
        
        if max_score > 0.8: severity = AlertSeverity.LIFE_THREATENING
        elif max_score > 0.6: severity = AlertSeverity.CRITICAL
        elif max_score > 0.4: severity = AlertSeverity.HIGH
        elif max_score > 0.2: severity = AlertSeverity.MEDIUM

        # Determinar a predição principal baseada no maior score
        primary_prediction = "NORMAL"
        if scores:
            max_risk_key = max(scores, key=scores.get)
            risk_mapping = {
                'cardiac_risk': 'ACUTE_CARDIAC_EVENT',
                'hemodynamic_risk': 'HEMODYNAMIC_COLLAPSE',
                'metabolic_risk': 'METABOLIC_CRISIS',
                'stroke_risk': 'IMMINENT_STROKE'
            }
            primary_prediction = risk_mapping.get(max_risk_key, 'MULTI_SYSTEM_RISK')

        if severity != AlertSeverity.NORMAL or causal_result.get('status') == 'CRITICAL_CHAIN':
            # Usar a predição primária se a cascata não retornar um evento específico
            final_prediction = causal_result.get('predicted_next_event') or primary_prediction
            
            event = ClinicalEvent(
                timestamp=datetime.now(),
                patient_id=pid,
                source_module="HealthCausalEngine_v2",
                severity=severity,
                prediction=final_prediction,
                confidence=max_score,
                contributing_factors=all_factors,
                causal_chain=causal_result.get('causal_chain', [])
            )
            
            # Log estruturado da decisão causal
            self.logger.info(
                f"[ALERT] Paciente {pid}: {event.prediction}. "
                f"Cadeia Causal: {' | '.join(event.causal_chain) if event.causal_chain else 'Nenhuma cascata crítica detectada'}. "
                f"Ação: {causal_result.get('recommendation', 'MONITORAR CONTINUAMENTE')}"
            )
            return event
            
        return None

# ==============================================================================
# 6. SIMULAÇÃO E TESTE DE CENÁRIOS COMPLEXOS
# ==============================================================================

def generate_complex_scenario(scenario_type: str) -> Tuple[PatientContext, Dict[str, float]]:
    """Gera dados sintéticos para testar cenários específicos de falência multi-orgânica."""
    
    base_patient = PatientContext(
        patient_id="PT-998877",
        age=72,
        gender="M",
        history={"hypertension": True, "diabetes": True, "prior_stroke": False},
        baseline_metrics={"hr": 75, "bp": 130}
    )

    if scenario_type == "INFARTO_PROGRESSIVO":
        # Simula taquicardia + queda de HRV + pressão reativa
        return base_patient, {
            "heart_rate": 145,
            "bp_sys": 165,
            "bp_dia": 95,
            "spo2": 94,
            "resp_rate": 24,
            "glucose": 140
        }

    elif scenario_type == "AVC_IMINENTE":
        # Simula pico hipertensivo + arritmia (FA)
        return base_patient, {
            "heart_rate": 110, # Irregular na simulação real
            "bp_sys": 210,     # Crise hipertensiva
            "bp_dia": 130,
            "spo2": 96,
            "resp_rate": 18,
            "glucose": 110
        }

    elif scenario_type == "CHOQUE_SEPTICO":
        # Febre, Taquicardia, Hipotensão (Dissociação)
        return PatientContext(patient_id="PT-112233", age=65, gender="F", history={}), {
            "heart_rate": 130,
            "bp_sys": 85,      # Hipotensão perigosa
            "bp_dia": 50,
            "spo2": 91,
            "resp_rate": 32,
            "temperature": 39.5,
            "glucose": 180
        }
    
    elif scenario_type == "FALSO_POSITIVO_RUIDO":
        # HR impossível mas SpO2 normal (Incoerente)
        return base_patient, {
            "heart_rate": 220, # Provável erro de sensor
            "bp_sys": 120,
            "bp_dia": 80,
            "spo2": 99,        # Incoerente com HR 220
            "resp_rate": 16
        }

    # Caso padrão estável
    return base_patient, {
        "heart_rate": 72,
        "bp_sys": 125,
        "bp_dia": 82,
        "spo2": 98,
        "resp_rate": 16,
        "glucose": 95
    }

if __name__ == "__main__":
    print("="*60)
    print("HEALTHCAUSAL ENGINE v2.0 - INICIANDO SISTEMA")
    print("="*60)
    
    engine = HealthCausalOrchestrator()
    
    # Cenário 1: Infarto Progressivo (Teste de Detecção Cardíaca e Cascata)
    print("\n>>> CENÁRIO 1: INFARTO AGUDO DO MIOCÁRDIO EM EVOLUÇÃO")
    pt, vitals = generate_complex_scenario("INFARTO_PROGRESSIVO")
    # Alimentar histórico falso para dar contexto ao algoritmo
    for _ in range(20): 
        engine.get_patient_buffer(pt.patient_id)['hr'].append(80) # Baseline normal antes do evento
    
    event = engine.process_stream(pt, vitals)
    if event:
        print(f"✅ ALERTA GERADO: {event.prediction} (Severidade: {event.severity.name})")
        print(f"🔗 Cadeia Causal Detectada:")
        for step in event.causal_chain:
            print(f"   ↳ {step}")
        print(f"💡 Recomendação do Sistema: {engine.causal_engine.predict_cascade(vitals, {'cardiac_risk': 0.8})['recommendation']}")

    # Cenário 2: AVC Iminente (Teste de Especialista Neuro + Hemodinâmico)
    print("\n>>> CENÁRIO 2: RISCO DE AVC HEMORRÁGICO")
    pt2, vitals2 = generate_complex_scenario("AVC_IMINENTE")
    for _ in range(20): engine.get_patient_buffer(pt2.patient_id)['bp_sys'].append(130)
    
    event2 = engine.process_stream(pt2, vitals2)
    if event2:
        print(f"✅ ALERTA GERADO: {event2.prediction} (Severidade: {event2.severity.name})")
        print(f"🔗 Cadeia Causal: {event2.causal_chain}")

    # Cenário 3: Falso Positivo (Teste do Proxy de Validação)
    print("\n>>> CENÁRIO 3: RUÍDO DE SENSOR (TESTE DE FALSE POSITIVE SUPPRESSION)")
    pt3, vitals3 = generate_complex_scenario("FALSO_POSITIVO_RUIDO")
    event3 = engine.process_stream(pt3, vitals3)
    
    if event3:
        print(f"⚠️ ALERTA GERADO (Mas com confiança reduzida): {event3.prediction}")
        print(f"   Fatores de incoerência detectados pelo Proxy.")
    else:
        print("✅ SUCESSO: O Proxy de Validação Cruzada suprimiu o falso positivo corretamente.")

    print("\n" + "="*60)
    print("SIMULAÇÃO CONCLUÍDA COM SUCESSO")
    print("="*60)
