"""Decisões da rotina aérea com base nos avisos visíveis do jogo."""


class Embarque:
    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.saltou_em = None
        self.fechou_asa = False
        self.fechou_em = None
        self.voltas_movimento = 0
        self.proximo_movimento = 0.0
        self.pausar()

    def pausar(self):
        self.quadros_onibus = 0
        self.quadros_asa = 0

    def observar(self, *, onibus, asa):
        self.quadros_onibus = self.quadros_onibus + 1 if onibus else 0
        if onibus:
            self.quadros_asa = 0
            if self.saltou_em is not None:
                return None
            return "saltar_onibus" if self.quadros_onibus >= 2 else None
        self.quadros_asa = self.quadros_asa + 1 if asa else 0
        return "fechar_asa" if not self.fechou_asa and self.quadros_asa >= 2 else None

    def registrar(self, tipo, enviado, agora):
        if not enviado:
            self.pausar()
        elif tipo == "saltar_onibus":
            self.saltou_em = agora
            self.proximo_movimento = agora + 0.25
        elif tipo == "fechar_asa":
            self.fechou_asa = True
            self.fechou_em = agora
        elif tipo == "movimento_aereo":
            self.voltas_movimento += 1
            self.proximo_movimento = agora + 0.55

    def em_transicao(self, agora):
        return (self.saltou_em is not None and agora - self.saltou_em < 45
                or self.fechou_em is not None and agora - self.fechou_em < 12)
