"""Lê o número ao lado do ícone individual de jogadores, à esquerda do minimapa."""

from pathlib import Path

import cv2
import numpy as np


def _referencia(nome):
    caminho = Path(__file__).with_name("templates") / "contagem" / f"{nome}.png"
    imagem = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if imagem is None:
        raise ValueError(f"Referência do contador inválida: {nome}.")
    return imagem


class ContadorPartida:
    def __init__(self):
        icone = _referencia("jogadores")
        self.icones = [cv2.resize(icone, (lado, lado), interpolation=cv2.INTER_LINEAR)
                       for lado in (17, 15, 19, 13, 21, 24)]
        self.digitos = np.hsplit(_referencia("digitos"), 10)

    def _digito(self, mascara, lado):
        y, x = np.where(mascara >= 115)
        if not len(x):
            return None
        glifo = mascara[y.min():y.max()+1, x.min():x.max()+1]
        h, w = glifo.shape
        if not (0.34 * lado <= h <= 0.71 * lado and 0.16 <= w / h <= 1.18):
            return None
        modelo = np.zeros((24, 24), np.uint8)
        largura = round(20 * w / h)
        inicio = (24 - largura) // 2
        modelo[2:22, inicio:inicio+largura] = cv2.resize(glifo, (largura, 20))
        notas = [cv2.matchTemplate(modelo, referencia, cv2.TM_CCORR_NORMED).item()
                 for referencia in self.digitos]
        ordem = np.argsort(notas)
        melhor, segundo = ordem[-1], ordem[-2]
        if notas[melhor] < 0.82 or notas[melhor] - notas[segundo] < 0.015:
            return None
        if melhor == 1 and (w / h > 0.6 or notas[melhor] < 0.86 or notas[melhor] - notas[segundo] < 0.09):
            return None
        return int(melhor)

    def _ler_digitos(self, texto, cx, x0, lado, minimo):
        colunas = np.flatnonzero(np.count_nonzero(texto >= 120, axis=0) >= minimo)
        if not colunas.size or not .70 * lado <= cx - (x0 + colunas[-1]) <= 1.35 * lado:
            return None
        grupos = np.split(colunas, np.where(np.diff(colunas) > 1)[0] + 1)
        lidos = []
        direita = None
        for grupo in reversed(grupos):
            if direita is not None and direita - grupo[-1] > max(3, .23 * lado):
                break
            digito = self._digito(texto[:, grupo[0]:grupo[-1]+1], lado)
            if digito is None:
                return None
            lidos.append(digito)
            direita = grupo[0]
        if len(lidos) > 3 or lidos[-1] == 0:
            return None
        quantidade = sum(digito * 10 ** i for i, digito in enumerate(lidos))
        return (quantidade, x0 + direita) if quantidade <= 100 else None

    def _numero(self, faixa, cinza, cx, cy, lado):
        y0, y1 = round(cy - .51 * lado), round(cy + .38 * lado)
        x0, x1 = round(cx - 2.72 * lado), round(cx - .70 * lado)
        if x0 < 0 or y0 < 0 or y1 > faixa.shape[0]:
            return None
        texto = faixa[y0:y1, x0:x1]
        leitura = self._ler_digitos(texto, cx, x0, lado, 1)
        if leitura is None:
            # Uma coluna com apenas um pixel pode ligar dois dígitos pequenos.
            leitura = self._ler_digitos(texto, cx, x0, lado, 2)
        if leitura is None:
            return None
        quantidade, esquerda = leitura
        if quantidade == 1:
            # Um dígito anterior apagado ou afastado pode transformar 11/21/31
            # em um falso 1. Examine também traços de baixo contraste à esquerda.
            fim = esquerda - 1
            topo = max(0, y0 - 3)
            inicio = max(0, fim - round(1.65 * lado))
            entorno = cinza[topo:min(cinza.shape[0], y1 + 3), inicio:fim + 4]
            if fim <= inicio:
                return None
            tracos = cv2.morphologyEx(entorno, cv2.MORPH_TOPHAT, np.ones((7, 7), np.uint8))
            banda = tracos[round(cy - .35 * lado) - topo:round(cy + .25 * lado) - topo, :fim - inicio]
            suspeita = (banda >= 12).astype(np.uint8)
            contornos, _ = cv2.findContours(suspeita, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if any(cv2.boundingRect(c)[3] >= 2 for c in contornos):
                return None
        return quantidade

    def ler(self, quadro):
        altura, largura = quadro.shape[:2]
        if altura < 360 or largura < 480:
            return None
        # A coluna acompanha o tamanho do minimapa e a margem direita da janela.
        recorte = quadro[round(.012 * altura):round(.16 * altura),
                         max(0, largura - round(.34 * altura)):largura - round(.15 * altura)]
        cinza = cv2.resize(recorte.min(axis=2), None, fx=860/altura, fy=860/altura,
                           interpolation=cv2.INTER_LINEAR)
        faixa = np.clip((cinza.astype(np.int16) - 167) * 3, 0, 255).astype(np.uint8)
        melhor = None
        for icone in self.icones:
            lado = icone.shape[0]
            _, nota, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(faixa, icone, cv2.TM_CCOEFF_NORMED))
            if nota >= 0.79 and (melhor is None or nota > melhor[0]):
                melhor = nota, x + lado / 2, y + lado / 2, lado
        if melhor is None:
            return None
        return self._numero(faixa, cinza, *melhor[1:])
