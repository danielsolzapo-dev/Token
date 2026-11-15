"""Painel Windows para o Auto Farm do Token Pirata."""
import json
import os
import shutil
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
from tkinter import filedialog, messagebox, simpledialog, ttk
from types import SimpleNamespace

import macro_token_pirata as motor
import atualizacao
from versao import VERSAO

BG = "#0d131d"
PAINEL = "#161f2c"
CAMPO = "#101925"
TEXTO = "#edf3fc"
SECUNDARIO = "#b0c0d5"
AZUL = "#295788"
REALCE = "#a6caff"

PADROES = {
    "fila": True, "cronometrar": True, "minutos": "8", "pausar_apos": "0",
    "movimento": True, "resgatar": True, "discord": False, "regioes": False,
    "squad": False, "skins_padrao": "2", "limiar": "0.92", "previa": True,
    "botoes": "", "confirmar_modo": False, "fechar_inventario": True,
    "saltar_onibus": True, "ocr": True, "auto_atualizar": True,
}
CAPTURAS = {
    "Jogar": "jogar.png", "Voltar ao lobby (fim)": "lobby.png",
    "HUD em partida": "partida.png", "Sair da partida": "sair.png",
    "Aba de saída": "aba_saida.png", "Confirmar saída": "confirmar_saida.png",
    "Tesouro Encontrado": "tesouro.png", "Botão Resgatar": "resgatar.png",
    "Aba Tesouro ativa": "aba_tesouro.png", "Aba Jogar": "aba_jogar.png",
    "Inventário aberto": "inventario.png", "Assistindo": "espectando.png",
    "Salto do ônibus": "onibus.png", "Aviso de suspensão": "suspensao.png",
    "Esquadrão com Preencher": "esquadrao_ok.png",
}
REGIOES = {
    "Europa": "europa", "América do Norte": "america_do_norte", "Ásia": "asia",
    "Oceania": "oceania", "Oriente Médio": "oriente_medio",
}


def escrever(arquivo, conteudo):
    temporario = arquivo.with_suffix(arquivo.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8")
    temporario.replace(arquivo)


def ler_configuracao():
    try:
        dados = json.loads((motor.PASTA / "ajustes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return PADROES.copy()
    return {nome: dados.get(nome, padrao) for nome, padrao in PADROES.items()} if isinstance(dados, dict) else PADROES.copy()


def tema(janela):
    estilo = ttk.Style(janela)
    estilo.theme_use("clam")
    estilo.configure(".", background=BG, foreground=TEXTO, font=("Segoe UI", 10))
    estilo.configure("TFrame", background=BG)
    estilo.configure("Card.TFrame", background=PAINEL)
    estilo.configure("Titulo.TLabel", font=("Segoe UI", 23, "bold"))
    estilo.configure("Secao.TLabel", font=("Segoe UI", 16, "bold"))
    estilo.configure("Muted.TLabel", foreground=SECUNDARIO)
    estilo.configure("Badge.TLabel", background=PAINEL, foreground=REALCE, padding=(11, 7))
    estilo.configure("TButton", background=PAINEL, bordercolor="#3a485b", padding=(10, 7))
    estilo.configure("Primary.TButton", background=AZUL, foreground="#ffffff")
    estilo.configure("Nav.TButton", anchor="w", background=PAINEL, bordercolor=PAINEL,
                     padding=(15, 10))
    estilo.configure("NavActive.TButton", anchor="w", background=AZUL, bordercolor=AZUL,
                     padding=(15, 10))
    estilo.map("TButton", background=[("active", "#354b67")])
    estilo.configure("TEntry", fieldbackground=CAMPO, insertcolor=TEXTO, padding=5)
    estilo.configure("TCombobox", fieldbackground=CAMPO, arrowcolor=TEXTO, padding=5)
    estilo.map("TCombobox", fieldbackground=[("readonly", CAMPO)],
               foreground=[("readonly", TEXTO)])
    estilo.configure("TCheckbutton", indicatorcolor=CAMPO)
    estilo.map("TCheckbutton", indicatorcolor=[("selected", AZUL)])
    janela.configure(background=BG)


class Painel:
    def __init__(self, janela, windows):
        self.janela = janela
        self.windows = windows
        self.worker = None
        self.eventos = SimpleQueue()
        self.encerrando = False
        self.busca_em_andamento = False
        self.download_em_andamento = False
        self.release = None
        self.preparado = None
        self.atualizar_quando_parar = False
        self.variaveis = {}
        for nome, valor in ler_configuracao().items():
            tipo = tk.BooleanVar if isinstance(PADROES[nome], bool) else tk.StringVar
            self.variaveis[nome] = tipo(janela, value=valor)
        self.status = tk.StringVar(janela, "Parado")
        self.status_versao = tk.StringVar(janela, f"Versão {VERSAO}")
        self.contador = tk.StringVar(janela, f"{motor.carregar_contador()} partidas")
        self.paginas = {}
        self.navegacao = {}
        self.recorte = tk.StringVar(janela, next(iter(CAPTURAS)))
        self.regiao = tk.StringVar(janela, next(iter(REGIOES)))
        self.area_squad = tk.StringVar(janela)
        self.passo = tk.StringVar(janela, "01")
        self.verificar = tk.BooleanVar(janela)
        self.mostrar_url = tk.BooleanVar(janela)
        arquivo_url = motor.PASTA / "webhook_discord.txt"
        try:
            url = arquivo_url.read_text(encoding="utf-8-sig").strip()
        except OSError:
            url = ""
        self.webhook = tk.StringVar(janela, url)
        self.construir()
        self.ler_areas()
        self.abrir("Visão geral")
        janela.protocol("WM_DELETE_WINDOW", self.fechar)
        janela.after(100, self.atualizar)
        if getattr(sys, "frozen", False):
            janela.after(1800, self.verificacao_periodica)

    def construir(self):
        janela = self.janela
        janela.title("Auto Farm • Token Pirata")
        janela.geometry("920x650")
        janela.minsize(760, 565)
        tema(janela)
        topo = ttk.Frame(janela, padding=(22, 18, 22, 15))
        topo.pack(fill="x")
        ttk.Label(topo, text="Auto Farm", style="Titulo.TLabel").pack(side="left")
        ttk.Label(topo, text="Token Pirata", style="Muted.TLabel").pack(side="left", padx=14)
        ttk.Label(topo, textvariable=self.status, style="Badge.TLabel").pack(side="right")
        corpo = ttk.Frame(janela, padding=(22, 0, 22, 0))
        corpo.pack(fill="both", expand=True)
        lado = ttk.Frame(corpo, style="Card.TFrame", padding=8, width=172)
        lado.pack(side="left", fill="y", padx=(0, 20))
        self.conteudo = ttk.Frame(corpo)
        self.conteudo.pack(side="left", fill="both", expand=True)
        for nome, preencher in (
            ("Visão geral", self.geral), ("Fila e saída", self.fila),
            ("Movimento", self.movimento), ("Tesouro e Discord", self.tesouro),
            ("Esquadrão", self.esquadrao), ("Região de dia", self.regioes),
            ("Leitura de tela", self.recortes), ("Atividade", self.atividade),
            ("Atualizações", self.pagina_atualizacoes),
        ):
            botao = ttk.Button(lado, text=nome, style="Nav.TButton",
                               command=lambda pagina=nome: self.abrir(pagina))
            botao.pack(fill="x", pady=1)
            self.navegacao[nome] = botao
            pagina = ttk.Frame(self.conteudo, padding=(2, 4, 4, 8))
            self.paginas[nome] = pagina
            preencher(pagina)
        rodape = ttk.Frame(janela, padding=(22, 12, 22, 15))
        rodape.pack(fill="x")
        ttk.Label(rodape, text="F8 pausar / retomar   ·   F9 parar",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(rodape, text="Salvar ajustes", command=self.salvar).pack(side="right")
        self.iniciar_botao = ttk.Button(rodape, text="Iniciar", style="Primary.TButton",
                                         command=self.iniciar)
        self.iniciar_botao.pack(side="right", padx=8)
        self.parar_botao = ttk.Button(rodape, text="Parar", command=self.parar, state="disabled")
        self.parar_botao.pack(side="right")
        self.pausa_botao = ttk.Button(rodape, text="Pausar", command=self.pausar, state="disabled")
        self.pausa_botao.pack(side="right", padx=8)

    def abrir(self, nome):
        for pagina, painel in self.paginas.items():
            painel.pack_forget()
            self.navegacao[pagina].configure(style="NavActive.TButton" if pagina == nome else "Nav.TButton")
        self.paginas[nome].pack(fill="both", expand=True)

    def cabecalho(self, painel, titulo, ajuda):
        ttk.Label(painel, text=titulo, style="Secao.TLabel").pack(anchor="w", pady=(0, 6))
        self.nota(painel, ajuda, (0, 18))

    def nota(self, painel, texto, pady=(9, 0)):
        ttk.Label(painel, text=texto, wraplength=490, justify="left",
                  style="Muted.TLabel").pack(anchor="w", pady=pady)

    def escolha(self, painel, texto, var):
        ttk.Checkbutton(painel, text=texto, variable=self.variaveis[var]).pack(anchor="w", pady=4)

    def entrada(self, painel, descricao, var, largura=12, ocultar=False):
        linha = ttk.Frame(painel)
        linha.pack(fill="x", pady=6)
        ttk.Label(linha, text=descricao).pack(side="left", padx=(0, 12))
        campo = ttk.Entry(linha, textvariable=var, width=largura, show="*" if ocultar else "")
        campo.pack(side="left", fill="x", expand=largura >= 30)
        return campo

    def geral(self, painel):
        self.cabecalho(painel, "Visão geral", "Inicie uma sessão e coloque o Fortnite em primeiro plano. O painel lê o texto dos botões automaticamente.")
        ttk.Label(painel, textvariable=self.contador, style="Badge.TLabel").pack(anchor="w", pady=(0, 18))
        self.escolha(painel, "Modo prévia", "previa")
        self.nota(painel, "Na prévia, a atividade mostra as detecções. Os cliques e avisos do Discord ficam desativados.")
        ttk.Button(painel, text="Opções de leitura",
                   command=lambda: self.abrir("Leitura de tela")).pack(anchor="w", pady=18)

    def fila(self, painel):
        self.cabecalho(painel, "Fila e saída", "Controle o fluxo do lobby e o tempo da sessão.")
        self.escolha(painel, "Clicar em Jogar no lobby", "fila")
        self.escolha(painel, "Sair da partida por tempo", "cronometrar")
        self.entrada(painel, "Minutos por partida (4,5–8,5)", self.variaveis["minutos"])
        self.entrada(painel, "Pausa no lobby após (minutos)", self.variaveis["pausar_apos"])
        self.nota(painel, "Use 0 para desativar a pausa programada. O cronômetro da partida começa ao reconhecer o HUD ou o ônibus.")

    def movimento(self, painel):
        self.cabecalho(painel, "Movimento", "Atalhos do jogo usados após a detecção do HUD em partida.")
        self.escolha(painel, "Ativar movimentos aleatórios", "movimento")
        self.escolha(painel, "Fechar inventário reconhecido", "fechar_inventario")
        self.escolha(painel, "Saltar do ônibus ao reconhecer o aviso", "saltar_onibus")
        self.nota(painel, "Usa W/A/D, Ctrl esquerdo, Espaço e mouse. Os recortes do inventário, do ônibus e da tela de espectador habilitam a detecção dessas situações.")

    def tesouro(self, painel):
        self.cabecalho(painel, "Tesouro e Discord", "Configure o resgate e o destino dos avisos de itens detectados.")
        self.escolha(painel, "Resgatar Tesouro Encontrado", "resgatar")
        self.escolha(painel, "Enviar avisos para o Discord", "discord")
        self.campo_url = self.entrada(painel, "URL do webhook", self.webhook, 38, ocultar=True)
        ttk.Checkbutton(painel, text="Mostrar URL", variable=self.mostrar_url,
                        command=lambda: self.campo_url.configure(show="" if self.mostrar_url.get() else "*")).pack(anchor="w")
        ttk.Button(painel, text="Importar imagem de recompensa",
                   command=lambda: self.importar_pasta("recompensas")).pack(anchor="w", pady=15)
        self.nota(painel, "O nome do PNG aparece na mensagem. Salve o webhook para reutilizá-lo neste computador.")

    def esquadrao(self, painel):
        self.cabecalho(painel, "Esquadrão", "Use os recortes do HUD para sinalizar equipes com vagas ausentes ou retratos padrão.")
        self.escolha(painel, "Conferir Esquadrão com Preencher no lobby", "confirmar_modo")
        self.escolha(painel, "Ativar saída por composição da equipe", "squad")
        self.entrada(painel, "Limite de retratos padrão (1–3)", self.variaveis["skins_padrao"])
        campo = self.entrada(painel, "Áreas dos três retratos", self.area_squad, 40)
        campo.bind("<Return>", lambda _: self.salvar_areas())
        self.nota(painel, "Formato JSON com três listas [x, y, largura, altura], em frações da janela. A skin padrão é apenas um indício.")
        ttk.Button(painel, text="Salvar áreas", command=self.salvar_areas).pack(anchor="w", pady=7)
        botoes = ttk.Frame(painel)
        botoes.pack(anchor="w", pady=4)
        for texto, destino in (("Importar skin padrão", "skins_padrao"), ("Importar ausência", "ausentes")):
            ttk.Button(botoes, text=texto,
                       command=lambda pasta=destino: self.importar_pasta(f"squad/{pasta}")).pack(side="left", padx=(0, 8))
        ttk.Button(painel, text="Importar passo do modo",
                   command=self.importar_modo).pack(anchor="w", pady=6)

    def regioes(self, painel):
        self.cabecalho(painel, "Região de dia", "Importe a sequência do menu de pareamento para cada região disponível.")
        self.escolha(painel, "Escolher região pelo horário local", "regioes")
        ttk.Combobox(painel, state="readonly", textvariable=self.regiao,
                     values=list(REGIOES)).pack(anchor="w", pady=7)
        self.entrada(painel, "Número do passo", self.passo)
        ttk.Checkbutton(painel, text="Passo de verificação (sem clique)",
                        variable=self.verificar).pack(anchor="w", pady=4)
        ttk.Button(painel, text="Importar passo da região",
                   command=self.importar_regiao).pack(anchor="w", pady=10)
        self.nota(painel, "Cada região precisa de um passo de verificação. Use uma imagem da opção já aplicada e inclua os passos para voltar ao lobby.")

    def recortes(self, painel):
        self.cabecalho(painel, "Leitura de tela", "A leitura automática funciona localmente. Recortes são opcionais para personalizar ou corrigir detecções.")
        self.escolha(painel, "Reconhecer botões automaticamente (OCR)", "ocr")
        campo = self.entrada(painel, "Pasta", self.variaveis["botoes"], 42)
        campo.bind("<FocusOut>", lambda _: self.ler_areas())
        ttk.Button(painel, text="Escolher pasta", command=self.escolher_pasta).pack(anchor="w", pady=6)
        ttk.Combobox(painel, state="readonly", textvariable=self.recorte,
                     values=list(CAPTURAS), width=33).pack(anchor="w", pady=(15, 7))
        ttk.Button(painel, text="Importar PNG",
                   command=lambda: self.importar(self.pasta() / CAPTURAS[self.recorte.get()])).pack(anchor="w")
        ttk.Button(painel, text="Abrir pasta de recortes", command=self.abrir_pasta).pack(anchor="w", pady=8)
        self.entrada(painel, "Similaridade mínima (0–1)", self.variaveis["limiar"])
        self.nota(painel, "Jogar e Voltar ao Lobby só exigem recortes quando a leitura automática está desligada.")

    def pagina_atualizacoes(self, painel):
        self.cabecalho(painel, "Atualizações", "O aplicativo verifica as releases do GitHub e confere o hash antes de substituir o executável.")
        ttk.Label(painel, textvariable=self.status_versao, style="Badge.TLabel").pack(anchor="w", pady=(0, 14))
        self.escolha(painel, "Instalar automaticamente fora de uma sessão", "auto_atualizar")
        botoes = ttk.Frame(painel)
        botoes.pack(anchor="w", pady=10)
        ttk.Button(botoes, text="Verificar agora", command=lambda: self.verificar_atualizacao(True)).pack(side="left")
        self.botao_instalar = ttk.Button(botoes, text="Atualizar", state="disabled",
                                         command=self.agendar_atualizacao)
        self.botao_instalar.pack(side="left", padx=8)
        self.nota(painel, "O painel reinicia depois da atualização. Salve os ajustes para reutilizá-los.")

    def verificacao_periodica(self):
        if self.variaveis["auto_atualizar"].get():
            self.verificar_atualizacao(False)
        self.janela.after(30 * 60 * 1000, self.verificacao_periodica)

    def verificar_atualizacao(self, manual):
        if self.busca_em_andamento or self.download_em_andamento or self.preparado:
            return
        if not getattr(sys, "frozen", False):
            self.status_versao.set(f"Versão {VERSAO} · execute o .exe para atualizar")
            return
        self.busca_em_andamento = True
        if manual:
            self.status_versao.set("Verificando releases…")

        def consultar():
            try:
                self.eventos.put(("release", atualizacao.buscar()))
            except (OSError, ValueError) as erro:
                self.eventos.put(("erro_busca", str(erro)))

        Thread(target=consultar, daemon=True).start()

    def agendar_atualizacao(self):
        if self.release is None:
            return
        self.atualizar_quando_parar = True
        self.status_versao.set(f"Versão {self.release.versao} disponível · aguardando sessão parar")

    def baixar_atualizacao(self):
        release = self.release
        self.download_em_andamento = True
        self.atualizar_quando_parar = False
        self.status_versao.set(f"Baixando versão {release.versao}…")
        self.botao_instalar.configure(state="disabled")
        self.iniciar_botao.configure(state="disabled")

        def baixar():
            try:
                caminho = atualizacao.baixar(release, motor.PASTA)
                self.eventos.put(("preparado", (caminho, release)))
            except (OSError, ValueError) as erro:
                self.eventos.put(("erro_download", str(erro)))

        Thread(target=baixar).start()

    def atividade(self, painel):
        self.cabecalho(painel, "Atividade", "Acompanhe as detecções, ações e avisos do macro.")
        self.log = tk.Text(painel, background=CAMPO, foreground=TEXTO, relief="flat",
                           padx=12, pady=10, wrap="word", state="disabled",
                           font=("Consolas", 10))
        barra = ttk.Scrollbar(painel, orient="vertical", command=self.log.yview)
        barra.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=barra.set)
        self.log.pack(side="left", fill="both", expand=True)

    def pasta(self):
        valor = self.variaveis["botoes"].get().strip()
        return Path(valor).expanduser() if valor else motor.PASTA / "botoes"

    def escolher_pasta(self):
        caminho = filedialog.askdirectory(parent=self.janela)
        if caminho:
            self.variaveis["botoes"].set(caminho)
            self.ler_areas()

    def abrir_pasta(self):
        try:
            self.pasta().mkdir(parents=True, exist_ok=True)
            os.startfile(self.pasta())
        except OSError as erro:
            self.erro(str(erro))

    def erro(self, mensagem):
        messagebox.showerror("Auto Farm", mensagem, parent=self.janela)

    def importar(self, destino=None, pasta=None):
        origem = filedialog.askopenfilename(parent=self.janela, filetypes=[("Imagem PNG", "*.png")])
        if not origem:
            return
        origem = Path(origem)
        destino = destino or pasta / origem.name
        try:
            motor.imagem(origem)
            destino.parent.mkdir(parents=True, exist_ok=True)
            if origem.resolve() != destino.resolve():
                if destino.exists() and not messagebox.askyesno(
                        "Substituir recorte", f"Substituir {destino.name}?", parent=self.janela):
                    return
                shutil.copyfile(origem, destino)
            self.eventos.put(("log", f"Recorte disponível: {destino.name}."))
        except (OSError, ValueError) as erro:
            self.erro(str(erro))

    def importar_pasta(self, nome):
        self.importar(pasta=self.pasta() / nome)

    def numero_passo(self):
        passo = self.passo.get().strip()
        if not passo.isascii() or not passo.isdecimal() or not 1 <= int(passo) <= 99:
            raise ValueError("Use um número de passo entre 1 e 99.")
        return f"{int(passo):02}"

    def importar_modo(self):
        passo = simpledialog.askinteger("Passo do modo", "Número do passo (1–99)",
                                          parent=self.janela, minvalue=1, maxvalue=99)
        if passo is not None:
            self.importar(self.pasta() / f"modo_{passo:02}.png")

    def importar_regiao(self):
        try:
            numero = self.numero_passo()
        except ValueError as erro:
            self.erro(str(erro))
            return
        sufixo = "-verificar" if self.verificar.get() else ""
        self.importar(self.pasta() / "regioes" / REGIOES[self.regiao.get()] / f"{numero}{sufixo}.png")

    def ler_areas(self):
        try:
            dados = json.loads((self.pasta() / "squad.json").read_text(encoding="utf-8-sig"))
            self.area_squad.set(json.dumps(dados["slots"]))
        except (OSError, ValueError, KeyError, TypeError):
            self.area_squad.set("")

    def salvar_areas(self):
        try:
            slots = motor.validar_slots(json.loads(self.area_squad.get()))
            self.pasta().mkdir(parents=True, exist_ok=True)
            escrever(self.pasta() / "squad.json", json.dumps({"slots": slots}))
            self.eventos.put(("log", "Áreas do esquadrão salvas."))
        except (ValueError, OSError) as erro:
            self.erro(str(erro))

    def opcoes(self):
        dados = {nome: var.get() for nome, var in self.variaveis.items()}
        try:
            minutos, pausa, limiar = (float(dados[nome].replace(",", "."))
                                     for nome in ("minutos", "pausar_apos", "limiar"))
            skins = int(dados["skins_padrao"])
        except ValueError as erro:
            raise ValueError("Confira os valores numéricos em Fila e saída, Esquadrão e Recortes.") from erro
        if not (4.5 <= minutos <= 8.5 and 0 <= pausa < float("inf")
                and 0 < limiar <= 1 and skins in (1, 2, 3)):
            raise ValueError("Confira os limites ao lado dos campos numéricos.")
        args = SimpleNamespace(executar=not dados["previa"], minutos=minutos, pausar_apos=pausa,
                               limiar=limiar, sem_movimento=not dados["movimento"],
                               skins_padrao=skins, fila=dados["fila"],
                               cronometrar=dados["cronometrar"], resgatar=dados["resgatar"],
                               confirmar_modo=dados["confirmar_modo"],
                               fechar_inventario=dados["fechar_inventario"],
                               saltar_onibus=dados["saltar_onibus"])
        return dados, args

    def salvar(self):
        try:
            dados, _ = self.opcoes()
            self.persistir(dados)
            self.eventos.put(("log", "Ajustes salvos."))
        except (OSError, ValueError) as erro:
            self.erro(str(erro))

    def persistir(self, dados):
        url = motor.validar_webhook(self.webhook.get().strip())
        escrever(motor.PASTA / "ajustes.json", json.dumps(dados, ensure_ascii=False, indent=2))
        arq = motor.PASTA / "webhook_discord.txt"
        if url or arq.is_file():
            escrever(arq, url)

    def iniciar(self):
        if self.download_em_andamento or (self.worker is not None and self.worker.is_alive()):
            return
        try:
            dados, args = self.opcoes()
            botoes, recompensas, regioes = motor.carregar(self.pasta(), dados["regioes"],
                                                          exigir_pares=False, automatico=dados["ocr"])
            squad = motor.carregar_squad(self.pasta()) if dados["squad"] else None
            self.validar_capturas(dados, botoes, recompensas, regioes, squad)
            self.persistir(dados)
            url = motor.url_webhook() if dados["discord"] else ""
            if dados["discord"] and not url:
                raise ValueError("Informe a URL do webhook para enviar avisos.")
        except (OSError, ValueError) as erro:
            self.erro(str(erro))
            return
        self.sinal_parar = Event()
        self.sinal_pausa = Event()
        self.iniciar_botao.configure(state="disabled")
        self.parar_botao.configure(state="normal")
        self.pausa_botao.configure(state="normal", text="Pausar")
        self.status.set("Iniciando")
        self.abrir("Atividade")
        self.worker = Thread(target=self.rodar, args=(botoes, recompensas, regioes, squad, args, url, dados["ocr"]))
        self.worker.start()

    def validar_capturas(self, dados, botoes, recompensas, regioes, squad):
        if dados["previa"]:
            return
        if not dados["ocr"] and dados["cronometrar"] and not {"partida", "sair"} <= botoes.keys():
            raise ValueError("Importe HUD em partida e Sair da partida, ou desative a saída por tempo.")
        if not dados["ocr"] and dados["movimento"] and "partida" not in botoes:
            raise ValueError("Importe HUD em partida para usar movimentos.")
        if not dados["ocr"] and dados["resgatar"] and not {"tesouro", "resgatar"} <= botoes.keys():
            raise ValueError("Importe Tesouro Encontrado e Botão Resgatar, ou desative o resgate.")
        if dados["regioes"] and not regioes:
            raise ValueError("Importe uma sequência de seleção de região.")
        if dados["squad"] and (not squad or not (squad[1] or squad[2])):
            raise ValueError("Configure as áreas e importe um recorte de ausência ou de skin padrão.")
        if not dados["ocr"] and dados["confirmar_modo"] and "esquadrao_ok" not in botoes:
            raise ValueError("Importe Esquadrão com Preencher para conferir o modo no lobby.")
        if not dados["ocr"] and dados["discord"] and not recompensas and "tesouro" not in botoes:
            raise ValueError("Importe um recorte de recompensa ou de Tesouro Encontrado.")

    def rodar(self, botoes, recompensas, regioes, squad, args, url, usar_ocr):
        try:
            ocr = None
            if usar_ocr:
                from reconhecimento import Reconhecedor
                self.eventos.put(("log", "Carregando leitura automática…"))
                ocr = Reconhecedor()
            with ThreadPoolExecutor(max_workers=1) as executor:
                motor.monitorar(self.windows, botoes, recompensas, regioes, squad, args, url, executor,
                                parar=self.sinal_parar, alternar=self.sinal_pausa,
                                log=lambda msg: self.eventos.put(("log", msg)),
                                estado=lambda estado: self.eventos.put(("estado", estado)), ocr=ocr)
        except Exception as erro:
            self.eventos.put(("log", f"Erro: {erro}"))
        finally:
            self.eventos.put(("estado", "Parado"))

    def pausar(self):
        self.sinal_pausa.set()

    def parar(self):
        self.sinal_parar.set()
        self.status.set("Encerrando")
        self.pausa_botao.configure(state="disabled")

    def registrar(self, linha):
        self.log.configure(state="normal")
        self.log.insert("end", linha + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 400:
            self.log.delete("1.0", "2.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def atualizar(self):
        try:
            while True:
                tipo, valor = self.eventos.get_nowait()
                if tipo in {"release", "erro_busca", "preparado", "erro_download"}:
                    self.receber_atualizacao(tipo, valor)
                    continue
                if tipo == "log":
                    self.registrar(valor)
                    if valor.startswith("Partida "):
                        self.contador.set(f"{motor.carregar_contador()} partidas")
                    continue
                if self.status.get() == "Encerrando" and valor != "Parado":
                    continue
                self.status.set(valor)
                self.pausa_botao.configure(text="Retomar" if valor == "Pausado" else "Pausar")
                if valor == "Parado":
                    self.iniciar_botao.configure(state="normal")
                    self.pausa_botao.configure(state="disabled")
                    self.parar_botao.configure(state="disabled")
        except Empty:
            pass
        sessao_terminou = self.worker is None or not self.worker.is_alive()
        if sessao_terminou and not self.download_em_andamento and self.preparado:
            caminho, release = self.preparado
            try:
                atualizacao.iniciar_troca(caminho, release)
            except OSError as erro:
                caminho.unlink(missing_ok=True)
                self.receber_atualizacao("erro_download", str(erro))
                self.preparado = None
            else:
                self.janela.destroy()
                return
        if (sessao_terminou and self.atualizar_quando_parar and self.release
                and not self.download_em_andamento and not self.encerrando):
            self.baixar_atualizacao()
        if self.encerrando and sessao_terminou and not self.download_em_andamento:
            self.janela.destroy()
        else:
            self.janela.after(100, self.atualizar)

    def receber_atualizacao(self, tipo, valor):
        if tipo == "release":
            self.busca_em_andamento = False
            self.release = valor
            self.botao_instalar.configure(state="normal" if valor else "disabled")
            if valor:
                self.status_versao.set(f"Versão {valor.versao} disponível")
                if self.variaveis["auto_atualizar"].get():
                    self.agendar_atualizacao()
            else:
                self.status_versao.set(f"Versão {VERSAO} · atualizada")
        elif tipo == "erro_busca":
            self.busca_em_andamento = False
            self.status_versao.set(f"Versão {VERSAO} · falha ao verificar")
            self.registrar(f"Atualização: {valor}")
        elif tipo == "preparado":
            self.download_em_andamento = False
            self.preparado = valor
            self.status_versao.set("Atualização verificada. Reiniciando…")
        elif tipo == "erro_download":
            self.download_em_andamento = False
            self.status_versao.set(f"Versão {VERSAO} · falha ao baixar ou instalar")
            self.iniciar_botao.configure(state="normal")
            self.botao_instalar.configure(state="normal")
            self.registrar(f"Atualização: {valor}")

    def fechar(self):
        self.encerrando = True
        if self.worker is not None and self.worker.is_alive():
            self.parar()


def main():
    if sys.argv[1:] == ["--verificar-build"]:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        from reconhecimento import Reconhecedor

        tela = Image.new("RGB", (768, 432), "#1b2b61")
        fonte = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arialbd.ttf"), 44)
        ImageDraw.Draw(tela).text((78, 350), "JOGAR", fill="white", font=fonte)
        if "jogar" not in Reconhecedor().ler(np.asarray(tela)):
            raise RuntimeError("Falha na leitura de tela do executável.")
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--aplicar-atualizacao":
        atualizacao.aplicar_troca(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--limpar-atualizacao":
        Thread(target=atualizacao.limpar, args=(sys.argv[2],), daemon=True).start()
    windows = motor.Windows()
    janela = tk.Tk()
    Painel(janela, windows)
    janela.mainloop()


if __name__ == "__main__":
    main()
