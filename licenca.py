"""Chaves de venda, ativação inicial e validação local das licenças do Auto Farm."""

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


CHAVE_PUBLICA = bytes.fromhex("fdd57e5f40516e3016932e0a9e1be3a2f511a1413bd49df6c2f8bf7358b54602")
CHAVE_SERVIDOR = bytes.fromhex("7bfcf0e8d9e6b9ee31747576716227a0bec139569c243110a49e59cc40ba2cfc")
URL_ATIVACAO = "https://autofarm-ativacao-licencas.fancyfern1024.chatgpt.site/ativar"
_FORMATO = b"AutoFarmToken\x00\x01"
_VENDA = b"AutoFarmToken/Venda/v1\x00"
_RECIBO = b"AutoFarmToken/Ativacao/v1\x00"
_FORMATOS = {"AF1": (_FORMATO, 20), "AFV1": (_VENDA, 20), "AFA1": (_RECIBO, 52)}
_TAMANHO_ASSINATURA = 64
_LIMITE_CHAVE = 256
_BRASILIA = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class Licenca:
    pc: str
    expira: date | None
    por_venda: bool = False


def hoje_licenca(por_venda: bool) -> date:
    return datetime.now(_BRASILIA).date() if por_venda else date.today()


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


def carga_venda(dias: int) -> bytes:
    if type(dias) is not int or not 0 <= dias <= 36500:
        raise ValueError("A validade precisa estar entre 1 e 36.500 dias ou ser vitalícia.")
    return _VENDA + secrets.token_bytes(16) + dias.to_bytes(4, "big")


def montar_chave(carga: bytes, assinatura: bytes) -> str:
    if len(assinatura) != _TAMANHO_ASSINATURA:
        raise ValueError("Tamanho de licença inválido.")
    for etiqueta, (marca, tamanho) in _FORMATOS.items():
        if len(carga) == len(marca) + tamanho and carga.startswith(marca):
            dados = base64.urlsafe_b64encode(carga + assinatura).rstrip(b"=").decode("ascii")
            return etiqueta + "." + dados
    raise ValueError("Formato de licença inválido.")


def _abrir_assinada(chave: str, etiqueta: str, publica: bytes) -> bytes:
    prefixo, _, dados = chave.partition(".")
    marca, tamanho = _FORMATOS[etiqueta]
    if prefixo != etiqueta or len(chave) > _LIMITE_CHAVE or not re.fullmatch(r"[a-zA-Z0-9_-]+", dados):
        raise ValueError("Chave inválida. Cole a chave completa enviada pelo vendedor.")
    try:
        bruto = base64.b64decode(dados + "=" * (-len(dados) % 4), altchars=b"-_", validate=True)
        carga, assinatura = bruto[:-_TAMANHO_ASSINATURA], bruto[-_TAMANHO_ASSINATURA:]
        if not carga.startswith(marca) or len(carga) != len(marca) + tamanho or montar_chave(carga, assinatura) != chave:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(publica).verify(assinatura, carga)
    except (binascii.Error, ValueError, InvalidSignature) as erro:
        raise ValueError("Chave inválida. Confira se ela foi copiada por inteiro.") from erro
    return carga[len(marca):]


def verificar_venda(chave: str) -> int:
    dados = _abrir_assinada(chave.strip(), "AFV1", CHAVE_PUBLICA)
    dias = int.from_bytes(dados[-4:], "big")
    if dias > 36500:
        raise ValueError("A chave de venda contém um prazo inválido.")
    return dias


def _licenca_dos_dados(dados: bytes, pc: str, por_venda: bool) -> Licenca:
    vinculo = dados[-20:-4].hex().upper()
    if vinculo != normalizar_pc(pc):
        raise ValueError("Esta chave foi emitida para outro PC.")
    dia = int.from_bytes(dados[-4:], "big")
    if dia > date.max.toordinal():
        raise ValueError("O vencimento da licença é inválido.")
    expira = date.fromordinal(dia) if dia else None
    if expira is not None and hoje_licenca(por_venda) > expira:
        raise ValueError(f"Esta licença venceu em {expira:%d/%m/%Y}. Solicite uma renovação.")
    return Licenca(vinculo, expira, por_venda)


def validar_chave(chave: str, pc: str) -> Licenca:
    chave = chave.strip()
    if chave.startswith("AFA1."):
        return _licenca_dos_dados(_abrir_assinada(chave, "AFA1", CHAVE_SERVIDOR), pc, True)
    return _licenca_dos_dados(_abrir_assinada(chave, "AF1", CHAVE_PUBLICA), pc, False)


class _SemRedirecionar(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def ativar_venda(chave: str, pc: str, *, acesso_servico: str | None = None) -> str:
    chave = chave.strip()
    verificar_venda(chave)
    pc = normalizar_pc(pc)
    requisicao = Request(URL_ATIVACAO, data=json.dumps({"chave": chave, "pc": pc}).encode("utf-8"),
                         headers={"Content-Type": "application/json", "Accept": "application/json",
                                  "User-Agent": "AutoFarm-Ativacao"})
    if acesso_servico:
        requisicao.add_unredirected_header("OAI-Sites-Authorization", "Bearer " + acesso_servico)
    try:
        with build_opener(_SemRedirecionar()).open(requisicao, timeout=12) as resposta:
            corpo = resposta.read(2049)
            if len(corpo) > 2048 or resposta.headers.get_content_type() != "application/json":
                raise OSError("A ativação externa está indisponível. Tente novamente mais tarde.")
    except HTTPError as erro:
        erro.close()
        if erro.code == 409:
            raise ValueError("Esta chave já foi ativada em outro PC.") from None
        if erro.code == 410:
            raise ValueError("Esta licença venceu. Solicite uma renovação.") from None
        if erro.code in (400, 422):
            raise ValueError("O servidor recusou a chave de venda. Confira a chave recebida.") from None
        if erro.code in (301, 302, 303, 307, 308, 401, 403):
            raise OSError("A ativação externa está indisponível. Consulte o vendedor.") from None
        raise OSError("O servidor de ativação está indisponível. Tente novamente.") from None
    except (URLError, TimeoutError, HTTPException, ConnectionError) as erro:
        raise OSError("Não foi possível contatar o servidor. Confira a internet e tente novamente.") from erro
    try:
        recibo = json.loads(corpo)["licenca"]
        if not isinstance(recibo, str):
            raise ValueError
        dados = _abrir_assinada(recibo, "AFA1", CHAVE_SERVIDOR)
        if dados[:32] != hashlib.sha256(chave.encode("ascii")).digest():
            raise ValueError
    except (ValueError, KeyError, TypeError) as erro:
        raise ValueError("O servidor devolveu um comprovante de ativação inválido.") from erro
    _licenca_dos_dados(dados, pc, True)
    return recibo


def _arquivo_ativacao() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "AutoFarmToken" / "licenca.txt"


def ler_chave() -> str:
    try:
        with _arquivo_ativacao().open(encoding="ascii") as arquivo:
            return arquivo.read(_LIMITE_CHAVE + 1).strip()
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
