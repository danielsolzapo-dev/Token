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


def identificar(linhas, largura, altura, tipo):
    if tipo == "jogar":
        return next((linha for linha in linhas if normalizar(linha.texto) in
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
    for linha in central:
        titulo = normalizar(linha.texto)
        menciona_saida = any(p in titulo for p in (
            "VOLTAR AO LOBBY", "SAIR DA PARTIDA", "ABANDONAR A PARTIDA", "RETURN TO LOBBY", "LEAVE MATCH",
        ))
        pergunta = "?" in linha.texto or any(p in titulo for p in (
            "DESEJA", "TEM CERTEZA", "ARE YOU SURE", "DO YOU WANT",
        ))
        if not (menciona_saida and pergunta):
            continue
        botoes = [botao for botao in central
                  if 0.03 * altura <= botao.centro[1] - linha.centro[1] <= 0.50 * altura]
        for botao in botoes:
            rotulo = normalizar(botao.texto)
            if rotulo in {"VOLTAR AO LOBBY", "SAIR DA PARTIDA", "RETURN TO LOBBY", "LEAVE MATCH"}:
                return botao
            if rotulo in {"SIM", "CONFIRMAR", "YES", "CONFIRM"} and any(
                normalizar(outro.texto) in {"NAO", "CANCELAR", "NO", "CANCEL"}
                for outro in botoes
            ):
                return botao
    return None


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
