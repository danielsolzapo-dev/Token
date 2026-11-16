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

from logica_autofarm import Config, Detector, Fluxo
from versao import VERSAO
from windows_game import Windows


BG = "#10141c"
PAINEL = "#1b2230"
TEXTO = "#f0f3f9"
MUTED = "#aab7cb"
ACENTO = "#afd45e"
CONFIG = Path(os.getenv("LOCALAPPDATA", ".")) / "AutoFarmToken" / "ajustes.json"
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


def monitorar(windows, fluxo, eventos, parar):
    estado_anterior = acao_anterior = None
    try:
        detector = fluxo.detector
        if "jogar" not in detector.templates:
            raise ValueError("As imagens de referência não estão disponíveis.")
        while not parar.is_set():
            janela = windows.fortnite_em_foco()
            quadro = windows.capturar(janela) if janela else None
            pronto = janela is not None and windows.disponivel(janela, parar)
            if pronto:
                partida = detector.em_partida(quadro)
                if partida and detector.procurar(quadro, ("espectador", "reinicializando"), 0.8):
                    partida = False
                estado = "Em partida" if partida else "Procurando botões"
                cursor = windows.cursor_visivel()
                onibus = partida and bool(detector.procurar(quadro, ("onibus",), 0.8))
                contagem = fluxo.partidas
                acao = fluxo.passo(quadro, time.monotonic(), partida=partida, cursor=cursor, no_onibus=onibus)
                if acao and windows.executar(janela, acao, parar):
                    if acao.tipo == "clicar":
                        texto = "Clique enviado em " + ROTULOS.get(acao.alvo.nome, acao.alvo.nome)
                    else:
                        texto = {
                            "esc": "Esc enviado", "movimento": "Movimento anti-AFK",
                            "clique_confirmado": "Clique confirmado pela tela",
                            "clique_ignorado": "Botão continua visível após três tentativas",
                            "menu_nao_encontrado": "Menu de saída não encontrado",
                            "lobby_nao_encontrado": "Lobby não encontrado dentro do prazo",
                        }[acao.tipo]
                    if texto != acao_anterior:
                        eventos.put(("acao", texto))
                        acao_anterior = texto
                    if fluxo.partidas != contagem:
                        eventos.put(("total", fluxo.partidas))
                elif acao:
                    fluxo.partidas = contagem
                    fluxo.pausar()
            else:
                fluxo.pausar()
                estado = "Aguardando o Fortnite em primeiro plano"
            if estado != estado_anterior:
                eventos.put(("estado", estado))
                estado_anterior = estado
            parar.wait(0.18 if pronto else 0.3)
    except (OSError, ValueError, cv2.error) as erro:
        eventos.put(("erro", str(erro)))
    finally:
        fluxo.pausar()
        eventos.put(("fim", None))


def detectar_arquivo(caminho):
    quadro = cv2.imdecode(np.fromfile(caminho, dtype=np.uint8), cv2.IMREAD_COLOR)
    if quadro is None:
        raise ValueError("Não foi possível ler essa imagem.")
    return quadro


class Painel:
    def __init__(self, janela, windows, config=None):
        self.janela, self.windows = janela, windows
        self.config = config if config is not None else carregar_config()
        self.fluxo = None
        self.eventos = SimpleQueue()
        self.worker = self.parar = None
        self.f6_anterior = self.fechando = False
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
        ttk.Label(comandos, text="F6 inicia ou pausa", style="Info.TLabel").pack(side="right")

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
        self.status.set("Iniciando")
        self.botao.configure(text="Pausar")
        self.parar = Event()
        self.worker = Thread(target=monitorar, args=(self.windows, self.fluxo, self.eventos, self.parar))
        self.worker.start()

    def testar(self):
        caminho = filedialog.askopenfilename(parent=self.janela, title="Selecionar uma captura",
                                             filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp")])
        if not caminho:
            return
        try:
            quadro = detectar_arquivo(caminho)
            detector = Detector(config=self.ler_opcoes())
            alvo = detector.detectar(quadro) or detector.procurar(
                quadro, ("lobby_jogar", "lobby_pronto", "voltar_lobby", "resgatar"),
            )
        except (OSError, ValueError, cv2.error):
            self.atividade.set("Não foi possível testar a imagem. Confira o arquivo e os ajustes.")
            return
        if alvo:
            x, y, w, h = alvo.caixa
            cv2.rectangle(quadro, (x, y), (x + w, y + h), (85, 224, 183), max(2, quadro.shape[0] // 275))
            texto = f"{ROTULOS[alvo.nome]} · {alvo.score:.0%} · {alvo.metodo}"
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
    for nome, (x, y) in (("jogar", (650, 210)), ("continuar", (650, 448)), ("lobby_jogar", (20, 420))):
        template = detector.templates[nome]
        h, w = template.shape[:2]
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        quadro[y:y + h, x:x + w] = template
        alvo = detector.procurar(quadro, (nome,))
        if not alvo or alvo.caixa != (x, y, w, h):
            raise RuntimeError(f"Falha ao detectar {nome} no pacote.")
    fluxo = Fluxo(detector)
    if fluxo.passo(quadro, 0).alvo.nome != "lobby_jogar":
        raise RuntimeError("Falha na integração do fluxo de lobby.")
    hud = np.zeros((540, 960, 3), dtype=np.uint8)
    hud[475:486, 32:105] = (0, 215, 145)
    if not detector.em_partida(hud) or detector.em_partida(np.zeros_like(hud)):
        raise RuntimeError("Falha na leitura da barra de vida.")
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
    Painel(janela, windows)
    janela.mainloop()


if __name__ == "__main__":
    main()
