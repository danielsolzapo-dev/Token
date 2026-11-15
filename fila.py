"""Acompanha o clique em Jogar e a transição observada na tela."""
from dataclasses import dataclass


@dataclass
class Fila:
    tentativas: int = 0
    clique_em: float | None = None
    confirmou: bool = False
    aviso_tentativas: bool = False
    jogar_visivel: bool = False

    def atualizar(self, estaveis):
        jogar = "jogar" in estaveis
        if estaveis & {"fila_ativa", "partida", "onibus"}:
            confirmou_agora = self.clique_em is not None and not self.confirmou
            self.confirmou = True
            self.tentativas = 0
            self.aviso_tentativas = False
        elif jogar:
            confirmou_agora = False
            if self.confirmou:
                self.reiniciar()
        else:
            confirmou_agora = False
        self.jogar_visivel = jogar
        return confirmou_agora

    def pode_clicar(self, agora):
        return self.jogar_visivel and self.tentativas < 3 and (
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
        self.aviso_tentativas = False
