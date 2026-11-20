"""Confirma o último sobrevivente em leituras independentes do HUD."""

from contagem_partida import ContadorPartida
from hud_esquadrao import aguardando_jogadores, ler_esquadrao


class Sobreviventes:
    def __init__(self):
        self.contador = None
        self.reiniciar()

    def reiniciar(self):
        self.maior_equipe = 0
        self.equipe_com_vivos = 0
        self.interromper()

    def interromper(self):
        self.ultima_amostra = None
        self.tamanho_em_observacao = 0
        self.motivo = None
        self.confirmacoes = 0
        self.equipe = None
        self.jogadores = None

    def verificar(self, quadro, agora):
        if self.ultima_amostra is not None:
            intervalo = agora - self.ultima_amostra
            if intervalo < 1:
                return None
            if intervalo > 6:
                self.interromper()
        if aguardando_jogadores(quadro):
            self.reiniciar()
            self.ultima_amostra = agora
            return None
        self.ultima_amostra = agora
        if self.contador is None:
            self.contador = ContadorPartida()
        self.equipe = equipe = ler_esquadrao(quadro)
        self.jogadores = self.contador.ler(quadro)
        self.maior_equipe = max(self.maior_equipe, equipe.presentes)
        if equipe.vivos and equipe.vivos + equipe.eliminados == equipe.presentes:
            if self.tamanho_em_observacao == equipe.presentes:
                self.equipe_com_vivos = max(self.equipe_com_vivos, equipe.presentes)
            self.tamanho_em_observacao = equipe.presentes
        else:
            self.tamanho_em_observacao = 0

        motivo = None
        if (equipe.eliminados > 0 and equipe.eliminados == equipe.presentes == self.maior_equipe
                and (equipe.presentes == 3 or equipe.presentes == self.equipe_com_vivos)):
            motivo = "ultimo_vivo_no_esquadrao"
        elif self.jogadores == 1 and equipe.vivos == 0:
            motivo = "ultimo_vivo_na_partida"
        if motivo is None or motivo != self.motivo:
            self.confirmacoes = 0
        self.motivo = motivo
        if motivo:
            self.confirmacoes += 1
        return motivo if self.confirmacoes >= 3 else None
