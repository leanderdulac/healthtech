# Fundamentos Matemáticos, Biofísicos e Teóricos — HealthTech Platform

Este documento apresenta a formalização físico-matemática dos motores computacionais da plataforma **HealthTech**.

---

## 1. Processos Estocásticos e Geração de Sinais (Ornstein-Uhlenbeck)

A variabilidade intrínseca de variáveis hemodinâmicas ao redor do setpoint fisiológico homeostático é modelada pela Equação Diferencial Estocástica (SDE) de **Ornstein-Uhlenbeck**:

$$dX_t = \theta (\mu - X_t) dt + \sigma dW_t$$

onde:
- $\theta > 0$: Taxa de reversão à média (velocidade de regulação autonômica).
- $\mu$: Ponto de equilíbrio fisiológico homeostático (ex: 70 bpm).
- $\sigma$: Volatilidade do ruído gaussiano intrínseco.
- $W_t$: Processo de Wiener padrão ($dW_t \sim \mathcal{N}(0, dt)$).

A discretização temporal de Euler-Maruyama empregada na plataforma é dada por:

$$X_{k+1} = X_k + \theta (\mu - X_k) \Delta t + \sigma \sqrt{\Delta t} \cdot \varepsilon_k, \quad \varepsilon_k \sim \mathcal{N}(0, 1)$$

---

## 2. Fusão Sensorial Bayesiana Ótima (BLUE - Best Linear Unbiased Estimator)

A reconciliação de múltiplos sensores wearables redundantes com variâncias dinâmicas $\sigma_i^2(t)$ estimadas via EWMA (Exponentially Weighted Moving Average) é resolvida pelo estimador BLUE:

$$\hat{x}_{BLUE} = \frac{\sum_{i=1}^M \frac{z_i}{\sigma_i^2}}{\sum_{i=1}^M \frac{1}{\sigma_i^2}} = \sum_{i=1}^M w_i z_i, \quad w_i = \frac{\sigma_i^{-2}}{\sum_{j=1}^M \sigma_j^{-2}}$$

com variância resultante estritamente inferior a qualquer sensor individual:

$$\sigma_{fused}^2 = \left( \sum_{i=1}^M \frac{1}{\sigma_i^2} \right)^{-1} < \min_{i} \sigma_i^2$$

---

## 3. Modelo Hemodinâmico Windkessel de 4 Elementos (WK4) & Barorreflexo

A dinâmica do acoplamento ventrículo-arterial considera resistência vascular periférica ($R_p$), complacência elástica da aorta ($C$), impedância característica ($Z_c$) e inertância sanguínea ($L$):

$$\left(1 + \frac{Z_c}{R_p}\right) \frac{dP(t)}{dt} + \frac{P(t)}{R_p C} = \frac{Q(t)}{C} + \left(Z_c + \frac{L}{R_p C}\right) \frac{dQ(t)}{dt} + L \frac{d^2Q(t)}{dt^2}$$

A integração temporal contínua é realizada via Runge-Kutta de 4ª Ordem (**RK4**).

### Velocidade da Onda de Pulso (PWV — Bramwell-Hill)

$$PWV = \sqrt{\frac{V \cdot \Delta P}{\rho \cdot \Delta V}} = \sqrt{\frac{1}{\rho \cdot C_{dist}}}$$

### Alça de Controle do Barorreflexo

Taxa de disparo aferente dos barorreceptores do seio carotídeo:

$$f_{baro}(P) = \frac{f_{max}}{1 + \exp\left(-k (P_{mean} - P_{target})\right)}$$

Modulação eferente sobre frequência cardíaca ($HR$) e tônus vascular ($R_p$):

$$\Delta HR = -K_{hr} \cdot (P_{mean} - P_{target}), \quad \Delta R_p = -K_{rp} \cdot (P_{mean} - P_{target})$$

---

## 4. Estimação de Estados Latentes (Adaptive Unscented Kalman Filter — A-UKF)

O motor de Inferência de Dados Fantasmas reconstrói estados não observados ($PAS, PAD, SpO_2, \text{tônus vagal}, \text{glicemia}$) utilizando a Transformada Unscented Escalonada de Van der Merwe com adaptação online de Sage-Husa:

$$\mathbf{e}_k = \mathbf{z}_k - \hat{\mathbf{z}}_{k|k-1}$$

$$\hat{R}_k = (1 - d_k) \hat{R}_{k-1} + d_k \left( \mathbf{e}_k \mathbf{e}_k^T - H P_{k|k-1} H^T \right), \quad d_k = \frac{1 - b}{1 - b^k}$$

### Certificado de Observabilidade (Gramiano de Observabilidade)

$$\mathcal{W}_o = \sum_{k=0}^N (A^k)^T H^T H (A^k), \quad \kappa(\mathcal{W}_o) = \frac{\lambda_{max}(\mathcal{W}_o)}{\lambda_{min}(\mathcal{W}_o)}$$

---

## 5. Garantia Estatística via Conformal Prediction (Split Conformal)

Para qualquer probabilidade predita $\hat{p}(X)$, a plataforma constrói conjuntos e intervalos de predição $\mathcal{C}_{1-\alpha}(X)$ com garantia de cobertura finita e não-paramétrica:

$$\mathbb{P}\left( Y \in \mathcal{C}_{1-\alpha}(X_{n+1}) \right) \ge 1 - \alpha$$

utilizando quantil empírico dos resíduos de calibração:

$$\hat{q} = \text{Quantil}\left( \{s_i\}_{i=1}^{n_{cal}}, \frac{\lceil (n_{cal}+1)(1-\alpha) \rceil}{n_{cal}} \right)$$

---

## 6. Teoria dos Jogos e Alocação de Recursos (Triage & Alignment Game)

A tomada de decisão médica em cenários de alta pressão é formulada como jogos não-cooperativos e estáticos/dinâmicos (Dilema do Prisioneiro Clínico, Caça ao Cervo, Centipede e Triagem de Leitos).

O Equilíbrio de Nash $(\sigma_1^*, \sigma_2^*)$ satisfaz:

$$u_i(\sigma_i^*, \sigma_{-i}^*) \ge u_i(\sigma_i, \sigma_{-i}^*), \quad \forall \sigma_i \in \Delta(S_i)$$
