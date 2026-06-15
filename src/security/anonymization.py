import copy
import hashlib
import os
from dotenv import load_dotenv

load_dotenv()

def anonimizar_paciente_fhir(paciente_fhir: dict) -> dict:
    """
    Descaracteriza Informações Pessoais Identificáveis (PII) de um recurso FHIR 'Patient'.
    """
    paciente_anonimizado = copy.deepcopy(paciente_fhir)
    
    # 1. Remover Nomes Explícitos
    if 'name' in paciente_anonimizado:
        del paciente_anonimizado['name']
        
    # 2. Ofuscar Data de Nascimento (manter apenas o ano)
    if 'birthDate' in paciente_anonimizado:
        ano = paciente_anonimizado['birthDate'].split('-')[0]
        paciente_anonimizado['birthDate'] = f"{ano}-01-01"
        
    # 3. Remover Contatos de Telecomunicação
    if 'telecom' in paciente_anonimizado:
        del paciente_anonimizado['telecom']
        
    # 4. Anonimizar Identificadores (com Hash Determinístico Longitudinal)
    if 'identifier' in paciente_anonimizado:
        # Pega o primeiro identificador
        id_original = str(paciente_anonimizado['identifier'][0].get('value', ''))
        salt = os.getenv("SECRET_SALT", "default-salt")
        hash_id = hashlib.sha256((id_original + salt).encode('utf-8')).hexdigest()
        paciente_anonimizado['identifier'] = [{'system': 'urn:uuid', 'value': hash_id}]
        
    # 5. Generalizar Endereço
    if 'address' in paciente_anonimizado:
        para_manter = []
        for addr in paciente_anonimizado['address']:
            novo_addr = {}
            if 'city' in addr: novo_addr['city'] = addr['city']
            if 'state' in addr: novo_addr['state'] = addr['state']
            if 'country' in addr: novo_addr['country'] = addr['country']
            para_manter.append(novo_addr)
        paciente_anonimizado['address'] = para_manter

    return paciente_anonimizado
