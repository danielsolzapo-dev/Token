"""Acompanha o clique em Jogar e a transição observada na tela."""
import os
import re
from dataclasses import dataclass
from pathlib import Path


EVENTO_PAREAMENTO = re.compile(
    rb"LogMatchmaking:.*?Matchmaking Service State Changed From \w+ to (?:Registering|Registered|Assigned)\b"
)
EVENTO_ENTRADA = b"Game state set server entry confirmed. Signaling PostTravel."


class DiarioFortnite:
    """Lê apenas eventos novos e retorna nomes de estado, sem incluir linhas do jogo."""

    def __init__(self, caminho=None):
        local = os.environ.get("LOCALAPPDATA")
        self.caminho = caminho or (Path(local) / "FortniteGame/Saved/Logs/FortniteGame.log" if local else None)
        self.identidade = None
        self.posicao = 0
        self.restante = b""
        if self.caminho:
            try:
                info = self.caminho.stat()
            except OSError:
                return
            self.identidade = (info.st_dev, info.st_ino)
            self.posicao = info.st_size

    def ler(self):
        if not self.caminho:
            return set()
        try:
            with self.caminho.open("rb") as arquivo:
                info = os.fstat(arquivo.fileno())
                identidade = (info.st_dev, info.st_ino)
                if identidade != self.identidade or info.st_size < self.posicao:
                    self.identidade = identidade
                    self.posicao = 0
                    self.restante = b""
                arquivo.seek(self.posicao)
                dados = arquivo.read(512 * 1024)
                self.posicao = arquivo.tell()
        except OSError:
            return set()
        if not dados:
            return set()
        *linhas, final = (self.restante + dados).split(b"\n")
        self.restante = final[-8192:]
        eventos = set()
        for linha in linhas:
            if EVENTO_PAREAMENTO.search(linha):
                eventos.add("fila_ativa")
            if b"LogMatchmaking:" in linha and EVENTO_ENTRADA in linha:
                eventos.add("partida")
        return eventos


@dataclass
class Fila:
    tentativas: int = 0
    clique_em: float | None = None
    confirmou: bool = False
    saiu_do_lobby: bool = False
    aviso_tentativas: bool = False
    jogar_visivel: bool = False

    def atualizar(self, estaveis):
        jogar = "jogar" in estaveis
        if estaveis & {"fila_ativa", "partida", "onibus"}:
            confirmou_agora = self.clique_em is not None and not self.confirmou
            self.confirmou = True
            self.saiu_do_lobby |= not jogar
            self.tentativas = 0
            self.aviso_tentativas = False
        elif jogar:
            confirmou_agora = False
            if self.confirmou and self.saiu_do_lobby:
                self.reiniciar()
        else:
            confirmou_agora = False
            if self.confirmou:
                self.saiu_do_lobby = True
        self.jogar_visivel = jogar
        return confirmou_agora

    def pode_clicar(self, agora):
        return self.jogar_visivel and not self.confirmou and self.tentativas < 3 and (
            self.clique_em is None or agora - self.clique_em >= 7
        )

    def registrar_clique(self, agora):
        self.tentativas += 1
        self.clique_em = agora

    def desistiu(self, agora):
        if (self.jogar_visivel and self.tentativas >= 3 and not self.aviso_tentativas
                and agora - self.clique_em >= 7):
            self.aviso_tentativas = True
            return True
        return False

    def reiniciar(self):
        self.tentativas = 0
        self.clique_em = None
        self.confirmou = False
        self.saiu_do_lobby = False
        self.aviso_tentativas = False
