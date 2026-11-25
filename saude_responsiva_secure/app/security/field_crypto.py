"""Criptografia de campos em repouso (R8) — envelope AES-256-GCM.

A chave de dados (DEK) vem de ``FIELD_ENCRYPTION_KEY`` (Secret Manager injeta
a env no Cloud Run). Cada valor cifrado carrega o key id, para rotação.

Formato (texto, versionado)::

    enc1:<key_id>:<nonce_b64url>:<ciphertext_b64url>

O ciphertext inclui a tag GCM (16 bytes). O AAD amarra o valor ao nome do
campo. Sem a env, ``protect``/``seal_json`` devolvem o texto original e
``open_*`` continuam lendo legado em claro.

Índice cego (busca por identificador)::

    bi1.<hmac_sha256_hex>

A chave do HMAC é ``FIELD_BLIND_INDEX_KEY`` (obrigatória em produção).
Sem ela, em desenvolvimento, deriva por HKDF da DEK ativa — rotação da DEK
nesse modo troca o índice.

Cloud KMS é opcional. Com ``FIELD_ENCRYPTION_KMS_KEY``, o valor de
``FIELD_ENCRYPTION_KEY`` é a DEK embrulhada (ciphertext KMS em base64) e
é desempacotada uma vez no processo. Sem a env, a DEK é usada direto.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_KID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TOKEN_PREFIX = "enc1:"
_BLIND_PREFIX = "bi1."
_AAD_PREFIX = "healthtech-r8|"
_PRODUCTION = frozenset({"production", "prod", "staging"})

_KMSUnwrap = Callable[[str, str], bytes]
_kms_unwrap: Optional[_KMSUnwrap] = None
_cache: Dict[str, Any] = {"token": None, "ring": None}


class FieldCryptoError(RuntimeError):
    """Configuração ou abertura inválida. A mensagem não traz chave nem PHI."""


@dataclass(frozen=True)
class KeyRing:
    active_id: str
    active_key: bytes
    keys: Dict[str, bytes]
    blind_key: bytes
    kms: bool


def reset_cache() -> None:
    """Limpa o cache do processo (testes e troca de env)."""
    _cache["token"] = None
    _cache["ring"] = None


def set_kms_unwrap_for_tests(fn: Optional[_KMSUnwrap]) -> None:
    """Substitui a chamada ao Cloud KMS. ``None`` restaura o cliente real."""
    global _kms_unwrap
    _kms_unwrap = fn
    reset_cache()


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _is_production() -> bool:
    return _env("ENVIRONMENT").lower() in _PRODUCTION


def _configured() -> bool:
    return bool(_env("FIELD_ENCRYPTION_KEY") or _env("FIELD_ENCRYPTION_KMS_KEY"))


def _env_token() -> str:
    names = (
        "FIELD_ENCRYPTION_KEY",
        "FIELD_ENCRYPTION_KEY_ID",
        "FIELD_ENCRYPTION_KEYS",
        "FIELD_ENCRYPTION_KMS_KEY",
        "FIELD_BLIND_INDEX_KEY",
        "ENVIRONMENT",
    )
    return "\n".join(_env(name) for name in names)


def _validate_kid(kid: str) -> str:
    if not _KID_RE.fullmatch(kid or ""):
        raise FieldCryptoError(
            "FIELD_ENCRYPTION_KEY_ID inválido. Use 1–32 caracteres [A-Za-z0-9._-]."
        )
    return kid


def parse_key_material(raw: str) -> bytes:
    """32 bytes em base64 (padrão ou urlsafe) ou em hex de 64 caracteres."""
    text = (raw or "").strip()
    if not text:
        raise FieldCryptoError("material de chave vazio")
    if _HEX_KEY_RE.fullmatch(text):
        return bytes.fromhex(text)
    pad = "=" * (-len(text) % 4)
    decoded = b""
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(text + pad)
        except Exception:
            decoded = b""
        if len(decoded) == 32:
            return decoded
    raise FieldCryptoError(
        "chave deve ter exatamente 32 bytes (openssl rand -base64 32 ou openssl rand -hex 32)"
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode((data or "") + pad)
    except Exception as exc:
        raise FieldCryptoError("ciphertext malformado") from exc


def _aad(field: str) -> bytes:
    name = (field or "").strip()
    if not name or len(name) > 80 or any(ord(ch) < 32 for ch in name):
        raise FieldCryptoError("nome de campo inválido para AAD")
    return f"{_AAD_PREFIX}{name}".encode("utf-8")


def is_ciphertext(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(_TOKEN_PREFIX):
        return False
    parts = value.split(":")
    return len(parts) == 4 and bool(parts[1] and parts[2] and parts[3])


def _parse_additional_keys(raw: str) -> Dict[str, bytes]:
    keys: Dict[str, bytes] = {}
    text = (raw or "").strip()
    if not text:
        return keys
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise FieldCryptoError(
                "FIELD_ENCRYPTION_KEYS deve ser id:material, separado por vírgula"
            )
        kid, material = item.split(":", 1)
        kid = _validate_kid(kid.strip())
        key = parse_key_material(material.strip())
        previous = keys.get(kid)
        if previous is not None and not hmac.compare_digest(previous, key):
            raise FieldCryptoError("key id repetido com material diferente")
        keys[kid] = key
    return keys


def _unwrap_with_kms(wrapped: str, key_name: str) -> bytes:
    if _kms_unwrap is not None:
        dek = _kms_unwrap(wrapped, key_name)
        if not isinstance(dek, (bytes, bytearray)) or len(dek) != 32:
            raise FieldCryptoError("unwrap de teste não devolveu 32 bytes")
        return bytes(dek)
    try:
        from google.cloud import kms
    except ImportError as exc:
        raise FieldCryptoError(
            "FIELD_ENCRYPTION_KMS_KEY definido, mas google-cloud-kms não está instalado"
        ) from exc
    try:
        ciphertext = base64.b64decode(wrapped)
    except Exception as exc:
        raise FieldCryptoError("FIELD_ENCRYPTION_KEY não é base64 da DEK embrulhada") from exc
    client = kms.KeyManagementServiceClient()
    response = client.decrypt(request={"name": key_name, "ciphertext": ciphertext})
    dek = bytes(response.plaintext)
    if len(dek) != 32:
        raise FieldCryptoError("DEK desempacotada pelo Cloud KMS não tem 32 bytes")
    return dek


def _blind_key(dek: bytes) -> bytes:
    explicit = _env("FIELD_BLIND_INDEX_KEY")
    if explicit:
        return parse_key_material(explicit)
    if _is_production():
        raise FieldCryptoError(
            "Em produção defina FIELD_BLIND_INDEX_KEY separada da DEK "
            "(openssl rand -base64 32). Sem ela, rodar a DEK troca o índice cego."
        )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"healthtech-r8-blind-index",
        info=b"blind-index-v1",
    ).derive(dek)


def _load_ring() -> KeyRing:
    kms_name = _env("FIELD_ENCRYPTION_KMS_KEY")
    material = _env("FIELD_ENCRYPTION_KEY")
    if kms_name:
        if not material:
            raise FieldCryptoError(
                "FIELD_ENCRYPTION_KMS_KEY exige FIELD_ENCRYPTION_KEY com a DEK embrulhada"
            )
        dek = _unwrap_with_kms(material, kms_name)
    else:
        if not material:
            raise FieldCryptoError("FIELD_ENCRYPTION_KEY ausente")
        dek = parse_key_material(material)
    kid = _validate_kid(_env("FIELD_ENCRYPTION_KEY_ID") or "v1")
    keys = _parse_additional_keys(_env("FIELD_ENCRYPTION_KEYS"))
    previous = keys.get(kid)
    if previous is not None and not hmac.compare_digest(previous, dek):
        raise FieldCryptoError(
            "FIELD_ENCRYPTION_KEYS repete o key id ativo com outro material"
        )
    keys[kid] = dek
    return KeyRing(
        active_id=kid,
        active_key=dek,
        keys=keys,
        blind_key=_blind_key(dek),
        kms=bool(kms_name),
    )


def get_ring() -> Optional[KeyRing]:
    """Anel de chaves, ou ``None`` se a criptografia está desligada."""
    if not _configured():
        return None
    token = _env_token()
    if _cache["token"] == token and _cache["ring"] is not None:
        return _cache["ring"]
    ring = _load_ring()
    _cache["token"] = token
    _cache["ring"] = ring
    return ring


def is_enabled() -> bool:
    """True só quando há DEK carregável. Chave inválida levanta ``FieldCryptoError``."""
    if not _configured():
        return False
    get_ring()
    return True


def validate_startup() -> None:
    """Falha o boot se a chave existe mas está incompleta ou inválida."""
    if _configured():
        get_ring()


def describe_status() -> str:
    """Uma linha para o log de boot. Não inclui material de chave."""
    if not _configured():
        return (
            "desligada (FIELD_ENCRYPTION_KEY vazia; "
            "leituras legadas em claro continuam válidas)"
        )
    ring = get_ring()
    assert ring is not None
    kms = "sim" if ring.kms else "não"
    return (
        f"ligada key_id={ring.active_id} "
        f"chaves_de_leitura={len(ring.keys)} kms={kms}"
    )


def protect(plaintext: str, *, aad: str) -> str:
    """Cifra uma string. Token já cifrado volta igual (idempotente)."""
    if not isinstance(plaintext, str):
        raise FieldCryptoError("protect recebe texto")
    if is_ciphertext(plaintext):
        return plaintext
    ring = get_ring()
    if ring is None:
        return plaintext
    nonce = os.urandom(12)
    ciphertext = AESGCM(ring.active_key).encrypt(nonce, plaintext.encode("utf-8"), _aad(aad))
    return f"{_TOKEN_PREFIX}{ring.active_id}:{_b64(nonce)}:{_b64(ciphertext)}"


def open_field(value: str, *, aad: str) -> str:
    """Abre um token ``enc1``. Texto sem o prefixo (legado) volta intacto."""
    if not isinstance(value, str) or not is_ciphertext(value):
        return value
    _prefix, kid, nonce_b64, ct_b64 = value.split(":")
    ring = get_ring()
    if ring is None:
        raise FieldCryptoError("dado cifrado sem FIELD_ENCRYPTION_KEY")
    key = ring.keys.get(kid)
    if key is None:
        raise FieldCryptoError("key id desconhecido para o dado cifrado")
    try:
        opened = AESGCM(key).decrypt(_b64d(nonce_b64), _b64d(ct_b64), _aad(aad))
    except Exception as exc:
        raise FieldCryptoError("falha ao abrir campo cifrado") from exc
    try:
        return opened.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FieldCryptoError("campo cifrado não é texto") from exc


def seal_text(value: Optional[str], *, aad: str) -> Optional[str]:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if is_ciphertext(text) or not is_enabled():
        return text
    return protect(text, aad=aad)


def open_text(value: Any, *, aad: str) -> Any:
    if isinstance(value, str) and is_ciphertext(value):
        return open_field(value, aad=aad)
    return value


def seal_json(obj: Any, *, aad: str) -> str:
    """JSON em claro, ou ``{"_enc": "enc1:..."}`` quando a chave está ligada.

    O invólucro é JSON válido para colunas ``json``/``jsonb`` já existentes.
    """
    raw = json.dumps(obj, default=str)
    if not is_enabled():
        return raw
    return json.dumps({"_enc": protect(raw, aad=aad)}, separators=(",", ":"))


def open_json_value(value: Any, *, aad: str) -> Any:
    """Desfaz ``seal_json``. Dict/list legado volta sem alteração."""
    if isinstance(value, dict) and set(value.keys()) == {"_enc"} and isinstance(value.get("_enc"), str):
        return json.loads(open_field(value["_enc"], aad=aad))
    if isinstance(value, str):
        if is_ciphertext(value):
            return json.loads(open_field(value, aad=aad))
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, dict) and set(parsed.keys()) == {"_enc"} and isinstance(parsed.get("_enc"), str):
            return json.loads(open_field(parsed["_enc"], aad=aad))
        return parsed
    return value


def blind_index(value: str, *, context: str) -> str:
    """HMAC-SHA256 determinístico. ``context`` separa paciente de dispositivo."""
    if not isinstance(value, str) or value == "":
        raise FieldCryptoError("índice cego exige texto")
    ctx = (context or "").strip()
    if not ctx:
        raise FieldCryptoError("índice cego exige contexto")
    ring = get_ring()
    if ring is None:
        raise FieldCryptoError("índice cego sem FIELD_ENCRYPTION_KEY")
    digest = hmac.new(
        ring.blind_key,
        f"{ctx}|{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _BLIND_PREFIX + digest


def is_blind_index(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_BLIND_PREFIX) and len(value) == 4 + 64
