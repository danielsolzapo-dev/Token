"""Auto Farm do Token Pirata. Consulte Configuracao.md para os recortes."""
import argparse
import ctypes
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from PIL import Image, ImageGrab

from fila import DiarioFortnite, Fila

F8, F9, ESC = 0x77, 0x78, 0x1B
MOUSE_ESQUERDO_PRESSIONAR, MOUSE_ESQUERDO_SOLTAR = 0x0002, 0x0004
MOUSE_MOVER_ABSOLUTO = 0x0001 | 0x4000 | 0x8000
PASTA = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
FUSOS = {
    "europa": "Europe/Paris",
    "america_do_norte": "America/Chicago",
    "asia": "Asia/Tokyo",
    "oceania": "Australia/Sydney",
    "oriente_medio": "Asia/Bahrain",
}


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class Input(ctypes.Structure):
    # MOUSEINPUT é o maior membro da união INPUT no Windows.
    _fields_ = [("type", wintypes.DWORD), ("mouse", MouseInput)]


class Windows:
    def __init__(self):
        api = self.api = ctypes.WinDLL("user32", use_last_error=True)
        api.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        api.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        api.GetForegroundWindow.restype = wintypes.HWND
        api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        api.GetAsyncKeyState.restype = ctypes.c_short
        api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        api.WindowFromPoint.argtypes = [wintypes.POINT]
        api.WindowFromPoint.restype = wintypes.HWND
        api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        api.GetAncestor.restype = wintypes.HWND
        api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        api.SendInput.restype = wintypes.UINT
        api.mouse_event.argtypes = [wintypes.DWORD, ctypes.c_long, ctypes.c_long,
                                    wintypes.DWORD, ctypes.c_size_t]
        api.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE,
                                     wintypes.DWORD, ctypes.c_size_t]

    def janela(self):
        hwnd = self.api.GetForegroundWindow()
        if not hwnd:
            return None
        titulo = ctypes.create_unicode_buffer(256)
        self.api.GetWindowTextW(hwnd, titulo, len(titulo))
        if titulo.value.strip().casefold() != "fortnite":
            return None
        area, origem = wintypes.RECT(), wintypes.POINT()
        if (not self.api.GetClientRect(hwnd, ctypes.byref(area))
                or not self.api.ClientToScreen(hwnd, ctypes.byref(origem))
                or min(area.right, area.bottom) <= 0):
            return None
        return hwnd, (origem.x, origem.y, origem.x + area.right, origem.y + area.bottom)

    def tecla(self, codigo):
        return bool(self.api.GetAsyncKeyState(codigo) & 0x8000)

    def clicar(self, janela, ponto):
        hwnd, (esq, topo, dir_, base) = janela
        x, y = ponto
        if not (esq <= x < dir_ and topo <= y < base):
            raise OSError("O ponto detectado ficou fora da janela do Fortnite.")
        if self.janela() != janela:
            raise OSError("O Fortnite perdeu o foco antes do clique.")
        if not self.mover_cursor(x, y):
            raise OSError("O Windows recusou o movimento do cursor.")
        time.sleep(0.12)
        cursor = wintypes.POINT()
        if (not self.api.GetCursorPos(ctypes.byref(cursor))
                or max(abs(cursor.x - x), abs(cursor.y - y)) > 4):
            raise OSError("O cursor não chegou ao ponto detectado.")
        abaixo = self.api.WindowFromPoint(cursor)
        if self.janela() != janela or self.api.GetAncestor(abaixo, 2) != hwnd:
            raise OSError("O botão está coberto ou a janela perdeu o foco.")
        if not self.botao_mouse(MOUSE_ESQUERDO_PRESSIONAR):
            raise OSError("O Windows não enviou o clique ao jogo.")
        try:
            time.sleep(0.085)
        finally:
            if not self.botao_mouse(MOUSE_ESQUERDO_SOLTAR):
                self.api.mouse_event(MOUSE_ESQUERDO_SOLTAR, 0, 0, 0, 0)
        return True

    def botao_mouse(self, flag):
        return self.enviar_mouse(MouseInput(dwFlags=flag))

    def enviar_mouse(self, mouse):
        evento = Input(mouse=mouse)
        return self.api.SendInput(1, ctypes.byref(evento), ctypes.sizeof(Input)) == 1

    def mover_cursor(self, x, y):
        # Os índices 76–79 descrevem toda a área virtual, inclusive monitores à esquerda.
        esquerda, topo, largura, altura = (self.api.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        if largura > 0 and altura > 0 and esquerda <= x < esquerda + largura and topo <= y < topo + altura:
            dx = int((x - esquerda + 0.5) * 65536 / largura)
            dy = int((y - topo + 0.5) * 65536 / altura)
            if self.enviar_mouse(MouseInput(dx=dx, dy=dy, dwFlags=MOUSE_MOVER_ABSOLUTO)):
                return True
        return bool(self.api.SetCursorPos(x, y))
    def pressionar(self, janela, teclas, duracao=0.06, giro=0):
        if self.janela() != janela:
            return False
        enviadas = []
        try:
            for tecla in teclas:
                if not self.tecla(tecla):
                    scan = self.api.MapVirtualKeyW(tecla, 0)
                    self.api.keybd_event(tecla, scan, 0, 0)
                    enviadas.append((tecla, scan))
            for passo in (1, 2, 3, 3, 2, 1):
                if self.janela() != janela or self.tecla(F9) or self.tecla(F8):
                    break
                if giro:
                    self.api.mouse_event(1, round(giro * passo / 12), 0, 0, 0)
                time.sleep(duracao / 6)
        finally:
            for tecla, scan in reversed(enviadas):
                self.api.keybd_event(tecla, scan, 2, 0)
        return True


def imagem(caminho):
    if not caminho.is_file():
        raise ValueError(f"Falta o recorte: {caminho}")
    with Image.open(caminho) as foto:
        recorte = np.asarray(foto.convert("RGB"))
    if min(recorte.shape[:2]) < 12 or not np.any(recorte.std(axis=(0, 1)) >= 5):
        raise ValueError(f"Recorte pequeno ou uniforme: {caminho}")
    return recorte


def carregar(pasta, usar_regioes=True, exigir_pares=True, automatico=False):
    botoes = {nome: imagem(pasta / f"{nome}.png") for nome in ("jogar", "lobby")} if not automatico else {}
    for caminho in pasta.glob("*.png"):
        if caminho.stem not in botoes:
            botoes[caminho.stem] = imagem(caminho)
    for primeiro, segundo in (("partida", "sair"), ("tesouro", "resgatar")):
        if exigir_pares and (primeiro in botoes) != (segundo in botoes):
            raise ValueError(f"Salve juntos os recortes {primeiro}.png e {segundo}.png.")
    recompensas = {
        caminho.stem: imagem(caminho) for caminho in (pasta / "recompensas").glob("*.png")
    }
    regioes = {}
    for nome in FUSOS if usar_regioes else ():
        dir_regiao = pasta / "regioes" / nome
        if dir_regiao.is_dir():
            passos = sorted(dir_regiao.glob("[0-9][0-9]*.png"))
            if not any(passo.stem.endswith("-verificar") for passo in passos):
                raise ValueError(f"Inclua um passo NN-verificar.png em {dir_regiao}.")
            regioes[nome] = [(imagem(passo), passo.stem.endswith("-verificar")) for passo in passos]
    return botoes, recompensas, regioes


def localizar(tela, recorte, limiar):
    altura, largura = recorte.shape[:2]
    if altura > tela.shape[0] or largura > tela.shape[1]:
        return None
    resultado = cv2.matchTemplate(tela, recorte, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(resultado)
    if score >= limiar:
        return x + largura // 2, y + altura // 2
    return None


def validar_slots(slots):
    if not isinstance(slots, list) or len(slots) != 3:
        raise ValueError("squad.json precisa de três áreas, uma por companheiro.")
    for slot in slots:
        if (not isinstance(slot, list) or len(slot) != 4
                or any(type(n) not in (float, int) or not 0 <= n <= 1 for n in slot)
                or not (0 < slot[2] and 0 < slot[3])
                or slot[0] + slot[2] > 1 or slot[1] + slot[3] > 1):
            raise ValueError("Cada área deve ter [x, y, largura, altura] entre 0 e 1.")
    return slots


def carregar_squad(pasta):
    arquivo = pasta / "squad.json"
    if not arquivo.is_file():
        return None
    dados = json.loads(arquivo.read_text(encoding="utf-8-sig"))
    slots = validar_slots(dados.get("slots") if isinstance(dados, dict) else None)
    ausentes = [imagem(f) for f in (pasta / "squad" / "ausentes").glob("*.png")]
    skins = [imagem(f) for f in (pasta / "squad" / "skins_padrao").glob("*.png")]
    return slots, ausentes, skins


def detectar_squad(tela, squad, limiar, min_skins):
    slots, ausentes, skins = squad
    altura, largura = tela.shape[:2]
    n_ausentes = n_skins = 0
    for x, y, w, h in slots:
        area = tela[round(y * altura):round((y + h) * altura),
                    round(x * largura):round((x + w) * largura)]
        if any(localizar(area, img, limiar) is not None for img in ausentes):
            n_ausentes += 1
        elif any(localizar(area, img, limiar) is not None for img in skins):
            n_skins += 1
    return n_ausentes >= 2 or n_skins >= min_skins


def escolher_regiao(disponiveis, agora):
    horas = {}
    for nome in disponiveis:
        local = agora.astimezone(ZoneInfo(FUSOS[nome]))
        hora = local.hour + local.minute / 60
        if 7 <= hora < 19:
            horas[nome] = abs(hora - 14)
    return min(horas, key=horas.get) if horas else None


def validar_webhook(url):
    if url and not re.fullmatch(r"https://discord\.com/api/(?:v\d+/)?webhooks/\d+/[\w-]+", url, re.ASCII):
        raise ValueError("Use a URL do webhook de um canal do Discord.")
    return url


def url_webhook():
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    arquivo = PASTA / "webhook_discord.txt"
    if not url and arquivo.is_file():
        url = arquivo.read_text(encoding="utf-8-sig").strip()
    return validar_webhook(url)


def enviar_discord(url, item, suspensao=False, *, log=print):
    mensagem = item if suspensao else f"🏴‍☠️ Fortnite — Tesouro detectado: {item}"
    corpo = json.dumps({
        "content": mensagem[:1900],
        "allowed_mentions": {"parse": []},
    }).encode("utf-8")
    pedido = Request(url + "?wait=true", data=corpo, headers={
        "Content-Type": "application/json",
        "User-Agent": "MacroTokenPirata (webhook local)",
    }, method="POST")
    for tentativa in range(2):
        try:
            with urlopen(pedido, timeout=6):
                log(f"Discord: aviso enviado para {item}.")
            return
        except HTTPError as erro:
            espera = erro.headers.get("Retry-After", "")
            if (erro.code == 429 and tentativa == 0 and
                    re.fullmatch(r"\d+(?:\.\d+)?", espera) and float(espera) <= 10):
                time.sleep(float(espera))
                continue
            log(f"Discord: falha HTTP {erro.code} ao enviar o aviso.")
            return
        except (URLError, OSError):
            log("Discord: falha de conexão ao enviar o aviso.")
            return


class Partida:
    def __init__(self, duracao):
        self.duracao = duracao
        self.inicio = None
        self.saida = set()
        self.notificados = set()
        self.ultimo_tesouro = -float("inf")
        self.limite_aviso = False
        self.proximo_movimento = 0
        self.ultimo_movimento = None
        self.squad_ruim_desde = None
        self.saltou = False
        self.queda_ate = 0.0

    def entrar(self, agora):
        self.inicio = agora
        self.saida.clear()
        self.notificados.clear()
        self.limite_aviso = False
        self.proximo_movimento = agora + 4
        self.squad_ruim_desde = None
        self.saltou = False
        self.queda_ate = 0.0

    def encerrar(self):
        self.inicio = None
        self.saida.clear()

    def venceu(self, agora):
        return self.inicio is not None and agora - self.inicio >= self.duracao

    def checar_squad(self, agora, ruim):
        if not ruim:
            self.squad_ruim_desde = None
            return False
        if self.squad_ruim_desde is None:
            self.squad_ruim_desde = agora
        return agora - self.squad_ruim_desde >= 20

    def movimento(self, agora):
        opcoes = ["andar", "camera", "agachar"]
        if self.ultimo_movimento != "andar":
            opcoes.append("pular")
        acao = random.choices(opcoes, weights=[5, 4, 2, 1][:len(opcoes)])[0]
        self.ultimo_movimento = acao
        self.proximo_movimento = agora + random.uniform(2.5, 5.5)
        giro = random.choice((-1, 1)) * random.randint(90, 250)
        if acao == "andar":
            teclas = random.choice(((0x57,), (0x57, 0x41), (0x57, 0x44)))
            return teclas, random.uniform(0.45, 1.4), giro
        if acao == "camera":
            return (), 0.25, giro
        if acao == "agachar":
            return (0xA2,), 0.22, 0
        return (0x20,), 0.10, 0


def carregar_contador():
    arquivo = PASTA / "partidas.json"
    if arquivo.is_file():
        try:
            return max(0, int(json.loads(arquivo.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError):
            print("Não foi possível ler o contador anterior.", flush=True)
    return 0


def gravar_contador(total):
    pendente = PASTA / "partidas.tmp"
    try:
        pendente.write_text(json.dumps(total), encoding="utf-8")
        pendente.replace(PASTA / "partidas.json")
    except OSError:
        print("Não foi possível gravar o contador de partidas.", flush=True)


def monitorar(windows, botoes, recompensas, regioes, squad, args, url, executor,
              *, parar=None, alternar=None, log=print, estado=lambda _: None, ocr=None):
    ativo = parar is not None or getattr(sys, "frozen", False) or not args.executar
    estado("Ativo" if ativo else "Pausado")
    teste_fila = getattr(args, "teste_fila", False)
    fila = teste_fila or getattr(args, "fila", True)
    cronometrar = getattr(args, "cronometrar", True)
    resgatar = getattr(args, "resgatar", True)
    anterior = {}
    tela_anterior = None
    f8_anterior = False
    proxima_captura = 0
    proxima_acao = 0
    partida = Partida(args.minutos * 60)
    configurando = regiao_aplicada = None
    passo_regiao = 0
    total = carregar_contador()
    iniciou_sessao = time.monotonic()
    fase_fila = None
    estado_fila = Fila()
    diario = DiarioFortnite()
    teste_inicio = time.monotonic()
    modo_passo = None
    avisos = set()
    atraso_clique = {"jogar": 7, "lobby": 5, "resgatar": 3}
    log(f"Partidas registradas: {total}. F8 pausa/retoma, F9 encerra.")
    log("Coloque o Fortnite em primeiro plano. Aguardando a tela do jogo.")
    if not args.executar:
        log("Prévia: detecção sem cliques e sem mensagens no Discord.")
    else:
        log("Execução: cliques habilitados.")
        if teste_fila:
            log("Teste de fila: volte ao lobby. O teste termina ao confirmar a entrada ou após 45 segundos.")
        if not fila:
            log("Fila automática desligada em Fila e saída.")

    while not windows.tecla(F9) and not (parar and parar.is_set()):
        agora = time.monotonic()
        f8 = windows.tecla(F8)
        botao_pausa = alternar is not None and alternar.is_set()
        if botao_pausa:
            alternar.clear()
        if (f8 and not f8_anterior) or botao_pausa:
            ativo = not ativo
            anterior = {}
            if ativo:
                iniciou_sessao = agora
                estado_fila.reiniciar()
            estado("Ativo" if ativo else "Pausado")
            log("Ativo." if ativo else "Pausado.")
        f8_anterior = f8
        if not ativo or agora < proxima_captura:
            time.sleep(0.04)
            continue
        proxima_captura = agora + 0.75
        if teste_fila and agora - teste_inicio >= 45:
            log("Teste encerrado: o Fortnite não confirmou a fila em 45 segundos.")
            break
        janela = windows.janela()
        if janela != tela_anterior:
            anterior = {}
            tela_anterior = janela
            if teste_fila:
                log("Fortnite em primeiro plano." if janela else "Fortnite perdeu o foco.")
        if janela is None:
            continue

        _, area = janela
        tela = np.asarray(ImageGrab.grab(bbox=area, all_screens=True).convert("RGB"))
        modelos = dict(botoes)
        for nome in botoes:
            if nome.startswith("modo_") and nome != modo_passo:
                modelos.pop(nome)
        modelos.update({f"item:{nome}": img for nome, img in recompensas.items()})
        if configurando is not None:
            modelos["passo_regiao"] = regioes[configurando][passo_regiao][0]
        atual = ocr.ler(tela, saindo=bool(partida.saida and fase_fila != "saindo"),
                       confirmar="sair" in partida.saida,
                       aguardando_fila=estado_fila.clique_em is not None) if ocr else {}
        atual.update({nome: ponto for nome, recorte in modelos.items()
                      if (ponto := localizar(tela, recorte, args.limiar)) is not None})
        estaveis = {nome for nome, ponto in atual.items() if nome in anterior and
                    max(abs(a - b) for a, b in zip(ponto, anterior[nome])) <= (8 if ocr else 0)}
        novos = estaveis - avisos
        avisos = estaveis
        anterior = atual

        itens = {nome[5:] for nome in estaveis if nome.startswith("item:")}
        if "tesouro" in estaveis:
            if itens:
                partida.ultimo_tesouro = agora
            elif agora - partida.ultimo_tesouro > 20:
                if not any(nome.startswith("item:") for nome in atual):
                    itens.add("Tesouro Encontrado (item não identificado)")
                    partida.ultimo_tesouro = agora
        for item in sorted(itens - partida.notificados):
            partida.notificados.add(item)
            log(f"Recompensa detectada: {item}.")
            if url and args.executar:
                executor.submit(enviar_discord, url, item, log=log)
        if windows.tecla(F9) or (parar and parar.is_set()):
            break

        eventos = diario.ler()
        # O log pode confirmar a fila mesmo se a tela ainda estiver trocando.
        if estado_fila.atualizar(estaveis | eventos):
            fonte = "o log do Fortnite" if eventos else "a tela do Fortnite"
            log(f"Fila confirmada por {fonte}.")
            if teste_fila:
                break
        if estado_fila.desistiu(agora):
            log("O botão Jogar continuou visível após três cliques.")
            if teste_fila:
                break
            log("Pause e retome para tentar de novo.")
        if "jogar" in novos and args.executar:
            log(f"Botão Jogar detectado em {atual['jogar']}.")

        if "lobby" in estaveis or "jogar" in estaveis:
            partida.encerrar()
        elif estaveis & {"partida", "onibus"} and partida.inicio is None and fase_fila != "saindo":
            partida.entrar(agora)
            fase_fila = "partida"
            total += 1
            if args.executar:
                gravar_contador(total)
            log(f"Partida {total}: cronômetro de {args.minutos:g} min iniciado.")

        squad_ruim = (
            squad and "partida" in estaveis and "espectando" not in atual
            and detectar_squad(tela, squad, args.limiar, args.skins_padrao)
        )
        sair_squad = partida.checar_squad(agora, squad_ruim)
        acao = None
        if "suspensao" in estaveis:
            ativo = False
            estado("Pausado")
            log("Aviso de suspensão detectado. Macro pausado.")
            if url and args.executar and "suspensao" not in partida.notificados:
                partida.notificados.add("suspensao")
                executor.submit(enviar_discord, url, "Aviso de suspensão detectado na tela do Fortnite.", True, log=log)
            continue
        if teste_fila:
            if "jogar" in estaveis:
                acao = "jogar"
        elif "tesouro" in atual or itens:
            if resgatar and "tesouro" in estaveis and "resgatar" in estaveis:
                acao = "resgatar"
        elif configurando is not None:
            if "passo_regiao" in estaveis:
                acao = "passo_regiao"
        elif modo_passo is not None:
            if "esquadrao_ok" in estaveis:
                modo_passo = None
            elif modo_passo in estaveis:
                acao = modo_passo
        elif "lobby" in estaveis:
            acao = "lobby"
        elif "aba_tesouro" in estaveis and "aba_jogar" in estaveis:
            acao = "aba_jogar"
        elif "jogar" in estaveis:
            fase_fila = None if fase_fila == "saindo" else fase_fila
            if args.pausar_apos and agora - iniciou_sessao >= args.pausar_apos * 60:
                ativo = False
                estado("Pausado")
                log("Pausa programada no lobby. F8 retoma.")
                continue
            if not fila:
                continue
            if (getattr(args, "confirmar_modo", True)
                    and (ocr or "esquadrao_ok" in botoes) and "esquadrao_ok" not in estaveis):
                if "esquadrao_ok" not in atual and "modo_01" in botoes:
                    modo_passo = "modo_01"
                elif "jogar" in novos:
                    log("Jogar aguardando a confirmação de Esquadrão com Preencher.")
            elif regioes:
                regiao = escolher_regiao(regioes, datetime.now(timezone.utc))
                if regiao != regiao_aplicada and regiao is not None:
                    configurando, passo_regiao = regiao, 0
                    log(f"Região escolhida pelo horário local: {regiao}.")
                elif regiao is None:
                    if "jogar" in novos:
                        log("Nenhuma região configurada está de dia. Aguardando.")
                else:
                    acao = "jogar"
            else:
                acao = "jogar"
        elif (cronometrar and partida.venceu(agora)) or sair_squad or partida.saida:
            if not partida.limite_aviso:
                motivo = "Squad sinalizado" if sair_squad else "Tempo atingido"
                log(f"{motivo}. Procurando a saída da partida.")
                partida.limite_aviso = True
            opcoes_saida = ("confirmar_saida",) if "sair" in partida.saida else ("sair", "aba_saida")
            for nome in opcoes_saida:
                if nome in estaveis and nome not in partida.saida:
                    acao = nome
                    break
            if acao is None and not partida.saida:
                acao = "esc"
        elif ("inventario" in estaveis and partida.inicio is not None
              and getattr(args, "fechar_inventario", True)):
            acao = "fechar_inventario"
        elif ("onibus" in estaveis and not partida.saltou
              and getattr(args, "saltar_onibus", True)):
            acao = "saltar_onibus"
        elif (args.executar and not args.sem_movimento and "partida" in estaveis
              and "onibus" not in atual and agora >= partida.proximo_movimento
              and agora >= partida.queda_ate and "espectando" not in atual
              and agora >= proxima_acao and "inventario" not in atual):
            windows.pressionar(janela, *partida.movimento(agora))

        if not args.executar:
            for nome in sorted(novos - {"partida", "resgatar", "passo_regiao"}):
                if not nome.startswith("item:"):
                    log(f"Detectado: {nome} em {atual[nome]}.")
            continue
        if (acao is None or agora < proxima_acao or (parar and parar.is_set())
                or (acao == "jogar" and not estado_fila.pode_clicar(agora))):
            continue
        if acao in ("esc", "fechar_inventario"):
            ok = windows.pressionar(janela, (ESC,))
        elif acao == "saltar_onibus":
            ok = windows.pressionar(janela, (0x20,))
        elif acao == "passo_regiao" and regioes[configurando][passo_regiao][1]:
            ok = True
        else:
            x, y = atual[acao]
            try:
                ok = windows.clicar(janela, (area[0] + x, area[1] + y))
            except OSError as erro:
                log(f"Clique em {acao} não enviado. {erro}")
                proxima_acao = time.monotonic() + 3
                continue
        if not ok:
            continue
        proxima_acao = time.monotonic() + atraso_clique.get(acao, 1.25)
        log(f"Ação: {acao}.")
        if acao == "jogar":
            estado_fila.registrar_clique(time.monotonic())
            log(f"Clique em Jogar enviado ({estado_fila.tentativas}). Aguardando a tela confirmar a fila.")
        anterior = {}
        if acao in ("esc", "aba_saida", "sair", "confirmar_saida"):
            partida.saida.add(acao)
        if acao == "saltar_onibus":
            partida.saltou = True
            partida.queda_ate = agora + 15
        if acao == "lobby":
            fase_fila = "saindo"
        if acao == "passo_regiao":
            passo_regiao += 1
            if passo_regiao == len(regioes[configurando]):
                regiao_aplicada, configurando = configurando, None
                log("Sequência de região concluída. Aguardando o lobby.")
        if acao.startswith("modo_"):
            proximo = f"modo_{int(acao[-2:]) + 1:02}"
            modo_passo = proximo if proximo in botoes else None


def main():
    empacotado = getattr(sys, "frozen", False)
    parser = argparse.ArgumentParser(description=__doc__)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--executar", action="store_true")
    modo.add_argument("--previa", action="store_true")
    parser.add_argument("--botoes", type=Path, default=PASTA / "botoes")
    parser.add_argument("--limiar", type=float, default=0.92)
    parser.add_argument("--minutos", type=float, default=8.0)
    parser.add_argument("--pausar-apos", type=float, default=0, metavar="MINUTOS")
    parser.add_argument("--sem-movimento", action="store_true")
    parser.add_argument("--skins-padrao", type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    args.executar = args.executar or (empacotado and not args.previa)
    if not 4.5 <= args.minutos <= 8.5 or not 0 < args.limiar <= 1:
        parser.error("Use --minutos entre 4.5 e 8.5 e --limiar entre 0 (exclusivo) e 1.")
    if not 0 <= args.pausar_apos < float("inf"):
        parser.error("--pausar-apos deve ser zero ou um tempo positivo em minutos.")
    try:
        botoes, recompensas, regioes = carregar(args.botoes)
        squad = carregar_squad(args.botoes)
        url = url_webhook()
        if url and not recompensas and "tesouro" not in botoes:
            raise ValueError("Configure os recortes de recompensas ou tesouro.png para o Discord.")
        if "partida" not in botoes:
            print("Recortes partida.png e sair.png ausentes. Temporizador e movimento desativados.")
        with ThreadPoolExecutor(max_workers=1) as executor:
            monitorar(Windows(), botoes, recompensas, regioes, squad, args, url, executor)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, cv2.error) as erro:
        print(f"Erro: {erro}", file=sys.stderr, flush=True)
        if empacotado:
            try:
                input("Pressione Enter para fechar.")
            except EOFError:
                pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

