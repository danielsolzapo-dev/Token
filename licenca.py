"""Ativação offline das distribuições Windows do Auto Farm."""

import base64
import binascii
import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


CHAVE_PUBLICA = bytes.fromhex("fdd57e5f40516e3016932e0a9e1be3a2f511a1413bd49df6c2f8bf7358b54602")
_FORMATO = b"AutoFarmToken\x00\x01"
_TAMANHO_CARGA = len(_FORMATO) + 16 + 4
_TAMANHO_ASSINATURA = 64


@dataclass(frozen=True)
class Licenca:
    pc: str
    expira: date | None


def normalizar_pc(texto: str) -> str:
    codigo = re.sub(r"[\s-]+", "", texto).upper()
    if not re.fullmatch(r"[0-9A-F]{32}", codigo):
        raise ValueError("O código do PC deve conter 32 caracteres hexadecimais.")
    return codigo


def _codigo_do_guid(valor: str) -> str:
    guid = uuid.UUID(valor)
    if guid.int == 0:
        raise ValueError("Identificador do Windows vazio.")
    return hashlib.sha256(b"AutoFarmToken/PC/v1\x00" + guid.bytes).digest()[:16].hex().upper()


def codigo_pc() -> str:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
            access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as chave:
            guid, tipo = winreg.QueryValueEx(chave, "MachineGuid")
        if tipo != winreg.REG_SZ:
            raise ValueError("Tipo de identificador inesperado.")
        return _codigo_do_guid(guid)
    except (OSError, ValueError) as erro:
        raise ValueError("Não foi possível ler o identificador deste Windows.") from erro


def carga_licenca(pc: str, expira: date | None) -> bytes:
    dia = 0 if expira is None else expira.toordinal()
    return _FORMATO + bytes.fromhex(normalizar_pc(pc)) + dia.to_bytes(4, "big")


def montar_chave(carga: bytes, assinatura: bytes) -> str:
    if len(carga) != _TAMANHO_CARGA or len(assinatura) != _TAMANHO_ASSINATURA:
        raise ValueError("Tamanho de licença inválido.")
    dados = base64.urlsafe_b64encode(carga + assinatura).rstrip(b"=").decode("ascii")
    return "AF1." + dados


def validar_chave(chave: str, pc: str) -> Licenca:
    chave = chave.strip()
    if len(chave) > 200 or not re.fullmatch(r"AF1\.[a-zA-Z0-9_-]+", chave):
        raise ValueError("Chave inválida. Cole a chave completa enviada pelo vendedor.")
    dados = chave[4:]
    try:
        bruto = base64.b64decode(dados + "=" * (-len(dados) % 4), altchars=b"-_", validate=True)
        carga, assinatura = bruto[:_TAMANHO_CARGA], bruto[_TAMANHO_CARGA:]
        if not carga.startswith(_FORMATO) or montar_chave(carga, assinatura) != chave:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(CHAVE_PUBLICA).verify(assinatura, carga)
        dia = int.from_bytes(carga[-4:], "big")
        expira = date.fromordinal(dia) if dia else None
    except (binascii.Error, ValueError, InvalidSignature, OverflowError) as erro:
        raise ValueError("Chave inválida. Confira se ela foi copiada por inteiro.") from erro
    vinculo = carga[len(_FORMATO):-4].hex().upper()
    if vinculo != normalizar_pc(pc):
        raise ValueError("Esta chave foi emitida para outro PC.")
    if expira is not None and date.today() > expira:
        raise ValueError(f"Esta licença venceu em {expira:%d/%m/%Y}. Solicite uma renovação.")
    return Licenca(vinculo, expira)


def _arquivo_ativacao() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "AutoFarmToken" / "licenca.txt"


def ler_chave() -> str:
    try:
        with _arquivo_ativacao().open(encoding="ascii") as arquivo:
            return arquivo.read(201).strip()
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def salvar_chave(chave: str) -> None:
    arquivo = _arquivo_ativacao()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    descritor, nome = tempfile.mkstemp(dir=arquivo.parent, prefix=".licenca-", suffix=".tmp")
    try:
        with os.fdopen(descritor, "w", encoding="ascii") as temporario:
            temporario.write(chave.strip())
            temporario.flush()
            os.fsync(temporario.fileno())
        os.replace(nome, arquivo)
    finally:
        Path(nome).unlink(missing_ok=True)
