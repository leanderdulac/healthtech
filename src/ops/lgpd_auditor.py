"""Auditor interno de segurança e LGPD do Healthtech.

Gera um relatório de prontidão para a Lei 13.709/2018, o Anexo A da
ISO/IEC 27001:2022 e os objetivos de privacidade da ISO/IEC 27701.
Não emite certificação, parecer jurídico nem declara conformidade
sem evidência no repositório.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = ROOT / "docs" / "auditor" / "relatorios"

STATUS_EVIDENCED = "Evidenciado no repositório"
STATUS_PARTIAL = "Parcial"
STATUS_GAP = "Lacuna"
STATUS_EXTERNAL = "Pendente de evidência externa"
STATUS_PROVIDER = "Responsabilidade do provedor"


@dataclass(frozen=True)
class ProbeResult:
    probe_id: str
    ok: bool
    detail: str
    evidence: Tuple[str, ...]


@dataclass(frozen=True)
class Control:
    control_id: str
    framework: str
    title: str
    applicability: str
    probes: Tuple[str, ...] = ()
    legal_duty: bool = False


@dataclass(frozen=True)
class Finding:
    finding_id: str
    severity: str
    title: str
    detail: str
    refs: Tuple[str, ...]


def _read(root: Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).is_file()


def _search(root: Path, folder: str, needles: Sequence[str], suffix: str) -> List[str]:
    base = root / folder
    if not base.exists():
        return []
    found: List[str] = []
    lowered = tuple(n.lower() for n in needles)
    for path in base.rglob(f"*{suffix}"):
        if any(part in {".git", "node_modules", "__pycache__", "build", "auditor"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(n in text for n in lowered):
            found.append(str(path.relative_to(root)))
            if len(found) >= 8:
                break
    return found


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if done.returncode != 0:
        return ""
    return done.stdout.strip()


def collect_probes(root: Path) -> Dict[str, ProbeResult]:
    lgpd = _read(root, "saude_responsiva_secure/app/api/lgpd.py")
    store = _read(root, "saude_responsiva_secure/app/services/telemetry_store.py")
    audit = _read(root, "saude_responsiva_secure/app/services/audit.py")
    auth = _read(root, "saude_responsiva_secure/app/security/auth.py")
    headers = _read(root, "saude_responsiva_secure/app/security/headers.py")
    main = _read(root, "saude_responsiva_secure/app/main.py")
    config = _read(root, "saude_responsiva_secure/app/config.py")
    rate = _read(root, "saude_responsiva_secure/app/security/rate_limit.py")
    tests = _read(root, "saude_responsiva_secure/test_security.py")
    fhir = _read(root, "src/security/anonymization.py")
    gitignore = _read(root, ".gitignore")
    agents = _read(root, "AGENTS.md")
    prefs = _read(root, "companion-android/app/src/main/java/com/healthtech/companion/data/AppPrefs.kt")
    billing = _read(root, "src/ops/gcp_billing_sim.py")

    def result(probe_id: str, ok: bool, detail: str, *evidence: str) -> ProbeResult:
        return ProbeResult(probe_id, ok, detail, evidence)

    consent_kt = _search(root, "companion-android/app/src", ("consentimento", "consent"), ".kt")
    notice_kt = _search(root, "companion-android/app/src", ("sem conduta obrigatória",), ".kt")
    incident_docs = _search(
        root,
        "docs",
        ("comunicação de incidente", "comunicacao de incidente", "art. 48", "plano de resposta a incidente"),
        ".md",
    )
    ropa_docs = _search(root, "docs", ("registro das operações de tratamento", "registro de operações"), ".md")
    ripd_docs = _search(root, "docs", ("relatório de impacto", "ripd", "dpia"), ".md")
    retention_docs = _search(root, "docs", ("política de retenção", "politica de retencao", "prazo de retenção"), ".md")
    basis_text = _read(root, "docs/privacidade/base-legal.md").lower()
    dpo_text = _read(root, "docs/privacidade/encarregado.md").lower()
    transfer_text = _read(root, "docs/privacidade/transferencia-internacional.md").lower()
    legal_ok = bool(consent_kt) and "art. 11" in basis_text and "consentimento específico" in basis_text
    dpo_ok = "nomeado: sim" in dpo_text and "canal:" in dpo_text and "não informado" not in dpo_text
    transfer_open = "mecanismo_vigente: nenhum" in transfer_text or "mecanismo_vigente:nenhum" in transfer_text
    transfer_ok = (not transfer_open) and any(
        marker in transfer_text
        for marker in (
            "cláusulas-padrão vigentes",
            "clausulas-padrao vigentes",
            "região de tratamento: brasil",
            "regiao de tratamento: brasil",
        )
    )
    env_tracked = _git(root, "ls-files", "--", ".env")
    in_us_central = "us-central1" in billing

    probes = [
        result(
            "purge_endpoint",
            "anonymize" in lgpd and 'require_scope("admin")' in lgpd,
            "Há exclusão de histórico com escopo admin.",
            "saude_responsiva_secure/app/api/lgpd.py",
        ),
        result(
            "purge_durable",
            any(
                name in (store.split("def anonymize_patient", 1)[1][:800] if "def anonymize_patient" in store else "")
                for name in ("device_registry", "pilot_review")
            ),
            (
                "A exclusão alcança a telemetria, a frota e a revisão de piloto."
                if any(
                    name in (store.split("def anonymize_patient", 1)[1][:800] if "def anonymize_patient" in store else "")
                    for name in ("device_registry", "pilot_review")
                )
                else "A exclusão remove só o dicionário em memória deste processo. Não alcança device registry, revisão de piloto nem logs."
            ),
            "saude_responsiva_secure/app/services/telemetry_store.py",
        ),
        result(
            "fhir_deid",
            "anonimizar_paciente_fhir" in fhir and "telecom" in fhir,
            "Há descaracterização de recurso FHIR Patient (nome, contato, identificador com hash).",
            "src/security/anonymization.py",
        ),
        result(
            "audit_log",
            "api_access_audit" in audit and "masked_api_key" in audit and "AuditLoggingMiddleware" in main,
            "A API registra acesso com chave mascarada e X-Request-ID.",
            "saude_responsiva_secure/app/services/audit.py",
            "saude_responsiva_secure/app/main.py",
        ),
        result(
            "audit_minimized",
            "patient_id" not in audit,
            (
                "A trilha não grava o identificador cru do paciente."
                if "patient_id" not in audit
                else "A trilha grava patient_id. Isso é dado pessoal dentro do log."
            ),
            "saude_responsiva_secure/app/services/audit.py",
        ),
        result(
            "hmac_auth",
            "hmac.compare_digest" in auth and "X-API-Key" in auth,
            "A chave de API é comparada com hmac.compare_digest, sem casar por prefixo.",
            "saude_responsiva_secure/app/security/auth.py",
        ),
        result(
            "scopes",
            "wearables:write" in auth and "wearables:read" in auth and '"admin"' in auth,
            "Há três escopos: escrita, leitura e admin.",
            "saude_responsiva_secure/app/security/auth.py",
        ),
        result(
            "patient_authz",
            "require_patient_access" in auth and "IDOR" in auth,
            "Há trava por paciente. Em produção, sem lista autorizada, o acesso cruzado é negado.",
            "saude_responsiva_secure/app/security/auth.py",
        ),
        result(
            "headers",
            "Strict-Transport-Security" in headers and "Content-Security-Policy" in headers and "SecurityHeadersMiddleware" in main,
            "HSTS, CSP, nosniff, frame deny e Permissions-Policy estão no middleware.",
            "saude_responsiva_secure/app/security/headers.py",
        ),
        result(
            "rate_limit",
            "PathRateLimitMiddleware" in main and bool(rate),
            "Rate limit está ligado na aplicação secure.",
            "saude_responsiva_secure/app/security/rate_limit.py",
            "saude_responsiva_secure/app/main.py",
        ),
        result(
            "security_tests",
            "test_unauthenticated_request_returns_401" in tests and "anti-IDOR" in tests and "purge LGPD" in tests,
            "A suíte secure cobre 401, escopo, cabeçalhos, trilha, rate limit, anti-IDOR e purga.",
            "saude_responsiva_secure/test_security.py",
        ),
        result(
            "gitignore_secrets",
            ".env" in gitignore and "*.keystore" in gitignore and "*.pem" in gitignore,
            ".env, keystore e pem estão no gitignore.",
            ".gitignore",
        ),
        result(
            "env_untracked",
            env_tracked == "",
            ".env não está no índice do git." if env_tracked == "" else ".env está versionado.",
            ".gitignore",
        ),
        result(
            "encrypted_prefs",
            "EncryptedSharedPreferences" in prefs and "AES256_GCM" in prefs,
            "A chave de ingestão do companion fica em EncryptedSharedPreferences.",
            "companion-android/app/src/main/java/com/healthtech/companion/data/AppPrefs.kt",
        ),
        result(
            "consent_ui",
            bool(consent_kt),
            "Há tela de consentimento no companion." if consent_kt else "Não há tela de consentimento no código Kotlin do companion.",
            *(consent_kt or ("companion-android/ARCHITECTURE_ONEPAGER.md",)),
        ),
        result(
            "holder_notice",
            bool(notice_kt),
            "O app informa que o alerta é apoio à decisão, sem conduta obrigatória." if notice_kt else "O app não informa o apoio à decisão ao titular.",
            *(notice_kt or ("companion-android/ARCHITECTURE_ONEPAGER.md",)),
        ),
        result(
            "legal_basis",
            legal_ok,
            "A hipótese do art. 11 exigida pelo app é o consentimento específico." if legal_ok else "Não há registro da hipótese do art. 11 ligada ao app.",
            "docs/privacidade/base-legal.md",
        ),
        result(
            "holder_rights",
            False,
            "Confirmação, acesso, correção e portabilidade não têm fluxo do titular.",
            "saude_responsiva_secure/app/api/lgpd.py",
        ),
        result(
            "incident_procedure",
            bool(incident_docs),
            "Há procedimento de comunicação de incidente à ANPD e ao titular." if incident_docs else "Não há procedimento de comunicação de incidente à ANPD e ao titular.",
            *(incident_docs or ("docs/",)),
        ),
        result(
            "ropa",
            bool(ropa_docs),
            "Há registro das operações de tratamento (art. 37)." if ropa_docs else "Não há registro das operações de tratamento (art. 37).",
            *(ropa_docs or ("docs/",)),
        ),
        result(
            "ripd",
            bool(ripd_docs),
            "Há relatório de impacto à proteção de dados (art. 38)." if ripd_docs else "Não há relatório de impacto à proteção de dados (art. 38).",
            *(ripd_docs or ("docs/",)),
        ),
        result(
            "dpo",
            dpo_ok,
            "Há nomeação de encarregado com canal." if dpo_ok else "Não há nomeação de encarregado no repositório (art. 41).",
            "docs/privacidade/encarregado.md",
        ),
        result(
            "retention",
            bool(retention_docs),
            "Há política de retenção e descarte." if retention_docs else "Não há política de retenção e descarte.",
            *(retention_docs or ("docs/",)),
        ),
        result(
            "cloud_region",
            not in_us_central,
            "O faturamento do projeto aponta us-central1. Dado de saúde fora do Brasil é transferência internacional." if in_us_central else "O ledger não aponta us-central1.",
            "src/ops/gcp_billing_sim.py",
        ),
        result(
            "transfer_mechanism",
            transfer_ok,
            "Há mecanismo vigente para a transferência internacional." if transfer_ok else "Não há cláusulas, decisão de adequação nem garantia do art. 33 em vigor.",
            "docs/privacidade/transferencia-internacional.md",
        ),
        result(
            "decision_support",
            "decision_support" in agents and "sem conduta obrigatória" in agents,
            "O piloto declara que o alerta é apoio à decisão, sem conduta obrigatória.",
            "AGENTS.md",
        ),
        result(
            "auth_prod_lock",
            "AUTH_DISABLED só vale fora de produção" in config and "auth_disabled: bool = False" in config,
            "AUTH_DISABLED não permanece ligado quando o ambiente é produção.",
            "saude_responsiva_secure/app/config.py",
        ),
        result(
            "weak_keys",
            "_WEAK_KEYS" in auth and "is_production" in auth,
            "Há lista de chaves fracas e bloqueio associado à produção.",
            "saude_responsiva_secure/app/security/auth.py",
        ),
        result(
            "lgpd_module",
            _exists(root, "saude_responsiva_secure/app/api/lgpd.py"),
            "Existe módulo de endpoint LGPD. Isso não substitui política, base legal nem RIPD.",
            "saude_responsiva_secure/app/api/lgpd.py",
        ),
    ]
    # purge_durable ok means the limitation is confirmed. Invert for control scoring:
    # callers use the raw flag. evaluate() treats ok=True as "evidence of the control".
    # The durable-purge control must FAIL when deletion is memory-only.
    return {item.probe_id: item for item in probes}


def _iso_controls() -> List[Control]:
    org_5 = [
        ("5.1", "Políticas de segurança da informação"),
        ("5.2", "Papéis e responsabilidades de segurança da informação"),
        ("5.3", "Segregação de funções"),
        ("5.4", "Responsabilidades da direção"),
        ("5.5", "Contato com autoridades"),
        ("5.6", "Contato com grupos de interesse especial"),
        ("5.7", "Inteligência de ameaças"),
        ("5.8", "Segurança da informação na gestão de projetos"),
        ("5.9", "Inventário de ativos de informação"),
        ("5.10", "Uso aceitável de ativos de informação"),
        ("5.11", "Devolução de ativos"),
        ("5.12", "Classificação da informação"),
        ("5.13", "Rotulagem da informação"),
        ("5.14", "Transferência da informação"),
        ("5.15", "Controle de acesso"),
        ("5.16", "Gestão de identidades"),
        ("5.17", "Informação de autenticação"),
        ("5.18", "Direitos de acesso"),
        ("5.19", "Segurança da informação nas relações com fornecedores"),
        ("5.20", "Segurança da informação em acordos com fornecedores"),
        ("5.21", "Segurança da cadeia de suprimento de TIC"),
        ("5.22", "Monitoramento e mudança de serviços de fornecedores"),
        ("5.23", "Segurança da informação no uso de serviços em nuvem"),
        ("5.24", "Planejamento e preparação para incidentes"),
        ("5.25", "Avaliação e decisão sobre eventos de segurança"),
        ("5.26", "Resposta a incidentes de segurança da informação"),
        ("5.27", "Aprendizado com incidentes"),
        ("5.28", "Coleta de evidências"),
        ("5.29", "Segurança da informação durante disrupção"),
        ("5.30", "Prontidão de TIC para continuidade"),
        ("5.31", "Requisitos legais, estatutários, regulatórios e contratuais"),
        ("5.32", "Direitos de propriedade intelectual"),
        ("5.33", "Proteção de registros"),
        ("5.34", "Privacidade e proteção de PII"),
        ("5.35", "Revisão independente da segurança da informação"),
        ("5.36", "Conformidade com políticas e normas"),
        ("5.37", "Procedimentos operacionais documentados"),
    ]
    people = [
        ("6.1", "Verificação de antecedentes"),
        ("6.2", "Termos e condições de contratação"),
        ("6.3", "Conscientização, educação e treinamento"),
        ("6.4", "Processo disciplinar"),
        ("6.5", "Responsabilidades após desligamento ou mudança"),
        ("6.6", "Acordos de confidencialidade"),
        ("6.7", "Trabalho remoto"),
        ("6.8", "Comunicação de eventos de segurança da informação"),
    ]
    physical = [
        ("7.1", "Perímetros de segurança física"),
        ("7.2", "Entrada física"),
        ("7.3", "Proteção de escritórios, salas e instalações"),
        ("7.4", "Monitoramento de segurança física"),
        ("7.5", "Proteção contra ameaças físicas e ambientais"),
        ("7.6", "Trabalho em áreas seguras"),
        ("7.7", "Mesa limpa e tela limpa"),
        ("7.8", "Posicionamento e proteção de equipamentos"),
        ("7.9", "Segurança de ativos fora das instalações"),
        ("7.10", "Mídias de armazenamento"),
        ("7.11", "Utilidades de suporte"),
        ("7.12", "Segurança do cabeamento"),
        ("7.13", "Manutenção de equipamentos"),
        ("7.14", "Descarte ou reuso seguro de equipamentos"),
    ]
    tech = [
        ("8.1", "Dispositivos endpoint de usuário"),
        ("8.2", "Direitos de acesso privilegiado"),
        ("8.3", "Restrição de acesso à informação"),
        ("8.4", "Acesso ao código-fonte"),
        ("8.5", "Autenticação segura"),
        ("8.6", "Gestão de capacidade"),
        ("8.7", "Proteção contra malware"),
        ("8.8", "Gestão de vulnerabilidades técnicas"),
        ("8.9", "Gestão de configuração"),
        ("8.10", "Eliminação da informação"),
        ("8.11", "Mascaramento de dados"),
        ("8.12", "Prevenção de vazamento de dados"),
        ("8.13", "Backup da informação"),
        ("8.14", "Redundância das instalações de processamento"),
        ("8.15", "Registro de logs"),
        ("8.16", "Atividades de monitoramento"),
        ("8.17", "Sincronização de relógios"),
        ("8.18", "Uso de programas utilitários privilegiados"),
        ("8.19", "Instalação de software em sistemas operacionais"),
        ("8.20", "Segurança de redes"),
        ("8.21", "Segurança de serviços de rede"),
        ("8.22", "Segregação de redes"),
        ("8.23", "Filtragem web"),
        ("8.24", "Uso de criptografia"),
        ("8.25", "Ciclo de vida de desenvolvimento seguro"),
        ("8.26", "Requisitos de segurança de aplicação"),
        ("8.27", "Arquitetura e princípios de engenharia seguros"),
        ("8.28", "Codificação segura"),
        ("8.29", "Testes de segurança em desenvolvimento e aceitação"),
        ("8.30", "Desenvolvimento terceirizado"),
        ("8.31", "Separação de ambientes de desenvolvimento, teste e produção"),
        ("8.32", "Gestão de mudanças"),
        ("8.33", "Informação de teste"),
        ("8.34", "Proteção de sistemas durante testes de auditoria"),
    ]
    product: Dict[str, Tuple[str, ...]] = {
        "5.15": ("scopes", "patient_authz"),
        "5.17": ("hmac_auth", "weak_keys", "auth_prod_lock"),
        "5.23": ("cloud_region", "transfer_mechanism"),
        "5.24": ("incident_procedure",),
        "5.25": ("incident_procedure",),
        "5.26": ("incident_procedure",),
        "5.33": ("retention",),
        "5.34": ("lgpd_module", "consent_ui", "ropa", "ripd"),
        "8.2": ("scopes",),
        "8.3": ("patient_authz", "scopes"),
        "8.5": ("hmac_auth", "auth_prod_lock", "weak_keys"),
        "8.10": ("purge_endpoint", "purge_durable"),
        "8.11": ("audit_log", "fhir_deid", "audit_minimized"),
        "8.15": ("audit_log", "audit_minimized"),
        "8.20": ("headers",),
        "8.24": ("encrypted_prefs", "hmac_auth"),
        "8.25": ("security_tests",),
        "8.26": ("headers", "scopes", "rate_limit"),
        "8.28": ("security_tests",),
        "8.29": ("security_tests",),
        "8.31": ("auth_prod_lock",),
        "8.33": ("weak_keys", "env_untracked", "gitignore_secrets"),
    }
    provider = {item[0] for item in physical}
    rows: List[Control] = []
    for control_id, title in org_5 + people + tech:
        if control_id in product:
            applicability = "produto"
            probes = product[control_id]
        elif control_id in provider:
            applicability = "provedor"
            probes = ()
        else:
            applicability = "organizacao"
            probes = ()
        rows.append(Control(control_id, "ISO/IEC 27001:2022 Anexo A", title, applicability, probes))
    for control_id, title in physical:
        rows.append(Control(control_id, "ISO/IEC 27001:2022 Anexo A", title, "provedor"))
    rows.sort(key=lambda item: [int(part) for part in item.control_id.split(".")])
    return rows


def _lgpd_controls() -> List[Control]:
    items = [
        ("Art. 6", "Princípios: finalidade, necessidade, segurança, prevenção e responsabilização", ("lgpd_module", "decision_support", "retention"), True),
        ("Art. 7", "Base legal para dado pessoal", ("legal_basis",), True),
        ("Art. 11", "Base legal para dado pessoal sensível de saúde", ("legal_basis",), True),
        ("Art. 9", "Informação ao titular quando o tratamento se apoia em consentimento", ("consent_ui",), True),
        ("Art. 18", "Direitos do titular: confirmação, acesso, correção, portabilidade, eliminação e revogação", ("purge_endpoint", "purge_durable", "holder_rights"), True),
        ("Art. 20", "Revisão de decisão automatizada", ("decision_support", "holder_notice"), True),
        ("Art. 33", "Transferência internacional", ("cloud_region", "transfer_mechanism"), True),
        ("Art. 37", "Registro das operações de tratamento", ("ropa",), True),
        ("Art. 38", "Relatório de impacto à proteção de dados", ("ripd",), True),
        ("Art. 41", "Encarregado pelo tratamento", ("dpo",), True),
        ("Art. 46", "Medidas de segurança", ("hmac_auth", "headers", "rate_limit", "security_tests", "patient_authz"), True),
        ("Art. 48", "Comunicação de incidente de segurança", ("incident_procedure",), True),
        ("Art. 49", "Sistemas estruturados para segurança e privacidade desde a concepção", ("lgpd_module", "consent_ui", "encrypted_prefs"), True),
        ("Art. 50", "Boas práticas e governança", ("ropa", "ripd", "dpo", "retention"), True),
    ]
    return [
        Control(control_id, "LGPD Lei 13.709/2018", title, "produto", probes, legal)
        for control_id, title, probes, legal in items
    ]


def _pims_controls() -> List[Control]:
    items = [
        ("PIMS-01", "Identificar finalidade e base legal do tratamento", ("ropa",)),
        ("PIMS-02", "Registrar consentimento ou outra base, e a informação dada ao titular", ("consent_ui",)),
        ("PIMS-03", "Atender direitos do titular, inclusive eliminação", ("purge_endpoint", "purge_durable", "holder_rights")),
        ("PIMS-04", "Privacidade desde a concepção e por padrão", ("consent_ui", "encrypted_prefs", "audit_minimized")),
        ("PIMS-05", "Contrato com operador e serviços em nuvem", ("transfer_mechanism", "cloud_region")),
        ("PIMS-06", "Transferência internacional de PII", ("cloud_region", "transfer_mechanism")),
        ("PIMS-07", "Avaliação de impacto à privacidade", ("ripd",)),
        ("PIMS-08", "Ponto de contato de privacidade (encarregado)", ("dpo",)),
    ]
    return [
        Control(control_id, "ISO/IEC 27701 objetivo de privacidade", title, "produto", probes, True)
        for control_id, title, probes in items
    ]


def all_controls() -> List[Control]:
    return _lgpd_controls() + _iso_controls() + _pims_controls()


def evaluate(control: Control, probes: Dict[str, ProbeResult]) -> str:
    if not control.probes:
        if control.applicability == "provedor":
            return STATUS_PROVIDER
        return STATUS_EXTERNAL
    linked = [probes[probe_id] for probe_id in control.probes]
    if all(item.ok for item in linked):
        return STATUS_EVIDENCED
    if any(item.ok for item in linked):
        return STATUS_PARTIAL
    return STATUS_GAP


def build_findings(probes: Dict[str, ProbeResult]) -> List[Finding]:
    findings: List[Finding] = []

    def add(finding_id: str, severity: str, title: str, detail: str, *refs: str) -> None:
        findings.append(Finding(finding_id, severity, title, detail, refs))

    if not probes["incident_procedure"].ok:
        add(
            "F-01",
            "crítico",
            "Não há procedimento de incidente do art. 48",
            "O repositório não descreve prazo razoável, comunicação à ANPD nem comunicação ao titular quando o incidente puder acarretar risco ou dano relevante. Sem isso, uma certificação ISO 27001 também falha nos controles 5.24 a 5.26.",
            "LGPD art. 48",
            "ISO/IEC 27001:2022 A.5.24 A.5.25 A.5.26",
        )
    if not probes["legal_basis"].ok:
        add(
            "F-02",
            "crítico",
            "Base legal do dado sensível de saúde não está documentada",
            "Frequência cardíaca, SpO2, pressão, temperatura e identificador do paciente são dado pessoal sensível (art. 5, II, e art. 11). Não há registro da hipótese do art. 11 usada no piloto, nem informação correspondente ao titular.",
            "LGPD art. 5, II",
            "LGPD art. 11",
            "ISO/IEC 27701 PIMS-01",
        )
    if not probes["transfer_mechanism"].ok and not probes["cloud_region"].ok:
        add(
            "F-03",
            "crítico",
            "Tratamento em us-central1 sem mecanismo de transferência",
            "O projeto de nuvem está em us-central1. Dado pessoal sensível fora do Brasil exige uma das hipóteses do art. 33. Não há cláusulas, garantia ou registro dessa escolha.",
            "LGPD art. 33",
            "ISO/IEC 27001:2022 A.5.23",
            "src/ops/gcp_billing_sim.py",
        )
    if not probes["purge_durable"].ok:
        add(
            "F-04",
            "alto",
            "A eliminação não cobre o que o produto grava",
            "DELETE /api/v1/patient/{id}/anonymize exige escopo admin e apaga o histórico em memória do processo. Não apaga device registry, revisão de piloto nem a trilha que já gravou o patient_id. Direito de eliminação do art. 18 fica parcial.",
            "LGPD art. 18",
            "ISO/IEC 27001:2022 A.8.10",
            "saude_responsiva_secure/app/api/lgpd.py",
            "saude_responsiva_secure/app/services/telemetry_store.py",
        )
    if not probes["consent_ui"].ok:
        add(
            "F-05",
            "alto",
            "O companion não registra consentimento",
            "A arquitetura deixa o texto de LGPD e o unlink para uma sprint futura. Se a base escolhida for consentimento, o app ainda não informa finalidade, compartilhamento e forma de revogar.",
            "LGPD art. 9",
            "LGPD art. 11",
            "companion-android/ARCHITECTURE_ONEPAGER.md",
        )
    if not probes["dpo"].ok:
        add(
            "F-06",
            "alto",
            "Encarregado não nomeado nos documentos do produto",
            "O art. 41 exige encarregado divulgado, de forma pública, de preferência no site. O repositório não tem nome, canal nem ato de nomeação.",
            "LGPD art. 41",
        )
    if not probes["ripd"].ok:
        add(
            "F-07",
            "alto",
            "Não há RIPD do tratamento de saúde",
            "Dado sensível de saúde em escala de piloto é candidato natural a relatório de impacto (art. 38). Não há RIPD no docs/.",
            "LGPD art. 38",
            "ISO/IEC 27701 PIMS-07",
        )
    if not probes["ropa"].ok:
        add(
            "F-08",
            "alto",
            "Não há registro das operações de tratamento",
            "O art. 37 exige o registro, que a ANPD pode pedir. Também é a entrada da declaração de aplicabilidade de privacidade.",
            "LGPD art. 37",
        )
    if not probes["retention"].ok:
        add(
            "F-09",
            "alto",
            "Não há prazo de retenção e descarte",
            "O princípio da necessidade (art. 6, III) e o controle A.5.33 pedem prazo, base de guarda e descarte. O histórico em memória tem teto por paciente, mas isso não é política de retenção.",
            "LGPD art. 6, III",
            "ISO/IEC 27001:2022 A.5.33",
        )
    if not probes["audit_minimized"].ok:
        add(
            "F-10",
            "médio",
            "A trilha de auditoria guarda identificador do paciente",
            "O log mascara a chave de API, mas grava patient_id, IP e user-agent. Falta regra de minimização, acesso restrito e prazo desse log.",
            "LGPD art. 6, III",
            "ISO/IEC 27001:2022 A.8.11 A.8.15",
            "saude_responsiva_secure/app/services/audit.py",
        )
    if probes["decision_support"].ok and not probes["holder_notice"].ok:
        add(
            "F-11",
            "médio",
            "Apoio à decisão ainda não é informado ao titular",
            "O repositório diz que o alerta não impõe conduta. O art. 20 pede transparência e revisão de decisão automatizada. Falta esse texto no app e no aviso de privacidade.",
            "LGPD art. 20",
            "AGENTS.md",
        )
    return findings


def _count(statuses: Iterable[str]) -> Dict[str, int]:
    acc = {STATUS_EVIDENCED: 0, STATUS_PARTIAL: 0, STATUS_GAP: 0, STATUS_EXTERNAL: 0, STATUS_PROVIDER: 0}
    for status in statuses:
        acc[status] = acc.get(status, 0) + 1
    return acc


def _table(controls: Sequence[Control], probes: Dict[str, ProbeResult]) -> str:
    lines = ["| ID | Controle | Aplicabilidade | Situação |", "|---|---|---|---|"]
    for control in controls:
        status = evaluate(control, probes)
        label = control.control_id
        if control.framework.startswith("ISO/IEC 27001"):
            label = f"A.{control.control_id}"
        lines.append(f"| {label} | {control.title} | {control.applicability} | {status} |")
    return "\n".join(lines)


def _evidence_lines(probes: Dict[str, ProbeResult]) -> str:
    lines = []
    for probe in probes.values():
        mark = "sim" if probe.ok else "não"
        where = ", ".join(f"`{item}`" for item in probe.evidence)
        lines.append(f"- `{probe.probe_id}` ({mark}): {probe.detail} Evidência: {where}.")
    return "\n".join(lines)


def render_report(root: Path, on: Optional[date] = None) -> str:
    today = on or date.today()
    probes = collect_probes(root)
    controls = all_controls()
    findings = build_findings(probes)
    revision = _git(root, "rev-parse", "--short", "HEAD") or "não disponível"
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD") or "não disponível"
    by_framework: Dict[str, List[Control]] = {}
    for control in controls:
        by_framework.setdefault(control.framework, []).append(control)

    lgpd = by_framework["LGPD Lei 13.709/2018"]
    iso = by_framework["ISO/IEC 27001:2022 Anexo A"]
    pims = by_framework["ISO/IEC 27701 objetivo de privacidade"]
    lgpd_counts = _count(evaluate(item, probes) for item in lgpd)
    iso_counts = _count(evaluate(item, probes) for item in iso)
    critical = sum(1 for item in findings if item.severity == "crítico")
    high = sum(1 for item in findings if item.severity == "alto")
    if probes["purge_durable"].ok and probes["consent_ui"].ok:
        operation = (
            "Coleta no companion depois do consentimento, ingestão, alerta por regra, "
            "exibição no painel e exclusão admin da telemetria, da frota, da revisão de piloto "
            "e do cadastro quando há banco"
        )
    else:
        operation = "Coleta no companion, ingestão, alerta por regra, exibição no painel, exclusão admin em memória"
    missing_bits = []
    if not probes["dpo"].ok:
        missing_bits.append("encarregado e canal do titular")
    if not probes["cloud_region"].ok and not probes["transfer_mechanism"].ok:
        missing_bits.append("mecanismo de transferência internacional")
    if not probes["holder_rights"].ok:
        missing_bits.append("acesso, correção e portabilidade pelo titular")
    unwritten = ", ".join(missing_bits) if missing_bits else "nenhum item desta lista"
    if probes["purge_durable"].ok:
        art18_note = (
            "A exclusão admin alcança a telemetria em memória, a frota, a revisão de piloto e o cadastro operacional quando o banco existe. "
            "Confirmação, acesso, correção e portabilidade ainda não são fluxo do titular. Revogar o consentimento no companion interrompe a coleta nova."
        )
    else:
        art18_note = (
            "O art. 18, hoje, só tem exclusão admin do histórico em memória. "
            "Confirmação de tratamento, acesso, correção, portabilidade, informação sobre compartilhamento e revogação não aparecem como fluxo do titular."
        )
    plan_lines = ["| Ordem | Ação | Fecha |", "|---|---|---|"]
    for index, item in enumerate(findings, start=1):
        plan_lines.append(f"| {index} | {item.title} | {item.finding_id} |")
    plan_md = "\n".join(plan_lines) if findings else "Nenhum achado aberto nesta execução."

    finding_md = []
    for item in findings:
        refs = ", ".join(item.refs)
        finding_md.append(f"### {item.finding_id} — {item.severity}: {item.title}\n\n{item.detail}\n\nReferências: {refs}.\n")

    return f"""# Relatório de auditoria interna — segurança e LGPD

**Organização:** Next2U Saúde / produto Saúde Responsiva (Healthtech)
**Escopo:** repositório `healthtech`, caminho crítico companion → ingest → alertas → painel, mais lacunas de governança que o código não cobre
**Data:** {today.isoformat()}
**Revisão git:** `{revision}` na branch `{branch}`
**Normas de referência:** Lei 13.709/2018 (LGPD); ISO/IEC 27001:2022 Anexo A (adotada no Brasil como ABNT NBR ISO/IEC 27001:2023); objetivos de privacidade da ISO/IEC 27701
**Tipo:** auditoria interna de prontidão. Este documento não é certificação ISO, não é selo, não é parecer jurídico e não declara o tratamento regular perante a ANPD.

## 1. Como ler este relatório

Situação de cada controle:

- **Evidenciado no repositório** — o código ou o documento citado sustenta o controle.
- **Parcial** — há um pedaço e falta outro exigido pela norma.
- **Lacuna** — o controle se aplica ao produto e a evidência não foi encontrada.
- **Pendente de evidência externa** — política, contrato, treinamento ou ato da direção, fora deste repositório.
- **Responsabilidade do provedor** — controle físico de datacenter, a cargo de quem opera a nuvem. A organização ainda precisa do contrato e da região.

Um controle sem evidência permanece lacuna. O auditor não promove lacuna a conformidade.

## 2. Escopo do tratamento

O produto trata telemetria de saúde: frequência cardíaca, variabilidade, temperatura, SpO2, pressão e identificador do paciente, vindos de pulseira ou perfil Bluetooth, pelo companion Android, até `POST /api/v1/wearables/ingest` na API secure, matriz de alertas e painel.

Isso é dado pessoal sensível (LGPD art. 5, II). O laboratório (TCN, conformal, Language v1, hemodinâmica) não entra na resposta do piloto e fica fora do escopo desta auditoria de produto, salvo se um deploy passar a expô-lo.

Papéis que a auditoria precisa receber da direção, e que este repositório não fixa: quem é o controlador, quem é o operador (em especial o provedor de nuvem) e quem é o encarregado.

## 3. Resumo

| Quadro | Evidenciado | Parcial | Lacuna | Evidência externa | Provedor |
|---|---:|---:|---:|---:|---:|
| LGPD | {lgpd_counts[STATUS_EVIDENCED]} | {lgpd_counts[STATUS_PARTIAL]} | {lgpd_counts[STATUS_GAP]} | {lgpd_counts[STATUS_EXTERNAL]} | {lgpd_counts[STATUS_PROVIDER]} |
| ISO/IEC 27001:2022 Anexo A (93 controles) | {iso_counts[STATUS_EVIDENCED]} | {iso_counts[STATUS_PARTIAL]} | {iso_counts[STATUS_GAP]} | {iso_counts[STATUS_EXTERNAL]} | {iso_counts[STATUS_PROVIDER]} |

Achados críticos: {critical}. Achados altos: {high}. O produto não está pronto para certificação ISO/IEC 27001 nem para um relatório de conformidade LGPD fechado. O repositório sustenta o controle técnico da API, o consentimento no companion, a exclusão além da memória, o plano de incidente, o registro de operações, o RIPD e a retenção. Seguem abertos a região `us-central1` e a nomeação do encarregado.

## 4. Inventário mínimo do tratamento

| Item | O que o repositório mostra |
|---|---|
| Titulares | Pacientes do piloto, identificados por `patient_id` |
| Dados | Telemetria vital, identificador de dispositivo, origem do ingest (HTTP, BLE simulado, BLE físico) |
| Operação | {operation} |
| Operadores técnicos | API secure, companion, nuvem na região citada pelo ledger (`us-central1`) |
| Decisão automatizada | Alerta com `decision_support`, sem conduta obrigatória |
| O que não está escrito | {unwritten} |

## 5. Achados

{chr(10).join(finding_md)}

## 6. LGPD — prontidão por artigo

{_table(lgpd, probes)}

{art18_note}

## 7. Declaração de aplicabilidade — ISO/IEC 27001:2022 Anexo A

Títulos em português de trabalho, alinhados ao Anexo A. A SoA que for para um organismo de certificação deve usar a redação da ABNT NBR ISO/IEC 27001:2023 e a justificativa de não aplicabilidade assinada pela direção. Nenhum controle abaixo foi marcado como não aplicável: ou há evidência, ou fica pendente.

{_table(iso, probes)}

Controles físicos (A.7) estão com o provedor de datacenter. A organização continua responsável pelo escritório, pelo descarte de mídia e pelo contrato que cobre essa parte.

## 8. ISO/IEC 27701 — objetivos de privacidade

A ISO/IEC 27701 estende o sistema de gestão para privacidade. Aqui os objetivos estão sem número de cláusula de uma edição específica, para não inventar numeração. Uma certificação PIMS usa a edição vigente no organismo acreditado e a SoA de privacidade correspondente.

{_table(pims, probes)}

## 9. O que uma certificação ainda exige e este relatório não substitui

1. Escopo escrito do sistema de gestão, aprovado pela direção.
2. Análise de riscos e plano de tratamento, com dono e prazo.
3. SoA completa, com justificativa do que for excluído.
4. Políticas de controle de acesso, criptografia, backup, classificação e mesa limpa.
5. Contratos com operadores, inclusive o provedor de nuvem, e o mecanismo do art. 33.
6. Nomeação pública do encarregado e canal do titular.
7. RIPD do tratamento de saúde e registro do art. 37.
8. Procedimento de incidente testado, com comunicação à ANPD e ao titular.
9. Auditoria interna independente e análise crítica da direção.
10. Auditoria de certificação por organismo acreditado pela CGCRE. Este arquivo não é esse certificado.

## 10. Plano de ação sugerido

{plan_md}

## 11. Evidências coletadas nesta execução

{_evidence_lines(probes)}

## 12. Limite

A coleta olha o código e os markdown deste repositório. Não entrevista a direção, não lê contrato com a nuvem, não testa produção e não acessa dado de paciente. Onde a evidência falta, a situação permanece lacuna ou pendência. Repetir a auditoria: `python run_auditoria_lgpd.py`.
"""


def write_report(root: Optional[Path] = None, on: Optional[date] = None) -> Path:
    root = root or ROOT
    today = on or date.today()
    target = root / "docs" / "auditor" / "relatorios" / f"auditoria-lgpd-iso-{today.isoformat()}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(root, today), encoding="utf-8")
    return target
