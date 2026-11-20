"""Identifica a pesquisa opcional do Fortnite e o botão Pular."""

from pathlib import Path

import cv2
import numpy as np

from avisos_lobby import AvisoLobby


class DetectorPesquisa:
    def __init__(self):
        pasta = Path(__file__).with_name("templates") / "pesquisa"
        self.modelos = {}
        for nome in ("queremos_ouvir", "pular"):
            dados = np.frombuffer((pasta / f"{nome}.png").read_bytes(), np.uint8)
            imagem = cv2.imdecode(dados, cv2.IMREAD_GRAYSCALE)
            if imagem is None:
                raise ValueError(f"Referência inválida da pesquisa de feedback: {nome}.")
            self.modelos[nome] = imagem
        self.tamanho = None
        self.escalas = []

    def _preparar(self, largura, altura):
        if self.tamanho == (largura, altura):
            return
        self.tamanho = largura, altura
        self.escalas = []
        horizontal, vertical = largura / 1919, altura / 1032
        # Compara em meia escala de referência inclusive em telas 4K.
        self.reducao = min(1.0, 0.5 / min(horizontal, vertical))
        fatores = [(s, s) for s in (min(horizontal, vertical), vertical, horizontal,
                                     altura / 1079, vertical * 0.9, vertical * 1.1)]
        # Uma captura enviada para "Testar imagem" também pode ter sido esticada.
        fatores.extend(((horizontal, vertical), (horizontal, altura / 1079)))
        vistos = set()
        h, w = self.modelos["queremos_ouvir"].shape
        for sx, sy in fatores:
            fx, fy = sx * self.reducao, sy * self.reducao
            chave = round(w * fx), round(h * fy)
            if chave in vistos or min(chave) < 6:
                continue
            vistos.add(chave)
            self.escalas.append({
                nome: cv2.resize(modelo, None, fx=fx, fy=fy, interpolation=cv2.INTER_AREA)
                for nome, modelo in self.modelos.items()
            })

    @staticmethod
    def _buscar(mascara, modelo, limiar):
        h, w = modelo.shape
        if h > mascara.shape[0] or w > mascara.shape[1]:
            return None
        _, score, _, pos = cv2.minMaxLoc(cv2.matchTemplate(mascara, modelo, cv2.TM_CCOEFF_NORMED))
        if score >= limiar:
            return pos[0] + w / 2, pos[1] + h / 2
        return None

    def reconhecer(self, quadro):
        altura, largura = quadro.shape[:2]
        if largura < 320 or altura < 200:
            return None
        self._preparar(largura, altura)
        faixa = quadro[round(altura * 0.035):round(altura * 0.21),
                       round(largura * 0.22):round(largura * 0.78)]
        # O título tem muitas bordas brancas na mesma linha. Descarta rapidamente
        # quadros de partida e fundos uniformes antes da comparação de modelos.
        passo = max(2, round(largura / 640))
        amostra = cv2.inRange(faixa[::passo, ::passo], (190, 190, 190), (255, 255, 255))
        if (amostra[:, 1:] != amostra[:, :-1]).sum(axis=1).max() < 14:
            return None
        branco = cv2.inRange(faixa, (194, 194, 194), (255, 255, 255))
        branco = cv2.resize(branco, None, fx=self.reducao, fy=self.reducao, interpolation=cv2.INTER_AREA)
        escala = next((modelos for modelos in self.escalas
                       if self._buscar(branco, modelos["queremos_ouvir"], 0.78)), None)
        if escala is None:
            return None

        x0, y0 = round(largura * 0.28), round(altura * 0.65)
        rodape = quadro[y0:round(altura * 0.90), x0:round(largura * 0.72)]
        cinza = cv2.cvtColor(rodape, cv2.COLOR_BGR2GRAY)
        escuro = cv2.inRange(cinza, 0, 130)
        escuro = cv2.resize(escuro, None, fx=self.reducao, fy=self.reducao, interpolation=cv2.INTER_AREA)
        modelo = escala["pular"]
        centro = self._buscar(escuro, modelo, 0.80)
        botao = None
        if centro is not None:
            x, y = (round(p / self.reducao) for p in centro)
            margem = round(modelo.shape[1] * 0.55 / self.reducao)
            # O nome deverá estar sobre o botão claro e habilitado.
            if 0 <= x - margem and x + margem < cinza.shape[1] and min(
                int(cinza[y, x - margem]), int(cinza[y, x + margem])
            ) >= 172:
                botao = (x + x0, y + y0)
        return AvisoLobby("pesquisa", "Pesquisa de feedback", botao)
