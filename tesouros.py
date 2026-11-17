"""Reconhecimento do aviso de dispositivo elemental e de seus ícones."""

from pathlib import Path
import time

import cv2
import numpy as np

from windows_game import reduzir_prioridade_thread


TESOUROS = {
    "acelerador": "Acelerador de Extração",
    "extrator": "Extrator Portátil",
    "fogos": "Fogos de Artifício Dourados",
    "localizador_elementais": "Localizador de Elementais",
    "localizador_sorte": "Localizador da Sorte",
}
DESCONHECIDO = "Dispositivo Elemental"
ESCALAS = (0.45, 0.52, 0.56, 0.60, 0.64, 0.67, 0.71, 0.76, 0.83, 0.92, 1.0, 1.12, 1.24)


def _mascara(imagem, dourado=False):
    hsv = cv2.cvtColor(imagem, cv2.COLOR_BGR2HSV)
    if dourado:
        return cv2.inRange(hsv, (22, 90, 154), (37, 255, 255))
    return cv2.inRange(hsv, (0, 0, 186), (179, 80, 255))


def _redimensionar(imagem, escala):
    return cv2.resize(imagem, None, fx=escala, fy=escala,
                      interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR)


def _recortar(imagem, esquerda, topo, direita, base):
    altura, largura = imagem.shape[:2]
    return imagem[max(0, round(topo)):max(0, min(altura, round(base))),
                  max(0, round(esquerda)):max(0, min(largura, round(direita)))]


def _correlacao(quadro, modelo):
    if quadro.shape[0] < modelo.shape[0] or quadro.shape[1] < modelo.shape[1]:
        return 0.0, (0, 0)
    resultado = cv2.matchTemplate(quadro, modelo, cv2.TM_CCOEFF_NORMED)
    _, score, _, centro = cv2.minMaxLoc(resultado)
    return score, centro


class DetectorTesouros:
    def __init__(self, pasta=None):
        self.pasta = Path(pasta) if pasta else Path(__file__).with_name("templates") / "tesouros"
        titulo = self._ler("encontrou")
        subtitulo = self._ler("elemental")
        self.avisos = [(escala, _mascara(_redimensionar(titulo, escala)),
                        _mascara(_redimensionar(subtitulo, escala), dourado=True)) for escala in ESCALAS]
        self.icones = {nome: self._ler(nome, cv2.IMREAD_UNCHANGED) for nome in TESOUROS}
        self._icones_por_escala = {}

    def _ler(self, nome, modo=cv2.IMREAD_COLOR):
        arquivo = self.pasta / f"{nome}.png"
        imagem = cv2.imdecode(np.frombuffer(arquivo.read_bytes(), np.uint8), modo)
        if imagem is None or (modo == cv2.IMREAD_UNCHANGED and imagem.shape[-1] != 4):
            raise ValueError("Imagem de referência de tesouro inválida.")
        return imagem

    def reconhecer(self, quadro):
        escala_quadro = min(1.0, 640 / quadro.shape[0])
        imagem = quadro if escala_quadro == 1 else _redimensionar(quadro, escala_quadro)
        branco = _mascara(imagem)
        candidatos = []
        for escala, titulo, subtitulo in self.avisos:
            score, (x, y) = _correlacao(branco, titulo)
            if score >= 0.60:
                candidatos.append((score, x, y, escala, subtitulo))
        for score, x, y, escala, subtitulo in sorted(candidatos, key=lambda item: item[0], reverse=True):
            abaixo = _recortar(imagem, x - 9 * escala, y + 15 * escala, x + 157 * escala, y + 75 * escala)
            limiar = 0.56 if score >= 0.68 else 0.65
            if abaixo.size and _correlacao(_mascara(abaixo, dourado=True), subtitulo)[0] >= limiar:
                acima = _recortar(imagem, x + 15 * escala, y - 94 * escala, x + 132 * escala, y - 3 * escala)
                return self._classificar(acima, escala)
        return None

    def _classificar(self, recorte, escala):
        if escala not in self._icones_por_escala:
            self._icones_por_escala[escala] = {
                nome: [_redimensionar(icone, escala * variacao) for variacao in (0.72, 0.85, 1.0, 1.15, 1.30)]
                for nome, icone in self.icones.items()
            }
        erros = []
        altura, largura = recorte.shape[:2]
        for nome, modelos in self._icones_por_escala[escala].items():
            erro = 1.0
            for modelo in modelos:
                h, w = modelo.shape[:2]
                if altura < h or largura < w:
                    continue
                mascara = cv2.threshold(modelo[:, :, 3], 200, 255, cv2.THRESH_BINARY)[1]
                comparacao = cv2.matchTemplate(recorte, modelo[:, :, :3], cv2.TM_SQDIFF_NORMED, mask=mascara)
                valido = comparacao[np.isfinite(comparacao)]
                if valido.size:
                    erro = min(erro, float(valido.min()))
            erros.append((erro, nome))
        erros.sort()
        (erro, vencedor), (segundo, _) = erros[:2]
        return TESOUROS[vencedor] if erro <= 0.18 and segundo - erro >= 0.025 else DESCONHECIDO


class AvisosTesouros:
    """Mantém um único alerta enquanto o mesmo ícone aparece continuamente."""

    def __init__(self):
        self._visto_em = {}
        self._desconhecido_desde = None

    def novo(self, nome, agora):
        if nome != DESCONHECIDO:
            self._desconhecido_desde = None
        if nome is None:
            return False
        if nome == DESCONHECIDO:
            self._desconhecido_desde = agora if self._desconhecido_desde is None else self._desconhecido_desde
            if (agora - self._desconhecido_desde < 0.45
                    or any(agora - visto < 1.2 for outro, visto in self._visto_em.items() if outro != nome)):
                return False
        anterior = self._visto_em.get(nome)
        self._visto_em[nome] = agora
        return anterior is None or agora - anterior >= 2.5


def monitorar_tesouros(windows, fluxo, eventos, parar, diagnostico=None):
    reduzir_prioridade_thread()
    detector = None
    avisos = AvisosTesouros()
    while not parar.is_set():
        config = fluxo.config
        if not (config.notificar_tesouros and config.webhook_url):
            parar.wait(0.35)
            continue
        try:
            if detector is None:
                detector = DetectorTesouros()
            janela = windows.fortnite_em_foco()
            if janela and windows.disponivel(janela, parar):
                quadro = windows.capturar(janela)
                if windows.disponivel(janela, parar):
                    nome = detector.reconhecer(quadro)
                    if not parar.is_set() and avisos.novo(nome, time.monotonic()):
                        eventos.put(("tesouro_webhook", (config.webhook_url, nome, quadro, parar)))
                        if diagnostico:
                            diagnostico.registrar("tesouro_elemental", nome=nome)
        except (OSError, cv2.error, ValueError) as erro:
            if diagnostico:
                diagnostico.registrar("erro_tesouros", tipo=type(erro).__name__)
            parar.wait(2)
        parar.wait(0.16)
