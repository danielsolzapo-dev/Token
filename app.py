"""Interface do Auto Farm para Windows."""

from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
import webbrowser
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from atualizador import (
    ErroAtualizacao, baixar_atualizacao, buscar_atualizacao, criar_script_instalacao,
    iniciar_instalacao, preparar_executavel,
)
from logica_autofarm import (
    Config, Detector, DetectorBau, Fluxo, ObservadorBau, TECLAS, TEMPLATES,
)
from notificacoes import NotificadorWindows
from versao import VERSAO
from windows_game import Windows


BG = "#0c121c"
PAINEL = "#151f2e"
PAINEL_CLARO = "#1c2a3d"
BORDA = "#2a3a50"
TEXTO = "#edf2fa"
MUTED = "#9caec4"
ACENTO = "#b9e879"
VERDE = "#75d6a1"
LARANJA = "#f0b76b"
VERMELHO = "#f07b83"
CONFIG = Path(os.getenv("LOCALAPPDATA", ".")) / "AutoFarmToken" / "ajustes.json"
LOG_FILE = CONFIG.with_name("autofarm.log")
CHEST_REFERENCE = CONFIG.with_name("referencia_bau.png")
DEBUG_DIR = CONFIG.parent / "debug"
CAMPOS = ("clicar_continuar", "fallback_cor", "sair_por_tempo", "anti_afk",
          "avisar_bau", "notificacoes", "capturas_diagnostico", "minutos_partida")
ROTULOS = {
    "jogar": "Jogar Novamente", "continuar": "Continuar", "lobby_jogar": "Jogar",
    "lobby_pronto": "Pronto", "menu_aba": "Abrir menu", "voltar_lobby": "Voltar ao lobby",
    "resgatar": "Resgatar", "confirmar_sair": "Confirmar saída", "aba_jogar": "Aba Jogar",
    "bau": "Baú visível",
}


def configurar_logger(caminho=None):
    caminho = Path(caminho) if caminho is not None else LOG_FILE
    caminho.parent.mkdir(parents=True, exist_ok=True)
    identificador = str(caminho.resolve())
    nome = hashlib.sha256(identificador.encode("utf-8")).hexdigest()
    logger = logging.getLogger("autofarm." + nome)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(caminho, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def descrever_entrada(acao, janela):
    if acao.tipo == "clicar" and acao.alvo is not None:
        alvo = acao.alvo
        x, y = (round(ponto) for ponto in alvo.centro)
        coordenadas = f"centro_janela=({x},{y})"
        area = getattr(janela, "area", None)
        if area and len(area) == 4:
            coordenadas += f" tela=({area[0] + x},{area[1] + y})"
        nome = {
            "lobby_jogar": "JOGAR (lobby)",
            "lobby_pronto": "PRONTO (lobby)",
        }.get(alvo.nome, ROTULOS.get(alvo.nome, alvo.nome))
        identificacao = "OCR" if alvo.metodo == "texto" else f"{alvo.metodo} {alvo.score:.2f}"
        return (
            f"Clique em {nome} ({identificacao}) "
            f"{coordenadas} via SendInput."
        )
    if acao.tipo == "esc":
        return "ESC pressionado via SendInput."
    if acao.tipo == "movimento":
        inverso = {scan: tecla for tecla, scan in TECLAS.items()}
        teclas = sorted({
            inverso[scan]
            for passo in acao.passos if passo[0] in ("teclas", "andar_mouse")
            for scan in passo[1] if scan in inverso
        })
        return (
            f"Movimento anti-AFK ({'/'.join(teclas) or 'mouse'}; "
            f"{len(acao.passos)} passo(s)) via SendInput."
        )
    return f"Ação {acao.tipo} via SendInput."


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


def monitorar(windows, fluxo, eventos, parar, detector_bau=None):
    estado_anterior = acao_anterior = None
    assinatura_anterior = None
    dialogo_ambiguo_anterior = False
    logger = None
    observador_bau = ObservadorBau()
    proxima_busca_bau = 0.0
    capturas_salvas = set()
    quadro = None
    inicio_monotonic = time.monotonic()
    relatorio = {
        "versao": VERSAO,
        "inicio_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fim_local": None,
        "duracao_segundos": 0.0,
        "filas_confirmadas": 0,
        "partidas_iniciadas": 0,
        "retornos_ao_lobby": 0,
        "alertas_bau": 0,
        "falhas_de_entrada": 0,
        "interrupcoes_foco_janela": 0,
        "erros": [],
    }
    retorno_lobby_pendente = False

    def avisar(titulo, mensagem):
        if fluxo.config.notificacoes:
            eventos.put(("notificacao", (titulo, mensagem)))

    def salvar_captura(motivo, imagem):
        if (not getattr(fluxo.config, "capturas_diagnostico", False)
                or logger is None or imagem is None or motivo in capturas_salvas):
            return
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            nome = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_{motivo}.jpg"
            sucesso, buffer = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not sucesso:
                raise ValueError("O OpenCV não conseguiu codificar a captura.")
            caminho = DEBUG_DIR / nome
            caminho.write_bytes(buffer.tobytes())
        except (OSError, ValueError, cv2.error):
            logger.exception("Falha ao salvar captura de diagnóstico motivo=%s", motivo)
        else:
            capturas_salvas.add(motivo)
            logger.info("Captura salva em %s", caminho)

    aguardar = getattr(windows, "aguardar", parar.wait)
    try:
        logger = configurar_logger()
        logger.info("Automação INICIADA. versão=%s.", VERSAO)
        detector = fluxo.detector
        if fluxo.config.avisar_bau and detector_bau is None:
            raise ValueError("Selecione uma referência de baú antes de iniciar o aviso.")
        if faltando := TEMPLATES.keys() - detector.templates.keys():
            raise ValueError("Imagens de referência ausentes: " + ", ".join(sorted(faltando)))
        while not parar.is_set():
            janela = windows.fortnite_em_foco()
            quadro = windows.capturar(janela) if janela else None
            pronto = janela is not None and windows.disponivel(janela, parar)
            if pronto:
                hud_visivel = detector.em_partida(quadro)
                estado_especial = detector.procurar(
                    quadro, ("espectador", "reinicializando"), 0.8,
                ) if hud_visivel else None
                espectador_ou_reset = estado_especial is not None
                partida = hud_visivel and not espectador_ou_reset
                inventario = bool(detector.procurar(quadro, ("inventario",), 0.8)) if partida else False
                cursor = windows.cursor_visivel()
                menu_saida = bool(detector.procurar(
                    quadro, ("voltar_lobby",), limiar=None if cursor else 0.92,
                )) if partida else False
                pausado = menu_saida
                tela_desconhecida = not hud_visivel and not detector.procurar(
                    quadro, ("jogar", "continuar", "lobby_jogar", "lobby_pronto", "voltar_lobby"), 0.8,
                )
                if detector.dialogo_ambiguo and not dialogo_ambiguo_anterior:
                    logger.warning("dialogo_saida_ambiguo acao_bloqueada")
                    eventos.put(("acao", "Confirmação de saída ambígua. Confira o jogo."))
                    salvar_captura("dialogo_ambiguo", quadro)
                dialogo_ambiguo_anterior = detector.dialogo_ambiguo
                onibus = bool(detector.procurar(quadro, ("onibus",), 0.8))
                contagem = fluxo.partidas
                partida_antes = fluxo.inicio_partida is not None
                instante = time.monotonic()
                acao = fluxo.passo(quadro, instante, partida=partida, cursor=cursor,
                                   no_onibus=onibus, hud_visivel=hud_visivel)
                partida_agora = fluxo.inicio_partida is not None
                if not partida_antes and partida_agora:
                    relatorio["partidas_iniciadas"] += 1
                    logger.info(
                        "Partida nova reconhecida. Cronômetro iniciado; anti-AFK ativo=%s.",
                        fluxo.config.anti_afk,
                    )
                    avisar("Partida reconhecida", "O Auto Farm confirmou uma partida nova.")
                if partida_antes and not partida_agora and retorno_lobby_pendente:
                    relatorio["retornos_ao_lobby"] += 1
                    logger.info("Retorno ao lobby reconhecido.")
                    avisar("Retorno ao lobby", "O retorno ao lobby foi reconhecido.")
                    retorno_lobby_pendente = False
                if (acao and (acao.tipo == "esc" or (
                        acao.tipo == "clicar" and acao.alvo and acao.alvo.nome == "voltar_lobby"))):
                    retorno_lobby_pendente = True
                alvo_bau = None
                if detector_bau is not None:
                    if (partida and fluxo.inicio_partida is not None and not inventario
                            and not pausado and not onibus):
                        if instante >= proxima_busca_bau:
                            alvo_bau = detector_bau.detectar(quadro)
                            proxima_busca_bau = instante + 0.9
                            if observador_bau.observar(alvo_bau, quadro.shape[0]) and alvo_bau:
                                relatorio["alertas_bau"] += 1
                                x, y = (round(ponto) for ponto in alvo_bau.centro)
                                logger.info("bau_visivel caixa=%s score=%.3f",
                                            alvo_bau.caixa, alvo_bau.score)
                                mensagem = (
                                    f"Baú visível detectado perto de ({x}, {y}). Nenhuma entrada enviada."
                                )
                                eventos.put(("acao", mensagem))
                                avisar("Baú visível", mensagem)
                    else:
                        proxima_busca_bau = 0.0
                        observador_bau.observar(None, quadro.shape[0])
                if not fluxo.config.anti_afk:
                    bloqueio = "desativado"
                elif not pronto:
                    bloqueio = "janela_ou_foco_indisponivel"
                elif not hud_visivel:
                    bloqueio = "hud_nao_reconhecido"
                elif espectador_ou_reset:
                    bloqueio = "espectador_ou_reinicializacao"
                elif onibus:
                    bloqueio = "onibus"
                elif inventario:
                    bloqueio = "inventario"
                elif pausado:
                    bloqueio = "pausa"
                elif fluxo.inicio_partida is None:
                    bloqueio = "aguardando_partida_nova"
                else:
                    bloqueio = "ativo"
                assinatura = (
                    bool(janela), hud_visivel, partida, espectador_ou_reset, onibus, inventario,
                    pausado, tela_desconhecida, fluxo.inicio_partida is not None, bloqueio,
                    detector.dialogo_ambiguo,
                )
                if assinatura != assinatura_anterior:
                    logger.info(
                        "Estado do detector: focus=%s hud=%s partida=%s espectador_reset=%s onibus=%s "
                        "inventario=%s pausa=%s tela_desconhecida=%s cronometro=%s "
                        "anti_afk=%s bloqueio=%s",
                        bool(janela), hud_visivel, partida, espectador_ou_reset, onibus, inventario,
                        pausado, tela_desconhecida, fluxo.inicio_partida is not None,
                        fluxo.config.anti_afk, bloqueio,
                    )
                    assinatura_anterior = assinatura
                if not pronto:
                    fluxo.pausar()
                    estado = "Aguardando o Fortnite em primeiro plano"
                elif espectador_ou_reset:
                    estado = "Anti-AFK bloqueado: espectador/reinicialização"
                elif onibus:
                    estado = "Anti-AFK bloqueado: ônibus"
                elif inventario:
                    estado = "Anti-AFK bloqueado: inventário"
                elif pausado:
                    estado = "Anti-AFK bloqueado: menu/pausa"
                elif partida and fluxo.inicio_partida is None:
                    estado = "HUD detectado; aguardando confirmação de partida nova"
                elif partida and fluxo.inicio_partida is not None:
                    estado = "Em partida" if fluxo.config.anti_afk else "Em partida · anti-AFK desativado"
                elif tela_desconhecida:
                    estado = "Tela não reconhecida; anti-AFK bloqueado"
                else:
                    estado = "Procurando botões"
                acao_de_entrada = acao is not None and acao.tipo in ("esc", "clicar", "movimento")
                if acao_de_entrada:
                    alvo = acao.alvo.nome if acao.tipo == "clicar" else acao.tipo
                    descricao_entrada = descrever_entrada(acao, janela)
                    logger.info(
                        "Ação solicitada: %s tentativa=%s.",
                        descricao_entrada, acao.tentativa,
                    )
                    try:
                        executada = windows.executar(janela, acao, parar)
                    except (OSError, ValueError, cv2.error):
                        relatorio["falhas_de_entrada"] += 1
                        logger.exception("Erro ao executar ação: %s", descricao_entrada)
                        raise
                    if executada:
                        logger.info("Ação enviada: %s", descricao_entrada)
                    else:
                        motivo = getattr(windows, "ultima_falha", None) or "entrada_recusada"
                        relatorio["falhas_de_entrada"] += 1
                        logger.warning(
                            "Ação não concluída: %s tentativa=%s motivo=%s.",
                            descricao_entrada, acao.tentativa, motivo,
                        )
                        salvar_captura("entrada_recusada", quadro)
                else:
                    executada = acao is not None
                    if acao and acao.tipo in (
                        "clique_ignorado", "partida_nao_confirmada", "fila_sem_partida",
                        "tela_nao_reconhecida", "menu_nao_encontrado", "lobby_nao_encontrado",
                    ):
                        salvar_captura(acao.tipo, quadro)
                if acao and acao.tipo == "clicar":
                    fluxo.registrar_clique(acao, executada, time.monotonic(), hud_visivel=hud_visivel)
                if fluxo.partidas != contagem:
                    relatorio["filas_confirmadas"] += max(0, fluxo.partidas - contagem)
                    if acao and acao.tipo == "fila_confirmada":
                        logger.info("Fila confirmada. Partidas reiniciadas: %s.", fluxo.partidas)
                    else:
                        logger.info("Partida reconhecida na fila. Contador: %s.", fluxo.partidas)
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
                        }.get(acao.tipo)
                    if texto and texto != acao_anterior:
                        eventos.put(("acao", texto))
                        logger.info("Evento: %s.", texto)
                        acao_anterior = texto
                elif acao:
                    fluxo.pausar()
                    if not parar.is_set():
                        eventos.put(("acao", "Ação interrompida. Confira a janela e o foco do Fortnite."))
            else:
                observador_bau.observar(None, 1)
                fluxo.pausar()
                estado = "Aguardando o Fortnite em primeiro plano"
                assinatura = (False, "janela_ou_foco_indisponivel")
                if assinatura != assinatura_anterior:
                    logger.info("estado focus=false anti_afk=%s bloqueio=janela_ou_foco_indisponivel",
                                fluxo.config.anti_afk)
                    assinatura_anterior = assinatura
            if estado != estado_anterior:
                logger.info("Status: %s.", estado)
                eventos.put(("estado", estado))
                if estado == "Aguardando o Fortnite em primeiro plano":
                    relatorio["interrupcoes_foco_janela"] += 1
                    logger.info("Foco perdido; automação aguardando o Fortnite.")
                    avisar("Fortnite sem foco", "O monitor aguarda o Fortnite em primeiro plano.")
                elif estado_anterior == "Aguardando o Fortnite em primeiro plano":
                    logger.info("Foco do Fortnite restaurado.")
                    avisar("Foco restaurado", "O Fortnite voltou ao primeiro plano.")
                estado_anterior = estado
            aguardar(0.18 if pronto else 0.3)
    except (OSError, ValueError, cv2.error) as erro:
        relatorio["erros"].append(f"{type(erro).__name__}: {erro}")
        if logger:
            logger.exception("monitor_encerrado_com_erro")
            salvar_captura("erro_monitor", quadro)
        eventos.put(("erro", str(erro)))
        avisar("Erro no Auto Farm", str(erro))
    finally:
        fluxo.pausar()
        if logger:
            logger.info("Automação PAUSADA/ENCERRADA.")
        relatorio["fim_local"] = datetime.now().astimezone().isoformat(timespec="seconds")
        relatorio["duracao_segundos"] = round(max(0.0, time.monotonic() - inicio_monotonic), 1)
        eventos.put(("relatorio", relatorio))
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
        self.eventos_atualizacao = SimpleQueue()
        self.worker = self.parar = None
        self.worker_atualizacao = None
        self.release_disponivel = None
        self.resumo_sessao = None
        self.notificador = None
        self.f6_anterior = self.fechando = False
        self.status = tk.StringVar(janela, "Pausado")
        self.atividade = tk.StringVar(janela, "A sessão começa quando você clicar em Iniciar.")
        self.status_atualizacao = tk.StringVar(janela, "Verificando atualizações ao iniciar…")
        self.total = tk.StringVar(janela, "0")
        self.opcoes = {nome: tk.BooleanVar(janela, getattr(self.config, nome)) for nome in CAMPOS[:-1]}
        self.minutos = tk.StringVar(janela, f"{self.config.minutos_partida:g}".replace(".", ","))
        self.detector_bau = None

        janela.title(f"Auto Farm · {VERSAO}")
        janela.configure(bg=BG)
        janela.minsize(640, 660)
        janela.geometry("720x780")
        janela.protocol("WM_DELETE_WINDOW", self.fechar)
        self.estilo()
        self.montar()
        janela.after(45, self.atualizar)
        janela.after(1000, lambda: self.verificar_atualizacoes(automatico=True))

    def estilo(self):
        estilo = ttk.Style(self.janela)
        estilo.theme_use("clam")
        estilo.configure(".", font=("Segoe UI", 10), foreground=TEXTO, background=BG)
        estilo.configure("TFrame", background=BG)
        estilo.configure("Card.TFrame", background=PAINEL)
        estilo.configure("Inset.TFrame", background=PAINEL_CLARO)
        estilo.configure("Card.TLabel", background=PAINEL, foreground=TEXTO)
        estilo.configure("Inset.TLabel", background=PAINEL_CLARO, foreground=TEXTO)
        estilo.configure("Info.TLabel", foreground=MUTED, background=BG)
        estilo.configure("CardInfo.TLabel", foreground=MUTED, background=PAINEL)
        estilo.configure("InsetInfo.TLabel", foreground=MUTED, background=PAINEL_CLARO)
        estilo.configure("Eyebrow.TLabel", foreground=ACENTO, background=BG,
                         font=("Segoe UI", 9, "bold"))
        estilo.configure("CardEyebrow.TLabel", foreground=ACENTO, background=PAINEL,
                         font=("Segoe UI", 9, "bold"))
        estilo.configure("Titulo.TLabel", foreground=TEXTO, background=BG,
                         font=("Segoe UI Semibold", 25))
        estilo.configure("Secao.TLabel", foreground=TEXTO, background=BG,
                         font=("Segoe UI Semibold", 12))
        estilo.configure("Numero.TLabel", foreground=ACENTO, background=PAINEL_CLARO,
                         font=("Segoe UI Semibold", 26))
        estilo.configure("Badge.TLabel", foreground=ACENTO, background=PAINEL_CLARO,
                         font=("Segoe UI", 9, "bold"), padding=(10, 5))
        estilo.configure("Status.TLabel", foreground=ACENTO, background=PAINEL,
                         font=("Segoe UI Semibold", 13))
        estilo.configure("StatusDot.TLabel", foreground=VERDE, background=PAINEL,
                         font=("Segoe UI", 12))
        estilo.configure("TCheckbutton", background=PAINEL, foreground=TEXTO,
                         indicatorcolor=PAINEL_CLARO, padding=4)
        estilo.map("TCheckbutton", indicatorcolor=[("selected", ACENTO)],
                   foreground=[("disabled", MUTED)])
        estilo.configure("TEntry", fieldbackground=PAINEL_CLARO, foreground=TEXTO,
                         insertcolor=TEXTO, bordercolor=BORDA, padding=(8, 6))
        estilo.configure("TButton", background=PAINEL_CLARO, foreground=TEXTO,
                         bordercolor=BORDA, padding=(14, 9), font=("Segoe UI Semibold", 9))
        estilo.map("TButton", background=[("active", "#293b53"), ("disabled", PAINEL)])
        estilo.configure("Primary.TButton", foreground="#17220d", background=ACENTO,
                         bordercolor=ACENTO, font=("Segoe UI Semibold", 10, "bold"))
        estilo.map("Primary.TButton", background=[("active", "#c9f39a"), ("disabled", "#657454")])
        estilo.configure("Separator", background=BORDA)

    def montar(self):
        painel = ttk.Frame(self.janela, padding=(30, 25, 30, 22))
        painel.pack(fill="both", expand=True)
        cabecalho = ttk.Frame(painel)
        cabecalho.pack(fill="x", pady=(0, 20))
        marca = ttk.Frame(cabecalho)
        marca.pack(side="left", fill="x", expand=True)
        ttk.Label(marca, text="AUTO FARM  /  FORTNITE", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(marca, text="Painel de sessão", style="Titulo.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(marca, text="Fila, retorno ao lobby e proteção de inatividade",
                  style="Info.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(cabecalho, text=f"VERSÃO  {VERSAO}", style="Badge.TLabel").pack(anchor="ne", pady=6)

        resumo = ttk.Frame(painel, style="Card.TFrame", padding=16)
        resumo.pack(fill="x", pady=(0, 22))
        esquerda = ttk.Frame(resumo, style="Card.TFrame")
        esquerda.pack(side="left", fill="both", expand=True)
        linha_status = ttk.Frame(esquerda, style="Card.TFrame")
        linha_status.pack(fill="x")
        self.indicador_status = ttk.Label(linha_status, text="●", style="StatusDot.TLabel")
        self.indicador_status.pack(side="left", padx=(0, 8))
        ttk.Label(linha_status, textvariable=self.status, style="Status.TLabel",
                  wraplength=390).pack(side="left", anchor="w")
        ttk.Label(esquerda, textvariable=self.atividade, style="CardInfo.TLabel",
                  wraplength=420).pack(anchor="w", padx=(20, 0), pady=(6, 0))
        direita = ttk.Frame(resumo, style="Inset.TFrame", padding=(16, 8))
        direita.pack(side="right", padx=(18, 0), fill="y")
        ttk.Label(direita, textvariable=self.total, style="Numero.TLabel").pack(anchor="e")
        ttk.Label(direita, text="PARTIDAS", style="InsetInfo.TLabel",
                  font=("Segoe UI", 8, "bold")).pack(anchor="e")

        ttk.Label(painel, text="AUTOMAÇÃO", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 8))
        ajustes = ttk.Frame(painel, style="Card.TFrame", padding=(16, 12))
        ajustes.pack(fill="x", pady=(0, 20))
        opcoes = (
            ("clicar_continuar", "Continuar após eliminação"),
            ("fallback_cor", "Usar alternativa de cor + OCR"),
            ("anti_afk", "Ativar movimento anti-AFK"),
            ("sair_por_tempo", "Retornar ao lobby por tempo"),
            ("avisar_bau", "Avisar ao detectar baú visível"),
            ("notificacoes", "Notificações do Windows"),
        )
        for indice, (nome, texto) in enumerate(opcoes):
            coluna, linha = indice % 2, indice // 2
            ttk.Checkbutton(ajustes, text=texto, variable=self.opcoes[nome]).grid(
                row=linha, column=coluna, sticky="w", padx=(0, 18), pady=5,
            )
        ajustes.columnconfigure(0, weight=1)
        ajustes.columnconfigure(1, weight=1)
        ttk.Separator(ajustes).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 12))
        ttk.Label(ajustes, text="Duração máxima da partida", style="Card.TLabel").grid(
            row=4, column=0, sticky="w",
        )
        campo = ttk.Frame(ajustes, style="Card.TFrame")
        campo.grid(row=4, column=1, sticky="e")
        ttk.Entry(campo, textvariable=self.minutos, width=7, justify="center").pack(side="left")
        ttk.Label(campo, text="minutos  ·  1–60", style="CardInfo.TLabel").pack(side="left", padx=(9, 0))

        comandos = ttk.Frame(painel)
        comandos.pack(fill="x", pady=(0, 18))
        self.botao = ttk.Button(comandos, text="Iniciar", style="Primary.TButton", command=self.alternar)
        self.botao.pack(side="left")
        ttk.Button(comandos, text="Testar imagem", command=self.testar).pack(side="left", padx=(10, 8))
        ttk.Button(comandos, text="Configurar baú", command=self.selecionar_referencia_bau).pack(
            side="left", padx=(0, 8),
        )
        ttk.Label(comandos, text="F6  ·  iniciar / pausar", style="Info.TLabel").pack(side="right")

        diagnosticos = ttk.Frame(painel)
        diagnosticos.pack(fill="x", pady=(0, 18))
        ttk.Button(diagnosticos, text="Abrir log", command=self.abrir_log).pack(side="left")
        self.botao_relatorio = ttk.Button(
            diagnosticos, text="Exportar resumo da sessão", command=self.exportar_resumo,
        )
        self.botao_relatorio.pack(side="left", padx=(10, 0))
        self.botao_relatorio.state(["disabled"])
        ttk.Checkbutton(
            diagnosticos, text="Salvar capturas em falhas",
            variable=self.opcoes["capturas_diagnostico"],
        ).pack(side="left", padx=(10, 0))

        atualizacao = ttk.Frame(painel, style="Card.TFrame", padding=(15, 11))
        atualizacao.pack(fill="x")
        detalhe = ttk.Frame(atualizacao, style="Card.TFrame")
        detalhe.pack(side="left", fill="x", expand=True)
        ttk.Label(detalhe, text="ATUALIZAÇÕES", style="CardEyebrow.TLabel").pack(anchor="w")
        ttk.Label(detalhe, textvariable=self.status_atualizacao, style="CardInfo.TLabel",
                  wraplength=390).pack(anchor="w", pady=(3, 0))
        self.botao_atualizacao = ttk.Button(
            atualizacao, text="Verificar", command=self.acao_atualizacao,
        )
        self.botao_atualizacao.pack(side="right", padx=(12, 0))

    def ler_opcoes(self):
        minutos = float(self.minutos.get().replace(",", "."))
        if not 1 <= minutos <= 60:
            raise ValueError("Informe um tempo de partida entre 1 e 60 minutos.")
        return replace(self.config, minutos_partida=minutos,
                       **{nome: var.get() for nome, var in self.opcoes.items()})

    def verificar_atualizacoes(self, automatico=False):
        if self.fechando or (self.worker_atualizacao and self.worker_atualizacao.is_alive()):
            return
        self.status_atualizacao.set("Consultando os releases oficiais…")
        self.botao_atualizacao.state(["disabled"])
        self.worker_atualizacao = Thread(
            target=self._verificar_atualizacoes_worker,
            args=(automatico,),
            name="verificar-atualizacao",
            daemon=True,
        )
        self.worker_atualizacao.start()

    def _verificar_atualizacoes_worker(self, automatico):
        try:
            release = buscar_atualizacao(VERSAO)
        except (ErroAtualizacao, OSError) as erro:
            self.eventos_atualizacao.put(("falha", str(erro)))
        else:
            self.eventos_atualizacao.put(("resultado", (release, automatico)))

    def acao_atualizacao(self):
        if self.release_disponivel is not None:
            self.instalar_atualizacao()
        else:
            self.verificar_atualizacoes()

    def instalar_atualizacao(self, confirmar=True):
        release = self.release_disponivel
        if release is None or self.fechando:
            return
        if not getattr(sys, "frozen", False):
            if confirmar and not messagebox.askyesno(
                    "Atualização disponível",
                    f"Abrir a página oficial da versão {release.versao} para baixar o executável?",
                    parent=self.janela):
                return
            try:
                abriu = webbrowser.open(release.pagina)
            except OSError:
                abriu = False
            if not abriu:
                messagebox.showinfo(
                    "Atualização disponível",
                    f"Baixe a versão {release.versao} em:\n{release.pagina}",
                    parent=self.janela,
                )
            else:
                self.status_atualizacao.set(f"Página da versão {release.versao} aberta no navegador.")
            return
        if confirmar and not messagebox.askyesno(
                "Instalar atualização",
                f"Baixar a versão {release.versao}, substituir este executável e reiniciar o app?",
                parent=self.janela):
            return
        if self.worker_atualizacao and self.worker_atualizacao.is_alive():
            return
        self.status_atualizacao.set(f"Baixando e verificando a versão {release.versao}…")
        self.botao_atualizacao.state(["disabled"])
        self.worker_atualizacao = Thread(
            target=self._instalar_atualizacao_worker,
            args=(release,),
            name="instalar-atualizacao",
            daemon=True,
        )
        self.worker_atualizacao.start()

    def _instalar_atualizacao_worker(self, release):
        baixado = staged = script = None
        pasta = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "AutoFarmToken" / "updates"
        try:
            baixado = baixar_atualizacao(release, pasta)
            staged = preparar_executavel(baixado, sys.executable, release.sha256)
            script = criar_script_instalacao(staged, sys.executable, os.getpid(), pasta)
            iniciar_instalacao(script)
        except (ErroAtualizacao, OSError) as erro:
            falhas_limpeza = []
            for temporario in (staged, script):
                if temporario is not None:
                    try:
                        temporario.unlink(missing_ok=True)
                    except OSError as erro_limpeza:
                        falhas_limpeza.append(f"{temporario}: {erro_limpeza}")
            mensagem = str(erro)
            if falhas_limpeza:
                mensagem += " · limpeza incompleta: " + "; ".join(falhas_limpeza)
            try:
                configurar_logger().error("atualizacao_falhou versao=%s erro=%s", release.versao, mensagem)
            except OSError as erro_log:
                mensagem += f" · log indisponível: {erro_log}"
            self.eventos_atualizacao.put(("falha", mensagem))
            return
        self.eventos_atualizacao.put(("instalacao_iniciada", release.versao))

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
        detector_bau = None
        if config.avisar_bau:
            try:
                detector_bau = DetectorBau(CHEST_REFERENCE)
            except (OSError, ValueError, cv2.error) as erro:
                self.atividade.set(f"Configure uma referência de baú válida antes de iniciar: {erro}")
                return
        try:
            salvar_config(config)
        except OSError:
            erro_ajustes = "Não foi possível salvar os ajustes neste computador. "
        else:
            erro_ajustes = ""
        self.config = config
        if self.fluxo is None:
            self.fluxo = Fluxo(Detector(config=config))
        else:
            self.fluxo.config = self.fluxo.detector.config = config
        self.fluxo.rearmar_fila()
        self.status.set("Iniciando")
        self.atividade.set(erro_ajustes + self.ativar_fortnite_ao_iniciar())
        self.botao.configure(text="Pausar")
        self.resumo_sessao = None
        self.botao_relatorio.state(["disabled"])
        self.parar = Event()
        self.worker = Thread(
            target=monitorar,
            args=(self.windows, self.fluxo, self.eventos, self.parar, detector_bau),
        )
        self.worker.start()

    def ativar_fortnite_ao_iniciar(self):
        focar = getattr(self.windows, "focar_fortnite", None)
        if not callable(focar):
            return "Clique no Fortnite para liberar a automação."
        try:
            ativado = focar()
        except OSError as erro:
            return f"Não consegui ativar o Fortnite: {erro}. Clique no jogo para continuar."
        if ativado:
            return "Fortnite em primeiro plano; verificando janela e foco antes das ações."
        motivo = getattr(self.windows, "ultima_falha", None) or "não confirmado"
        return f"Fortnite não foi ativado ({motivo}). Clique no jogo para continuar."

    def selecionar_referencia_bau(self):
        caminho = filedialog.askopenfilename(
            parent=self.janela, title="Selecionar um recorte de baú",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp")],
        )
        if not caminho:
            return
        temporaria = CHEST_REFERENCE.with_suffix(".tmp")
        try:
            quadro = detectar_arquivo(caminho)
            DetectorBau(imagem=quadro)
            ok, codificada = cv2.imencode(".png", quadro)
            if not ok:
                raise ValueError("Não foi possível converter a imagem selecionada.")
            CHEST_REFERENCE.parent.mkdir(parents=True, exist_ok=True)
            temporaria.write_bytes(codificada.tobytes())
            temporaria.replace(CHEST_REFERENCE)
        except (OSError, ValueError, cv2.error) as erro:
            mensagem = f"Referência de baú inválida: {erro}"
            try:
                temporaria.unlink(missing_ok=True)
            except OSError as erro_limpeza:
                mensagem += f" · não foi possível limpar o arquivo temporário: {erro_limpeza}"
            self.atividade.set(mensagem)
            return
        self.atividade.set("Referência salva. Ative “Avisar ao detectar baú visível” para receber avisos.")

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
            if alvo is None and not detector.dialogo_ambiguo and CHEST_REFERENCE.is_file():
                alvo = DetectorBau(CHEST_REFERENCE).detectar(quadro)
        except (OSError, ValueError, cv2.error):
            self.atividade.set("Não foi possível testar a imagem. Confira o arquivo e os ajustes.")
            return
        if alvo:
            x, y, w, h = alvo.caixa
            cv2.rectangle(quadro, (x, y), (x + w, y + h), (85, 224, 183), max(2, quadro.shape[0] // 275))
            centro_x, centro_y = (round(ponto) for ponto in alvo.centro)
            cv2.drawMarker(quadro, (centro_x, centro_y), (0, 0, 255), cv2.MARKER_CROSS, 15, 2)
            metodo = {
                "cor+OCR": "cor/OCR",
                "referencia": "referência de imagem",
            }.get(alvo.metodo, "template")
            texto = (f"{ROTULOS.get(alvo.nome, alvo.nome)} · centro ({centro_x}, {centro_y})"
                     f" · {metodo} · score {alvo.score:.0%}")
        elif detector.dialogo_ambiguo:
            texto = "Mais de um botão de confirmação plausível nesta imagem."
        else:
            texto = "Nenhum botão reconhecido nesta imagem."
        self.mostrar_teste(quadro, texto)

    def abrir_log(self):
        if not LOG_FILE.is_file():
            self.atividade.set(f"Log ainda não criado. Inicie o monitoramento; arquivo: {LOG_FILE}")
            return
        try:
            os.startfile(str(LOG_FILE))
        except OSError as erro:
            self.atividade.set(f"Não foi possível abrir o log: {erro}")

    def exportar_resumo(self):
        if self.resumo_sessao is None:
            self.atividade.set("O resumo ficará disponível ao pausar ou encerrar o monitoramento.")
            return
        caminho = filedialog.asksaveasfilename(
            parent=self.janela, title="Exportar resumo da sessão",
            defaultextension=".json", filetypes=[("Relatório JSON", "*.json")],
        )
        if not caminho:
            return
        try:
            Path(caminho).write_text(
                json.dumps(self.resumo_sessao, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as erro:
            self.atividade.set(f"Não foi possível salvar o resumo: {erro}")
            return
        self.atividade.set(f"Resumo exportado: {caminho}")

    def notificar_windows(self, titulo, mensagem):
        if self.fechando or not self.opcoes["notificacoes"].get():
            return
        try:
            if self.notificador is None:
                self.notificador = NotificadorWindows(self.janela.winfo_id())
            self.notificador.notificar(titulo, mensagem)
        except (OSError, RuntimeError) as erro:
            self.atividade.set(f"Notificações do Windows indisponíveis: {erro}")
            try:
                configurar_logger().warning("notificacao_falhou titulo=%s erro=%s", titulo, erro)
            except OSError as erro_log:
                self.atividade.set(f"Notificação falhou: {erro} · log indisponível: {erro_log}")

    def remover_notificador(self):
        if self.notificador is None:
            return
        try:
            self.notificador.fechar()
        except OSError as erro:
            try:
                configurar_logger().warning("notificacao_encerramento_falhou erro=%s", erro)
            except OSError as erro_log:
                self.atividade.set(f"Falha ao remover notificação: {erro} · log indisponível: {erro_log}")
        else:
            self.notificador = None

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
            elif evento == "notificacao":
                self.notificar_windows(*valor)
            elif evento == "relatorio":
                self.resumo_sessao = valor
                self.botao_relatorio.state(["!disabled"])
            elif evento == "total":
                self.total.set(str(valor))
            elif evento in ("acao", "erro"):
                self.atividade.set(valor)
            elif evento == "fim":
                self.status.set("Pausado")
                self.botao.configure(text="Iniciar")
                self.botao.state(["!disabled"])
        while True:
            try:
                evento, valor = self.eventos_atualizacao.get_nowait()
            except Empty:
                break
            if evento == "resultado":
                release, automatico = valor
                self.worker_atualizacao = None
                self.botao_atualizacao.state(["!disabled"])
                self.release_disponivel = release
                if release is None:
                    self.botao_atualizacao.configure(text="Verificar")
                    self.status_atualizacao.set("Você está usando a versão mais recente.")
                else:
                    self.botao_atualizacao.configure(text=f"Atualizar · {release.versao}")
                    self.status_atualizacao.set(f"Versão {release.versao} disponível.")
                    if not automatico or self.fechando:
                        continue
                    if getattr(sys, "frozen", False):
                        pergunta = f"A versão {release.versao} está pronta. Deseja baixar e instalar agora?"
                    else:
                        pergunta = f"A versão {release.versao} está pronta. Abrir a página oficial?"
                    if messagebox.askyesno(
                            "Atualização disponível", pergunta, parent=self.janela):
                        self.instalar_atualizacao(confirmar=False)
            elif evento == "falha":
                self.worker_atualizacao = None
                self.botao_atualizacao.state(["!disabled"])
                self.botao_atualizacao.configure(text="Tentar novamente")
                self.status_atualizacao.set(f"Verificação/instalação falhou: {valor}")
            elif evento == "instalacao_iniciada":
                self.status_atualizacao.set(f"Instalando a versão {valor}; o app será reiniciado.")
                self.fechar()
        self.atualizar_indicador_status()
        if self.fechando and (self.worker is None or not self.worker.is_alive()):
            self.remover_notificador()
            self.janela.destroy()
        else:
            self.janela.after(45, self.atualizar)

    def atualizar_indicador_status(self):
        texto = self.status.get().casefold()
        if any(sinal in texto for sinal in ("bloqueado", "aguardando", "não reconhecida")):
            cor = LARANJA
        elif "partida" in texto or "iniciando" in texto:
            cor = VERDE
        elif "paus" in texto:
            cor = MUTED
        else:
            cor = ACENTO
        self.indicador_status.configure(foreground=cor)

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

    referencia_bau = np.full((48, 56, 3), (38, 29, 24), dtype=np.uint8)
    cv2.rectangle(referencia_bau, (5, 9), (50, 39), (10, 115, 218), -1)
    cv2.rectangle(referencia_bau, (9, 14), (46, 34), (24, 177, 245), 2)
    cv2.line(referencia_bau, (8, 24), (48, 24), (55, 215, 255), 3)
    cv2.circle(referencia_bau, (28, 29), 3, (20, 45, 80), -1)
    detector_bau = DetectorBau(imagem=referencia_bau)
    quadro_bau = np.zeros((540, 960, 3), dtype=np.uint8)
    quadro_bau[200:248, 400:456] = referencia_bau
    alvo_bau = detector_bau.detectar(quadro_bau)
    if alvo_bau is None or alvo_bau.metodo != "referencia":
        raise RuntimeError("Falha na detecção de baú com a referência visual.")
    if detector_bau.detectar(np.zeros_like(quadro_bau)) is not None:
        raise RuntimeError("Uma tela vazia foi confundida com um baú.")

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
    painel = Painel(janela, windows, config=Config())
    if not hasattr(painel, "botao_atualizacao"):
        raise RuntimeError("O painel de atualização não foi criado.")
    if not hasattr(painel, "botao_relatorio"):
        raise RuntimeError("O botão de exportação do resumo não foi criado.")
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
