"""Arquivo que identifica o PC do comprador no formulário privado do Discord."""

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from licenca import normalizar_pc


LIMITE_ARQUIVO = 512
FORMATO = "autofarm-pedido-v1"


@dataclass(frozen=True)
class PedidoPC:
    pc: str
    id: str

    @property
    def nome_arquivo(self):
        return f"pedido-autofarm-{self.id}.json"

    @property
    def nome_licenca(self):
        return f"licenca-autofarm-{self.id}.txt"

    def serializar(self):
        return json.dumps({"formato": FORMATO, "pc": self.pc, "pedido": self.id}).encode("ascii")


def novo_pedido(pc):
    return PedidoPC(normalizar_pc(pc), secrets.token_hex(12))


def ler_pedido(conteudo):
    erro = "Anexe o arquivo .json gerado em «Gerar arquivo do PC» no Auto Farm."
    if not 0 < len(conteudo) <= LIMITE_ARQUIVO:
        raise ValueError(erro)
    try:
        dados = json.loads(conteudo.decode("utf-8"))
        if (not isinstance(dados, dict) or set(dados) != {"formato", "pc", "pedido"}
                or dados["formato"] != FORMATO or not isinstance(dados["pc"], str)
                or not isinstance(dados["pedido"], str) or not re.fullmatch(r"[a-f0-9]{24}", dados["pedido"])):
            raise ValueError
        return PedidoPC(normalizar_pc(dados["pc"]), dados["pedido"])
    except (ValueError, RecursionError) as causa:
        raise ValueError(erro) from causa


def pasta_downloads():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as chave:
            caminho, _ = winreg.QueryValueEx(chave, "{374DE290-123F-4565-9164-39C4925E467B}")
            return Path(os.path.expandvars(caminho))
    except OSError:
        return Path.home() / "Downloads"


def ler_recibo(caminho):
    with caminho.open("rb") as arquivo:
        dados = arquivo.read(LIMITE_ARQUIVO + 1)
    if len(dados) > LIMITE_ARQUIVO or not dados.startswith(b"AFA1.") or not dados.isascii():
        raise ValueError("Escolha o arquivo de licença .txt que o bot devolveu pelo Discord.")
    return dados.decode("ascii").strip()
