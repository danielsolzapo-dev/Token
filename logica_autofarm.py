"""State machine and screen detector for the independent Auto Farm app."""

from dataclasses import dataclass
import math
from pathlib import Path
import random

import cv2
import numpy as np


# Nome do PNG, região de busca (x0, y0, x1, y1) e fator de trabalho em 1080p.
TEMPLATES = {
    "jogar": ("jogar_novamente.png", (0.45, 0, 1, 1), 0.5),
    "continuar": ("continuar.png", (0.6, 0.8, 1, 1), 0.5),
    "menu_aba": ("menu_aba.png", (0.55, 0, 1, 0.25), 1.0),
    "menu_aba_sel": ("menu_aba_sel.png", (0.55, 0, 1, 0.25), 1.0),
    "voltar_lobby": ("voltar_lobby.png", (0.55, 0, 1, 0.45), 1.0),
    "lobby_jogar": ("lobby_jogar.png", (0, 0.6, 0.4, 1), 0.5),
    "lobby_pronto": ("lobby_pronto.png", (0, 0.6, 0.4, 1), 0.5),
    "resgatar": ("resgatar.png", (0.25, 0.7, 0.75, 1), 0.5),
    "espectador": ("espectador.png", (0.3, 0, 0.7, 0.12), 1.0),
    "inventario": ("inventario.png", (0.65, 0.82, 1, 1), 1.0),
    "aba_jogar": ("aba_jogar.png", (0, 0, 0.3, 0.12), 1.0),
    "onibus": ("onibus.png", (0.5, 0.45, 0.85, 0.65), 1.0),
    "reinicializando": ("reinicializando.png", (0.3, 0.45, 0.7, 0.7), 1.0),
}
BOTOES_LOBBY = ("lobby_jogar", "lobby_pronto")
BOTOES_FILA = ("jogar", *BOTOES_LOBBY)
AVISOS = ("onibus", "reinicializando")


@dataclass(frozen=True)
class Config:
    limiar: float = 0.85
    escala_min: float = 0.6
    escala_max: float = 1.4
    escala_passo: float = 0.1
    fallback_cor: bool = True
    clicar_continuar: bool = True
    confirmacoes: int = 2
    timeout_lobby: float = 90.0
    sair_por_tempo: bool = True
    minutos_partida: float = 6.5
    anti_afk: bool = True
    avisar_bau: bool = False


@dataclass(frozen=True)
class Alvo:
    nome: str
    score: float
    caixa: tuple[int, int, int, int]
    escala: float | None
    metodo: str = "template"

    @property
    def centro(self):
        x, y, largura, altura = self.caixa
        return x + largura / 2, y + altura / 2


def _resize(imagem, fator):
    if abs(fator - 1) < 0.001:
        return imagem
    interpolacao = cv2.INTER_AREA if fator < 1 else cv2.INTER_LINEAR
    if round(min(imagem.shape[:2]) * fator) < 1:
        largura = max(1, round(imagem.shape[1] * fator))
        altura = max(1, round(imagem.shape[0] * fator))
        return cv2.resize(imagem, (largura, altura), interpolation=interpolacao)
    return cv2.resize(imagem, None, fx=fator, fy=fator, interpolation=interpolacao)


def _branco(imagem):
    mascara = ((imagem.min(axis=2) >= 200) * 255).astype(np.uint8)
    return cv2.cvtColor(mascara, cv2.COLOR_GRAY2BGR)


def _roi(imagem, limites):
    altura, largura = imagem.shape[:2]
    x0, y0, x1, y1 = limites
    x0, y0 = int(x0 * largura), int(y0 * altura)
    return imagem[y0:int(y1 * altura), x0:int(x1 * largura)], x0, y0


class Detector:
    def __init__(self, pasta=None, config=Config(), leitor=None):
        self.config = config
        self.leitor = leitor
        self._ultimo_texto = None
        self.dialogo_ambiguo = False
        pasta = Path(pasta) if pasta else Path(__file__).with_name("templates")
        self.templates = {}
        self.ultima_escala = {}
        self._cache = {}
        self._quadro = None
        self._redimensionados = {}
        for nome, (arquivo, _, fator) in TEMPLATES.items():
            caminho = pasta / arquivo
            if caminho.is_file():
                imagem = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
                if imagem is not None:
                    imagem = _resize(imagem, fator)
                    self.templates[nome] = _branco(imagem) if nome in AVISOS else imagem

    def preparar(self, quadro, fator_trabalho=0.5):
        if self._quadro is not quadro:
            self._quadro = quadro
            self._redimensionados.clear()
        if fator_trabalho not in self._redimensionados:
            fator = 1080 * fator_trabalho / quadro.shape[0]
            self._redimensionados[fator_trabalho] = _resize(quadro, fator), fator
        return self._redimensionados[fator_trabalho]

    def escalas(self):
        menor, maior = sorted((self.config.escala_min, self.config.escala_max))
        if not (0 < menor <= maior < math.inf):
            raise ValueError("As escalas precisam ser positivas e finitas.")
        passo = max(0.02, self.config.escala_passo)
        escalas = []
        while menor <= maior + 1e-6:
            escalas.append(round(menor, 3))
            menor += passo
        return escalas or [1.0]

    @staticmethod
    def _comparar(regiao, template):
        h, w = template.shape[:2]
        if not (6 <= h <= regiao.shape[0] and 6 <= w <= regiao.shape[1]):
            return 0.0, (0, 0)
        matriz = cv2.matchTemplate(regiao, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, posicao = cv2.minMaxLoc(matriz)
        return score, posicao

    def _estimar_escala(self, quadro, nome, limites, escalas):
        imagem, _ = self.preparar(quadro)
        regiao, _, _ = _roi(imagem, limites)
        if not regiao.size:
            return 1.0
        regiao = cv2.cvtColor(regiao, cv2.COLOR_BGR2GRAY)
        base = cv2.cvtColor(_resize(self.templates[nome], 0.5), cv2.COLOR_BGR2GRAY)
        escala, maior = min(escalas), max(escalas)
        melhor_score, estimativa = -1.0, 1.0
        while escala <= maior + 1e-6:
            score, _ = self._comparar(regiao, _resize(base, escala))
            if score > melhor_score:
                melhor_score, estimativa = score, escala
            escala += 0.04
        return estimativa

    def buscar_template(self, quadro, nome, limiar=None):
        if nome not in self.templates:
            return None
        limiar = self.config.limiar if limiar is None else limiar
        _, limites, fator_trabalho = TEMPLATES[nome]
        imagem, fator = self.preparar(quadro, fator_trabalho)
        regiao, x0, y0 = _roi(imagem, limites)
        if nome in AVISOS:
            regiao = _branco(regiao)
        escalas = self.escalas()
        ultima = self.ultima_escala.get(nome)
        melhor = None

        def testar(escala):
            nonlocal melhor
            chave = nome, escala
            if chave not in self._cache:
                self._cache[chave] = _resize(self.templates[nome], escala)
            template = self._cache[chave]
            score, (x, y) = self._comparar(regiao, template)
            if score > (melhor.score if melhor else 0):
                h, w = template.shape[:2]
                caixa = tuple(round(v / fator) for v in (x + x0, y + y0, w, h))
                melhor = Alvo(nome, score, caixa, escala)
            return score

        if fator_trabalho >= 1:
            if ultima is None or testar(ultima) < limiar:
                centro = self._estimar_escala(quadro, nome, limites, escalas)
                for passo in sorted(range(-5, 6), key=abs):
                    if testar(round(centro + passo * 0.01, 3)) >= limiar:
                        break
        else:
            ordem = escalas if ultima is None else [ultima, *sorted(
                (e for e in escalas if e != ultima), key=lambda e: abs(e - ultima)
            )]
            for escala in ordem:
                if testar(escala) >= limiar:
                    break
        if melhor and limiar - 0.2 <= melhor.score < 0.95:
            centro = melhor.escala
            for ajuste in (-0.05, 0.05, -0.025, 0.025):
                testar(round(centro + ajuste, 3))
        if melhor and melhor.score >= limiar:
            self.ultima_escala[nome] = melhor.escala
        return melhor

    def procurar(self, quadro, nomes, limiar=None):
        limiar = self.config.limiar if limiar is None else limiar
        candidatos = (self.buscar_template(quadro, nome, limiar) for nome in nomes)
        validos = (alvo for alvo in candidatos if alvo and alvo.score >= limiar)
        return max(validos, key=lambda alvo: alvo.score, default=None)

    def buscar_por_cor(self, quadro):
        imagem, fator = self.preparar(quadro)
        altura, largura = imagem.shape[:2]
        x0, y0 = int(largura * 0.6), int(altura * 0.3)
        recorte = imagem[y0:int(altura * 0.75), x0:]
        hsv = cv2.cvtColor(recorte, cv2.COLOR_BGR2HSV)
        mascara = cv2.inRange(hsv, (22, 150, 190), (38, 255, 255))
        # A borda externa engloba os furos das letras sem fundir controles vizinhos.
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
        melhor, maior_area = None, 0
        for contorno in contornos:
            x, y, w, h = cv2.boundingRect(contorno)
            if not (0.045 * altura <= h <= 0.16 * altura
                    and 0.25 * altura <= w <= 0.8 * altura and 3 <= w / h <= 9):
                continue
            area = w * h
            janela = np.s_[y:y + h, x:x + w]
            amarelo = cv2.countNonZero(mascara[janela]) / area
            escuro = float((cinza[janela] < 90).mean())
            if (area > maior_area and cv2.contourArea(contorno) / area >= 0.85
                    and amarelo >= 0.5 and 0.03 <= escuro <= 0.45):
                caixa = tuple(round(v / fator) for v in (x + x0, y + y0, w, h))
                melhor, maior_area = Alvo("jogar", amarelo, caixa, None, "cor+OCR"), area
        return melhor

    def fora_de_partida(self, quadro):
        return self.procurar(quadro, (*BOTOES_LOBBY, "menu_aba", "menu_aba_sel")) is not None

    def em_partida(self, quadro):
        """Busca a barra de vida no HUD inferior esquerdo, normalizado para 1080p."""
        imagem, _ = self.preparar(quadro, 1.0)
        recorte, _, _ = _roi(imagem, (0, 0.60, 0.45, 1))
        hsv = cv2.cvtColor(recorte, cv2.COLOR_BGR2HSV)
        altura, largura = hsv.shape[:2]
        # Duas faixas de brilho acomodam HUDs claros e escuros.
        for v_min in (155, 95):
            verde = cv2.inRange(hsv, (28, 120, v_min), (82, 255, 255))
            contornos, _ = cv2.findContours(verde, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contorno in contornos:
                x, y, w, h = cv2.boundingRect(contorno)
                if not (10 <= h <= 60 and w >= 1.2 * h and x < 0.35 * largura and y > 0.4 * altura):
                    continue
                if (cv2.countNonZero(verde[y:y + h, x:x + w]) >= 0.60 * w * h
                        and hsv[y:y + h, x:x + w, 0].mean() < 42):
                    return True
        return False

    def detectar(self, quadro):
        """Prioridade da v59: Jogar Novamente, alternativa por cor, Continuar."""
        referencia = self.buscar_template(quadro, "jogar")
        if referencia and referencia.score >= self.config.limiar:
            return referencia
        if self.config.fallback_cor:
            alvo = self.buscar_por_cor(quadro)
            if alvo and not self.fora_de_partida(quadro):
                x, y, w, h = alvo.caixa
                if self.ler_contexto(quadro[y:y + h, x:x + w], "jogar"):
                    return alvo
        if self.config.clicar_continuar:
            return self.procurar(quadro, ("continuar",))
        return None

    def ler_contexto(self, quadro, tipo):
        if self.leitor is None:
            from texto_tela import Reconhecedor
            self.leitor = Reconhecedor()
        if self._ultimo_texto is not None:
            imagem, contexto, alvo = self._ultimo_texto
            if imagem is quadro and contexto == tipo:
                return alvo
        linha = self.leitor.ler(quadro, tipo)
        if tipo == "confirmar_sair":
            self.dialogo_ambiguo = getattr(self.leitor, "dialogo_ambiguo", False)
        alvo = Alvo(tipo, 1.0, linha.caixa, None, "texto") if linha else None
        self._ultimo_texto = quadro, tipo, alvo
        return alvo


class Confirmacao:
    def __init__(self):
        self.limpar()

    def limpar(self):
        self.candidato = None
        self.total = 0

    def observar(self, alvo, altura, minimo):
        centro = alvo.centro
        tolerancia = altura * 0.05
        mesmo = (self.candidato is not None and self.candidato[0] == alvo.nome
                 and all(abs(a - b) < tolerancia for a, b in zip(centro, self.candidato[1])))
        self.total = self.total + 1 if mesmo else 1
        self.candidato = alvo.nome, centro
        if self.total < max(1, minimo):
            return False
        self.limpar()
        return True


class DetectorBau:
    def __init__(self, referencia=None, imagem=None, limiar=0.90):
        self.limiar = limiar
        if imagem is not None:
            quadro = imagem
        elif referencia is not None:
            quadro = cv2.imdecode(np.frombuffer(Path(referencia).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            if quadro is None:
                raise ValueError("Não foi possível ler a referência de baú.")
        else:
            raise ValueError("Selecione uma imagem de referência de baú.")
        altura, largura = quadro.shape[:2]
        cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
        if not (20 <= largura <= 512 and 20 <= altura <= 512):
            raise ValueError("A referência deve ser um recorte de 20 a 512 pixels por lado.")
        if float(cinza.std()) < 5:
            raise ValueError("A referência precisa mostrar detalhes visuais do baú.")
        self.referencia = cinza

    def detectar(self, quadro):
        fator = min(1.0, 540 / quadro.shape[0])
        reduzido = _resize(quadro, fator)
        cinza = cv2.cvtColor(reduzido, cv2.COLOR_BGR2GRAY)
        referencia = _resize(self.referencia, fator)
        melhor = None
        for escala in (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.25):
            template = _resize(referencia, escala)
            altura, largura = template.shape[:2]
            if largura > cinza.shape[1] or altura > cinza.shape[0] or min(largura, altura) < 8:
                continue
            matriz = cv2.matchTemplate(cinza, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(matriz)
            if not math.isfinite(score):
                continue
            recorte = cinza[y:y + altura, x:x + largura]
            if float(recorte.std()) < 5:
                continue
            if melhor is None or score > melhor.score:
                caixa = tuple(round(v / fator) for v in (x, y, largura, altura))
                melhor = Alvo("bau", score, caixa, escala, "referencia")
        return melhor if melhor and melhor.score >= self.limiar else None


class ObservadorBau:
    def __init__(self, confirmacoes=2, perdas_para_limpar=2):
        self.confirmacoes = confirmacoes
        self.perdas_para_limpar = perdas_para_limpar
        self.centro = None
        self.total = 0
        self.perdas = 0
        self.avisado = False

    def observar(self, alvo, altura):
        if alvo is None:
            self.perdas += 1
            if self.perdas >= self.perdas_para_limpar:
                self.centro = None
                self.total = self.perdas = 0
                self.avisado = False
            return False
        self.perdas = 0
        centro = alvo.centro
        tolerancia = altura * 0.06
        mesmo = self.centro is not None and all(
            abs(a - b) <= tolerancia for a, b in zip(centro, self.centro)
        )
        self.total = self.total + 1 if mesmo else 1
        self.centro = centro
        if self.total >= self.confirmacoes and not self.avisado:
            self.avisado = True
            return True
        return False


@dataclass(frozen=True)
class Acao:
    tipo: str
    alvo: Alvo | None = None
    passos: tuple = ()
    tentativa: int = 0


class Fluxo:
    """Adaptação em máquina de estados, avançada pelo chamador a cada captura.

    As coordenadas são relativas à captura. O chamador verifica a janela,
    executa a ação, obtém uma captura nova e fornece a leitura do HUD.
    """

    def __init__(self, detector, rng=None):
        self.detector = detector
        self.config = detector.config
        self.rng = rng if rng is not None else random.Random()
        self.confirmacao = Confirmacao()
        self.partidas = 0
        self.inicio_partida = None
        self._proxima_acao = 0.0
        self._prazo_lobby = None
        self._prazo_menu = None
        self._prazo_fila = None
        self._fila_contada = False
        self._fila_expirada = False
        self._quadros_partida = 0
        self._quadros_sem_hud = 0
        self._transicao_hud = False
        self._inicio_sem_sinais = None
        self._inicio_hud_novo = None
        self._hud_visto = False
        self._quadros_sem_hud_previo = 0
        self._inicio_sem_hud_previo = None
        self._fila_bloqueada = False
        self._botoes_fila_clicados = set()
        self._leituras_fila = 0
        self._leituras_cancelamento = 0
        self._proximo_texto_fila = 0.0
        self._sem_leitura_desde = None
        self._aviso_leitura = False
        self._pendente = None
        self._tentativas = 0
        self._quadros_sem_alvo = 0
        self._bloqueado = None
        self._humor = None
        self._troca_humor = 0.0
        self._desvio = (0.0, 0.0, 0.0)
        self._sem_pulo_ate = 0.0
        self._quadros_hud_afk = 0
        self._proxima_caminhada = 0.0

    def pausar(self):
        self.confirmacao.limpar()
        self._quadros_sem_alvo = self._quadros_partida = self._leituras_fila = 0
        self._quadros_sem_hud = 0
        self._transicao_hud = False
        self._inicio_sem_sinais = self._inicio_hud_novo = None
        self._leituras_cancelamento = 0
        self._sem_leitura_desde = None
        self._aviso_leitura = False
        self._quadros_hud_afk = 0

    def _iniciar_partida(self, agora):
        self.inicio_partida = agora
        self._desvio = (0.0, 0.0, 0.0)
        self._sem_pulo_ate = 0.0
        self._quadros_hud_afk = 0
        self._proxima_caminhada = agora
        self._inicio_hud_novo = None

    def _observar_hud_previo(self, hud_visivel, agora):
        if hud_visivel:
            self._hud_visto = True
            self._quadros_sem_hud_previo = 0
            self._inicio_sem_hud_previo = None
            return
        if self._inicio_sem_hud_previo is None:
            self._inicio_sem_hud_previo = agora
        self._quadros_sem_hud_previo += 1
        if (self._quadros_sem_hud_previo >= 4
                and agora - self._inicio_sem_hud_previo >= 0.65):
            self._hud_visto = False

    def rearmar_fila(self):
        """Permite uma nova tentativa somente após ação explícita de iniciar."""
        if self._prazo_fila is None or self._fila_expirada:
            if self._fila_expirada:
                self._encerrar_espera_fila()
            self._fila_bloqueada = False

    def _procurar(self, quadro, *nomes):
        return self.detector.procurar(quadro, nomes)

    def _alvo(self, quadro, nome):
        if nome in ("jogar", "continuar"):
            alvo = self.detector.detectar(quadro)
            return alvo if alvo and alvo.nome == nome else None
        if nome == "confirmar_sair":
            return self.detector.ler_contexto(quadro, nome)
        return self._procurar(quadro, nome)

    def _clicar_e_verificar(self, alvo, quadro):
        if alvo.nome == self._bloqueado:
            return None
        if self._pendente is None and not self.confirmacao.observar(
                alvo, quadro.shape[0], self.config.confirmacoes):
            return None
        return Acao("clicar", alvo, tentativa=self._tentativas)

    def registrar_clique(self, acao, enviado, agora, *, hud_visivel=False):
        """Registra a tentativa quando o Windows aceitou a entrada do clique."""
        self._proxima_acao = agora + (1.5 if enviado else 0.35)
        if not enviado:
            self.pausar()
            return
        self._pendente = acao.alvo.nome
        self._tentativas += 1
        self._quadros_sem_alvo = 0
        if self._pendente in BOTOES_FILA:
            self._fila_bloqueada = True
            self._botoes_fila_clicados.add(self._pendente)
            self._transicao_hud = not (hud_visivel or self._hud_visto)
            self._quadros_sem_hud = 0
            self._inicio_sem_sinais = self._inicio_hud_novo = None
            self._quadros_partida = 0

    def _observar_transicao(self, hud_visivel, agora):
        if not self._transicao_hud:
            if hud_visivel:
                self._quadros_sem_hud = 0
                self._inicio_sem_sinais = None
                return
            if self._inicio_sem_sinais is None:
                self._inicio_sem_sinais = agora
            self._quadros_sem_hud += 1
            self._transicao_hud = (
                self._quadros_sem_hud >= 4 and agora - self._inicio_sem_sinais >= 0.65
            )

    def _verificar_clique(self, quadro, agora, hud_visivel):
        nome = self._pendente
        abriu_modal = nome == "voltar_lobby" and self.detector.ler_contexto(quadro, "confirmar_sair")
        alvo = None if abriu_modal else self._alvo(quadro, nome)
        if nome in ("voltar_lobby", "confirmar_sair") and self.detector.dialogo_ambiguo:
            self._quadros_sem_alvo = 0
            return None
        if alvo and self._tentativas < 3:
            return self._clicar_e_verificar(alvo, quadro)
        if not alvo:
            if nome in BOTOES_FILA:
                self._observar_transicao(hud_visivel, agora)
            self._quadros_sem_alvo += 1
            if self._quadros_sem_alvo < 2:
                return None
        self._pendente, self._tentativas = None, 0
        if alvo:
            self._bloqueado = nome
            self._quadros_sem_alvo = 0
            return Acao("clique_ignorado", alvo)
        if nome in BOTOES_FILA:
            self.inicio_partida = None
            self._prazo_lobby = None
            self._prazo_fila = agora + self.config.timeout_lobby
            self._fila_contada = False
            self._fila_expirada = False
            self._leituras_cancelamento = 0
            self._quadros_partida = self._leituras_fila = 0
            self._proximo_texto_fila = agora
            return Acao("aguardando_fila")
        elif nome == "voltar_lobby":
            self.inicio_partida = None
            self._prazo_menu = None
            self._prazo_lobby = agora + self.config.timeout_lobby
        return Acao("clique_confirmado")

    def _encerrar_espera_fila(self):
        self._prazo_fila = None
        self._fila_contada = self._fila_expirada = False
        self._botoes_fila_clicados.clear()
        self.confirmacao.limpar()

    def _confirmar_fila(self, quadro, agora, partida, hud_visivel):
        if agora >= self._prazo_fila and not self._fila_expirada:
            if not self._fila_contada:
                self._encerrar_espera_fila()
                return Acao("partida_nao_confirmada")
            self._fila_expirada = True
            return Acao("fila_sem_partida")
        self._observar_transicao(hud_visivel, agora)
        jogo_novo = partida and self._transicao_hud
        self._quadros_partida = self._quadros_partida + 1 if jogo_novo else 0
        if jogo_novo:
            if self._inicio_hud_novo is None:
                self._inicio_hud_novo = agora
        else:
            self._inicio_hud_novo = None
        if (self._quadros_partida >= 3 and self._inicio_hud_novo is not None
                and agora - self._inicio_hud_novo >= 0.35):
            self._iniciar_partida(agora)
            if not self._fila_contada:
                self.partidas += 1
            self._fila_bloqueada = False
            self._encerrar_espera_fila()
            return Acao("partida_confirmada")
        if self._fila_contada:
            if not jogo_novo and agora >= self._proximo_texto_fila:
                self._proximo_texto_fila = agora + 1
                cancelada = self.detector.ler_contexto(quadro, "fila_cancelada")
                self._leituras_cancelamento = self._leituras_cancelamento + 1 if cancelada else 0
                if self._leituras_cancelamento >= 2:
                    self._encerrar_espera_fila()
                    self._fila_bloqueada = False
                    return Acao("fila_cancelada")
            return None
        if not jogo_novo and agora >= self._proximo_texto_fila:
            self._proximo_texto_fila = agora + 1
            fila = self.detector.ler_contexto(quadro, "fila")
            self._leituras_fila = self._leituras_fila + 1 if fila else 0
            if self._leituras_fila >= 2:
                self.partidas += 1
                self._fila_contada = True
                self.confirmacao.limpar()
                return Acao("fila_confirmada")
        if not self._fila_bloqueada and not (self._leituras_fila or partida):
            botoes = tuple(nome for nome in BOTOES_LOBBY if nome not in self._botoes_fila_clicados)
            alvo = self._procurar(quadro, *botoes)
            if alvo:
                return self._clicar_e_verificar(alvo, quadro)
        self.confirmacao.limpar()
        return None

    def passo(self, quadro, agora, *, partida=False, foco=True, cursor=False, no_onibus=False,
              hud_visivel=None):
        """Recebe imagem BGR e tempo monotônico em segundos. Retorna Acao ou None."""
        if not foco:
            self.pausar()
            return None
        hud_visivel = partida if hud_visivel is None else hud_visivel
        self._observar_hud_previo(hud_visivel, agora)
        if agora < self._proxima_acao:
            return None
        if not partida:
            self._quadros_hud_afk = 0
        if self._pendente:
            return self._verificar_clique(quadro, agora, hud_visivel)
        if self._bloqueado and self._alvo(quadro, self._bloqueado) is None:
            self._quadros_sem_alvo += 1
            if self._quadros_sem_alvo >= 2:
                self._bloqueado = None
        elif self._bloqueado:
            self._quadros_sem_alvo = 0
        if self._prazo_fila is not None:
            em_jogo = partida
            return self._confirmar_fila(quadro, agora, em_jogo, hud_visivel)
        self._botoes_fila_clicados.clear()
        if self._prazo_menu is not None:
            if agora >= self._prazo_menu:
                self._prazo_menu = None
                self._proxima_acao = agora + 30
                return Acao("menu_nao_encontrado")
            alvo = self._procurar(quadro, "voltar_lobby") or self._procurar(quadro, "menu_aba")
            if alvo:
                return self._clicar_e_verificar(alvo, quadro)
            self.confirmacao.limpar()
            return None

        if self.detector.dialogo_ambiguo or (self._prazo_lobby is not None and agora < self._prazo_lobby):
            alvo = self.detector.ler_contexto(quadro, "confirmar_sair")
            if self.detector.dialogo_ambiguo:
                self.confirmacao.limpar()
                return None
            if alvo:
                return self._clicar_e_verificar(alvo, quadro)
        alvo = self.detector.detectar(quadro)
        if alvo:
            self._sem_leitura_desde = None
            self._aviso_leitura = False
            return self._clicar_e_verificar(alvo, quadro)

        if self._prazo_lobby is not None and agora >= self._prazo_lobby:
            self._prazo_lobby = None
            return Acao("lobby_nao_encontrado")
        alvo = self._procurar(quadro, "resgatar")
        if alvo is None and not self._fila_bloqueada:
            alvo = self._procurar(quadro, *BOTOES_LOBBY)
        if alvo:
            self.inicio_partida = None
            self._sem_leitura_desde = None
            self._aviso_leitura = False
            return self._clicar_e_verificar(alvo, quadro)
        if self._prazo_lobby is not None or not partida:
            alvo = self._procurar(quadro, "aba_jogar")
            if alvo:
                return self._clicar_e_verificar(alvo, quadro)
        if self._prazo_lobby is not None:
            self.confirmacao.limpar()
            return None
        self.confirmacao.limpar()
        inventario_aberto = bool(partida and self._procurar(quadro, "inventario"))
        if inventario_aberto:
            self._quadros_hud_afk = 0
        if partida:
            self._sem_leitura_desde = None
            self._aviso_leitura = False
            if (self.inicio_partida is not None and self.config.sair_por_tempo
                    and not inventario_aberto and not no_onibus
                    and agora - self.inicio_partida >= self.config.minutos_partida * 60):
                self._prazo_menu = agora + 10
                self._proxima_acao = agora + 1
                return Acao("esc")
        elif self._sem_leitura_desde is None:
            self._sem_leitura_desde = agora
        elif not self._aviso_leitura and agora - self._sem_leitura_desde >= self.config.timeout_lobby:
            self._aviso_leitura = True
            return Acao("tela_nao_reconhecida")
        if not (self.inicio_partida is not None and partida and not no_onibus
                and self.config.anti_afk):
            return None
        # O ícone do menu isolado também pode aparecer junto do HUD de jogo.
        # Exige o controle de saída, com limiar maior se não houver cursor.
        if self.detector.procurar(quadro, ("voltar_lobby",), limiar=None if cursor else 0.92):
            self._quadros_hud_afk = 0
            return Acao("movimento_menu")
        if inventario_aberto:
            return None
        self._quadros_hud_afk += 1
        if self._quadros_hud_afk < 2:
            return None
        if agora >= self._proxima_caminhada:
            x, y, rumo = self._desvio
            tecla = "S" if x * math.sin(math.radians(rumo)) + y * math.cos(math.radians(rumo)) > 1 else "W"
            duracao = 0.8
            x, y = _andar(x, y, rumo, tecla, duracao)
            self._desvio = x, y, rumo
            self._proxima_caminhada = agora + 5.0
            self._proxima_acao = agora + duracao + 0.2
            return Acao("movimento", passos=(("teclas", (TECLAS[tecla],), duracao),))
        if self._humor is None or agora >= self._troca_humor:
            self._humor = self.rng.choice([h for h in HUMORES if h != self._humor])
            self._troca_humor = agora + self.rng.uniform(20, 90)
        passos, self._desvio = plano_anti_afk(
            self._desvio, not cursor, self._humor, not no_onibus and agora >= self._sem_pulo_ate,
            rng=self.rng,
        )
        duracao = sum(p[2] if p[0] in ("teclas", "andar_mouse") else p[-1] for p in passos)
        if any(p[0] == "teclas" and 57 in p[1] for p in passos):
            self._sem_pulo_ate = agora + duracao + 1.2
        self._proxima_acao = agora + duracao + intervalo_anti_afk(0.2, self._humor, rng=self.rng)
        return Acao("movimento", passos=tuple(passos))


TECLAS = {"W": 17, "A": 30, "S": 31, "D": 32}
VETORES = {"W": (0, 1), "S": (0, -1), "A": (-1, 0), "D": (1, 0)}
PESOS = {"W": 3.0, "A": 1.0, "D": 1.0, "S": 0.4}
TIPOS = ("explorar", "andar", "camera", "picareta", "pular", "agachar", "ajeitar")
HUMORES = {
    "calmo": ((6, 1.5, 1.5, 0.6, 0.5, 0.4, 0.3), 1.35),
    "andando": ((9, 1.5, 1, 1, 1, 0.6, 0.5), 0.9),
    "inquieto": ((5, 2, 1.5, 2.5, 2.5, 3, 3), 0.65),
}


def _rodar(tecla, rumo):
    x, y = VETORES[tecla]
    radianos = math.radians(rumo)
    seno, cosseno = math.sin(radianos), math.cos(radianos)
    return x * cosseno + y * seno, y * cosseno - x * seno


def _andar(x, y, rumo, teclas, duracao):
    fator = 1.0 if len(teclas) == 1 else 0.7
    for tecla in teclas:
        dx, dy = _rodar(tecla, rumo)
        x += dx * duracao * fator
        y += dy * duracao * fator
    return x, y


def _direcao(x, y, rumo, rng):
    distancia = math.hypot(x, y)
    pesos = []
    for tecla in VETORES:
        dx, dy = _rodar(tecla, rumo)
        volta = -(dx * x + dy * y) / distancia if distancia > 0.01 else 0
        pesos.append(PESOS[tecla] * max(0.15, 1 + volta * min(2 * distancia / 10, 3)))
    return rng.choices(list(VETORES), weights=pesos)[0]


def _diagonal(tecla, rng):
    return "W" + rng.choice("AD") if tecla == "W" and rng.random() < 0.4 else tecla


def _angulo(graus):
    return (graus + 180) % 360 - 180


def plano_anti_afk(desvio, camera=True, humor="andando", pular=True, *, rng=random):
    """Devolve passos (scancodes e movimentos relativos) e o novo desvio estimado."""
    x, y, rumo = desvio
    passos = []
    n = rng.choices((1, 2, 3), weights=(5, 3, 1))[0]
    for i in range(n):
        pesos = [
            0 if (tipo in ("camera", "picareta") and not camera)
            or (tipo == "pular" and (i > 0 or not pular)) else peso
            for tipo, peso in zip(TIPOS, HUMORES[humor][0])
        ]
        tipo = rng.choices(TIPOS, weights=pesos)[0]
        if tipo in ("explorar", "andar"):
            longa = tipo == "explorar"
            if longa:
                duracao = min(4.5, max(0.8, rng.lognormvariate(math.log(2.0), 0.45)))
                correr = rng.random() < 0.45
            else:
                duracao = min(1.4, max(0.1, rng.lognormvariate(math.log(0.45), 0.5)))
                correr = False
            teclas = _diagonal("W" if longa and camera else _direcao(x, y, rumo, rng), rng)
            codigos = [TECLAS[t] for t in teclas] + [42] * correr
            if longa and camera:
                if math.hypot(x, y) > 10:
                    volta = _angulo(math.degrees(math.atan2(-x, -y)) - rumo)
                    giro = max(-120, min(120, volta)) + rng.gauss(0, 15)
                else:
                    giro = max(-90, min(90, rng.gauss(0, 40)))
                mx = round(giro / 0.03)
                x, y = _andar(x, y, rumo + giro * 0.7, teclas, duracao)
                rumo = _angulo(rumo + mx * 0.03)
                passos.append(("andar_mouse", codigos, duracao, mx, rng.randint(-60, 60)))
            else:
                x, y = _andar(x, y, rumo, teclas, duracao)
                passos.append(("teclas", codigos, duracao))
            if longa:
                break
        elif tipo == "camera":
            mx, my = rng.choice((-1, 1)) * rng.randint(700, 3000), rng.randint(-120, 120)
            passos.append(("mouse", mx, my, rng.uniform(0.12, 0.4)))
            sorte = rng.random()
            if sorte < 0.25:
                fator = rng.uniform(0.08, 0.18)
                passos.append(("pausa", rng.uniform(0.05, 0.2)))
                passos.append(("mouse", -round(mx * fator), -round(my * fator), rng.uniform(0.06, 0.15)))
                mx -= round(mx * fator)
            elif sorte < 0.5:
                volta = -round(mx * rng.uniform(0.6, 1.4))
                passos.append(("pausa", rng.uniform(0.15, 0.35)))
                passos.append(("mouse", volta, -my, rng.uniform(0.15, 0.4)))
                mx += volta
            rumo = _angulo(rumo + mx * 0.03)
        elif tipo == "picareta":
            for k in range(rng.choices((1, 2, 3), weights=(3, 3, 2))[0]):
                if k:
                    passos.append(("pausa", rng.uniform(0.15, 0.35)))
                passos.append(("clique", rng.uniform(0.05, 0.12)))
        elif tipo == "pular":
            passos.append(("teclas", [57], rng.uniform(0.05, 0.15)))
        elif tipo == "ajeitar":
            primeira, segunda = rng.choice((("A", "D"), ("D", "A")))
            passos.append(("teclas", [TECLAS[primeira]], rng.uniform(0.06, 0.18)))
            passos.append(("pausa", rng.uniform(0.03, 0.1)))
            passos.append(("teclas", [TECLAS[segunda]], rng.uniform(0.06, 0.18)))
        else:
            passos.append(("teclas", [29], rng.uniform(0.05, 0.12)))
            passos.append(("pausa", rng.uniform(0.15, 0.35)))
            passos.append(("teclas", [29], rng.uniform(0.05, 0.12)))
        if i < n - 1:
            passos.append(("pausa", rng.uniform(0.1, 0.35)))
    return passos, (x, y, rumo)


def intervalo_anti_afk(base, humor, *, rng=random):
    sigma = 0.35
    intervalo = base * HUMORES[humor][1] * rng.lognormvariate(-(sigma ** 2) / 2, sigma)
    if rng.random() < 0.2:
        intervalo *= rng.uniform(0.3, 0.5)
    return min(0.35, max(0.1, intervalo))
