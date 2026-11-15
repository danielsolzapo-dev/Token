"""Reconhecimento local dos controles do Fortnite por texto e contexto."""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import cv2
from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

MODELOS = Path(__file__).resolve().with_name("modelos")
RECOMPENSAS = {
    "Token da Loja Pirata": ("TOKEN DA LOJA PIRATA", "ACESSO A LOJA PIRATA", "PIRATE SHOP ACCESS"),
    "Extrator Portátil": ("EXTRATOR PORTATIL", "PORTABLE EXTRACTOR"),
    "Localizador da Sorte": ("LOCALIZADOR DA SORTE", "LUCKY LOCATOR"),
    "Localizador de Elemental": ("LOCALIZADOR DE ELEMENTAL", "SPRITE LOCATOR"),
}


@dataclass(frozen=True)
class Linha:
    texto: str
    x: int
    y: int
    largura: int
    altura: int


def normalizar(texto):
    sem_acentos = unicodedata.normalize("NFKD", texto.upper())
    ascii_texto = "".join(c for c in sem_acentos if not unicodedata.combining(c))
    return " ".join(re.findall(r"[A-Z0-9]+", ascii_texto))


def identificar(linhas, largura, altura, *, saindo=False, confirmar=False, aguardando_fila=False):
    saida = {}

    def localizar(chave, expressoes, zona=lambda x, y: True):
        candidatos = [
            linha for linha in linhas
            if normalizar(linha.texto) in expressoes
            and zona(linha.x / largura, linha.y / altura)
        ]
        if candidatos:
            linha = max(candidatos, key=lambda linha: linha.largura * linha.altura)
            saida[chave] = (linha.x, linha.y)
            return True
        return False

    def central(x, y):
        return 0.18 <= x <= 0.82 and 0.18 <= y <= 0.95

    def inferior(x, y):
        return y >= 0.54

    textos = {normalizar(linha.texto) for linha in linhas}
    titulo = localizar("tesouro", {"TESOURO ENCONTRADO", "TREASURE FOUND"}, central)
    if titulo:
        localizar("resgatar", {
            "RESGATAR", "COLETAR", "REIVINDICAR", "CLAIM", "COLLECT", "CONTINUAR", "CONTINUE",
        }, lambda x, y: central(x, y) and y > saida["tesouro"][1] / altura)
        for item, expressoes in RECOMPENSAS.items():
            if any(any(exp in texto for exp in expressoes) for texto in textos):
                saida[f"item:{item}"] = saida["tesouro"]
        return saida

    if localizar("suspensao", {"SUSPENSAO DE PAREAMENTO", "MATCHMAKING BAN", "BANIMENTO DE PAREAMENTO"}, central):
        return saida

    contexto_confirmacao = any(
        ("VOLTAR AO LOBBY" in t or "RETURN TO LOBBY" in t or "SAIR DA PARTIDA" in t)
        and ("DESEJA" in t or "CERTEZA" in t or "ARE YOU SURE" in t or "LEAVE AND" in t)
        for t in textos
    )
    if confirmar and contexto_confirmacao:
        localizar("confirmar_saida", {"SIM", "CONFIRMAR", "YES", "CONFIRM"}, central)
        return saida

    if saindo and localizar("sair", {"SAIR DA PARTIDA", "LEAVE MATCH", "VOLTAR AO LOBBY", "RETURN TO LOBBY"}):
        return saida

    if localizar("lobby", {"VOLTAR AO LOBBY", "RETORNAR AO LOBBY", "RETURN TO LOBBY"},
                 lambda x, y: y >= 0.40 and (x >= 0.55 or y >= 0.67)):
        return saida

    rotulos_fila = {"CANCELAR PAREAMENTO", "CANCEL MATCHMAKING", "CANCEL READY", "PROCURANDO PARTIDA",
                    "BUSCANDO PARTIDA", "FINDING MATCH", "MATCHMAKING", "PAREAMENTO", "NA FILA", "IN QUEUE"}
    if aguardando_fila:
        rotulos_fila.update({"CANCELAR", "CANCEL"})
    if localizar("fila_ativa", rotulos_fila, inferior):
        return saida
    if localizar("jogar", {"JOGAR", "PRONTO", "PLAY", "READY UP"}, inferior):
        tem_squad = bool(textos & {"ESQUADRAO", "ESQUADROES", "SQUAD", "SQUADS"})
        tem_preencher = bool(textos & {"PREENCHER", "PREENCHER EQUIPE", "FILL", "FILL TEAM"})
        sem_preencher = any("NAO PREENCHER" in t or "NO FILL" in t or "DONT FILL" in t for t in textos)
        if tem_squad and tem_preencher and not sem_preencher:
            saida["esquadrao_ok"] = saida["jogar"]
        return saida

    if localizar("onibus", {"PULAR", "SALTAR", "PULAR DO ONIBUS", "SALTAR DO ONIBUS",
                            "TO JUMP", "JUMP FROM THE BUS"},
                 lambda x, y: 0.2 <= x <= 0.9 and 0.2 <= y <= 0.8):
        return saida

    if any(t.startswith(("ESPECTANDO", "ASSISTINDO A", "SPECTATING")) for t in textos):
        saida["espectando"] = (0, 0)
    if textos & {"INVENTARIO", "INVENTORY"} and textos & {"EQUIPAMENTO", "RECURSOS", "LOADOUT", "RESOURCES"}:
        saida["inventario"] = (0, 0)
    elif not saindo:
        # O temporizador ao lado do minimapa permanece no topo direito durante a partida.
        tem_cronometro = any(
            re.fullmatch(r"[0-9]{1,2}[:∶][0-5][0-9]", linha.texto.strip())
            and linha.x >= 0.76 * largura and linha.y <= 0.36 * altura
            for linha in linhas
        )
        if tem_cronometro:
            saida["partida"] = (0, 0)
    return saida


class Reconhecedor:
    def __init__(self):
        det = MODELOS / "PP-OCRv6_det_small.onnx"
        rec = MODELOS / "latin_PP-OCRv5_rec_mobile.onnx"
        if not (det.is_file() and rec.is_file()):
            raise ValueError("Modelos de leitura ausentes. Use o executável oficial ou prepare os modelos.")
        self.ocr = RapidOCR(params={
            "Global.use_cls": False, "Global.log_level": "error",
            "Global.max_side_len": 1600,
            "Det.limit_side_len": 960, "Det.limit_type": "min",
            "Det.model_path": str(det),
            "Rec.model_path": str(rec), "Rec.lang_type": LangRec.LATIN,
            "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })

    def ler(self, tela, **contexto):
        altura, largura = tela.shape[:2]
        imagem = cv2.cvtColor(tela, cv2.COLOR_RGB2BGR)
        resultado = self.ocr(imagem, use_cls=False)
        if resultado.boxes is None:
            return {}
        linhas = []
        for caixa, texto, score in zip(resultado.boxes, resultado.txts, resultado.scores):
            if score < 0.70:
                continue
            x, y, w, h = cv2.boundingRect(caixa.astype("float32"))
            linhas.append(Linha(texto, x + w // 2, y + h // 2, w, h))
        return identificar(linhas, largura, altura, **contexto)
