"""Interface do Auto Farm para Windows."""

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import filedialog, ttk
import webbrowser

import cv2
import numpy as np
from PIL import Image, ImageTk

from atualizador import (ErroAtualizacao, baixar_atualizacao, buscar_atualizacao,
                         criar_script_instalacao, iniciar_instalacao, preparar_executavel)
from diagnostico import Diagnostico
from logica_autofarm import ACOES_AEREAS, Config, Detector, Fluxo, TECLAS, TEMPLATES
from relogio_painel import RelogioPainel
from versao import VERSAO
from windows_game import Windows


BG = "#10141c"
PAINEL = "#1b2230"
TEXTO = "#f0f3f9"
MUTED = "#aab7cb"
ACENTO = "#afd45e"
SOLTANDO_CONTROLES = "Soltando os controles da automação…"
FINALIZANDO_LEITURA = "Controles liberados. Finalizando a leitura da tela…"
FUNDO_METRICA = "#10141c"
TEXTO_METRICA = "#ffe600"
CONFIG = Path(os.getenv("LOCALAPPDATA", ".")) / "AutoFarmToken" / "ajustes.json"
ARQUIVO_LOG = CONFIG.with_name("diagnostico.log")
CAMPOS = ("clicar_continuar", "fallback_cor", "sair_por_tempo", "anti_afk", "rotina_aerea",
          "atualizar_auto", "minutos_partida")
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
    prazo_anterior = fluxo.prazo_saida
    eventos.put(("prazo_saida", prazo_anterior))
    proximo_esquadrao = 0.0
    candidato_esquadrao = contagem_esquadrao = None
    quadros_esquadrao = 0
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
                bloqueio_hud = detector.procurar(quadro, ("espectador", "reinicializando"), 0.8)
                if bloqueio_hud:
                    partida = False
                cursor = windows.cursor_visivel()
                alvo_onibus, score_onibus = detector.aviso_onibus(quadro)
                if parar.is_set():
                    break
                onibus = bool(alvo_onibus)
                alvo_asa, score_asa = detector.aviso_asa(quadro) if not onibus else (None, 0.0)
                if parar.is_set():
                    break
                asa_delta = bool(alvo_asa)
                contagem = fluxo.partidas
                agora = time.monotonic()
                if not partida or onibus or asa_delta:
                    candidato_esquadrao = contagem_esquadrao = None
                    quadros_esquadrao = 0
                elif agora >= proximo_esquadrao:
                    proximo_esquadrao = agora + 1
                    quantidade = detector.barras_esquadrao(quadro)
                    quadros_esquadrao = quadros_esquadrao + 1 if quantidade == candidato_esquadrao else 1
                    candidato_esquadrao = quantidade
                    if quadros_esquadrao >= 3 and quantidade != contagem_esquadrao:
                        contagem_esquadrao = quantidade
                        if diagnostico:
                            diagnostico.registrar("hud_esquadrao", barras=quantidade)
                etapa = "decidir"
                acao = fluxo.passo(quadro, agora, partida=partida, cursor=cursor,
                                   no_onibus=onibus, hud_visivel=hud_visivel,
                                   asa_delta=asa_delta, espectando=bool(bloqueio_hud))
                if parar.is_set():
                    break
                leituras = (True, hud_visivel, partida, cursor, onibus, asa_delta, fluxo.motivo_anti_afk)
                if diagnostico and (leituras != leituras_anteriores or agora >= proximo_registro):
                    diagnostico.registrar("leitura", foco=True, hud=hud_visivel, partida=partida,
                                          cursor=cursor, onibus=onibus, asa_delta=asa_delta,
                                          anti_afk=fluxo.motivo_anti_afk,
                                          bloqueio_hud=bloqueio_hud.nome if bloqueio_hud else None,
                                          score_onibus=round(score_onibus, 3),
                                          metodo_onibus=alvo_onibus.metodo if alvo_onibus else None,
                                          score_asa=round(score_asa, 3),
                                          metodo_asa=alvo_asa.metodo if alvo_asa else None,
                                          resolucao=[quadro.shape[1], quadro.shape[0]])
                    leituras_anteriores, proximo_registro = leituras, agora + 10
                if detector.dialogo_ambiguo and not dialogo_ambiguo_anterior:
                    eventos.put(("acao", "Confirmação de saída ambígua. Confira o jogo."))
                dialogo_ambiguo_anterior = detector.dialogo_ambiguo
                estado = ("Espectando" if bloqueio_hud else "No ônibus" if onibus else
                          "Descendo de asa-delta" if asa_delta else "Em partida" if partida else
                          "Procurando botões")
                if fluxo.motivo_anti_afk == "aguardando_transicao_da_fila":
                    estado = "Aguardando transição da fila"
                elif partida and contagem_esquadrao:
                    estado = f"Em partida · {contagem_esquadrao} no HUD do esquadrão"
                tem_entrada = acao is not None and (bool(acao.passos) or acao.tipo in ("clicar", "esc"))
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
                elif acao and acao.tipo in ACOES_AEREAS:
                    fluxo.embarque.registrar(acao.tipo, executada, time.monotonic())
                if fluxo.partidas != contagem:
                    eventos.put(("total", fluxo.partidas))
                prazo_saida = fluxo.prazo_saida
                if prazo_saida != prazo_anterior:
                    eventos.put(("prazo_saida", prazo_saida))
                    prazo_anterior = prazo_saida
                if executada:
                    if acao.tipo == "clicar":
                        texto = "Clique enviado em " + ROTULOS.get(acao.alvo.nome, acao.alvo.nome)
                    elif acao.tipo == "movimento":
                        teclas = [nome for nome, scan in TECLAS.items()
                                  if any(p[0] in ("teclas", "andar_mouse") and scan in p[1] for p in acao.passos)]
                        acoes = [f"caminhada ({'/'.join(teclas)})"] if teclas else []
                        if any(p[0] in ("andar_mouse", "mouse") for p in acao.passos):
                            acoes.append("câmera")
                        if any(p[0] == "clique" for p in acao.passos):
                            acoes.append("picareta")
                        texto = f"Anti-AFK · {', '.join(acoes)} às {time.strftime('%H:%M:%S')}" if acoes else None
                    else:
                        texto = {
                            "esc": "Esc enviado",
                            "saltar_onibus": "Salto do ônibus enviado com Espaço.",
                            "fechar_asa": "Espaço enviado após confirmar Entrar em queda livre.",
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
                candidato_esquadrao = contagem_esquadrao = None
                quadros_esquadrao = 0
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
        self.eventos_atualizacao = SimpleQueue()
        self.release_disponivel = self.atualizacao_preparada = self.operacao_atualizacao = None
        self.worker = self.parar = None
        self.fechando = False
        self.f7_anterior = False
        self.status = tk.StringVar(janela, "Pausado")
        self.atividade = tk.StringVar(janela, "Clique em Iniciar no lobby ou já na partida.")
        self.total = tk.StringVar(janela, "0")
        self.proxima_saida = tk.StringVar(janela, "—")
        self.farmando = tk.StringVar(janela, "—")
        self.relogio = RelogioPainel()
        self.status_atualizacao = tk.StringVar(janela, f"Versão {VERSAO}")
        self.opcoes = {nome: tk.BooleanVar(janela, getattr(self.config, nome)) for nome in CAMPOS[:-1]}
        self.minutos = tk.StringVar(janela, f"{self.config.minutos_partida:g}".replace(".", ","))

        janela.title(f"Auto Farm · {VERSAO}")
        janela.configure(bg=BG)
        janela.minsize(590, 650)
        janela.geometry("650x675")
        janela.protocol("WM_DELETE_WINDOW", self.fechar)
        self.estilo()
        self.montar()
        janela.after(45, self.atualizar)
        janela.after(1000, self.verificar_automaticamente)

    def estilo(self):
        estilo = ttk.Style(self.janela)
        estilo.theme_use("clam")
        estilo.configure(".", font=("Segoe UI", 10), foreground=TEXTO, background=BG)
        estilo.configure("Card.TFrame", background=PAINEL)
        estilo.configure("Card.TLabel", background=PAINEL)
        estilo.configure("Info.TLabel", foreground=MUTED)
        estilo.configure("CardInfo.TLabel", foreground=MUTED, background=PAINEL)
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 25, "bold"))
        estilo.configure("Metrica.TFrame", background=FUNDO_METRICA)
        estilo.configure("MetricaTitulo.TLabel", background=FUNDO_METRICA, foreground=MUTED,
                         font=("Segoe UI", 9, "bold"))
        estilo.configure("MetricaValor.TLabel", background=FUNDO_METRICA, foreground=TEXTO_METRICA,
                         font=("Segoe UI", 19, "bold"))
        estilo.configure("MetricaVazia.TLabel", background=FUNDO_METRICA, foreground=MUTED,
                         font=("Segoe UI", 19, "bold"))
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
        ttk.Label(resumo, textvariable=self.status, style="Status.TLabel", wraplength=485).pack(anchor="w")
        ttk.Label(resumo, textvariable=self.atividade, style="CardInfo.TLabel", wraplength=485).pack(anchor="w")
        metricas = ttk.Frame(resumo, style="Card.TFrame")
        metricas.pack(fill="x", pady=(10, 0))
        for coluna, (titulo, valor) in enumerate((
            ("PARTIDAS", self.total), ("PRÓXIMA SAÍDA", self.proxima_saida), ("FARMANDO", self.farmando),
        )):
            metricas.columnconfigure(coluna, weight=1, uniform="metricas")
            cartao = ttk.Frame(metricas, padding=(12, 7), style="Metrica.TFrame")
            cartao.grid(row=0, column=coluna, sticky="nsew", padx=(0, 6 if coluna < 2 else 0))
            ttk.Label(cartao, text=titulo, style="MetricaTitulo.TLabel").pack(anchor="w")
            estilo_valor = "MetricaVazia.TLabel" if valor is self.proxima_saida else "MetricaValor.TLabel"
            rotulo = ttk.Label(cartao, textvariable=valor, style=estilo_valor)
            rotulo.pack(anchor="w")
            if valor is self.proxima_saida:
                self.rotulo_proxima_saida = rotulo
        for nome, texto in (
            ("clicar_continuar", "Clicar em Continuar após a eliminação"),
            ("fallback_cor", "Procurar Jogar Novamente pela cor"),
            ("anti_afk", "Ativar movimento anti-AFK"),
            ("rotina_aerea", "Saltar e fechar a asa-delta com Espaço"),
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
        atualizacao = ttk.Frame(painel)
        atualizacao.pack(fill="x", pady=(13, 0))
        ttk.Checkbutton(atualizacao, text="Atualizar automaticamente", variable=self.opcoes["atualizar_auto"],
                        command=self.salvar_preferencia_atualizacao).pack(side="left")
        self.botao_atualizacao = ttk.Button(atualizacao, text="Verificar", command=self.acao_atualizacao)
        self.botao_atualizacao.pack(side="right")
        ttk.Label(painel, textvariable=self.status_atualizacao, style="Info.TLabel",
                  wraplength=515).pack(anchor="w", pady=(4, 0))

    def salvar_preferencia_atualizacao(self):
        self.config = replace(self.config, atualizar_auto=self.opcoes["atualizar_auto"].get())
        try:
            salvar_config(self.config)
        except OSError:
            self.status_atualizacao.set("Não foi possível salvar o ajuste de atualização.")
        if self.config.atualizar_auto:
            self.verificar_atualizacoes()

    def verificar_automaticamente(self):
        if self.fechando:
            return
        if self.opcoes["atualizar_auto"].get() and self.release_disponivel is None:
            self.verificar_atualizacoes()
        self.janela.after(3600000, self.verificar_automaticamente)

    def verificar_atualizacoes(self):
        if self.operacao_atualizacao or self.fechando:
            return
        self.operacao_atualizacao = "consulta"
        self.status_atualizacao.set("Verificando atualizações…")
        self.botao_atualizacao.state(["disabled"])
        Thread(target=self._consultar_release, daemon=True).start()

    def _consultar_release(self):
        try:
            self.eventos_atualizacao.put(("release", buscar_atualizacao(VERSAO)))
        except (ErroAtualizacao, OSError) as erro:
            self.eventos_atualizacao.put(("erro", str(erro)))

    def acao_atualizacao(self):
        if self.release_disponivel is None:
            self.verificar_atualizacoes()
        elif getattr(sys, "frozen", False):
            self._baixar_release()
        else:
            webbrowser.open(self.release_disponivel.pagina)

    def _baixar_release(self):
        if self.operacao_atualizacao or self.fechando:
            return
        if self.worker is not None and self.worker.is_alive():
            self.status_atualizacao.set("Pause a automação para instalar a atualização.")
            return
        self.operacao_atualizacao = "download"
        self.botao_atualizacao.state(["disabled"])
        self.status_atualizacao.set(f"Baixando e verificando a v{self.release_disponivel.versao}…")
        Thread(target=self._preparar_release, args=(self.release_disponivel,), daemon=True).start()

    def _preparar_release(self, release):
        pasta = CONFIG.parent / "updates"
        pronto = None
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=pasta) as temporaria:
                baixado = baixar_atualizacao(release, temporaria)
                pronto = preparar_executavel(baixado, sys.executable, release.sha256)
                script = criar_script_instalacao(pronto, sys.executable, os.getpid(), pasta, release.sha256)
            self.eventos_atualizacao.put(("preparada", (pronto, script)))
        except (ErroAtualizacao, OSError) as erro:
            if pronto is not None:
                try:
                    pronto.unlink(missing_ok=True)
                except OSError:
                    pass
            self.eventos_atualizacao.put(("erro", str(erro)))

    def _processar_atualizacao(self):
        while True:
            try:
                evento, valor = self.eventos_atualizacao.get_nowait()
            except Empty:
                break
            if evento == "release":
                self.operacao_atualizacao = None
                self.release_disponivel = valor
                self.botao_atualizacao.state(["!disabled"])
                self.botao_atualizacao.configure(text="Atualizar" if valor else "Verificar")
                self.status_atualizacao.set(f"v{valor.versao} disponível." if valor else f"v{VERSAO} atualizada.")
            elif evento == "preparada":
                self.atualizacao_preparada = valor
            else:
                self.operacao_atualizacao = self.release_disponivel = None
                self.botao_atualizacao.state(["!disabled"])
                self.botao_atualizacao.configure(text="Tentar novamente")
                self.status_atualizacao.set(valor)
        if self.fechando or (self.worker is not None and self.worker.is_alive()):
            return
        if self.atualizacao_preparada:
            executavel, script = self.atualizacao_preparada
            self.atualizacao_preparada = None
            try:
                iniciar_instalacao(script)
            except (ErroAtualizacao, OSError) as erro:
                self.release_disponivel = self.operacao_atualizacao = None
                self.botao_atualizacao.state(["!disabled"])
                self.botao_atualizacao.configure(text="Tentar novamente")
                self.status_atualizacao.set(str(erro))
                try:
                    executavel.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                self.status_atualizacao.set("Instalando a atualização. O app será reiniciado.")
                self.fechar()
            finally:
                try:
                    script.unlink(missing_ok=True)
                except OSError:
                    pass
        elif self.release_disponivel and self.opcoes["atualizar_auto"].get() and getattr(sys, "frozen", False):
            self._baixar_release()

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

    def alternar(self, origem="botao"):
        if self.worker is not None:
            if not self.parar.is_set():
                self.parar.set()
                self.relogio.pausar(time.monotonic())
                self.botao.state(["disabled"])
                self.atividade.set(SOLTANDO_CONTROLES)
                self.atualizar_pausa()
                if self.diagnostico:
                    self.diagnostico.registrar("pausa_solicitada", origem=origem)
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
        if self.fluxo.rearmar_fila() and self.diagnostico:
            self.diagnostico.registrar("espera_fila_rearmada_por_iniciar")
        self.relogio.prazo_saida = self.fluxo.prazo_saida
        self.relogio.iniciar(time.monotonic())
        self.status.set("Iniciando")
        self.botao.configure(text="Pausar")
        self.parar = Event()
        self.worker = Thread(target=monitorar, args=(self.windows, self.fluxo, self.eventos, self.parar, self.diagnostico))
        self.worker.start()

    def atualizar_pausa(self):
        if self.worker is None:
            return
        if not self.worker.is_alive():
            self.worker = None
            self.relogio.pausar(time.monotonic())
            self.status.set("Pausado")
            self.botao.configure(text="Iniciar")
            self.botao.state(["!disabled"])
            if self.atividade.get() in (SOLTANDO_CONTROLES, FINALIZANDO_LEITURA):
                self.atividade.set("Automação pausada. Use Iniciar ou F6 para retomar.")
        elif self.parar.is_set():
            if self.windows.entrada_em_andamento():
                self.status.set("Pausando")
            else:
                if self.status.get() != "Pausado":
                    self.status.set("Pausado")
                    if self.atividade.get() == SOLTANDO_CONTROLES:
                        self.atividade.set(FINALIZANDO_LEITURA)

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
            metodo = {"cor+OCR": "cor/OCR", "texto": "OCR", "template": "template"}[alvo.metodo]
            texto = (f"{ROTULOS.get(alvo.nome, alvo.nome)} · centro ({centro_x}, {centro_y})"
                     f" · {metodo} · score {alvo.score:.0%}")
        elif detector.dialogo_ambiguo:
            texto = "Mais de um botão de confirmação plausível nesta imagem."
        elif detector.ler_contexto(quadro, "modo_esquadrao"):
            texto = "Painel reconhecido: Esquadrão com Preencher."
        elif detector.ler_contexto(quadro, "tela_regiao"):
            texto = "Aba Jogo reconhecida: Região de Pareamento."
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
        self._processar_atualizacao()
        if self.windows.f6_pressionado() and not self.fechando and "disabled" not in self.botao.state():
            self.alternar("f6")
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
            elif evento == "prazo_saida":
                self.relogio.prazo_saida = valor
            elif evento == "erro" or (evento == "acao" and self.parar is not None and not self.parar.is_set()):
                self.atividade.set(valor)
        self.atualizar_pausa()
        saida, farmando = self.relogio.valores(time.monotonic())
        if saida != self.proxima_saida.get():
            self.proxima_saida.set(saida)
            self.rotulo_proxima_saida.configure(style="MetricaVazia.TLabel" if saida == "—" else "MetricaValor.TLabel")
        if farmando != self.farmando.get():
            self.farmando.set(farmando)
        if self.fechando and (self.worker is None or not self.worker.is_alive()):
            self.janela.destroy()
        else:
            self.janela.after(45, self.atualizar)

    def fechar(self):
        self.fechando = True
        self.relogio.pausar(time.monotonic())
        if self.parar:
            self.parar.set()


def verificar_build():
    detector = Detector()
    if faltando := TEMPLATES.keys() - detector.templates.keys():
        raise RuntimeError("Imagens ausentes no pacote: " + ", ".join(sorted(faltando)))
    for nome, (x, y) in (("jogar", (650, 210)), ("continuar", (650, 448)), ("lobby_pronto", (20, 420)),
                        ("lobby_jogar", (20, 420))):
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
    onibus = np.zeros((1080, 1920, 3), dtype=np.uint8)
    aviso = detector.templates["onibus"]
    h, w = aviso.shape[:2]
    onibus[550:550 + h, 1150:1150 + w] = aviso
    reconhecido, score = detector.aviso_onibus(onibus)
    if reconhecido is None or score < 0.8:
        raise RuntimeError("Falha na leitura do aviso PARA PULAR.")
    fluxo_no_onibus = Fluxo(detector)
    if fluxo_no_onibus.passo(onibus, 0, no_onibus=True) is not None:
        raise RuntimeError("O salto exigia dois quadros do aviso.")
    salto = fluxo_no_onibus.passo(onibus.copy(), 0.3, no_onibus=True)
    if salto is None or salto.passos != (("teclas", (57,), 0.16),):
        raise RuntimeError("O salto precisa enviar somente Espaço, inclusive sem fila iniciada pelo app.")
    asa = np.zeros_like(onibus)
    aviso = detector.templates["asa_delta"]
    h, w = aviso.shape[:2]
    asa[550:550 + h, 1150:1150 + w] = aviso
    alvo_asa, _ = detector.aviso_asa(asa)
    if alvo_asa is None:
        raise RuntimeError("O aviso Entrar em queda livre não foi reconhecido.")
    fluxo_asa = Fluxo(detector)
    fluxo_asa.passo(asa, 0, asa_delta=True)
    if (fechar_asa := fluxo_asa.passo(asa.copy(), 0.3, asa_delta=True)) is None or fechar_asa.tipo != "fechar_asa":
        raise RuntimeError("O app precisa fechar a asa-delta após dois quadros consecutivos.")
    hud = np.zeros((540, 960, 3), dtype=np.uint8)
    hud[475:486, 32:105] = (0, 215, 145)
    if detector.em_partida(hud):
        raise RuntimeError("Uma barra verde sem cruz foi confundida com HUD.")
    hud[477:484, 25:27] = 255
    hud[479:482, 23:30] = 255
    hud = hud.copy()
    if not detector.em_partida(hud):
        raise RuntimeError("Falha na leitura da barra de vida.")
    fluxo_sem_fila = Fluxo(detector)
    for instante in (0, 0.3, 0.8, 1.1, 1.5):
        fluxo_sem_fila.passo(hud, instante, partida=True)
    if fluxo_sem_fila.inicio_partida is not None or fluxo_sem_fila.partidas:
        raise RuntimeError("HUD já visível iniciou uma partida sem nova fila.")
    from PIL import ImageDraw, ImageFont
    fonte_aviso = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arialbd.ttf"), 25)
    aviso_texto = Image.new("RGB", (1280, 800), "#224463")
    ImageDraw.Draw(aviso_texto).text((855, 432), "ESPAÇO PARA PULAR", font=fonte_aviso,
                                   fill="white", anchor="mm")
    quadro_aviso = cv2.cvtColor(np.asarray(aviso_texto), cv2.COLOR_RGB2BGR)
    alvo_texto, _ = detector.aviso_onibus(quadro_aviso)
    if alvo_texto is None or alvo_texto.metodo != "texto":
        raise RuntimeError("O aviso do ônibus com outro estilo precisa ser reconhecido pelo texto.")
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
        windows.iniciar_atalho()
        janela.mainloop()
    finally:
        windows.fechar_atalho()
        if diagnostico:
            diagnostico.fechar()


if __name__ == "__main__":
    main()
