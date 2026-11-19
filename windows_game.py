"""Captura do cliente do Fortnite e envio de entrada no Windows."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from queue import Empty, SimpleQueue
import sys
from threading import Event, Lock, Thread
import time

import cv2
import numpy as np
from PIL import ImageGrab


F6 = 0x75
F7 = 0x76
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


def reduzir_prioridade_thread():
    """Usa prioridade de fundo para a thread que chamou esta função."""
    if sys.platform != "win32":
        return
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentThread.restype = wintypes.HANDLE
    kernel.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    kernel.SetThreadPriority(kernel.GetCurrentThread(), -1)


@dataclass(frozen=True)
class Janela:
    hwnd: int
    area: tuple[int, int, int, int]
    pid_fundo: int = 0
    cursor_fundo: bool = False


class Mouse(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("dados", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("tempo", wintypes.DWORD), ("extra", ctypes.c_size_t),
    ]


class Tecla(ctypes.Structure):
    _fields_ = [
        ("vk", wintypes.WORD), ("scan", wintypes.WORD), ("flags", wintypes.DWORD),
        ("tempo", wintypes.DWORD), ("extra", ctypes.c_size_t),
    ]


class Dados(ctypes.Union):
    _fields_ = [("mouse", Mouse), ("tecla", Tecla)]


class Entrada(ctypes.Structure):
    _fields_ = [("tipo", wintypes.DWORD), ("dados", Dados)]


class Cursor(ctypes.Structure):
    _fields_ = [("tamanho", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("cursor", wintypes.HANDLE), ("ponto", wintypes.POINT)]


class UltimaEntrada(ctypes.Structure):
    _fields_ = [("tamanho", wintypes.UINT), ("instante", wintypes.DWORD)]


class CapturaJanela:
    def __init__(self, janela):
        from windows_capture import WindowsCapture

        self.janela = janela
        self.quadro = None
        self._proximo_quadro = 0.0
        captura = WindowsCapture(window_hwnd=janela.hwnd, cursor_capture=False)

        @captura.event
        def on_frame_arrived(frame, _):
            agora = time.monotonic()
            if agora >= self._proximo_quadro:
                self.quadro = (agora, frame.frame_buffer.copy())
                self._proximo_quadro = agora + 0.08

        @captura.event
        def on_closed():
            self.quadro = None

        self.controle = captura.start_free_threaded()

    def ler(self):
        ultimo = self.quadro
        if ultimo and time.monotonic() - ultimo[0] <= 1.5:
            return ultimo[1]
        return None

    def fechar(self):
        if not self.controle.is_finished():
            self.controle.stop()


class Windows:
    def __init__(self, *, relogio=None, esperar=None):
        self.relogio = relogio or time.monotonic
        self.esperar_evento = esperar or (lambda parar, duracao: parar.wait(duracao))
        self._entrada = Lock()
        self._eventos_f6 = SimpleQueue()
        self._encerrar_atalho = Event()
        self._f6_registrado = self._f6_anterior = False
        self._fortnite_localizado = (0, 0)
        self._proxima_busca_fortnite = 0
        self._ponto_fundo = None
        self._motivo_cursor_fundo = None
        self._trava_captura = Lock()
        self._captura_fundo = None
        self._repetir_captura_em = 0.0
        self.erro_captura = None
        self._callback_enumerar = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self.dwm.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]
        api = self.user
        api.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        api.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        api.GetForegroundWindow.restype = wintypes.HWND
        api.EnumWindows.argtypes = [self._callback_enumerar, wintypes.LPARAM]
        api.IsWindowVisible.argtypes = [wintypes.HWND]
        api.IsIconic.argtypes = [wintypes.HWND]
        api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        api.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        api.MapVirtualKeyW.restype = wintypes.UINT
        api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        api.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ]
        api.SendMessageTimeoutW.restype = wintypes.LPARAM
        api.GetLastInputInfo.argtypes = [ctypes.POINTER(UltimaEntrada)]
        api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        api.GetAsyncKeyState.restype = ctypes.c_short
        api.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        api.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        api.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                     wintypes.UINT, wintypes.UINT, wintypes.UINT]
        api.GetCursorInfo.argtypes = [ctypes.POINTER(Cursor)]
        api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        api.GetClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
        api.WindowFromPoint.argtypes = [wintypes.POINT]
        api.WindowFromPoint.restype = wintypes.HWND
        api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        api.GetAncestor.restype = wintypes.HWND
        api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Entrada), ctypes.c_int]
        api.SendInput.restype = wintypes.UINT
        api.mouse_event.argtypes = [wintypes.DWORD, wintypes.LONG, wintypes.LONG,
                                    wintypes.DWORD, ctypes.c_size_t]
        api.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.GetTickCount.restype = wintypes.DWORD
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]

    def fortnite_em_foco(self):
        hwnd = self.user.GetForegroundWindow()
        if hwnd and self._pid_fortnite(hwnd):
            area = self._area(hwnd)
            if area:
                return Janela(hwnd, area)
        return None

    def _pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _pid_fortnite(self, hwnd):
        pid = self._pid(hwnd)
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return 0
        nome = ctypes.create_unicode_buffer(1024)
        comprimento = wintypes.DWORD(len(nome))
        try:
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, nome, ctypes.byref(comprimento)):
                return 0
            if nome.value.rsplit("\\", 1)[-1].casefold() != "fortniteclient-win64-shipping.exe":
                return 0
        finally:
            self.kernel.CloseHandle(handle)
        return pid

    def localizar_fortnite(self):
        primeiro_plano = self.fortnite_em_foco()
        if primeiro_plano:
            self._fortnite_localizado = (primeiro_plano.hwnd, self._pid(primeiro_plano.hwnd))
            self.fechar_captura_fundo()
            return primeiro_plano
        hwnd, pid = self._fortnite_localizado
        if not (pid and self._pid(hwnd) == pid and self.user.IsWindowVisible(hwnd)):
            agora = self.relogio()
            if agora < self._proxima_busca_fortnite:
                return None
            self._proxima_busca_fortnite = agora + 1
            hwnd, pid = self._buscar_janela_fortnite()
            self._fortnite_localizado = (hwnd, pid)
        if pid and not self.user.IsIconic(hwnd):
            area = self._area(hwnd)
            if area:
                return Janela(hwnd, area, pid)
        self.fechar_captura_fundo()
        return None

    def _buscar_janela_fortnite(self):
        encontrado = (0, 0)
        titulo = ctypes.create_unicode_buffer(64)

        @self._callback_enumerar
        def examinar(hwnd, _):
            nonlocal encontrado
            if self.user.IsWindowVisible(hwnd) and self.user.GetWindowTextW(hwnd, titulo, len(titulo)):
                if titulo.value.strip().casefold() == "fortnite" and (pid := self._pid_fortnite(hwnd)):
                    encontrado = hwnd, pid
                    return False
            return True

        self.user.EnumWindows(examinar, 0)
        return encontrado

    def _area(self, hwnd):
        rect, origem = wintypes.RECT(), wintypes.POINT()
        if (not self.user.GetClientRect(hwnd, ctypes.byref(rect))
                or not self.user.ClientToScreen(hwnd, ctypes.byref(origem))
                or rect.right < 64 or rect.bottom < 64):
            return None
        return origem.x, origem.y, origem.x + rect.right, origem.y + rect.bottom

    def iniciar_atalho(self):
        Thread(target=self._receber_atalho, daemon=True).start()

    def fechar_atalho(self):
        self._encerrar_atalho.set()

    def _receber_atalho(self):
        if not self.user.RegisterHotKey(None, 1, MOD_NOREPEAT, F6):
            return
        self._f6_registrado = True
        mensagem = wintypes.MSG()
        try:
            while not self._encerrar_atalho.is_set():
                while self.user.PeekMessageW(ctypes.byref(mensagem), None, WM_HOTKEY, WM_HOTKEY, 1):
                    self._eventos_f6.put(True)
                self._encerrar_atalho.wait(0.015)
        finally:
            self.user.UnregisterHotKey(None, 1)
            self._f6_registrado = False

    def f6_pressionado(self):
        if self._f6_registrado:
            try:
                self._eventos_f6.get_nowait()
            except Empty:
                return False
            return True
        pressionado = bool(self.user.GetAsyncKeyState(F6) & 0x8000)
        novo = pressionado and not self._f6_anterior
        self._f6_anterior = pressionado
        return novo

    def f7(self):
        return bool(self.user.GetAsyncKeyState(F7) & 0x8000)

    def cursor_visivel(self):
        cursor = Cursor(tamanho=ctypes.sizeof(Cursor))
        return bool(self.user.GetCursorInfo(ctypes.byref(cursor)) and cursor.flags & 1)

    def capturar(self, janela, parar=None):
        if not janela.pid_fundo:
            imagem = ImageGrab.grab(bbox=janela.area, all_screens=True)
            return cv2.cvtColor(np.asarray(imagem.convert("RGB")), cv2.COLOR_RGB2BGR)
        with self._trava_captura:
            if (parar is not None and parar.is_set()) or not self._modo_disponivel(janela):
                return None
            captura = self._captura_fundo
            # Mover a janela preserva a sessão. Trocar de HWND exige outra captura.
            if captura and (captura.janela.hwnd != janela.hwnd or captura.janela.pid_fundo != janela.pid_fundo
                            or captura.controle.is_finished()):
                self._fechar_captura()
                captura = None
            if captura is None:
                agora = self.relogio()
                if agora < self._repetir_captura_em:
                    return None
                self._repetir_captura_em = agora + 2
                try:
                    captura = self._captura_fundo = CapturaJanela(janela)
                except Exception as erro:  # A extensão nativa também usa Exception diretamente.
                    self.erro_captura = str(erro)
                    return None
                self.erro_captura = None
            imagem = captura.ler()
        if imagem is None:
            return None
        altura, largura = imagem.shape[:2]
        esquerda, topo, direita, base = janela.area
        if (largura, altura) == (direita - esquerda, base - topo):
            cliente = imagem
        else:
            rect = wintypes.RECT()
            if self.dwm.DwmGetWindowAttribute(janela.hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
                return None
            x1, y1, x2, y2 = esquerda - rect.left, topo - rect.top, direita - rect.left, base - rect.top
            if not (0 <= x1 < x2 <= largura and 0 <= y1 < y2 <= altura):
                return None
            cliente = imagem[y1:y2, x1:x2]
        if np.ptp(cliente[::12, ::12, :3], axis=(0, 1)).max() < 8:
            return None
        return cv2.cvtColor(cliente, cv2.COLOR_BGRA2BGR)

    def fechar_captura_fundo(self):
        with self._trava_captura:
            self._fechar_captura()

    def _fechar_captura(self):
        captura, self._captura_fundo = self._captura_fundo, None
        if captura:
            captura.fechar()

    def disponivel(self, janela, parar):
        return (not parar.is_set() and self._area(janela.hwnd) == janela.area
                and not parar.is_set() and self._modo_disponivel(janela))

    def _modo_disponivel(self, janela):
        em_foco = self.user.GetForegroundWindow() == janela.hwnd
        if janela.pid_fundo:
            return (not em_foco and self._pid(janela.hwnd) == janela.pid_fundo
                    and self.user.IsWindowVisible(janela.hwnd) and not self.user.IsIconic(janela.hwnd))
        return em_foco

    def motivo_interrupcao(self, janela, parar):
        if parar.is_set():
            return "painel_pausado"
        if janela.pid_fundo and not self._modo_disponivel(janela):
            return "janela_ou_foco_mudou"
        if not janela.pid_fundo and not self._modo_disponivel(janela):
            return "fortnite_perdeu_foco"
        if self._area(janela.hwnd) != janela.area:
            return "area_da_janela_mudou"
        if janela.cursor_fundo and self._motivo_cursor_fundo:
            return self._motivo_cursor_fundo
        return "mensagem_de_janela_recusada" if janela.pid_fundo else "entrada_interrompida"

    def _enviar(self, evento):
        ctypes.set_last_error(0)
        if self.user.SendInput(1, ctypes.byref(evento), ctypes.sizeof(Entrada)) != 1:
            erro = ctypes.get_last_error()
            detalhe = f" (código {erro})" if erro else ""
            excecao = OSError(f"O Windows recusou o comando de entrada{detalhe}.")
            excecao.winerror = erro or None
            raise excecao

    def _tecla(self, scan, soltando=False):
        estendida = 1 if scan > 0xFF else 0
        self._enviar(Entrada(1, Dados(tecla=Tecla(scan=scan & 0xFF, flags=8 | estendida | (2 if soltando else 0)))))

    def _mouse(self, flags, dx=0, dy=0):
        self._enviar(Entrada(0, Dados(mouse=Mouse(dx=dx, dy=dy, flags=flags))))

    def _postar(self, janela, mensagem, wparam, lparam):
        # Confira o processo inclusive ao soltar comandos depois de uma pausa.
        return (self._pid(janela.hwnd) == janela.pid_fundo
                and bool(self.user.PostMessageW(janela.hwnd, mensagem, wparam, lparam)))

    def _tecla_fundo(self, janela, scan, soltando=False):
        tecla = self.user.MapVirtualKeyW(scan, 3)
        dados = 1 | ((scan & 0xFF) << 16) | (int(scan > 0xFF) << 24)
        if soltando:
            dados |= 0xC0000000
        return bool(tecla and self._postar(janela, 0x101 if soltando else 0x100, tecla, dados))

    def _ponto_cliente(self, janela):
        esquerda, topo, direita, base = janela.area
        if self._ponto_fundo and self._ponto_fundo[0] == janela:
            return self._ponto_fundo[1]
        return (direita - esquerda) // 2, (base - topo) // 2

    @staticmethod
    def _coordenadas_mouse(x, y):
        return x | (y << 16)

    def _apontar_fundo(self, janela, x, y):
        if not self._postar(janela, 0x200, 0, self._coordenadas_mouse(x, y)):
            return False
        self._ponto_fundo = janela, (x, y)
        return True

    def _enviar_mouse_para_janela(self, janela, mensagem, botao, coordenadas):
        resultado = ctypes.c_size_t()
        return (self._pid(janela.hwnd) == janela.pid_fundo
                and bool(self.user.SendMessageTimeoutW(janela.hwnd, mensagem, botao, coordenadas,
                                                       0x0002, 80, ctypes.byref(resultado))))

    def _cursor_parado(self):
        ultima = UltimaEntrada(tamanho=ctypes.sizeof(UltimaEntrada))
        return bool(self.user.GetLastInputInfo(ctypes.byref(ultima))
                    and ((self.kernel.GetTickCount() - ultima.instante) & 0xFFFFFFFF) >= 700)

    def _posicao_cursor(self):
        ponto = wintypes.POINT()
        if self.user.GetCursorPos(ctypes.byref(ponto)):
            return ponto.x, ponto.y
        return None

    def _ativacao_clique_fundo(self, janela, ativo):
        if not ativo and self.user.GetForegroundWindow() == janela.hwnd:
            return True
        mensagens = ((0x1C, 1), (0x06, 1), (0x07, 0)) if ativo else (
            (0x08, 0), (0x06, 0), (0x1C, 0))
        sucesso = True
        for mensagem, valor in mensagens:
            if not self._enviar_mouse_para_janela(janela, mensagem, valor, 0):
                sucesso = False
        return sucesso

    def _clicar_fundo_com_cursor(self, janela, parar, x, y, tentativa):
        if not self._cursor_parado():
            self._motivo_cursor_fundo = "mouse_ou_teclado_em_uso"
            return False
        anterior = self._posicao_cursor()
        limites = wintypes.RECT()
        if not (self.user.GetClipCursor(ctypes.byref(limites))
                and limites.left <= x < limites.right and limites.top <= y < limites.bottom):
            self._motivo_cursor_fundo = "cursor_fora_dos_limites_do_desktop"
            return False
        if anterior is None or not self.disponivel(janela, parar) or not self.user.SetCursorPos(x, y):
            return False
        destino = x, y
        dados = self._coordenadas_mouse(x - janela.area[0], y - janela.area[1])
        # Após uma tentativa sem confirmação, dê mais de um quadro ao menu.
        passo = min(tentativa, 2)
        tempo_ponteiro = 0.04 + 0.065 * passo
        tempo_pressionado = 0.035 + 0.04 * passo
        try:
            if tentativa > 0 and not self._ativacao_clique_fundo(janela, True):
                self._motivo_cursor_fundo = "ativacao_da_janela_recusada"
                return False
            if not self.disponivel(janela, parar):
                return False
            if self._posicao_cursor() != destino:
                return False
            if not self._enviar_mouse_para_janela(janela, 0x200, 0, dados):
                return False
            if not self._esperar(janela, parar, tempo_ponteiro) or self._posicao_cursor() != destino:
                return False
            try:
                enviado = self._enviar_mouse_para_janela(janela, 0x201, 1, dados)
                mantido = enviado and self._esperar(janela, parar, tempo_pressionado)
            finally:
                liberado = self._enviar_mouse_para_janela(janela, 0x202, 0, dados)
            return bool(mantido and liberado)
        finally:
            if tentativa > 0:
                self._ativacao_clique_fundo(janela, False)
            if self._posicao_cursor() == destino:
                self.user.SetCursorPos(*anterior)

    def _deslocar_mouse(self, janela, dx, dy):
        if not janela.pid_fundo:
            self._mouse(1, dx, dy)
            return True
        x, y = self._ponto_cliente(janela)
        esquerda, topo, direita, base = janela.area
        return self._apontar_fundo(janela, min(max(0, x + dx), direita - esquerda - 1),
                                  min(max(0, y + dy), base - topo - 1))

    def _esperar(self, janela, parar, duracao):
        fim = self.relogio() + duracao
        while self.disponivel(janela, parar):
            restante = fim - self.relogio()
            if restante <= 0:
                return True
            self.esperar_evento(parar, min(0.04, restante))
        return False

    def _pressionar(self, janela, parar, teclas, duracao, dx=0, dy=0):
        enviadas = []
        try:
            for scan in teclas:
                if not self.disponivel(janela, parar):
                    return False
                if janela.pid_fundo:
                    if not self._tecla_fundo(janela, scan):
                        return False
                else:
                    self._tecla(scan)
                enviadas.append(scan)
            if not (dx or dy):
                return self._esperar(janela, parar, duracao)
            segmentos = max(1, round(duracao / 0.04))
            x_anterior = y_anterior = 0
            for i in range(1, segmentos + 1):
                if not self.disponivel(janela, parar):
                    return False
                x, y = round(i * dx / segmentos), round(i * dy / segmentos)
                if not self._deslocar_mouse(janela, x - x_anterior, y - y_anterior):
                    return False
                x_anterior, y_anterior = x, y
                if not self._esperar(janela, parar, duracao / segmentos):
                    return False
            return True
        finally:
            falha = None
            for scan in reversed(enviadas):
                if janela.pid_fundo:
                    if not self._tecla_fundo(janela, scan, soltando=True):
                        falha = OSError("O Windows recusou a liberação de uma tecla em segundo plano.")
                    continue
                try:
                    self._tecla(scan, soltando=True)
                except OSError as erro:
                    falha = falha or erro
                    try:
                        self.user.keybd_event(0, scan & 0xFF, 8 | 2 | (1 if scan > 0xFF else 0), 0)
                    except OSError as erro_fallback:
                        falha = falha or erro_fallback
            if falha is not None:
                raise falha

    def _clique(self, janela, parar, duracao):
        if not self.disponivel(janela, parar):
            return False
        if janela.pid_fundo:
            dados = self._coordenadas_mouse(*self._ponto_cliente(janela))
            if not self._postar(janela, 0x201, 1, dados):
                return False
            try:
                return self._esperar(janela, parar, duracao)
            finally:
                if not self._postar(janela, 0x202, 0, dados):
                    raise OSError("O Windows recusou a liberação do clique em segundo plano.")
        self._mouse(2)
        try:
            self._esperar(janela, parar, duracao)
        finally:
            try:
                self._mouse(4)
            except OSError:
                self.user.mouse_event(4, 0, 0, 0, 0)
                raise
        return True

    def executar(self, janela, acao, parar):
        with self._entrada:
            self._motivo_cursor_fundo = None
            if parar.is_set():
                return False
            return self._executar(janela, acao, parar)

    def entrada_em_andamento(self):
        return self._entrada.locked()

    def _executar(self, janela, acao, parar):
        if not self.disponivel(janela, parar):
            return False
        if acao.tipo == "esc":
            return self._pressionar(janela, parar, (1,), 0.06)
        if acao.tipo in ("clicar", "apontar"):
            esquerda, topo, direita, base = janela.area
            x, y = acao.alvo.centro
            x, y = esquerda + round(x), topo + round(y)
            if not (esquerda <= x < direita and topo <= y < base):
                return False
            if janela.pid_fundo:
                if janela.cursor_fundo and acao.tipo == "clicar":
                    return self._clicar_fundo_com_cursor(janela, parar, x, y, acao.tentativa)
                if not self._apontar_fundo(janela, x - esquerda, y - topo):
                    return False
                if acao.tipo == "apontar":
                    return True
                return (self._esperar(janela, parar, 0.10)
                        and self._clique(janela, parar, 0.15 if acao.tentativa % 2 else 0.085))
            if self.fortnite_em_foco() != janela or not self.disponivel(janela, parar):
                return False
            if not self.user.SetCursorPos(x, y):
                return False
            if not self._esperar(janela, parar, 0.10):
                return False
            ponto = wintypes.POINT()
            if (not self.user.GetCursorPos(ctypes.byref(ponto))
                    or max(abs(ponto.x - x), abs(ponto.y - y)) > 4
                    or self.user.GetAncestor(self.user.WindowFromPoint(ponto), 2) != janela.hwnd
                    or self.fortnite_em_foco() != janela):
                return False
            if acao.tipo == "apontar":
                return self.disponivel(janela, parar)
            return self._clique(janela, parar, 0.15 if acao.tentativa % 2 else 0.085)
        if acao.passos:
            for tipo, *dados in acao.passos:
                if tipo == "pausa":
                    ok = self._esperar(janela, parar, *dados)
                elif tipo == "clique":
                    ok = (janela.pid_fundo or not self.cursor_visivel()) and self._clique(janela, parar, *dados)
                elif tipo == "mouse":
                    dx, dy, duracao = dados
                    ok = self._pressionar(janela, parar, (), duracao, dx, dy)
                else:
                    ok = self._pressionar(janela, parar, *dados)
                if not ok:
                    return False
        return True
