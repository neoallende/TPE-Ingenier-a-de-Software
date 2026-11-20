"""JWT HS256 mínimo con HMAC (mismo estilo que la firma del webhook). ADR-020, D5."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

ROLES = ("user", "admin")


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    sub: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _json(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()


def _sign(signing_input: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())


def issue_token(sub: str, role: str, secret: str, ttl_seconds: int, now) -> str:
    if not sub or role not in ROLES:
        raise ValueError("sub vacío o rol inválido")
    iat = int(now.timestamp())
    payload = {"sub": sub, "role": role, "iat": iat, "exp": iat + ttl_seconds}
    signing = f"{_b64e(_json({'alg': 'HS256', 'typ': 'JWT'}))}.{_b64e(_json(payload))}"
    return f"{signing}.{_sign(signing, secret)}"


def verify_token(token: str, secret: str, now) -> Principal:
    try:
        head_b64, payload_b64, sig = token.split(".")
        header = json.loads(_b64d(head_b64))
        payload = json.loads(_b64d(payload_b64))
    except Exception as exc:
        raise AuthError("token malformado") from exc
    if header.get("alg") != "HS256":
        raise AuthError("algoritmo no permitido")
    expected = _sign(f"{head_b64}.{payload_b64}", secret)
    if not hmac.compare_digest(expected, sig):
        raise AuthError("firma inválida")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= int(now.timestamp()):
        raise AuthError("token vencido")
    sub, role = payload.get("sub"), payload.get("role")
    if not isinstance(sub, str) or not sub or role not in ROLES:
        raise AuthError("claims inválidos")
    return Principal(sub, role)
