"""Reconhece avisos de conta e o desbloqueio da Loja Pirata no lobby em português."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class AvisoLobby:
    tipo: str
    nome: str
    centro_botao: tuple[int, int] | None = None


# Áreas de busca relativas à janela do jogo. Os recortes contêm apenas o
# texto fixo; duração da restrição, ano da recompensa e conta não fazem parte.
_AREAS = {
    "loja_pirata": (0.01, 0.28, 0.39, 0.50),
    "acesso_loja": (0.56, 0.20, 0.99, 0.46),
    "resgatar_tudo": (0.32, 0.78, 0.68, 0.98),
    "conta_banida": (0.31, 0.20, 0.73, 0.46),
    "continuar": (0.34, 0.60, 0.66, 0.85),
    "pareamento_restrito": (0.00, 0.68, 0.34, 0.99),
}


class DetectorAvisosLobby:
    def __init__(self):
        pasta = Path(__file__).with_name("templates") / "avisos_lobby"
        self.modelos = {}
        for nome in _AREAS:
            dados = np.frombuffer((pasta / f"{nome}.png").read_bytes(), dtype=np.uint8)
            modelo = cv2.imdecode(dados, cv2.IMREAD_GRAYSCALE)
            if modelo is None:
                raise ValueError(f"Referência inválida para o aviso de lobby: {nome}")
            self.modelos[nome] = modelo
        self._formato = None
        self._redimensionados = {}

    def _modelo(self, nome, largura, altura):
        chave = nome, largura, altura
        if chave not in self._redimensionados:
            original = self.modelos[nome]
            self._redimensionados[chave] = cv2.resize(
                original, (largura, altura), interpolation=cv2.INTER_AREA if altura < original.shape[0]
                else cv2.INTER_LINEAR)
        return self._redimensionados[chave]

    def _localizar(self, quadro, nome, *, escala=0.5, limiar=0.77):
        altura, largura = quadro.shape[:2]
        if self._formato != (altura, largura):
            self._redimensionados.clear()
            self._formato = altura, largura
        esquerda, topo, direita, base = _AREAS[nome]
        x, y = round(esquerda * largura), round(topo * altura)
        area = quadro[y:round(base * altura), x:round(direita * largura)]
        if area.size == 0:
            return None
        fator = escala * 1032 / altura
        cinza = cv2.cvtColor(area, cv2.COLOR_BGR2GRAY)
        reduzido = cv2.resize(cinza, None, fx=fator, fy=fator,
                              interpolation=cv2.INTER_AREA if fator < 1 else cv2.INTER_LINEAR)
        h, w = self.modelos[nome].shape
        proporcao = (largura / altura) / (1920 / 1032)
        # Tanto uma janela de aspecto diferente como uma captura redimensionada
        # podem chegar aqui. A primeira preserva a forma dos glifos.
        aspectos = (1.0, proporcao) if abs(proporcao - 1.0) > 0.025 else (1.0,)
        for aspecto in aspectos:
            for ajuste in (1.0, .96, 1.04, .92, 1.08, .88, 1.12, .84, 1.16):
                mw, mh = round(w * escala * ajuste * aspecto), round(h * escala * ajuste)
                if mw < 2 or mh < 2 or mw > reduzido.shape[1] or mh > reduzido.shape[0]:
                    continue
                modelo = self._modelo(nome, mw, mh)
                scores = cv2.matchTemplate(reduzido, modelo, cv2.TM_CCOEFF_NORMED)
                _, nota, _, (mx, my) = cv2.minMaxLoc(scores)
                if nota >= limiar:
                    return round(x + (mx + mw / 2) / fator), round(y + (my + mh / 2) / fator)
        return None

    def reconhecer(self, quadro):
        altura, largura = quadro.shape[:2]
        if altura < 120 or largura < 160:
            return None
        passo = max(1, altura // 160)
        topo = quadro[altura // 12:altura // 5:passo, largura // 6:5 * largura // 6:passo]
        azul = cv2.inRange(cv2.cvtColor(topo, cv2.COLOR_BGR2HSV), (99, 140, 58), (125, 255, 255))
        if cv2.countNonZero(azul) > 0.66 * azul.size:
            if self._localizar(quadro, "loja_pirata") and self._localizar(quadro, "acesso_loja"):
                return AvisoLobby("token_loja_pirata", "Acesso à Loja Pirata",
                                  self._localizar(quadro, "resgatar_tudo"))

        icone = quadro[round(.12 * altura):round(.34 * altura):passo,
                       round(.45 * largura):round(.55 * largura):passo]
        vermelho = cv2.inRange(icone, (0, 10, 165), (100, 135, 255))
        if cv2.countNonZero(vermelho) > .008 * vermelho.size and self._localizar(quadro, "conta_banida"):
            return AvisoLobby("conta_banida", "Esta conta foi banida",
                              self._localizar(quadro, "continuar"))
        return None

    def pareamento_restrito(self, quadro):
        """Reconhece a faixa de restrição, inclusive sob o modal escurecido."""
        # O texto é pequeno. Examine a imagem em detalhe só se sua silhueta
        # já tiver aparecido na triagem, que roda também durante as partidas.
        return (self._localizar(quadro, "pareamento_restrito", escala=.34, limiar=.64) is not None
                and self._localizar(quadro, "pareamento_restrito", escala=.8, limiar=.76) is not None)
