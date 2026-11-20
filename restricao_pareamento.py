"""Espera a liberação do pareamento indicada pelo próprio lobby."""

import cv2

def botao_lobby_liberado(quadro, detector):
    """Lê somente o rótulo do botão amarelo habilitado no rodapé esquerdo."""
    altura, largura = quadro.shape[:2]
    regiao = quadro[round(0.62 * altura):, :round(0.38 * largura)]
    if not regiao.size:
        return None
    hsv = cv2.cvtColor(regiao, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, (20, 140, 145), (38, 255, 255))
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if not (0.10 * largura <= w <= 0.32 * largura and 0.032 * altura <= h <= 0.14 * altura
                and w >= 2 * h and cv2.contourArea(contorno) >= 0.72 * w * h):
            continue
        recorte = regiao[y:y + h, x:x + w]
        escala = 80 / h
        ampliado = cv2.resize(recorte, (round(w * escala), 80), interpolation=cv2.INTER_LINEAR)
        com_margem = cv2.copyMakeBorder(ampliado, 12, 12, 12, 12, cv2.BORDER_CONSTANT,
                                        value=(255, 255, 255))
        linhas = detector._carregar_leitor().linhas(com_margem)
        # O texto completo evita interpretar "INFORMAÇÕES" ou outros botões como entrada liberada.
        rotulo = " ".join(linha.texto.strip().upper() for linha in linhas)
        if rotulo in ("JOGAR", "PLAY"):
            return "lobby_jogar"
        if rotulo in ("PRONTO", "READY", "READY UP"):
            return "lobby_pronto"
    return None


class RestricaoPareamento:
    def __init__(self):
        self.ativa = False
        self._modal_visivel = False
        self._proxima_tentativa = 0.0
        self._primeira_leitura = None
        self._ultima_leitura = None
        self._botao = None

    def observar(self, agora, *, modal=False, faixa_restrita=False, botao_lobby=None):
        """Retorna 'inicio' ou 'liberada' uma vez em cada transição."""
        self._modal_visivel = modal
        if modal or faixa_restrita:
            self._botao = None
            if not self.ativa:
                self.ativa = True
                self._proxima_tentativa = agora
                return "inicio"
        elif self.ativa:
            if botao_lobby not in ("lobby_jogar", "lobby_pronto"):
                self._botao = None
            elif self._botao != botao_lobby or agora - self._ultima_leitura > 10:
                self._botao = botao_lobby
                self._primeira_leitura = self._ultima_leitura = agora
            else:
                self._ultima_leitura = agora
                if agora - self._primeira_leitura >= 0.75:
                    self.ativa = False
                    self._botao = None
                    return "liberada"
        return None

    def pode_fechar_aviso(self, agora):
        return self._modal_visivel and agora >= self._proxima_tentativa

    def registrar_tentativa(self, agora):
        self._proxima_tentativa = agora + 10
