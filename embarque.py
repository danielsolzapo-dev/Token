"""Decisões da rotina aérea com base nos avisos visíveis do jogo."""


class Embarque:
    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.saltou_em = None
        self.fechou_asa = False
        self.fechou_em = None
        self.pausar()

    def pausar(self):
        self.quadros_onibus = 0
        self.asa_desde = None

    def observar(self, agora, *, onibus, asa):
        self.quadros_onibus = self.quadros_onibus + 1 if onibus else 0
        if self.saltou_em is None:
            return "saltar_onibus" if self.quadros_onibus >= 2 else None
        if not asa or self.fechou_asa or agora - self.saltou_em > 120:
            self.asa_desde = None
            return None
        if self.asa_desde is None:
            self.asa_desde = agora
        return "fechar_asa" if agora - self.asa_desde >= 8 else None

    def registrar(self, tipo, enviado, agora):
        if not enviado:
            self.pausar()
        elif tipo == "saltar_onibus":
            self.saltou_em = agora
        elif tipo == "fechar_asa":
            self.fechou_asa = True
            self.fechou_em = agora

    def em_transicao(self, agora):
        return (self.saltou_em is not None and agora - self.saltou_em < 45
                or self.fechou_em is not None and agora - self.fechou_em < 12)
