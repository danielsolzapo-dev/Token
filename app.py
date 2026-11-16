"""Interface do Auto Farm para Windows."""

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import filedialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from diagnostico import Diagnostico
from logica_autofarm import Config, Detector, Fluxo, TECLAS, TEMPLATES
from versao import VERSAO
from windows_game import Windows


BG = "#10141c"
PAINEL = "#1b2230"
TEXTO = "#f0f3f9"
MUTED = "#aab7cb"
ACENTO = "#afd45e"
CONFIG = Path(os.getenv("LOCALAPPDATA", ".")) / "AutoFarmToken" / "ajustes.json"
ARQUIVO_LOG = CONFIG.with_name("diagnostico.log")
CAMPOS = ("clicar_continuar", "fallback_cor", "sair_por_tempo", "anti_afk", "minutos_partida")
ROTULOS = {
    "jogar": "Jogar Novamente", "continuar": "Continuar", "lobby_jogar": "Jogar",
    "lobby_pronto": "Pronto", "menu_aba": "Abrir menu", "voltar_lobby": "Voltar ao lobby",
    "resgatar": "Resgatar", "confirmar_sair": "Confirmar saída", "aba_jogar": "Aba Jogar",
}


def carregar_config():
    padrao = Config()
    try:
        dados = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            return padrao
        ajustes = {chave: dados[chave] for chave in CAMPOS[:-1] if type(dados.get(chave)) is bool}
        minutos = dados.get("minutos_partida")
        if type(minutos) in (int, float) and 1 <= minutos <= 60:
            ajustes["minutos_partida"] = minutos
        return replace(padrao, **ajustes)
    except (OSError, ValueError):
        return padrao


def salvar_config(config):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    provisoria = CONFIG.with_suffix(".tmp")
    dados = asdict(config)
    provisoria.write_text(json.dumps({chave: dados[chave] for chave in CAMPOS}), encoding="utf-8")
    provisoria.replace(CONFIG)


def monitorar(windows, fluxo, eventos, parar, diagnostico=None):
    estado_anterior = acao_anterior = None
    dialogo_ambiguo_anterior = False
    leituras_anteriores = None
    proximo_registro = 0.0
    ultimo_tipo = None
    ordem = 0
    etapa = "iniciar"
    acao = None
    try:
        if diagnostico:
            diagnostico.registrar("sessao_iniciada", versao=VERSAO, anti_afk=fluxo.config.anti_afk,
                                  saida_por_tempo=fluxo.config.sair_por_tempo)
        detector = fluxo.detector
        if faltando := TEMPLATES.keys() - detector.templates.keys():
            raise ValueError("Imagens de referência ausentes: " + ", ".join(sorted(faltando)))
        while not parar.is_set():
            acao = None
            etapa = "capturar"
            janela = windows.fortnite_em_foco()
            quadro = windows.capturar(janela) if janela else None
            pronto = janela is not None and windows.disponivel(janela, parar)
            if pronto:
                etapa = "detectar"
                hud_visivel = partida = detector.em_partida(quadro)
                bloqueio_hud = detector.procurar(quadro, ("espectador", "reinicializando"), 0.8) if partida else None
                if bloqueio_hud:
                    partida = False
                cursor = windows.cursor_visivel()
                alvo_onibus = detector.procurar(quadro, ("onibus",), 0.8)
                onibus = bool(alvo_onibus)
                contagem = fluxo.partidas
                agora = time.monotonic()
                etapa = "decidir"
                acao = fluxo.passo(quadro, agora, partida=partida, cursor=cursor,
                                   no_onibus=onibus, hud_visivel=hud_visivel)
                leituras = (True, hud_visivel, partida, cursor, onibus, fluxo.motivo_anti_afk)
                if diagnostico and (leituras != leituras_anteriores or agora >= proximo_registro):
                    diagnostico.registrar("leitura", foco=True, hud=hud_visivel, partida=partida,
                                          cursor=cursor, onibus=onibus, anti_afk=fluxo.motivo_anti_afk,
                                          bloqueio_hud=bloqueio_hud.nome if bloqueio_hud else None,
                                          score_onibus=round(alvo_onibus.score, 3) if alvo_onibus else None,
                                          resolucao=[quadro.shape[1], quadro.shape[0]])
                    leituras_anteriores, proximo_registro = leituras, agora + 10
                if detector.dialogo_ambiguo and not dialogo_ambiguo_anterior:
                    eventos.put(("acao", "Confirmação de saída ambígua. Confira o jogo."))
                dialogo_ambiguo_anterior = detector.dialogo_ambiguo
                estado = "Em partida" if partida else "Procurando botões"
                tem_entrada = acao is not None and acao.tipo in ("clicar", "esc", "movimento")
                if diagnostico and acao and (tem_entrada or acao.tipo != ultimo_tipo):
                    ordem += 1
                    diagnostico.registrar("acao", id=ordem, tipo=acao.tipo,
                                          alvo=acao.alvo.nome if acao.alvo else None,
                                          tentativa=acao.tentativa + 1 if acao.tipo == "clicar" else None,
                                          passos=acao.passos)
                ultimo_tipo = acao.tipo if acao else None
                etapa = "enviar_entrada"
                executada = acao is not None and (not tem_entrada or windows.executar(janela, acao, parar))
                if diagnostico and tem_entrada:
                    motivo = None if executada else windows.motivo_interrupcao(janela, parar)
                    diagnostico.registrar("resultado_entrada", id=ordem,
                                          resultado="enviada" if executada else "interrompida", motivo=motivo)
                if acao and acao.tipo == "clicar":
                    fluxo.registrar_clique(acao, executada, time.monotonic(), no_onibus=onibus)
                if fluxo.partidas != contagem:
                    eventos.put(("total", fluxo.partidas))
                if executada:
                    if acao.tipo == "clicar":
                        texto = "Clique enviado em " + ROTULOS.get(acao.alvo.nome, acao.alvo.nome)
                    elif acao.tipo == "movimento":
                        teclas = [nome for nome, scan in TECLAS.items()
                                  if any(p[0] in ("teclas", "andar_mouse") and scan in p[1] for p in acao.passos)]
                        texto = (f"Anti-AFK · caminhada enviada ({'/'.join(teclas)}) às {time.strftime('%H:%M:%S')}"
                                 if teclas else None)
                    else:
                        texto = {
                            "esc": "Esc enviado",
                            "movimento_menu": "Anti-AFK aguardando fechar o menu de saída.",
                            "clique_confirmado": "Botão saiu da tela",
                            "clique_ignorado": "Botão continua visível após três tentativas",
                            "menu_nao_encontrado": "Menu de saída não encontrado",
                            "lobby_nao_encontrado": "Lobby não encontrado. Confira se o jogo pede confirmação.",
                            "aguardando_fila": "Aguardando confirmação da fila ou do início da partida",
                            "fila_confirmada": "Fila confirmada. Aguardando o início da partida.",
                            "fila_sem_partida": "Fila confirmada sem início de partida. Aguardando o jogo ou o cancelamento.",
                            "fila_cancelada": "Cancelamento de fila reconhecido.",
                            "partida_confirmada": "Partida reconhecida. Cronômetro iniciado.",
                            "partida_nao_confirmada": "Nenhuma partida reconhecida dentro do prazo",
                            "tela_nao_reconhecida": "Tela sem sinais conhecidos. Verifique o jogo ou use Testar imagem.",
                        }[acao.tipo]
                    if texto and texto != acao_anterior:
                        eventos.put(("acao", texto))
                        acao_anterior = texto
                elif acao:
                    fluxo.pausar()
                    if not parar.is_set():
                        eventos.put(("acao", "Ação interrompida. Confira a janela e o foco do Fortnite."))
            else:
                fluxo.pausar()
                estado = "Aguardando o Fortnite em primeiro plano"
                if diagnostico and leituras_anteriores != (False,):
                    motivo = windows.motivo_interrupcao(janela, parar) if janela else "fortnite_sem_foco"
                    diagnostico.registrar("leitura", foco=False, anti_afk=motivo)
                    leituras_anteriores = (False,)
            if estado != estado_anterior:
                eventos.put(("estado", estado))
                estado_anterior = estado
            parar.wait(0.18 if pronto else 0.3)
    except Exception as erro:
        if diagnostico:
            diagnostico.registrar("erro", etapa=etapa, tipo=type(erro).__name__,
                                  codigo=getattr(erro, "winerror", None),
                                  id=ordem if acao else None, acao=acao.tipo if acao else None)
        eventos.put(("erro", str(erro)))
    finally:
        if diagnostico:
            diagnostico.registrar("sessao_encerrada", pausada=parar.is_set())
        fluxo.pausar()
        eventos.put(("fim", None))


def detectar_arquivo(caminho):
    quadro = cv2.imdecode(np.fromfile(caminho, dtype=np.uint8), cv2.IMREAD_COLOR)
    if quadro is None:
        raise ValueError("Não foi possível ler essa imagem.")
    return quadro


class Painel:
    def __init__(self, janela, windows, config=None, diagnostico=None):
        self.janela, self.windows = janela, windows
        self.diagnostico = diagnostico
        self.config = config if config is not None else carregar_config()
        self.fluxo = None
        self.eventos = SimpleQueue()
        self.worker = self.parar = None
        self.f6_anterior = self.fechando = False
        self.f7_anterior = False
        self.status = tk.StringVar(janela, "Pausado")
        self.atividade = tk.StringVar(janela, "A sessão começa quando você clicar em Iniciar.")
        self.total = tk.StringVar(janela, "0")
        self.opcoes = {nome: tk.BooleanVar(janela, getattr(self.config, nome)) for nome in CAMPOS[:-1]}
        self.minutos = tk.StringVar(janela, f"{self.config.minutos_partida:g}".replace(".", ","))

        janela.title(f"Auto Farm · {VERSAO}")
        janela.configure(bg=BG)
        janela.minsize(570, 515)
        janela.geometry("620x540")
        janela.protocol("WM_DELETE_WINDOW", self.fechar)
        self.estilo()
        self.montar()
        janela.after(45, self.atualizar)

    def estilo(self):
        estilo = ttk.Style(self.janela)
        estilo.theme_use("clam")
        estilo.configure(".", font=("Segoe UI", 10), foreground=TEXTO, background=BG)
        estilo.configure("Card.TFrame", background=PAINEL)
        estilo.configure("Card.TLabel", background=PAINEL)
        estilo.configure("Info.TLabel", foreground=MUTED)
        estilo.configure("CardInfo.TLabel", foreground=MUTED, background=PAINEL)
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 25, "bold"))
        estilo.configure("Numero.TLabel", font=("Segoe UI", 24, "bold"), background=PAINEL)
        estilo.configure("Status.TLabel", foreground=ACENTO, background=PAINEL,
                         font=("Segoe UI", 12, "bold"))
        estilo.configure("TCheckbutton", indicatorcolor=PAINEL)
        estilo.map("TCheckbutton", indicatorcolor=[("selected", ACENTO)])
        estilo.configure("TEntry", fieldbackground=PAINEL, insertcolor=TEXTO, padding=5)
        estilo.configure("TButton", background=PAINEL, bordercolor="#3c4859", padding=(12, 8))
        estilo.map("TButton", background=[("active", "#2d3a50")])
        estilo.configure("Start.TButton", foreground="#16220b", background=ACENTO, bordercolor=ACENTO,
                         font=("Segoe UI", 10, "bold"))
        estilo.map("Start.TButton", background=[("active", "#cbe58f")])

    def montar(self):
        painel = ttk.Frame(self.janela, padding=(28, 24, 28, 20))
        painel.pack(fill="both", expand=True)
        ttk.Label(painel, text="Auto Farm", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(painel, text="Fortnite · Fila, saída por tempo e movimento",
                  style="Info.TLabel").pack(anchor="w", pady=(0, 18))
        resumo = ttk.Frame(painel, style="Card.TFrame", padding=(16, 12))
        resumo.pack(fill="x")
        esquerda = ttk.Frame(resumo, style="Card.TFrame")
        esquerda.pack(side="left", fill="both", expand=True)
        ttk.Label(esquerda, textvariable=self.status, style="Status.TLabel", wraplength=385).pack(anchor="w")
        ttk.Label(esquerda, textvariable=self.atividade, style="CardInfo.TLabel", wraplength=385).pack(anchor="w")
        direita = ttk.Frame(resumo, style="Card.TFrame")
        direita.pack(side="right", padx=(12, 0))
        ttk.Label(direita, textvariable=self.total, style="Numero.TLabel").pack(anchor="e")
        ttk.Label(direita, text="Reinícios nesta sessão", style="CardInfo.TLabel").pack(anchor="e")
        for nome, texto in (
            ("clicar_continuar", "Clicar em Continuar após a eliminação"),
            ("fallback_cor", "Procurar Jogar Novamente pela cor"),
            ("anti_afk", "Ativar movimento anti-AFK"),
            ("sair_por_tempo", "Voltar ao lobby após o tempo da partida"),
        ):
            ttk.Checkbutton(painel, text=texto, variable=self.opcoes[nome]).pack(anchor="w", pady=(10, 0))
        campo = ttk.Frame(painel)
        campo.pack(anchor="w", pady=(10, 16))
        ttk.Label(campo, text="Minutos por partida").pack(side="left", padx=(0, 10))
        ttk.Entry(campo, textvariable=self.minutos, width=7).pack(side="left", padx=(0, 8))
        ttk.Label(campo, text="1–60", style="Info.TLabel").pack(side="left")
        comandos = ttk.Frame(painel)
        comandos.pack(fill="x")
        self.botao = ttk.Button(comandos, text="Iniciar", style="Start.TButton", command=self.alternar)
        self.botao.pack(side="left")
        ttk.Button(comandos, text="Testar imagem", command=self.testar).pack(side="left", padx=8)
        ttk.Button(comandos, text="Copiar diagnóstico", command=self.copiar_diagnostico).pack(side="left")
        ttk.Label(comandos, text="F6 inicia ou pausa", style="Info.TLabel").pack(side="right")
        ttk.Label(painel, text="F7 marca uma falha no diagnóstico durante a sessão.",
                  style="Info.TLabel").pack(anchor="w", pady=(8, 0))

    def copiar_diagnostico(self):
        try:
            texto = self.diagnostico.texto() if self.diagnostico else ""
        except OSError:
            self.atividade.set("Não foi possível ler o diagnóstico local.")
            return
        if not texto:
            self.atividade.set("Inicie uma sessão para gerar o diagnóstico.")
            return
        self.janela.clipboard_clear()
        self.janela.clipboard_append(texto)
        self.atividade.set("Diagnóstico copiado. Cole o texto na conversa em que for relatar a falha.")

    def ler_opcoes(self):
        minutos = float(self.minutos.get().replace(",", "."))
        if not 1 <= minutos <= 60:
            raise ValueError("Informe um tempo de partida entre 1 e 60 minutos.")
        return replace(self.config, minutos_partida=minutos,
                       **{nome: var.get() for nome, var in self.opcoes.items()})

    def alternar(self):
        if self.worker is not None and self.worker.is_alive():
            self.parar.set()
            self.botao.state(["disabled"])
            self.status.set("Pausando")
            return
        try:
            config = self.ler_opcoes()
        except ValueError:
            self.atividade.set("Informe um tempo de partida entre 1 e 60 minutos.")
            return
        try:
            salvar_config(config)
        except OSError:
            self.atividade.set("Não foi possível salvar os ajustes neste computador.")
        else:
            self.atividade.set("Coloque o Fortnite em primeiro plano.")
        self.config = config
        if self.fluxo is None:
            self.fluxo = Fluxo(Detector(config=config))
        else:
            self.fluxo.config = self.fluxo.detector.config = config
        self.fluxo.rearmar_fila()
        self.status.set("Iniciando")
        self.botao.configure(text="Pausar")
        self.parar = Event()
        self.worker = Thread(target=monitorar, args=(self.windows, self.fluxo, self.eventos, self.parar, self.diagnostico))
        self.worker.start()

    def testar(self):
        caminho = filedialog.askopenfilename(parent=self.janela, title="Selecionar uma captura",
                                             filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp")])
        if not caminho:
            return
        try:
            quadro = detectar_arquivo(caminho)
            detector = Detector(config=self.ler_opcoes())
            alvo = detector.ler_contexto(quadro, "confirmar_sair")
            if alvo is None and not detector.dialogo_ambiguo:
                alvo = detector.detectar(quadro) or detector.procurar(
                    quadro, ("lobby_jogar", "lobby_pronto", "voltar_lobby", "resgatar"),
                )
        except (OSError, ValueError, cv2.error):
            self.atividade.set("Não foi possível testar a imagem. Confira o arquivo e os ajustes.")
            return
        if alvo:
            x, y, w, h = alvo.caixa
            cv2.rectangle(quadro, (x, y), (x + w, y + h), (85, 224, 183), max(2, quadro.shape[0] // 275))
            centro_x, centro_y = (round(ponto) for ponto in alvo.centro)
            cv2.drawMarker(quadro, (centro_x, centro_y), (0, 0, 255), cv2.MARKER_CROSS, 15, 2)
            metodo = "cor/OCR" if alvo.metodo == "cor+OCR" else "template"
            texto = (f"{ROTULOS.get(alvo.nome, alvo.nome)} · centro ({centro_x}, {centro_y})"
                     f" · {metodo} · score {alvo.score:.0%}")
        elif detector.dialogo_ambiguo:
            texto = "Mais de um botão de confirmação plausível nesta imagem."
        else:
            texto = "Nenhum botão reconhecido nesta imagem."
        self.mostrar_teste(quadro, texto)

    def mostrar_teste(self, quadro, texto):
        janela = tk.Toplevel(self.janela)
        janela.title("Teste de imagem")
        janela.transient(self.janela)
        painel = ttk.Frame(janela, padding=14)
        painel.pack(fill="both", expand=True)
        ttk.Label(painel, text=texto).pack(anchor="w", pady=(0, 10))
        foto = Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
        foto.thumbnail((720, 405))
        imagem = ttk.Label(painel)
        imagem.foto = ImageTk.PhotoImage(foto)
        imagem.configure(image=imagem.foto)
        imagem.pack()

    def atualizar(self):
        f6 = self.windows.f6()
        if not self.fechando and f6 and not self.f6_anterior and "disabled" not in self.botao.state():
            self.alternar()
        self.f6_anterior = f6
        if self.diagnostico:
            f7 = self.windows.f7()
            if f7 and not self.f7_anterior and self.worker is not None and self.worker.is_alive():
                self.diagnostico.registrar("falha_marcada_pelo_usuario", estado=self.status.get())
            self.f7_anterior = f7
        while True:
            try:
                evento, valor = self.eventos.get_nowait()
            except Empty:
                break
            if evento == "estado":
                if self.parar is not None and not self.parar.is_set():
                    self.status.set(valor)
            elif evento == "total":
                self.total.set(str(valor))
            elif evento in ("acao", "erro"):
                self.atividade.set(valor)
            elif evento == "fim":
                self.status.set("Pausado")
                self.botao.configure(text="Iniciar")
                self.botao.state(["!disabled"])
        if self.fechando and (self.worker is None or not self.worker.is_alive()):
            self.janela.destroy()
        else:
            self.janela.after(45, self.atualizar)

    def fechar(self):
        self.fechando = True
        if self.parar:
            self.parar.set()


def verificar_build():
    detector = Detector()
    if faltando := TEMPLATES.keys() - detector.templates.keys():
        raise RuntimeError("Imagens ausentes no pacote: " + ", ".join(sorted(faltando)))
    for nome, (x, y) in (("jogar", (650, 210)), ("continuar", (650, 448)), ("lobby_jogar", (20, 420))):
        template = detector.templates[nome]
        h, w = template.shape[:2]
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        quadro[y:y + h, x:x + w] = template
        alvo = detector.procurar(quadro, (nome,))
        if not alvo or alvo.caixa != (x, y, w, h):
            raise RuntimeError(f"Falha ao detectar {nome} no pacote.")
    fluxo = Fluxo(detector)
    if fluxo.passo(quadro, 0) is not None or fluxo.passo(quadro.copy(), 0.3).alvo.nome != "lobby_jogar":
        raise RuntimeError("Falha na integração do fluxo de lobby.")
    hud = np.zeros((540, 960, 3), dtype=np.uint8)
    hud[475:486, 32:105] = (0, 215, 145)
    if not detector.em_partida(hud) or detector.em_partida(np.zeros_like(hud)):
        raise RuntimeError("Falha na leitura da barra de vida.")
    fluxo_sem_fila = Fluxo(detector)
    for instante in (0, 0.3, 0.8, 1.1, 1.5):
        fluxo_sem_fila.passo(hud, instante, partida=True)
    if fluxo_sem_fila.inicio_partida is not None or fluxo_sem_fila.partidas:
        raise RuntimeError("HUD já visível iniciou uma partida sem nova fila.")
    from PIL import ImageDraw, ImageFont
    modal = Image.new("RGB", (960, 540), "#17263a")
    fonte = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arialbd.ttf"), 34)
    desenho = ImageDraw.Draw(modal)
    desenho.text((480, 205), "VOLTAR AO LOBBY?", font=fonte, anchor="mm")
    desenho.text((360, 332), "CONFIRMAR", font=fonte, anchor="mm")
    desenho.text((610, 332), "CANCELAR", font=fonte, anchor="mm")
    confirmacao = detector.ler_contexto(cv2.cvtColor(np.asarray(modal), cv2.COLOR_RGB2BGR), "confirmar_sair")
    if confirmacao is None or not 300 < confirmacao.centro[0] < 420:
        raise RuntimeError("Falha na leitura do diálogo de saída.")
    modal_ingles = Image.new("RGB", (960, 540), "#17263a")
    desenho = ImageDraw.Draw(modal_ingles)
    desenho.text((480, 162), "RETURN TO", font=fonte, anchor="mm")
    desenho.text((480, 207), "LOBBY?", font=fonte, anchor="mm")
    desenho.text((342, 332), "CONFIRM", font=fonte, anchor="mm")
    desenho.text((612, 332), "CANCEL", font=fonte, anchor="mm")
    confirmacao = detector.ler_contexto(cv2.cvtColor(np.asarray(modal_ingles), cv2.COLOR_RGB2BGR),
                                       "confirmar_sair")
    if confirmacao is None or not 300 < confirmacao.centro[0] < 400:
        raise RuntimeError("Falha na leitura do diálogo com título em duas linhas.")
    botao = Image.new("RGB", (960, 540), "#17263a")
    desenho = ImageDraw.Draw(botao)
    fonte_botao = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arialbd.ttf"), 23)
    desenho.rectangle((600, 220, 849, 269), fill="#ffff00")
    desenho.text((724, 245), "JOGAR   NOVAMENTE", font=fonte_botao, anchor="mm", fill="#101010")
    alvo = detector.detectar(cv2.cvtColor(np.asarray(botao), cv2.COLOR_RGB2BGR))
    if alvo is None or alvo.metodo != "cor+OCR" or not 650 < alvo.centro[0] < 790:
        raise RuntimeError("Falha na leitura por cor e texto de Jogar Novamente.")

    sem_rotulo = Image.new("RGB", (960, 540), "#17263a")
    ImageDraw.Draw(sem_rotulo).rectangle((600, 220, 849, 269), fill="#ffff00")
    if detector.detectar(cv2.cvtColor(np.asarray(sem_rotulo), cv2.COLOR_RGB2BGR)) is not None:
        raise RuntimeError("Uma caixa amarela sem rótulo foi confundida com Jogar Novamente.")

    botoes = Image.new("RGB", (960, 540), "#17263a")
    desenho = ImageDraw.Draw(botoes)
    for (x0, x1), palavra in (((600, 770), "JOGAR"), ((778, 948), "NOVAMENTE")):
        desenho.rectangle((x0, 220, x1, 269), fill="#ffff00")
        desenho.text(((x0 + x1) / 2, 245), palavra, font=fonte_botao, anchor="mm", fill="#101010")
    if detector.detectar(cv2.cvtColor(np.asarray(botoes), cv2.COLOR_RGB2BGR)) is not None:
        raise RuntimeError("Dois botões amarelos foram confundidos com Jogar Novamente.")

    empilhado = Image.new("RGB", (960, 540), "#17263a")
    desenho = ImageDraw.Draw(empilhado)
    desenho.text((480, 178), "RETURN TO LOBBY?", font=fonte, anchor="mm")
    desenho.text((480, 275), "CANCEL", font=fonte, anchor="mm")
    desenho.text((480, 335), "CONFIRM", font=fonte, anchor="mm")
    confirmacao = detector.ler_contexto(cv2.cvtColor(np.asarray(empilhado), cv2.COLOR_RGB2BGR),
                                       "confirmar_sair")
    if confirmacao is None or not 310 < confirmacao.centro[1] < 350:
        raise RuntimeError("Falha na leitura do diálogo com Cancelar acima de Confirmar.")

    duplo = Image.new("RGB", (960, 540), "#17263a")
    desenho = ImageDraw.Draw(duplo)
    for centro, titulo in ((310, "LEAVE MATCH?"), (635, "RETURN TO LOBBY?")):
        desenho.text((centro, 180), titulo, font=fonte, anchor="mm")
        desenho.text((centro - 67, 313), "CONFIRM", font=fonte_botao, anchor="mm")
        desenho.text((centro + 67, 313), "CANCEL", font=fonte_botao, anchor="mm")
    confirmacao = detector.ler_contexto(cv2.cvtColor(np.asarray(duplo), cv2.COLOR_RGB2BGR), "confirmar_sair")
    if confirmacao is not None or not detector.dialogo_ambiguo:
        raise RuntimeError("O OCR não bloqueou uma confirmação ambígua.")
    windows = Windows()
    janela = tk.Tk()
    janela.withdraw()
    Painel(janela, windows, config=Config())
    janela.update_idletasks()
    janela.destroy()


def main():
    if sys.argv[1:] == ["--verificar-build"]:
        verificar_build()
        return
    windows = Windows()
    janela = tk.Tk()
    try:
        diagnostico = Diagnostico(ARQUIVO_LOG)
    except OSError:
        diagnostico = None
    painel = Painel(janela, windows, diagnostico=diagnostico)
    if diagnostico is None:
        painel.atividade.set("O diagnóstico local não pôde ser criado.")
    try:
        janela.mainloop()
    finally:
        if diagnostico:
            diagnostico.fechar()


if __name__ == "__main__":
    main()
