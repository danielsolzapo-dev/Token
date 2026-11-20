"""Lê as três linhas de companheiros acima do HUD próprio do Fortnite."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class LeituraEsquadrao:
    presentes: int = 0
    vivos: int = 0
    eliminados: int = 0


@lru_cache(maxsize=2)
def _referencia(nome):
    caminho = Path(__file__).with_name("templates") / (nome + ".png")
    modelo = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if modelo is None:
        raise ValueError(f"Referência do HUD ilegível: {nome}")
    return modelo


@lru_cache(maxsize=1)
def _modelos_cartao():
    modelo = _referencia("cartao_reinicio_esquadrao")
    return tuple(cv2.resize(modelo, None, fx=fator, fy=fator, interpolation=cv2.INTER_LINEAR)
                 for fator in (1.0, 0.85, 1.15))


def _tem_letras(mascara):
    """Exige vários traços claros/escuros alinhados. Uma mancha não basta."""
    bits = mascara != 0
    inicios = (~bits[:, :-1] & bits[:, 1:]).sum(axis=1)
    return np.count_nonzero((inicios >= 3) & (bits.sum(axis=1) >= 5)) >= 2


def _barra_colorida(mascara):
    # A vida começa sob o marcador colorido do nome, mesmo sem escudo.
    if np.count_nonzero(np.count_nonzero(mascara[2:8, 43:79], axis=1) >= 31) >= 3:
        return True
    faixa = mascara[:, 34:153]
    contornos, _ = cv2.findContours(faixa, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if (x <= 17 and 2 <= h <= 11 and w >= 2 * h
                and np.count_nonzero(faixa[y:y+h, x:x+w]) >= 0.65 * w * h):
            return True
    return False


def _tem_cartao(ciano, y):
    # A correlação compara também o glifo escuro dentro do cartão; o escudo
    # ciano ao lado de um companheiro vivo ocupa essa mesma região.
    area = ciano[y-11:y+13, 145:205]
    if np.count_nonzero(area >= 75) < 20:
        return False
    for modelo in _modelos_cartao():
        score = cv2.minMaxLoc(cv2.matchTemplate(area, modelo, cv2.TM_CCOEFF_NORMED))[1]
        if score >= 0.90:
            return True
    return False


def ler_esquadrao(quadro):
    """Conta somente slots com nome legível. Slots sem estado contam como presentes.

    Vida verde ou barra de derrubado mantêm o companheiro vivo. A eliminação
    exige o nome em vermelho junto do cartão de reinicialização na mesma linha.
    """
    altura, largura = quadro.shape[:2]
    if altura < 360 or largura < 480:
        return LeituraEsquadrao()
    # Normaliza só o canto do HUD. Coordenadas de referência medidas em 1440×860.
    topo, base = 630, 759
    recorte = quadro[round(topo*altura/860):round(base*altura/860), :round(210*largura/1440)]
    imagem = cv2.resize(recorte, (210, base-topo), interpolation=cv2.INTER_LINEAR)
    hsv = cv2.cvtColor(imagem, cv2.COLOR_BGR2HSV)
    branco = cv2.inRange(hsv, (0, 0, 170), (179, 82, 255))
    rosa = cv2.inRange(hsv, (163, 95, 90), (179, 255, 255))
    vermelho = cv2.inRange(hsv, (0, 120, 105), (5, 255, 255))
    vermelho = cv2.bitwise_or(vermelho, rosa)
    verde = cv2.inRange(hsv, (33, 105, 82), (82, 255, 255))
    ciano = cv2.subtract(cv2.min(imagem[:, :, 0], imagem[:, :, 1]), imagem[:, :, 2])
    presentes = vivos = eliminados = 0
    for y in (671-topo, 704-topo, 737-topo):
        nome = np.s_[y-18:y-6, 49:150]
        nome_vermelho = _tem_letras(vermelho[nome])
        if not (nome_vermelho or _tem_letras(branco[nome])):
            continue
        faixa = np.s_[y-2:y+9, :]
        if _barra_colorida(verde[faixa]) or _barra_colorida(vermelho[faixa]):
            vivos += 1
        elif nome_vermelho and _tem_cartao(ciano, y):
            eliminados += 1
        else:
            # O pequeno marcador colorido antes do nome ancora uma linha sem
            # estado legível; texto do cenário sozinho não identifica um slot.
            marcador = hsv[y-15:y-7, 40:48]
            forte = (marcador[:, :, 1] >= 85) & (marcador[:, :, 2] >= 145)
            if np.count_nonzero(forte) < 16:
                continue
        presentes += 1
    return LeituraEsquadrao(presentes, vivos, eliminados)


@lru_cache(maxsize=8)
def _modelos_espera(proporcao):
    modelo = _referencia("aguardando_jogadores")
    return tuple(cv2.resize(modelo, None, fx=fator*aspecto, fy=fator, interpolation=cv2.INTER_LINEAR)
                 for aspecto in dict.fromkeys((1.0, proporcao))
                 for fator in (1.0, .95, 1.05, .85, 1.15))


def aguardando_jogadores(quadro):
    """Reconhece o texto fixo do pré-jogo sob o contador de segundos."""
    altura, largura = quadro.shape[:2]
    if altura < 360 or largura < 480:
        return False
    y0, y1 = round(.07*altura), round(.18*altura)
    x0, x1 = round(.34*largura), round(.66*largura)
    cinza = cv2.cvtColor(quadro[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    normalizada = cv2.resize(cinza, (461, 95), interpolation=cv2.INTER_LINEAR)
    contraste = cv2.subtract(normalizada, cv2.GaussianBlur(normalizada, (0, 0), 3))
    if cv2.countNonZero(cv2.inRange(contraste, 24, 255)) < 160:
        return False
    proporcao = round((1440/860)/(largura/altura), 2)
    for modelo in _modelos_espera(proporcao):
        if modelo.shape[1] > contraste.shape[1]:
            continue
        resultado = cv2.matchTemplate(contraste, modelo, cv2.TM_CCOEFF_NORMED)
        if cv2.minMaxLoc(resultado)[1] >= .73:
            return True
    return False
