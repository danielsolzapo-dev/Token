"""Download verificado e troca do executável após fechar o painel."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from versao import VERSAO

REPO = "danielsolzapo-dev/Token"
ARQUIVO = "AutoFarmTokenPirata.exe"
LIMITE = 250 * 1024 * 1024


@dataclass(frozen=True)
class Release:
    versao: str
    url: str
    tamanho: int
    sha256: str


def numeros(versao):
    if not isinstance(versao, str) or not re.fullmatch(r"[0-9]{1,5}(\.[0-9]{1,5}){2}", versao):
        raise ValueError("A release tem uma versão inválida.")
    return tuple(map(int, versao.split(".")))


def buscar():
    pedido = Request(f"https://api.github.com/repos/{REPO}/releases/latest", headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"AutoFarmTokenPirata/{VERSAO}",
    })
    with urlopen(pedido, timeout=12) as resposta:
        bruto = resposta.read(256 * 1024 + 1)
    if len(bruto) > 256 * 1024:
        raise ValueError("Os dados da release excederam o limite.")
    retorno = json.loads(bruto)
    tag = retorno.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("A release tem uma tag inválida.")
    versao = tag[1:]
    if numeros(versao) <= numeros(VERSAO):
        return None
    url = f"https://github.com/{REPO}/releases/download/{tag}/{ARQUIVO}"
    for ativo in retorno.get("assets", []):
        if ativo.get("name") == ARQUIVO and ativo.get("state") == "uploaded":
            digest, tamanho = ativo.get("digest", ""), ativo.get("size")
            if (ativo.get("browser_download_url") == url and type(tamanho) is int
                    and 0 < tamanho <= LIMITE
                    and isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
                return Release(versao, url, tamanho, digest[7:])
            break
    raise ValueError("O executável da release não contém tamanho e hash verificáveis.")


def baixar(release, pasta):
    preparado = tempfile.NamedTemporaryFile(dir=pasta, prefix=".token-update-", suffix=".exe", delete=False)
    caminho = Path(preparado.name)
    total = 0
    hash_recebido = hashlib.sha256()
    try:
        with preparado, urlopen(release.url, timeout=30) as resposta:
            while bloco := resposta.read(256 * 1024):
                total += len(bloco)
                if total > release.tamanho:
                    raise ValueError("A atualização excedeu o tamanho esperado.")
                preparado.write(bloco)
                hash_recebido.update(bloco)
        if total != release.tamanho or hash_recebido.hexdigest() != release.sha256:
            raise ValueError("A atualização falhou na verificação de integridade.")
        return caminho
    except BaseException:
        caminho.unlink(missing_ok=True)
        raise


def executar(exe, *args):
    subprocess.Popen([str(exe), *map(str, args)], cwd=exe.parent,
                     env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})


def iniciar_troca(preparado, release):
    executar(preparado, "--aplicar-atualizacao", Path(sys.executable).resolve(), release.sha256)


def arquivo_temporario(pasta, caminho):
    caminho = Path(caminho).resolve()
    return caminho.parent == pasta and bool(re.fullmatch(r"\.token-update-[a-z0-9_]+\.exe", caminho.name))


def aplicar_troca(alvo, sha256):
    origem = Path(sys.executable).resolve()
    alvo = Path(alvo).resolve()
    if (not getattr(sys, "frozen", False) or not arquivo_temporario(alvo.parent, origem)
            or origem == alvo or alvo.suffix.lower() != ".exe" or not alvo.is_file()):
        raise ValueError("Destino inválido para atualização.")
    with origem.open("rb") as arquivo:
        if hashlib.file_digest(arquivo, "sha256").hexdigest() != sha256:
            raise ValueError("O executável preparado não passou na verificação de integridade.")
    troca = origem.with_suffix(".swap")
    backup = alvo.with_name(alvo.name + ".previous")
    try:
        shutil.copyfile(origem, troca)
        shutil.copyfile(alvo, backup)
        for tentativa in range(120):
            try:
                os.replace(troca, alvo)
            except PermissionError:
                if tentativa == 119:
                    raise
                time.sleep(0.5)
            else:
                break
        try:
            executar(alvo, "--limpar-atualizacao", origem)
        except OSError:
            os.replace(backup, alvo)
            raise
    finally:
        troca.unlink(missing_ok=True)


def limpar(caminho):
    pasta = Path(sys.executable).resolve().parent
    if not arquivo_temporario(pasta, caminho):
        return
    for _ in range(45):
        try:
            Path(caminho).unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(1)
