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
from tkinter import filedialog, font as tkfont, ttk
import webbrowser

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageTk

from atualizador import (ErroAtualizacao, baixar_atualizacao, buscar_atualizacao,
                         criar_script_instalacao, iniciar_instalacao, preparar_executavel)
from diagnostico import Diagnostico
from logica_autofarm import ACOES_AEREAS, Config, Detector, Fluxo, TECLAS, TEMPLATES
from painel_tema import ACENTO, AMBAR, BG, TemaPainel, carregar_inter, escurecer_titulo
from regiao import AMERICA_DO_NORTE, MANHA, NOITE, NORTE, regiao_por_horario
from relogio_painel import RelogioPainel
from tesouros import DetectorTesouros, monitorar_tesouros
from versao import VERSAO
from webhook import ErroWebhook, enviar_webhook, validar_url
from windows_game import Windows, reduzir_prioridade_thread


SOLTANDO_CONTROLES = "Soltando os controles da automação…"
FINALIZANDO_LEITURA = "Controles liberados. Finalizando a leitura da tela…"
CONFIG = Path(os.getenv("LOCALAPPDATA", ".")) / "AutoFarmToken" / "ajustes.json"
ARQUIVO_LOG = CONFIG.with_name("diagnostico.log")
OPCOES = ("clicar_continuar", "fallback_cor", "sair_por_tempo", "anti_afk", "rotina_aerea",
          "atualizar_auto", "resgatar_recompensas", "notificar_tesouros", "regiao_auto")
CAMPOS = (*OPCOES, "minutos_partida", "webhook_url", "regiao_manha", "regiao_noite")
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
        ajustes = {chave: dados[chave] for chave in OPCOES if type(dados.get(chave)) is bool}
        if isinstance(dados.get("webhook_url"), str):
            ajustes["webhook_url"] = dados["webhook_url"]
        for chave, permitido in (("regiao_manha", MANHA), ("regiao_noite", NOITE)):
            if dados.get(chave) in permitido:
                ajustes[chave] = dados[chave]
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


def salvar_falha_regiao(quadro, diagnostico):
    if quadro is None:
        diagnostico.registrar("falha_regiao")
        return
    caminho = ARQUIVO_LOG.parent / "debug" / "regiao_ultima_falha.jpg"
    try:
        ok, imagem = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise ValueError("Captura inválida")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        provisoria = caminho.with_suffix(".tmp")
        provisoria.write_bytes(imagem.tobytes())
        provisoria.replace(caminho)
    except (OSError, ValueError, cv2.error):
        diagnostico.registrar("falha_regiao", captura="indisponivel")
    else:
        diagnostico.registrar("falha_regiao", captura="debug/regiao_ultima_falha.jpg")


def monitorar(windows, fluxo, eventos, parar, diagnostico=None):
    estado_anterior = acao_anterior = None
    dialogo_ambiguo_anterior = False
    leituras_anteriores = None
    proximo_registro = 0.0
    ultimo_tipo = None
    ordem = 0
    captura_resgate = None
    tela_regiao_anterior = leitura_regiao_anterior = captura_regiao = None
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
                                  saida_por_tempo=fluxo.config.sair_por_tempo,
                                  minutos_partida=fluxo.config.minutos_partida)
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
                if diagnostico and fluxo.motivo_anti_afk == "ajustando_regiao":
                    tela = fluxo.regiao.ultima_tela
                    if tela is not None and tela is not tela_regiao_anterior:
                        tela_regiao_anterior = tela
                        if tela.configuracoes or tela.social:
                            captura_regiao = quadro
                        principal, subregiao = tela.pareamento, tela.subregiao
                        seletor = subregiao if (principal and principal.valor == AMERICA_DO_NORTE
                                               and fluxo.regiao.alvo in NORTE) else principal
                        dados = (fluxo.regiao.alvo, tela.social, tela.configuracoes,
                                 principal.valor if principal else None, subregiao.valor if subregiao else None,
                                 bool(seletor and seletor.focada), bool(seletor and seletor.esquerda),
                                 bool(seletor and seletor.direita), bool(tela.aplicar), tela.dialogo_alteracoes)
                        if dados != leitura_regiao_anterior:
                            leitura_regiao_anterior = dados
                            diagnostico.registrar("leitura_regiao", alvo=dados[0], social=dados[1],
                                                  configuracoes=dados[2], pareamento=dados[3], subregiao=dados[4],
                                                  foco_seletor=dados[5], seta_esquerda=dados[6],
                                                  seta_direita=dados[7], aplicar=dados[8], dialogo_alteracoes=dados[9])
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
                          "Descendo de asa-delta" if asa_delta else
                          "Descendo após o salto" if fluxo.motivo_anti_afk == "movimento_aereo" else
                          "Em partida" if partida else
                          "Procurando botões")
                if fluxo.motivo_anti_afk == "aguardando_transicao_da_fila":
                    estado = "Aguardando transição da fila"
                elif fluxo.motivo_anti_afk in ("saida_por_tempo", "saida_por_tempo_sem_hud", "aguardando_menu_de_saida"):
                    estado = "Saindo da partida"
                elif fluxo.motivo_anti_afk == "ajustando_regiao":
                    estado = f"Ajustando região · {fluxo.regiao.alvo}" if fluxo.regiao.alvo else "Voltando ao lobby"
                elif partida and contagem_esquadrao:
                    estado = f"Em partida · {contagem_esquadrao} no HUD do esquadrão"
                tem_entrada = acao is not None and (bool(acao.passos) or acao.tipo in ("clicar", "esc", "apontar"))
                if diagnostico and acao and (tem_entrada or acao.tipo != ultimo_tipo):
                    ordem += 1
                    posicao = ({"centro": tuple(round(v) for v in acao.alvo.centro)}
                               if acao.tipo in ("clicar", "apontar") and acao.alvo.nome.startswith("regiao_")
                               else {})
                    diagnostico.registrar("acao", id=ordem, tipo=acao.tipo,
                                          alvo=acao.alvo.nome if acao.alvo else None,
                                          tentativa=acao.tentativa + 1 if acao.tipo == "clicar" else None,
                                          passos=acao.passos, **posicao)
                ultimo_tipo = acao.tipo if acao else None
                etapa = "enviar_entrada"
                executada = acao is not None and (not tem_entrada or windows.executar(janela, acao, parar))
                if diagnostico and tem_entrada:
                    motivo = None if executada else windows.motivo_interrupcao(janela, parar)
                    diagnostico.registrar("resultado_entrada", id=ordem,
                                          resultado="enviada" if executada else "interrompida", motivo=motivo)
                if diagnostico and acao and acao.tipo in ("regiao_falhou", "regiao_ok"):
                    if acao.tipo == "regiao_falhou":
                        salvar_falha_regiao(captura_regiao, diagnostico)
                    tela_regiao_anterior = leitura_regiao_anterior = captura_regiao = None
                if acao and acao.tipo == "clicar" and not acao.alvo.nome.startswith("regiao_"):
                    fluxo.registrar_clique(acao, executada, time.monotonic(), no_onibus=onibus)
                    if executada and acao.alvo.nome == "resgatar":
                        url = fluxo.config.webhook_url
                        captura_resgate = (url, acao.alvo.item, quadro) if url else None
                elif acao and acao.tipo == "resgate_confirmado":
                    if captura_resgate:
                        eventos.put(("resgate_webhook", captura_resgate))
                    captura_resgate = None
                elif acao and acao.tipo == "clique_ignorado" and acao.alvo.nome == "resgatar":
                    captura_resgate = None
                elif acao and (acao.tipo in ACOES_AEREAS or acao.tipo == "movimento_aereo"):
                    fluxo.embarque.registrar(acao.tipo, executada, time.monotonic())
                if fluxo.partidas != contagem:
                    eventos.put(("total", fluxo.partidas))
                prazo_saida = fluxo.prazo_saida
                if prazo_saida != prazo_anterior:
                    eventos.put(("prazo_saida", prazo_saida))
                    if diagnostico:
                        segundos = None if prazo_saida is None else round(max(0, prazo_saida - time.monotonic()), 1)
                        diagnostico.registrar("cronometro_saida", segundos_restantes=segundos)
                    prazo_anterior = prazo_saida
                if executada:
                    if acao.tipo.startswith("regiao_"):
                        texto = (f"Região confirmada · {acao.alvo.nome}." if acao.tipo == "regiao_ok" else
                                 f"A região {acao.alvo.nome} não foi confirmada. Nova tentativa em 20 min.")
                    elif acao.alvo and acao.alvo.nome.startswith("regiao_"):
                        texto = "Verificando região de pareamento…"
                    elif acao.tipo == "clicar":
                        texto = "Clique enviado em " + ROTULOS.get(acao.alvo.nome, acao.alvo.nome)
                    elif acao.tipo in ("movimento", "movimento_aereo"):
                        teclas = [nome for nome, scan in TECLAS.items()
                                  if any(p[0] in ("teclas", "andar_mouse") and scan in p[1] for p in acao.passos)]
                        rotulo = "descida" if acao.tipo == "movimento_aereo" else "caminhada"
                        acoes = [f"{rotulo} ({'/'.join(teclas)})"] if teclas else []
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
                            "resgate_confirmado": "Recompensa resgatada.",
                            "clique_ignorado": "Botão continua visível após três tentativas",
                            "menu_nao_encontrado": "Menu de saída não encontrado. Tentando de novo em instantes.",
                            "lobby_nao_encontrado": "Lobby não encontrado. Confira se o jogo pede confirmação.",
                            "aguardando_fila": "Aguardando confirmação da fila ou do início da partida",
                            "fila_confirmada": "Fila confirmada. Aguardando o início da partida.",
                            "fila_sem_partida": "Fila confirmada sem início de partida. Aguardando o jogo ou o cancelamento.",
                            "fila_cancelada": "Cancelamento de fila reconhecido.",
                            "partida_confirmada": "Partida reconhecida. Cronômetro iniciado.",
                            "partida_nao_confirmada": "Fila demorando. Continuo aguardando a partida.",
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
        parar.set()
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
        self.atividade = tk.StringVar(janela, "Use Iniciar ou F6 para retomar")
        self.total = tk.StringVar(janela, "0")
        self.proxima_saida = tk.StringVar(janela, "—")
        self.farmando = tk.StringVar(janela, "—")
        self.relogio = RelogioPainel()
        self.status_atualizacao = tk.StringVar(janela, f"Versão {VERSAO}")
        self.opcoes = {nome: tk.BooleanVar(janela, getattr(self.config, nome)) for nome in OPCOES}
        self.minutos = tk.StringVar(janela, f"{self.config.minutos_partida:g}".replace(".", ","))
        self.status_webhook = tk.StringVar(janela, "Webhook configurado" if self.config.webhook_url else "Webhook desativado")
        self.janela_webhook = self.botao_teste_webhook = None
        self.janela_regiao = None
        self.teste_webhook_em_curso = False
        self._pausado_visual = None
        self._proximo_relogio = 0.0

        janela.title(f"Auto Farm {VERSAO}")
        janela.configure(bg=BG)
        janela.geometry("650x735")
        janela.protocol("WM_DELETE_WINDOW", self.fechar)
        familias = set(tkfont.families(janela))
        familia = next((nome for nome in ("Inter Auto Farm", "Inter") if nome in familias), "Segoe UI")
        self.tema = TemaPainel(janela, familia)
        self.montar()
        janela.update_idletasks()
        janela.minsize(590, self.conteudo.winfo_reqheight())
        escurecer_titulo(janela)
        janela.bind("<Map>", lambda evento: escurecer_titulo(janela) if evento.widget is janela else None, add="+")
        self.status.trace_add("write", self.decorar_estado)
        self.decorar_estado()
        janela.after(45, self.atualizar)
        janela.after(1000, self.verificar_automaticamente)

    def decorar_estado(self, *_):
        pausado = self.status.get() in ("Pausado", "Pausando")
        if pausado == self._pausado_visual:
            return
        self._pausado_visual = pausado
        self.rotulo_estado.configure(style="Pausado.TLabel" if pausado else "Status.TLabel")
        self.icone_estado.configure(image=self.tema.icone(
            "pausa" if pausado else "play", AMBAR if pausado else ACENTO, 22))
        self.botao.configure(image=self.tema.icone("play" if pausado else "pausa", BG))

    def botao_com_icone(self, pai, nome, icone, comando, *, principal=False):
        imagem = self.tema.icone(icone, BG) if principal else self.tema.icone(icone)
        return ttk.Button(pai, text=f"  {nome}", image=imagem, compound="left", command=comando,
                          style="Start.TButton" if principal else "TButton")

    def montar(self):
        painel = self.conteudo = ttk.Frame(self.janela, padding=(24, 19, 24, 18))
        painel.pack(fill="both", expand=True)
        cabecalho = ttk.Frame(painel)
        cabecalho.pack(fill="x", pady=(0, 12))
        ttk.Label(cabecalho, image=self.tema.icone("bot", tamanho=28)).grid(row=0, column=0, padx=(0, 11))
        ttk.Label(cabecalho, text="Auto Farm", style="Titulo.TLabel").grid(row=0, column=1, sticky="w")
        versao = ttk.Frame(cabecalho, style="Metrica.TFrame", padding=1)
        versao.grid(row=0, column=2, padx=(10, 0), sticky="w")
        ttk.Label(versao, text=VERSAO, style="Versao.TLabel").pack()
        ttk.Label(cabecalho, text="Fortnite · Fila, saída por tempo e movimento", style="Info.TLabel").grid(
            row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))

        resumo = ttk.Frame(painel, style="Card.TFrame", padding=(14, 10))
        resumo.pack(fill="x", pady=(0, 10))
        estado = ttk.Frame(resumo, style="CardInterior.TFrame")
        estado.pack(fill="x", pady=(0, 8))
        self.icone_estado = ttk.Label(estado, style="Card.TLabel")
        self.icone_estado.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 9), pady=(2, 0))
        self.rotulo_estado = ttk.Label(estado, textvariable=self.status, wraplength=470)
        self.rotulo_estado.grid(row=0, column=1, sticky="w")
        ttk.Label(estado, textvariable=self.atividade, style="CardInfo.TLabel", wraplength=470).grid(
            row=1, column=1, sticky="w", pady=(2, 0))
        metricas = ttk.Frame(resumo, style="CardInterior.TFrame")
        metricas.pack(fill="x")
        for coluna, (titulo, valor) in enumerate((
            ("Partidas", self.total), ("Próxima saída", self.proxima_saida), ("Farmando", self.farmando),
        )):
            metricas.columnconfigure(coluna, weight=1, uniform="metricas")
            cartao = ttk.Frame(metricas, padding=(11, 6), style="Metrica.TFrame")
            cartao.grid(row=0, column=coluna, sticky="nsew", padx=(0, 8 if coluna < 2 else 0))
            ttk.Label(cartao, text=titulo, style="MetricaTitulo.TLabel").pack(anchor="w")
            estilo_valor = "MetricaVazia.TLabel" if valor is self.proxima_saida else "MetricaValor.TLabel"
            rotulo = ttk.Label(cartao, textvariable=valor, style=estilo_valor)
            rotulo.pack(anchor="w")
            if valor is self.proxima_saida:
                self.rotulo_proxima_saida = rotulo
        automacao = ttk.Frame(painel, style="Card.TFrame", padding=(14, 10))
        automacao.pack(fill="x", pady=(0, 10))
        ttk.Label(automacao, text="  Automação", image=self.tema.icone("automacao", tamanho=19),
                  compound="left", style="Secao.TLabel").pack(anchor="w", pady=(0, 5))
        for nome, icone, texto in (
            ("clicar_continuar", "alvo", "Clicar em Continuar após a eliminação"),
            ("fallback_cor", "cor", "Procurar Jogar Novamente pela cor"),
            ("anti_afk", "movimento", "Ativar movimento anti-AFK"),
            ("rotina_aerea", "salto", "Saltar e fechar a asa-delta com Espaço"),
            ("sair_por_tempo", "saida", "Voltar ao lobby após o tempo da partida"),
        ):
            ttk.Checkbutton(automacao, text=f"  {texto}", image=self.tema.icone(icone), compound="left",
                            variable=self.opcoes[nome], style="Switch.TCheckbutton").pack(anchor="w", pady=2)
        ttk.Frame(automacao, height=1, style="Separador.TFrame").pack(fill="x", pady=(5, 7))
        campo = ttk.Frame(automacao, style="CardInterior.TFrame")
        campo.pack(anchor="w")
        ttk.Label(campo, text="Minutos por partida", style="Card.TLabel").pack(side="left", padx=(0, 14))
        minutos = tuple(f"{passo / 2:g}".replace(".", ",") for passo in range(2, 121))
        ttk.Spinbox(campo, textvariable=self.minutos, values=minutos, width=9).pack(side="left", padx=(0, 12))
        ttk.Label(campo, text="1–60 min", style="CardInfo.TLabel").pack(side="left")

        comandos = ttk.Frame(painel)
        comandos.pack(fill="x")
        self.botao = self.botao_com_icone(comandos, "Iniciar", "play", self.alternar, principal=True)
        self.botao_testar = self.botao_com_icone(comandos, "Testar imagem", "imagem", self.testar)
        self.botao_diagnostico = self.botao_com_icone(comandos, "Copiar diagnóstico", "diagnostico",
                                                     self.copiar_diagnostico)
        for coluna, botao in enumerate((self.botao, self.botao_testar, self.botao_diagnostico)):
            comandos.columnconfigure(coluna, weight=1, uniform="acoes")
            botao.grid(row=0, column=coluna, sticky="ew", padx=(0, 8 if coluna < 2 else 0))
        atalhos = ttk.Frame(painel)
        atalhos.pack(fill="x", pady=(5, 10))
        ttk.Label(atalhos, text="F6 para iniciar ou pausar", style="Info.TLabel").pack(side="left", padx=4)
        ttk.Label(atalhos, text="F7 para marcar uma falha no diagnóstico", style="Info.TLabel").pack(side="right", padx=4)

        atualizacao = ttk.Frame(painel, style="Card.TFrame", padding=(14, 10))
        atualizacao.pack(fill="x")
        ttk.Label(atualizacao, text="  Atualizações", image=self.tema.icone("atualizar", tamanho=19),
                  compound="left", style="Secao.TLabel").pack(anchor="w", pady=(0, 5))
        opcoes_atualizacao = ttk.Frame(atualizacao, style="CardInterior.TFrame")
        opcoes_atualizacao.pack(fill="x")
        ttk.Checkbutton(opcoes_atualizacao, text="  Atualizar automaticamente", variable=self.opcoes["atualizar_auto"],
                        command=self.salvar_preferencia_atualizacao, style="Switch.TCheckbutton",
                        image=self.tema.icone("atualizar"), compound="left").pack(side="left")
        self.botao_atualizacao = self.botao_com_icone(opcoes_atualizacao, "Verificar", "atualizar", self.acao_atualizacao)
        self.botao_atualizacao.pack(side="right")
        ttk.Label(atualizacao, textvariable=self.status_atualizacao, style="CardInfo.TLabel",
                  wraplength=500).pack(anchor="w", pady=(4, 0))

        recompensas = ttk.Frame(painel)
        recompensas.pack(fill="x", pady=(10, 0))
        webhook = self.botao_com_icone(recompensas, "Recompensas e webhook", "presente", self.mostrar_webhook)
        regioes = self.botao_com_icone(recompensas, "Regiões por horário", "relogio", self.mostrar_regiao)
        aviso_webhook = ttk.Frame(recompensas, style="Card.TFrame", padding=(8, 4))
        ttk.Label(aviso_webhook, textvariable=self.status_webhook, style="CardInfo.TLabel",
                  image=self.tema.icone("link"), compound="left", wraplength=152,
                  anchor="center").pack(expand=True, fill="x")
        for coluna, item in enumerate((webhook, aviso_webhook, regioes)):
            recompensas.columnconfigure(coluna, weight=1)
            item.grid(row=0, column=coluna, sticky="nsew", padx=(0, 8 if coluna < 2 else 0))

    def mostrar_regiao(self):
        if self.janela_regiao and self.janela_regiao.winfo_exists():
            self.janela_regiao.lift()
            return
        janela = self.janela_regiao = tk.Toplevel(self.janela)
        janela.title("Regiões por horário")
        janela.transient(self.janela)
        painel = ttk.Frame(janela, padding=20)
        painel.pack(fill="both", expand=True)
        ativar = tk.BooleanVar(janela, self.config.regiao_auto)
        manha = tk.StringVar(janela, self.config.regiao_manha)
        noite = tk.StringVar(janela, self.config.regiao_noite)
        estado = tk.StringVar(janela)
        ttk.Checkbutton(painel, text="Ajustar a região antes de entrar na fila", variable=ativar).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(painel, text="Horário de Brasília · Construção e Zero Build", style="Info.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        for linha, (faixa, controle) in enumerate((
            ("00h–06h", ttk.Label(painel, text="NA-Oeste")),
            ("06h–11h", ttk.Combobox(painel, values=MANHA, textvariable=manha, state="readonly")),
            ("11h–18h", ttk.Label(painel, text="Europa")),
            ("18h–00h", ttk.Combobox(painel, values=NOITE, textvariable=noite, state="readonly")),
        ), 2):
            ttk.Label(painel, text=faixa).grid(row=linha, column=0, sticky="w", padx=(0, 24), pady=3)
            controle.grid(row=linha, column=1, sticky="w", pady=3)
        ttk.Button(painel, text="Salvar", command=lambda: self.salvar_regiao(
            ativar.get(), manha.get(), noite.get(), estado)).grid(row=6, column=0, sticky="w", pady=(12, 0))
        ttk.Label(painel, textvariable=estado, style="Info.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def salvar_regiao(self, ativar, manha, noite, estado):
        alteracoes = {"regiao_auto": ativar, "regiao_manha": manha, "regiao_noite": noite}
        config = replace(self.config, **alteracoes)
        try:
            salvar_config(config)
        except OSError:
            estado.set("Não foi possível salvar a programação.")
            return
        self.config = config
        self.opcoes["regiao_auto"].set(ativar)
        if self.fluxo is not None:
            self.fluxo.config = replace(self.fluxo.config, **alteracoes)
        estado.set(f"Região prevista agora: {regiao_por_horario(manha, noite)}." if ativar else
                   "Região automática desativada.")

    def mostrar_webhook(self):
        if self.janela_webhook and self.janela_webhook.winfo_exists():
            self.janela_webhook.lift()
            return
        janela = self.janela_webhook = tk.Toplevel(self.janela)
        janela.title("Recompensas e webhook")
        janela.transient(self.janela)
        painel = ttk.Frame(janela, padding=20)
        painel.pack(fill="both", expand=True)
        resgatar = tk.BooleanVar(janela, self.config.resgatar_recompensas)
        tesouros = tk.BooleanVar(janela, self.config.notificar_tesouros)
        url = tk.StringVar(janela, self.config.webhook_url)
        item = tk.StringVar(janela, "Picareta de teste")
        mensagem = tk.StringVar(janela, "Este é um teste do Auto Farm.")
        ttk.Checkbutton(painel, text="Resgatar recompensas automaticamente no lobby",
                        variable=resgatar).pack(anchor="w")
        ttk.Checkbutton(painel, text="Notificar tesouros elementais encontrados",
                        variable=tesouros).pack(anchor="w", pady=(6, 0))
        ttk.Label(painel, text="URL do webhook (Discord ou compatível)").pack(anchor="w", pady=(12, 2))
        entrada = ttk.Entry(painel, textvariable=url, width=62, show="•")
        entrada.pack(fill="x")
        ttk.Label(painel, text="Nome do item de teste").pack(anchor="w", pady=(12, 2))
        ttk.Entry(painel, textvariable=item).pack(fill="x")
        ttk.Label(painel, text="Mensagem de teste").pack(anchor="w", pady=(12, 2))
        ttk.Entry(painel, textvariable=mensagem).pack(fill="x")
        comandos = ttk.Frame(painel)
        comandos.pack(fill="x", pady=(12, 6))
        ttk.Button(comandos, text="Salvar", command=lambda: self.salvar_webhook(
            url.get(), resgatar.get(), tesouros.get())).pack(side="left")
        self.botao_teste_webhook = ttk.Button(
            comandos, text="Testar com tela atual",
            command=lambda: self.testar_webhook(url.get(), item.get(), mensagem.get())
        )
        self.botao_teste_webhook.pack(side="left", padx=8)
        if self.teste_webhook_em_curso:
            self.botao_teste_webhook.state(["disabled"])
        ttk.Label(painel, text="O teste captura a tela em 3 segundos. Deixe visível o que quer enviar.",
                  style="Info.TLabel", wraplength=440).pack(anchor="w")
        ttk.Label(painel, textvariable=self.status_webhook, style="Info.TLabel",
                  wraplength=440).pack(anchor="w", pady=(6, 0))

    def salvar_webhook(self, url, resgatar, tesouros=None):
        url = url.strip()
        tesouros = self.config.notificar_tesouros if tesouros is None else tesouros
        alteracoes = dict(webhook_url=url, resgatar_recompensas=resgatar, notificar_tesouros=tesouros)
        config = replace(self.config, **alteracoes)
        try:
            if url:
                validar_url(url)
            salvar_config(config)
        except ErroWebhook as erro:
            self.status_webhook.set(str(erro))
            return
        except OSError:
            self.status_webhook.set("Não foi possível salvar o webhook.")
            return
        self.config = config
        self.opcoes["resgatar_recompensas"].set(resgatar)
        self.opcoes["notificar_tesouros"].set(tesouros)
        if self.fluxo is not None:
            self.fluxo.config = replace(self.fluxo.config, **alteracoes)
        self.status_webhook.set("Webhook salvo." if url else "Envio de webhook desativado.")

    def testar_webhook(self, url, nome, mensagem):
        try:
            validar_url(url)
        except ErroWebhook as erro:
            self.status_webhook.set(str(erro))
            return
        self.teste_webhook_em_curso = True
        self.botao_teste_webhook.state(["disabled"])
        self.status_webhook.set("Capturando a tela em 3 segundos…")
        self.janela.after(3000, lambda: self.iniciar_envio_webhook(
            url, nome=nome.strip() or "Picareta de teste", teste=True, mensagem=mensagem))

    def iniciar_envio_webhook(self, url, nome, quadro=None, *, teste=False, mensagem="", tesouro=False):
        Thread(target=self._enviar_webhook, args=(url, nome, quadro, teste, mensagem, tesouro), daemon=True).start()

    def _enviar_webhook(self, url, nome, quadro, teste, mensagem, tesouro):
        try:
            if quadro is None:
                jogo = self.windows.fortnite_em_foco()
                quadro = (self.windows.capturar(jogo) if jogo else
                          cv2.cvtColor(np.asarray(ImageGrab.grab().convert("RGB")), cv2.COLOR_RGB2BGR))
            enviar_webhook(url, quadro, nome, teste=teste, texto_teste=mensagem, tesouro=tesouro)
            texto = "Teste enviado." if teste else "Recompensa enviada ao webhook."
            if tesouro:
                texto = "Tesouro enviado ao webhook."
            sucesso = True
        except ErroWebhook as erro:
            texto, sucesso = str(erro), False
        except (OSError, ValueError, cv2.error):
            texto, sucesso = "Não foi possível capturar ou enviar a tela.", False
        self.eventos.put(("resultado_webhook", (teste, sucesso, texto)))

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
        if self.botao_diagnostico.instate(["disabled"]):
            return
        self.botao_diagnostico.state(["disabled"])
        Thread(target=self._ler_diagnostico, daemon=True).start()

    def _ler_diagnostico(self):
        try:
            texto = self.diagnostico.texto() if self.diagnostico else ""
        except OSError:
            texto = None
        self.eventos.put(("diagnostico_copiado", texto))

    def _mostrar_diagnostico_copiado(self, texto):
        self.botao_diagnostico.state(["!disabled"])
        if texto is None:
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
        self.relogio.prazo_saida = self.fluxo.prazo_saida if self.fluxo else None
        self._proximo_relogio = 0.0
        self.relogio.iniciar(time.monotonic())
        self.status.set("Iniciando")
        self.botao.configure(text="Pausar")
        self.parar = Event()
        self.worker = Thread(target=self._executar_sessao, args=(self.parar,))
        self.worker.start()

    def _executar_sessao(self, parar):
        try:
            reduzir_prioridade_thread()
            if self.fluxo is None:
                self.fluxo = Fluxo(Detector(config=self.config))
            if parar.is_set():
                return
            self.fluxo.config = self.fluxo.detector.config = self.config
            if self.fluxo.rearmar_fila() and self.diagnostico:
                self.diagnostico.registrar("espera_fila_rearmada_por_iniciar")
            contexto = self.windows, self.fluxo, self.eventos, parar, self.diagnostico
            Thread(target=monitorar_tesouros, args=contexto, daemon=True).start()
            monitorar(*contexto)
        except (OSError, ValueError, cv2.error) as erro:
            self.eventos.put(("erro", f"Não foi possível iniciar a automação. {erro}"))
        finally:
            parar.set()

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
        if self.botao_testar.instate(["disabled"]):
            return
        caminho = filedialog.askopenfilename(parent=self.janela, title="Selecionar uma captura",
                                             filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp")])
        if not caminho:
            return
        try:
            config = self.ler_opcoes()
        except ValueError:
            self.atividade.set("Informe um tempo de partida entre 1 e 60 minutos.")
            return
        self.botao_testar.state(["disabled"])
        self.atividade.set("Analisando imagem…")
        Thread(target=self._testar_imagem, args=(caminho, config), daemon=True).start()

    def _testar_imagem(self, caminho, config):
        try:
            reduzir_prioridade_thread()
            quadro, texto = self._analisar_imagem(caminho, config)
            foto = Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
            foto.thumbnail((720, 405))
            resultado = foto, texto
        except Exception as erro:
            resultado = None
            if self.diagnostico:
                self.diagnostico.registrar("erro_teste_imagem", tipo=type(erro).__name__)
        self.eventos.put(("teste_imagem", resultado))

    def _analisar_imagem(self, caminho, config):
        quadro = detectar_arquivo(caminho)
        detector = Detector(config=config)
        alvo = detector.ler_contexto(quadro, "confirmar_sair")
        if alvo is None and not detector.dialogo_ambiguo:
            alvo = detector.detectar(quadro) or detector.procurar(
                quadro, ("lobby_jogar", "lobby_pronto", "voltar_lobby", "resgatar"),
            )
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
        return quadro, texto

    def mostrar_teste(self, foto, texto):
        janela = tk.Toplevel(self.janela)
        janela.title("Teste de imagem")
        janela.transient(self.janela)
        painel = ttk.Frame(janela, padding=14)
        painel.pack(fill="both", expand=True)
        ttk.Label(painel, text=texto).pack(anchor="w", pady=(0, 10))
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
        for _ in range(24):
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
                self._proximo_relogio = 0.0
            elif evento == "teste_imagem":
                self.botao_testar.state(["!disabled"])
                if valor is None:
                    self.atividade.set("Não foi possível testar a imagem. Confira o arquivo e os ajustes.")
                else:
                    if self.atividade.get() == "Analisando imagem…":
                        self.atividade.set("Análise de imagem concluída.")
                    self.mostrar_teste(*valor)
            elif evento == "diagnostico_copiado":
                self._mostrar_diagnostico_copiado(valor)
            elif evento == "resgate_webhook":
                url, nome, quadro = valor
                if url == self.config.webhook_url:
                    self.iniciar_envio_webhook(url, nome, quadro)
            elif evento == "tesouro_webhook":
                url, nome, quadro, sessao = valor
                if (sessao is self.parar and not sessao.is_set() and self.config.notificar_tesouros
                        and url == self.config.webhook_url):
                    self.iniciar_envio_webhook(url, nome, quadro, tesouro=True)
            elif evento == "resultado_webhook":
                teste, sucesso, texto = valor
                if teste:
                    self.teste_webhook_em_curso = False
                    if self.botao_teste_webhook and self.botao_teste_webhook.winfo_exists():
                        self.botao_teste_webhook.state(["!disabled"])
                self.status_webhook.set(texto)
                if self.diagnostico:
                    self.diagnostico.registrar("webhook", teste=teste, enviado=sucesso, resultado=texto)
            elif evento == "erro" or (evento == "acao" and self.parar is not None and not self.parar.is_set()):
                self.atividade.set(valor)
        self.atualizar_pausa()
        agora = time.monotonic()
        if agora >= self._proximo_relogio:
            self._proximo_relogio = agora + 0.25
            self.atualizar_relogio(agora)
        if self.fechando and (self.worker is None or not self.worker.is_alive()):
            self.janela.destroy()
        else:
            self.janela.after(45 if self.worker is not None else 65, self.atualizar)

    def atualizar_relogio(self, agora):
        saida, farmando = self.relogio.valores(agora)
        if saida != self.proxima_saida.get():
            self.proxima_saida.set(saida)
            self.rotulo_proxima_saida.configure(style="MetricaVazia.TLabel" if saida == "—" else "MetricaValor.TLabel")
        if farmando != self.farmando.get():
            self.farmando.set(farmando)

    def fechar(self):
        self.fechando = True
        self.relogio.pausar(time.monotonic())
        if self.parar:
            self.parar.set()


def verificar_build():
    detector = Detector()
    DetectorTesouros()
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
    fluxo_no_onibus.embarque.registrar(salto.tipo, True, 0.46)
    descida = fluxo_no_onibus.passo(np.zeros_like(onibus), 0.72)
    if descida is None or descida.tipo != "movimento_aereo" or descida.passos != (("teclas", (17,), 0.8),):
        raise RuntimeError("A descida precisa iniciar o movimento com W após o salto.")
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
    painel = Painel(janela, windows, config=Config())
    janela.update_idletasks()
    if getattr(sys, "frozen", False):
        fonte = tkfont.Font(janela, font=ttk.Style(janela).lookup("MetricaValor.TLabel", "font"))
        if fonte.actual("family") != "Inter Auto Farm" or len({fonte.measure(n) for n in "0123456789"}) != 1:
            raise RuntimeError("As fontes tabulares do painel não foram carregadas.")
    if painel.botao.cget("state") == "disabled":
        raise RuntimeError("O painel pausado deve permitir iniciar.")
    janela.destroy()


def main():
    carregar_inter()
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
