import copy
import hashlib
from typing import Any, Dict


def gerar_id_anonimo(dados_originais: str) -> str:
    """
    Gera um ID anônimo determinístico usando hash SHA-256.
    
    Args:
        dados_originais: String original para gerar o hash.
        
    Returns:
        Hash hexadecimal truncado para 16 caracteres.
    """
    return hashlib.sha256(dados_originais.encode()).hexdigest()[:16]


def anonimizar_paciente_fhir(paciente_fhir: Dict[str, Any]) -> Dict[str, Any]:
    """
    Descaracteriza Informações Pessoais Identificáveis (PII) de um recurso FHIR 'Patient'.
    
    Aplica as seguintes transformações:
    - Remove nomes explícitos
    - Ofusca data de nascimento (mantém apenas ano)
    - Remove contatos de telecomunicação
    - Substitui identificadores por ID anônimo derivado do original
    - Generaliza endereço (mantém apenas cidade, estado e país)
    
    Args:
        paciente_fhir: Dicionário representando recurso FHIR Patient com PII.
        
    Returns:
        Cópia anonimizada do recurso FHIR.
    """
    paciente_anonimizado = copy.deepcopy(paciente_fhir)
    
    # 1. Remover Nomes Explícitos
    paciente_anonimizado.pop('name', None)
        
    # 2. Ofuscar Data de Nascimento (manter apenas o ano)
    if 'birthDate' in paciente_anonimizado and paciente_anonimizado['birthDate']:
        ano = paciente_anonimizado['birthDate'].split('-')[0]
        paciente_anonimizado['birthDate'] = f"{ano}-01-01"
        
    # 3. Remover Contatos de Telecomunicação
    paciente_anonimizado.pop('telecom', None)
        
    # 4. Anonimizar Identificadores (gerar ID derivado do original para rastreabilidade)
    if 'identifier' in paciente_anonimizado and paciente_anonimizado['identifier']:
        id_original = paciente_anonimizado['identifier'][0].get('value', '')
        id_anonimo = gerar_id_anonimo(id_original)
        paciente_anonimizado['identifier'] = [
            {'system': 'urn:uuid', 'value': f'ANON-{id_anonimo}'}
        ]
        
    # 5. Generalizar Endereço (manter apenas informações de baixo risco)
    if 'address' in paciente_anonimizado:
        enderecos_generalizados = []
        for addr in paciente_anonimizado['address']:
            endereco_minimo = {}
            if addr.get('city'):
                endereco_minimo['city'] = addr['city']
            if addr.get('state'):
                endereco_minimo['state'] = addr['state']
            if addr.get('country'):
                endereco_minimo['country'] = addr['country']
            if endereco_minimo:
                enderecos_generalizados.append(endereco_minimo)
        paciente_anonimizado['address'] = enderecos_generalizados

    return paciente_anonimizado
