"""Tema do painel desktop e elementos gráficos do Tk."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


BG = "#0B1018"
PAINEL = "#111925"
BORDA = "#273344"
TEXTO = "#E8EEF6"
MUTED = "#A0AEC0"
ACENTO = "#B8F36D"
AMBAR = "#F2C56C"
FUNDO_METRICA = "#0D1520"

CAMINHOS = {
    "bot": (((4, 8), (20, 8), (20, 19), (4, 19), (4, 8)), ((12, 8), (12, 4)),
            ((1, 11), (4, 11)), ((1, 16), (4, 16)), ((20, 11), (23, 11)), ((20, 16), (23, 16))),
    "pausa": (((9, 8), (9, 16)), ((15, 8), (15, 16))),
    "play": (((7, 4), (19, 12), (7, 20), (7, 4)),),
    "alvo": (((12, 2), (12, 7)), ((12, 17), (12, 22)), ((2, 12), (7, 12)), ((17, 12), (22, 12))),
    "cor": (((4, 20), (5, 15), (16, 4), (19, 3), (21, 5), (20, 8), (9, 19), (4, 20)),
            ((13, 7), (17, 11))),
    "movimento": (((11, 7), (9, 13), (13, 15), (14, 21)), ((9, 13), (7, 18), (4, 20)),
                  ((11, 8), (15, 11), (19, 11)), ((11, 8), (7, 10), (5, 14))),
    "salto": (((5, 10), (12, 3), (19, 10)), ((12, 3), (12, 21))),
    "saida": (((11, 4), (4, 4), (4, 20), (11, 20)), ((9, 12), (20, 12)),
              ((16, 8), (20, 12), (16, 16))),
    "imagem": (((3, 4), (21, 4), (21, 20), (3, 20), (3, 4)),
               ((3, 16), (8, 11), (12, 15), (16, 10), (21, 15))),
    "diagnostico": (((8, 5), (4, 5), (4, 21), (20, 21), (20, 5), (16, 5)),
                    ((8, 3), (16, 3), (16, 7), (8, 7), (8, 3)),
                    ((8, 12), (16, 12)), ((8, 16), (14, 16))),
    "atualizar": (((3, 10), (5, 6), (9, 3), (15, 3), (20, 7)), ((20, 3), (20, 7), (16, 7)),
                  ((21, 14), (19, 18), (15, 21), (9, 21), (4, 17)), ((4, 21), (4, 17), (8, 17))),
    "presente": (((3, 9), (21, 9), (21, 13), (3, 13), (3, 9)), ((5, 13), (5, 21), (19, 21), (19, 13)),
                 ((12, 21), (12, 9), (6, 8), (6, 5), (8, 3), (12, 8), (16, 3), (18, 5), (18, 8), (12, 9))),
    "link": (((9, 14), (15, 8)), ((10, 17), (7, 20), (3, 20), (2, 17), (3, 14), (6, 11)),
              ((14, 7), (17, 4), (21, 4), (22, 7), (21, 10), (18, 13))),
    "relogio": (((12, 6), (12, 12), (16, 14)),),
    "automacao": (((9, 3), (15, 3), (15, 6), (18, 8), (20, 7), (22, 11), (19, 13), (19, 16),
                  (20, 18), (16, 21), (14, 19), (10, 19), (8, 21), (4, 18), (5, 16), (5, 13),
                  (2, 11), (4, 7), (6, 8), (9, 6), (9, 3)),),
}
CIRCULOS = {
    "bot": ((8, 12, 9, 13), (15, 12, 16, 13), (11, 2, 13, 4)),
    "pausa": ((2, 2, 22, 22),), "alvo": ((5, 5, 19, 19),), "movimento": ((10, 2, 14, 6),),
    "imagem": ((6, 7, 8, 9),), "relogio": ((2, 2, 22, 22),), "automacao": ((9, 9, 15, 15),),
}


def carregar_inter():
    if sys.platform != "win32":
        return
    gdi = ctypes.WinDLL("gdi32")
    adicionar = gdi.AddFontResourceExW
    adicionar.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    for fonte in Path(__file__).with_name("fontes").glob("Inter-*.otf"):
        adicionar(str(fonte), 0x10, None)  # FR_PRIVATE


def escurecer_titulo(janela):
    if sys.platform == "win32":
        try:
            hwnd = wintypes.HWND(int(janela.frame(), 0))
            valor = ctypes.c_int(1)
            dwm = ctypes.WinDLL("dwmapi")
            if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(valor), ctypes.sizeof(valor)):
                dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(valor), ctypes.sizeof(valor))
        except (OSError, ValueError, AttributeError):
            pass


class TemaPainel:
    def __init__(self, janela, familia):
        self.janela = janela
        self.imagens = {}
        estilo = ttk.Style(janela)
        estilo.theme_use("clam")
        normal = familia, 10
        forte = familia, 10, "bold"
        estilo.configure(".", font=normal, foreground=TEXTO, background=BG)
        estilo.configure("Info.TLabel", foreground=MUTED, font=(familia, 9))
        estilo.configure("CardInfo.TLabel", foreground=MUTED, background=PAINEL, font=(familia, 9))
        estilo.configure("Card.TLabel", background=PAINEL)
        estilo.configure("Secao.TLabel", background=PAINEL, font=(familia, 11, "bold"))
        estilo.configure("Titulo.TLabel", font=(familia, 25, "bold"))
        estilo.configure("Versao.TLabel", background=FUNDO_METRICA, padding=(7, 2), font=(familia, 9))
        estilo.configure("MetricaTitulo.TLabel", background=FUNDO_METRICA, foreground=MUTED, font=(familia, 9))
        estilo.configure("MetricaValor.TLabel", background=FUNDO_METRICA, foreground=AMBAR, font=(familia, 19, "bold"))
        estilo.configure("MetricaVazia.TLabel", background=FUNDO_METRICA, foreground=TEXTO, font=(familia, 19, "bold"))
        estilo.configure("Status.TLabel", foreground=ACENTO, background=PAINEL, font=(familia, 11, "bold"))
        estilo.configure("Pausado.TLabel", foreground=AMBAR, background=PAINEL, font=(familia, 11, "bold"))
        estilo.configure("CardInterior.TFrame", background=PAINEL)
        estilo.configure("Separador.TFrame", background=BORDA)
        estilo.configure("TCheckbutton", indicatorcolor=PAINEL)
        estilo.map("TCheckbutton", indicatorcolor=[("selected", ACENTO)])
        for campo in ("TEntry", "TSpinbox", "TCombobox"):
            estilo.configure(campo, fieldbackground=FUNDO_METRICA, insertcolor=TEXTO, bordercolor=BORDA,
                             lightcolor=BORDA, darkcolor=BORDA, background=PAINEL, arrowcolor=TEXTO, padding=5)
        estilo.map("TCombobox", fieldbackground=[("readonly", FUNDO_METRICA)])
        for nome, cor in (("Card", PAINEL), ("Metrica", FUNDO_METRICA)):
            elemento = f"AutoFarm.{nome}"
            estilo.element_create(elemento, "image", self._fundo(cor, BORDA, 10), border=11, sticky="nswe")
            estilo.layout(f"{nome}.TFrame", [(elemento, {"sticky": "nswe"})])
        self._botao(estilo, "TButton", PAINEL, BORDA, TEXTO, "#1A2636", normal)
        self._botao(estilo, "Start.TButton", ACENTO, ACENTO, BG, "#CCF895", forte)
        self._switch(estilo)

    def _fundo(self, cor, borda, raio):
        chave = cor, borda, raio
        if chave not in self.imagens:
            lado = raio * 2 + 5
            imagem = Image.new("RGBA", (lado * 4, lado * 4))
            ImageDraw.Draw(imagem).rounded_rectangle((0, 0, lado * 4 - 1, lado * 4 - 1),
                                                      radius=raio * 4, fill=cor, outline=borda, width=4)
            self.imagens[chave] = self._foto(imagem, (lado, lado))
        return self.imagens[chave]

    def _foto(self, imagem, tamanho):
        return ImageTk.PhotoImage(imagem.resize(tamanho, Image.Resampling.LANCZOS), master=self.janela)

    def _botao(self, estilo, nome, cor, borda, texto, hover, fonte):
        elemento = f"AutoFarm.{nome}.fundo"
        estilo.element_create(elemento, "image", self._fundo(cor, borda, 7),
                              ("disabled", self._fundo(PAINEL, BORDA, 7)),
                              ("focus", self._fundo(cor, MUTED if texto == TEXTO else TEXTO, 7)),
                              ("active", self._fundo(hover, borda, 7)), border=8, sticky="nswe")
        estilo.layout(nome, [(elemento, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [("Button.label", {"sticky": ""})]})
        ]})])
        estilo.configure(nome, foreground=texto, font=fonte, padding=(10, 5))
        estilo.map(nome, foreground=[("disabled", MUTED)])

    def _switch(self, estilo):
        tamanho = (43, 19)
        for ligado, foco in ((False, False), (True, False), (False, True), (True, True)):
            imagem = Image.new("RGBA", (172, 76))
            draw = ImageDraw.Draw(imagem)
            draw.rounded_rectangle((0, 2, 143, 73), radius=36, fill=ACENTO if ligado else BORDA,
                                   outline=TEXTO if foco else None, width=4)
            x = 76 if ligado else 10
            draw.ellipse((x, 10, x + 55, 65), fill=TEXTO if ligado else MUTED)
            self.imagens["switch", ligado, foco] = self._foto(imagem, tamanho)
        estado = self.imagens
        estilo.element_create("AutoFarm.switch", "image", estado["switch", False, False],
                              ("selected", "focus", estado["switch", True, True]),
                              ("focus", estado["switch", False, True]),
                              ("selected", estado["switch", True, False]))
        estilo.layout("Switch.TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("AutoFarm.switch", {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": ""})
        ]})])
        estilo.configure("Switch.TCheckbutton", background=PAINEL, foreground=TEXTO, padding=(0, 1))
        estilo.map("Switch.TCheckbutton", background=[("active", PAINEL)], foreground=[("active", TEXTO)])

    def icone(self, nome, cor=MUTED, tamanho=16):
        chave = nome, cor, tamanho
        if chave not in self.imagens:
            imagem = Image.new("RGBA", (96, 96))
            draw = ImageDraw.Draw(imagem)
            for caminho in CAMINHOS[nome]:
                draw.line([(x * 4, y * 4) for x, y in caminho], fill=cor, width=7, joint="curve")
            for caixa in CIRCULOS.get(nome, ()):
                draw.ellipse(tuple(v * 4 for v in caixa), outline=cor, width=7)
            self.imagens[chave] = self._foto(imagem, (tamanho, tamanho))
        return self.imagens[chave]
