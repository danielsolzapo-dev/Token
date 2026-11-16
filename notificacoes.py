"""Notificações locais pela área de trabalho do Windows."""

import ctypes
from ctypes import wintypes


NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
NIIF_INFO = 0x00000001


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    )


class _Timeout(ctypes.Union):
    _fields_ = (("uTimeout", wintypes.UINT), ("uVersion", wintypes.UINT))


class _NotifyIconData(ctypes.Structure):
    _anonymous_ = ("timeout",)
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("timeout", _Timeout),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    )


class NotificadorWindows:
    def __init__(self, hwnd, shell32=None, user32=None):
        if shell32 is None or user32 is None:
            if not hasattr(ctypes, "WinDLL"):
                raise OSError("Notificações nativas só estão disponíveis no Windows.")
            shell32 = shell32 or ctypes.WinDLL("shell32", use_last_error=True)
            user32 = user32 or ctypes.WinDLL("user32", use_last_error=True)
            shell32.Shell_NotifyIconW.argtypes = (
                wintypes.DWORD, ctypes.POINTER(_NotifyIconData),
            )
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL
            user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR)
            user32.LoadIconW.restype = wintypes.HICON

        self.shell32 = shell32
        self.data = _NotifyIconData()
        self.data.cbSize = ctypes.sizeof(self.data)
        self.data.hWnd = hwnd
        self.data.uID = 1
        self.data.uFlags = NIF_ICON | NIF_TIP
        self.data.szTip = "Auto Farm"
        self.data.hIcon = user32.LoadIconW(
            None, ctypes.cast(ctypes.c_void_p(32512), wintypes.LPCWSTR),
        )
        self.adicionado = False
        self._chamar(NIM_ADD, "adicionar o ícone de notificação")
        self.adicionado = True

    def _chamar(self, operacao, descricao):
        if self.shell32.Shell_NotifyIconW(operacao, ctypes.byref(self.data)):
            return
        codigo = ctypes.get_last_error()
        detalhe = ctypes.FormatError(codigo).strip() if codigo else "operação recusada pelo Windows"
        raise OSError(codigo, f"Não foi possível {descricao}: {detalhe}")

    def notificar(self, titulo, mensagem):
        if not self.adicionado:
            raise RuntimeError("O ícone de notificações não foi registrado.")
        self.data.uFlags = NIF_INFO
        self.data.szInfoTitle = str(titulo)[:63]
        self.data.szInfo = str(mensagem)[:255]
        self.data.dwInfoFlags = NIIF_INFO
        self._chamar(NIM_MODIFY, "mostrar a notificação")

    def fechar(self):
        if self.adicionado:
            self.data.uFlags = 0
            self._chamar(NIM_DELETE, "remover o ícone de notificação")
            self.adicionado = False
