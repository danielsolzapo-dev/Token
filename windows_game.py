"""Captura do cliente do Fortnite e envio de entrada no Windows."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import time

import cv2
import numpy as np
from PIL import ImageGrab


F6 = 0x75


@dataclass(frozen=True)
class Janela:
    hwnd: int
    area: tuple[int, int, int, int]


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


class Windows:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        api = self.user
        api.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        api.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        api.GetForegroundWindow.restype = wintypes.HWND
        api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        api.GetAsyncKeyState.restype = ctypes.c_short
        api.GetCursorInfo.argtypes = [ctypes.POINTER(Cursor)]
        api.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
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
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]

    def fortnite_em_foco(self):
        hwnd = self.user.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return None
        nome = ctypes.create_unicode_buffer(1024)
        comprimento = wintypes.DWORD(len(nome))
        try:
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, nome, ctypes.byref(comprimento)):
                return None
            if nome.value.rsplit("\\", 1)[-1].casefold() != "fortniteclient-win64-shipping.exe":
                return None
        finally:
            self.kernel.CloseHandle(handle)
        area = self._area(hwnd)
        return Janela(hwnd, area) if area else None

    def _area(self, hwnd):
        rect, origem = wintypes.RECT(), wintypes.POINT()
        if (not self.user.GetClientRect(hwnd, ctypes.byref(rect))
                or not self.user.ClientToScreen(hwnd, ctypes.byref(origem))
                or rect.right < 64 or rect.bottom < 64):
            return None
        return origem.x, origem.y, origem.x + rect.right, origem.y + rect.bottom

    def f6(self):
        return bool(self.user.GetAsyncKeyState(F6) & 0x8000)

    def cursor_visivel(self):
        cursor = Cursor(tamanho=ctypes.sizeof(Cursor))
        return bool(self.user.GetCursorInfo(ctypes.byref(cursor)) and cursor.flags & 1)

    @staticmethod
    def capturar(janela):
        imagem = ImageGrab.grab(bbox=janela.area, all_screens=True).convert("RGB")
        return cv2.cvtColor(np.asarray(imagem), cv2.COLOR_RGB2BGR)

    def disponivel(self, janela, parar):
        return (not parar.is_set() and self._area(janela.hwnd) == janela.area
                and not parar.is_set() and self.user.GetForegroundWindow() == janela.hwnd)

    def _enviar(self, evento):
        ctypes.set_last_error(0)
        if self.user.SendInput(1, ctypes.byref(evento), ctypes.sizeof(Entrada)) != 1:
            erro = ctypes.get_last_error()
            detalhe = f" (código {erro})" if erro else ""
            raise OSError(f"O Windows recusou o comando de entrada{detalhe}.")

    def _tecla(self, scan, soltando=False):
        self._enviar(Entrada(1, Dados(tecla=Tecla(scan=scan, flags=8 | (2 if soltando else 0)))))

    def _mouse(self, flags, dx=0, dy=0):
        self._enviar(Entrada(0, Dados(mouse=Mouse(dx=dx, dy=dy, flags=flags))))

    def _esperar(self, janela, parar, duracao):
        fim = time.monotonic() + duracao
        while self.disponivel(janela, parar):
            restante = fim - time.monotonic()
            if restante <= 0:
                return True
            parar.wait(min(0.04, restante))
        return False

    def _pressionar(self, janela, parar, teclas, duracao, dx=0, dy=0):
        enviadas = []
        try:
            for scan in teclas:
                if not self.disponivel(janela, parar):
                    return False
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
                self._mouse(1, x - x_anterior, y - y_anterior)
                x_anterior, y_anterior = x, y
                if not self._esperar(janela, parar, duracao / segmentos):
                    return False
            return True
        finally:
            falha = None
            for scan in reversed(enviadas):
                try:
                    self._tecla(scan, soltando=True)
                except OSError as erro:
                    self.user.keybd_event(0, scan, 8 | 2, 0)
                    falha = erro
            if falha is not None:
                raise falha

    def _clique(self, janela, parar, duracao):
        if not self.disponivel(janela, parar):
            return False
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
        if not self.disponivel(janela, parar):
            return False
        if acao.tipo == "esc":
            return self._pressionar(janela, parar, (1,), 0.06)
        if acao.tipo == "clicar":
            esquerda, topo, direita, base = janela.area
            x, y = acao.alvo.centro
            x, y = esquerda + round(x), topo + round(y)
            if not (esquerda <= x < direita and topo <= y < base):
                return False
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
            return self._clique(janela, parar, 0.15 if acao.tentativa % 2 else 0.085)
        if acao.tipo == "movimento":
            for tipo, *dados in acao.passos:
                if tipo == "pausa":
                    ok = self._esperar(janela, parar, *dados)
                elif tipo == "clique":
                    ok = self._clique(janela, parar, *dados)
                elif tipo == "mouse":
                    dx, dy, duracao = dados
                    ok = self._pressionar(janela, parar, (), duracao, dx, dy)
                else:
                    ok = self._pressionar(janela, parar, *dados)
                if not ok:
                    return False
        return True
