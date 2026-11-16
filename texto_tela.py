"""Leitura em português e inglês dos estados que não têm imagem de referência."""

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

import cv2
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR


@dataclass(frozen=True)
class Linha:
    texto: str
    caixa: tuple[int, int, int, int]

    @property
    def centro(self):
        x, y, w, h = self.caixa
        return x + w / 2, y + h / 2


def normalizar(texto):
    decomposicao = unicodedata.normalize("NFKD", texto.upper())
    sem_acentos = "".join(c for c in decomposicao if not unicodedata.combining(c))
    return " ".join(re.findall(r"[A-Z0-9]+", sem_acentos))


def combinar(linhas, *, vertical=False):
    """Inclui pares de caixas próximas do mesmo rótulo ou título."""
    yield from linhas
    eixo = 1 if vertical else 0
    ordenadas = sorted(linhas, key=lambda linha: linha.caixa[eixo])
    for i, primeira in enumerate(ordenadas):
        x, y, w, h = primeira.caixa
        for segunda in ordenadas[i + 1:]:
            xx, yy, ww, hh = segunda.caixa
            altura = max(h, hh)
            if vertical:
                perto = (-0.25 * altura <= yy - (y + h) <= 1.1 * altura
                         and abs(primeira.centro[0] - segunda.centro[0]) <= 0.35 * max(w, ww))
            else:
                perto = (-0.25 * altura <= xx - (x + w) <= 1.5 * altura
                         and abs(primeira.centro[1] - segunda.centro[1]) <= 0.45 * altura)
            if perto:
                esquerda, topo = min(x, xx), min(y, yy)
                direita, base = max(x + w, xx + ww), max(y + h, yy + hh)
                yield Linha(f"{primeira.texto} {segunda.texto}",
                            (esquerda, topo, direita - esquerda, base - topo))


def identificar(linhas, largura, altura, tipo):
    if tipo == "jogar":
        return next((linha for linha in combinar(linhas) if normalizar(linha.texto) in
                     {"JOGAR NOVAMENTE", "PLAY AGAIN", "READY UP AGAIN"}), None)
    if tipo == "fila":
        rotulos = {
            "PROCURANDO PARTIDA", "BUSCANDO PARTIDA", "CANCELAR PAREAMENTO",
            "FINDING MATCH", "LOOKING FOR MATCH", "CANCEL MATCHMAKING", "NA FILA", "IN QUEUE",
        }
        return next((linha for linha in linhas if linha.centro[1] >= 0.50 * altura
                     and normalizar(linha.texto) in rotulos), None)
    central = [linha for linha in linhas if 0.20 * largura <= linha.centro[0] <= 0.80 * largura
               and 0.18 * altura <= linha.centro[1] <= 0.88 * altura]
    afirmativos = {"SIM", "CONFIRMAR", "YES", "CONFIRM"}
    saidas = {"VOLTAR AO LOBBY", "SAIR DA PARTIDA", "RETURN TO LOBBY", "LEAVE MATCH"}
    negativos = [linha for linha in central if normalizar(linha.texto) in {"NAO", "CANCELAR", "NO", "CANCEL"}]
    botoes = [(linha, normalizar(linha.texto)) for linha in combinar(central)]
    candidatos = []
    for linha in combinar(list(combinar(central)), vertical=True):
        titulo = normalizar(linha.texto)
        menciona_saida = any(p in titulo for p in (
            "VOLTAR AO LOBBY", "SAIR DA PARTIDA", "ABANDONAR A PARTIDA", "RETURN TO LOBBY", "LEAVE MATCH",
        ))
        pergunta = "?" in linha.texto or any(p in titulo for p in (
            "DESEJA", "TEM CERTEZA", "ARE YOU SURE", "DO YOU WANT",
        ))
        if not (menciona_saida and pergunta):
            continue
        centro_titulo = linha.centro[0]
        base_titulo = linha.caixa[1] + linha.caixa[3]
        for botao, rotulo in botoes:
            if rotulo not in afirmativos | saidas:
                continue
            x, y = botao.centro
            if not 0.03 * altura <= y - base_titulo <= 0.50 * altura:
                continue
            for negativo in negativos:
                nx, ny = negativo.centro
                alinhamento = abs(y - ny) / altura
                desvio_centro = abs((x + nx) / 2 - centro_titulo) / largura
                distancia = abs(nx - x) / largura
                lado_a_lado = alinhamento <= 0.045 and 0.05 <= distancia <= 0.48
                empilhados = 0.05 <= (ny - y) / altura <= 0.18 and distancia <= 0.06
                if desvio_centro <= 0.12 and (lado_a_lado or empilhados):
                    candidatos.append(((rotulo not in afirmativos, alinhamento + desvio_centro), botao))
    return min(candidatos, key=lambda item: item[0])[1] if candidatos else None


class Reconhecedor:
    def __init__(self):
        modelos = Path(__file__).resolve().with_name("modelos")
        det = modelos / "PP-OCRv6_det_small.onnx"
        rec = modelos / "latin_PP-OCRv5_rec_mobile.onnx"
        if not (det.is_file() and rec.is_file()):
            raise ValueError("Modelos de leitura ausentes. Execute preparar_ocr.py ou use o executável.")
        self.ocr = RapidOCR(params={
            "Global.use_cls": False, "Global.log_level": "error", "Global.max_side_len": 1600,
            "Det.limit_side_len": 960, "Det.limit_type": "min", "Det.model_path": str(det),
            "Rec.model_path": str(rec), "Rec.lang_type": LangRec.LATIN,
            "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })

    def ler(self, quadro, tipo):
        altura, largura = quadro.shape[:2]
        resultado = self.ocr(quadro, use_cls=False)
        if resultado.boxes is None:
            return None
        linhas = [Linha(texto, cv2.boundingRect(caixa.astype("float32")))
                  for caixa, texto, score in zip(resultado.boxes, resultado.txts, resultado.scores)
                  if score >= 0.78]
        return identificar(linhas, largura, altura, tipo)
