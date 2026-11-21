"""Seleciona replays concluídos e chama o leitor local de baús."""

import atexit
from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
import subprocess
import threading


LEITOR = Path(__file__).resolve().parent / "leitor_replay" / "binario" / "LeitorBaus.exe"


@dataclass(frozen=True)
class ContagemBaus:
    voce: int | None
    esquadrao: int | None
    detalhe: str


def pasta_replays():
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "FortniteGame" / "Saved" / "Demos"


def _em_gravacao(caminho):
    # Cabeçalho da gravação local. A flag vem após o FString
    # do nome de exibição, com comprimento em bytes ou em unidades UTF-16.
    with caminho.open("rb") as arquivo:
        def inteiro():
            dados = arquivo.read(4)
            if len(dados) != 4:
                raise ValueError("O cabeçalho do replay está incompleto.")
            return struct.unpack("<i", dados)[0]

        if inteiro() != 0x1CA2E27F:
            raise ValueError("O arquivo não tem o cabeçalho de um replay do Fortnite.")
        versao = inteiro()
        if not 4 <= versao <= 7:
            raise ValueError(f"O leitor ainda não reconhece o formato {versao} deste replay.")
        if versao >= 7:
            versoes = inteiro()
            if versoes < 0:
                raise ValueError("O índice de versões do replay é inválido.")
            arquivo.seek(versoes * 20, 1)
        arquivo.seek(12, 1)
        tamanho_nome = inteiro()
        arquivo.seek(tamanho_nome if tamanho_nome >= 0 else -2 * tamanho_nome, 1)
        flag = inteiro()
        if flag not in (0, 1):
            raise ValueError("O estado da gravação é inválido.")
        return bool(flag)


def ultimo_replay():
    candidatos = []
    for caminho in pasta_replays().glob("*.replay"):
        try:
            candidatos.append((caminho.stat().st_mtime_ns, caminho))
        except OSError:
            continue
    for _, caminho in sorted(candidatos, reverse=True):
        try:
            if not _em_gravacao(caminho):
                return caminho
        except (ValueError, OSError):
            continue
    raise ValueError("Nenhum replay concluído e compatível na pasta Demos. Ative a gravação de replays no Fortnite ou escolha um arquivo.")


_processos = set()
_trava = threading.Lock()
_encerrando = False


@atexit.register
def _encerrar_leitores():
    global _encerrando
    with _trava:
        _encerrando = True
        for processo in _processos:
            if processo.poll() is None:
                processo.kill()
                processo.wait()


def _executar(argumento):
    with _trava:
        if _encerrando:
            raise ValueError("O aplicativo está fechando.")
        if not LEITOR.is_file():
            raise ValueError("Leitor de baús ausente. Reinstale o aplicativo ou compile o leitor ao executar pelo código-fonte.")
        processo = subprocess.Popen(
            [str(LEITOR), str(argumento)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _processos.add(processo)
    try:
        try:
            saida, _ = processo.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            processo.kill()
            processo.communicate()
            raise ValueError("O replay excedeu cinco minutos de análise. Tente outra gravação.") from None
        if processo.returncode:
            raise ValueError("O leitor foi interrompido antes de concluir a análise.")
    finally:
        with _trava:
            _processos.discard(processo)
    try:
        dados = json.loads(saida)
    except ValueError:
        dados = None
    if not isinstance(dados, dict):
        raise ValueError("O leitor devolveu uma resposta inválida.")
    if isinstance(dados.get("erro"), str):
        raise ValueError(dados["erro"])
    if type(dados.get("protocolo")) is not int or dados["protocolo"] != 1:
        raise ValueError("Versão de leitor incompatível. Atualize o aplicativo.")
    return dados


def verificar_leitor():
    _executar("--verificar-build")


def analisar_replay(caminho):
    caminho = Path(caminho).resolve()
    if caminho.suffix.casefold() != ".replay" or not caminho.is_file():
        raise ValueError("Selecione um arquivo .replay existente.")
    antes = caminho.stat()
    if _em_gravacao(caminho):
        raise ValueError("O Fortnite ainda está gravando esta partida. Aguarde o fim do replay.")
    dados = _executar(caminho)
    depois = caminho.stat()
    if (antes.st_size, antes.st_mtime_ns) != (depois.st_size, depois.st_mtime_ns):
        raise ValueError("O arquivo mudou durante a leitura. Aguarde a gravação terminar e tente novamente.")
    for campo in ("voce", "esquadrao"):
        if campo not in dados or not (dados[campo] is None or type(dados[campo]) is int and dados[campo] >= 0):
            raise ValueError("O leitor devolveu uma contagem inválida.")
    if dados["voce"] is not None and dados["esquadrao"] is not None and dados["esquadrao"] < dados["voce"]:
        raise ValueError("O total do esquadrão é menor que a contagem individual.")
    if not isinstance(dados.get("detalhe"), str):
        raise ValueError("O leitor não informou a cobertura da análise.")
    return ContagemBaus(dados["voce"], dados["esquadrao"], dados["detalhe"])
