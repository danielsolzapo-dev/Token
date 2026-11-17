"""Tema do painel desktop e elementos gráficos do Tk."""

import ctypes
from dataclasses import dataclass
from ctypes import wintypes
from pathlib import Path
import sys
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


APARENCIAS = {"mono": "Preto e branco", "rosa": "Off-white e rosa bebê"}


@dataclass(frozen=True)
class Paleta:
    fundo: str
    cartao: str
    borda: str
    texto: str
    secundario: str
    lateral: str
    texto_lateral: str
    secundario_lateral: str
    principal: str
    texto_principal: str
    botao: str
    foco: str
    switch: str


PALETAS = {
    "mono": Paleta("#FFFFFF", "#FFFFFF", "#DEDEDE", "#171717", "#585858", "#111111",
                   "#FFFFFF", "#C7C7C7", "#FFFFFF", "#111111", "#FFFFFF", "#696969", "#232323"),
    "rosa": Paleta("#FAF7F2", "#FFFCF8", "#EAD4DD", "#33252B", "#6E5661", "#FAF7F2",
                   "#33252B", "#6E5661", "#F5BCD2", "#33252B", "#FCE3ED", "#8F5A70", "#F5BCD2"),
}


CAMINHOS = {
    "pausa": (((9, 8), (9, 16)), ((15, 8), (15, 16))),
    "play": (((7, 4), (19, 12), (7, 20), (7, 4)),),
    "imagem": (((3, 4), (21, 4), (21, 20), (3, 20), (3, 4)),
               ((3, 16), (8, 11), (12, 15), (16, 10), (21, 15))),
    "diagnostico": (((8, 5), (4, 5), (4, 21), (20, 21), (20, 5), (16, 5)),
                    ((8, 3), (16, 3), (16, 7), (8, 7), (8, 3)),
                    ((8, 12), (16, 12)), ((8, 16), (14, 16))),
    "atualizar": (((3, 10), (5, 6), (9, 3), (15, 3), (20, 7)), ((20, 3), (20, 7), (16, 7)),
                  ((21, 14), (19, 18), (15, 21), (9, 21), (4, 17)), ((4, 21), (4, 17), (8, 17))),
    "presente": (((3, 9), (21, 9), (21, 13), (3, 13), (3, 9)), ((5, 13), (5, 21), (19, 21), (19, 13)),
                 ((12, 21), (12, 9), (6, 8), (6, 5), (8, 3), (12, 8), (16, 3), (18, 5), (18, 8), (12, 9))),
    "relogio": (((12, 6), (12, 12), (16, 14)),),
}
CIRCULOS = {"pausa": ((2, 2, 22, 22),), "imagem": ((6, 7, 8, 9),), "relogio": ((2, 2, 22, 22),)}


def carregar_inter():
    if sys.platform != "win32":
        return
    gdi = ctypes.WinDLL("gdi32")
    adicionar = gdi.AddFontResourceExW
    adicionar.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    for fonte in Path(__file__).with_name("fontes").glob("Inter-*.otf"):
        adicionar(str(fonte), 0x10, None)  # FR_PRIVATE


def ajustar_titulo(janela, escuro):
    if sys.platform == "win32":
        try:
            hwnd = wintypes.HWND(int(janela.frame(), 0))
            valor = ctypes.c_int(int(escuro))
            dwm = ctypes.WinDLL("dwmapi")
            if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(valor), ctypes.sizeof(valor)):
                dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(valor), ctypes.sizeof(valor))
        except (OSError, ValueError, AttributeError):
            pass


class TemaPainel:
    def __init__(self, janela, familia):
        self.janela = janela
        self.familia = familia
        self.imagens = {}
        self.estilo = ttk.Style(janela)
        self.estilo.theme_use("clam")
        for nome, paleta in PALETAS.items():
            self._criar_switch(nome, paleta)

    def aplicar(self, nome):
        self.paleta = cor = PALETAS[nome]
        self.switch = f"{nome}.Switch.TCheckbutton"
        estilo = self.estilo
        fonte = self.familia
        estilo.configure(".", font=(fonte, 10), foreground=cor.texto, background=cor.fundo)
        estilo.configure("TFrame", background=cor.fundo)
        estilo.configure("TLabel", background=cor.fundo, foreground=cor.texto)
        estilo.configure("Info.TLabel", foreground=cor.secundario, font=(fonte, 9))
        estilo.configure("Lateral.TFrame", background=cor.lateral)
        estilo.configure("Lateral.TLabel", background=cor.lateral, foreground=cor.texto_lateral)
        estilo.configure("LateralInfo.TLabel", background=cor.lateral, foreground=cor.secundario_lateral,
                         font=(fonte, 9))
        estilo.configure("Titulo.TLabel", background=cor.lateral, foreground=cor.texto_lateral,
                         font=(fonte, 23, "bold"))
        estilo.configure("Estado.TLabel", background=cor.lateral, foreground=cor.texto_lateral,
                         font=(fonte, 11, "bold"))
        estilo.configure("Card.TFrame", background=cor.cartao, relief="solid", borderwidth=1,
                         bordercolor=cor.borda, lightcolor=cor.borda, darkcolor=cor.borda)
        estilo.configure("CardInterior.TFrame", background=cor.cartao)
        estilo.configure("Card.TLabel", background=cor.cartao, foreground=cor.texto)
        estilo.configure("CardInfo.TLabel", background=cor.cartao, foreground=cor.secundario, font=(fonte, 9))
        estilo.configure("Secao.TLabel", background=cor.cartao, foreground=cor.texto, font=(fonte, 11, "bold"))
        estilo.configure("Metrica.TLabel", background=cor.lateral, foreground=cor.texto_lateral,
                         font=(fonte, 20, "bold"))
        estilo.configure("Tempo.TLabel", background=cor.lateral, foreground=cor.texto_lateral,
                         font=(fonte, 29, "bold"))
        estilo.configure("MetricaCard.TLabel", background=cor.cartao, foreground=cor.texto, font=(fonte, 17, "bold"))
        estilo.configure("Separador.TFrame", height=1, background=cor.borda)
        estilo.configure("TButton", background=cor.botao, foreground=cor.texto, borderwidth=1, relief="solid",
                         bordercolor=cor.borda, lightcolor=cor.borda, darkcolor=cor.borda, padding=(9, 7))
        estilo.map("TButton", background=[("active", cor.borda), ("disabled", cor.fundo)],
                   foreground=[("disabled", cor.secundario)], bordercolor=[("focus", cor.foco)])
        estilo.configure("Start.TButton", background=cor.principal, foreground=cor.texto_principal,
                         bordercolor=cor.foco, padding=(10, 9), font=(fonte, 10, "bold"))
        estilo.map("Start.TButton", background=[("active", cor.borda), ("disabled", cor.borda)],
                   foreground=[("disabled", cor.secundario)], bordercolor=[("focus", cor.foco)])
        estilo.configure("TCheckbutton", background=cor.fundo, foreground=cor.texto, indicatorcolor=cor.cartao)
        estilo.map("TCheckbutton", indicatorcolor=[("selected", cor.switch)],
                   background=[("active", cor.fundo)], foreground=[("active", cor.texto)])
        for campo in ("TEntry", "TSpinbox", "TCombobox"):
            estilo.configure(campo, fieldbackground=cor.cartao, foreground=cor.texto, insertcolor=cor.texto,
                             bordercolor=cor.borda, lightcolor=cor.borda, darkcolor=cor.borda,
                             background=cor.botao, arrowcolor=cor.texto, padding=4)
            estilo.map(campo, fieldbackground=[("readonly", cor.cartao)],
                       bordercolor=[("focus", cor.foco)], selectbackground=[("readonly", cor.cartao)],
                       selectforeground=[("readonly", cor.texto)])
        estilo.configure("Vertical.TScrollbar", background=cor.borda, troughcolor=cor.fundo,
                         bordercolor=cor.fundo, lightcolor=cor.borda, darkcolor=cor.borda, arrowcolor=cor.texto)

    def _criar_switch(self, nome, cor):
        estados = {}
        for ligado, foco in ((False, False), (True, False), (False, True), (True, True)):
            imagem = Image.new("RGBA", (144, 76))
            desenho = ImageDraw.Draw(imagem)
            desenho.rounded_rectangle((0, 2, 143, 73), radius=36, fill=cor.switch if ligado else cor.borda,
                                       outline=cor.foco if foco else None, width=4)
            x = 76 if ligado else 10
            desenho.ellipse((x, 10, x + 55, 65), fill="#FFFFFF" if nome == "mono" else cor.texto)
            estados[ligado, foco] = self._foto(imagem, (36, 19))
        self.imagens[nome] = estados
        elemento = f"AutoFarm.{nome}.switch"
        estilo = self.estilo
        estilo.element_create(elemento, "image", estados[False, False],
                              ("selected", "focus", estados[True, True]), ("focus", estados[False, True]),
                              ("selected", estados[True, False]))
        classe = f"{nome}.Switch.TCheckbutton"
        estilo.layout(classe, [("Checkbutton.padding", {"sticky": "nswe", "children": [
            (elemento, {"side": "right", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": "w"})
        ]})])
        estilo.configure(classe, background=cor.cartao, foreground=cor.texto, padding=(0, 2))
        estilo.map(classe, background=[("active", cor.cartao)], foreground=[("active", cor.texto)])

    def _foto(self, imagem, tamanho):
        return ImageTk.PhotoImage(imagem.resize(tamanho, Image.Resampling.LANCZOS), master=self.janela)

    def icone(self, nome, cor=None, tamanho=16):
        cor = cor or self.paleta.secundario
        chave = nome, cor, tamanho
        if chave not in self.imagens:
            imagem = Image.new("RGBA", (96, 96))
            desenho = ImageDraw.Draw(imagem)
            for caminho in CAMINHOS[nome]:
                desenho.line([(x * 4, y * 4) for x, y in caminho], fill=cor, width=7, joint="curve")
            for caixa in CIRCULOS.get(nome, ()):
                desenho.ellipse(tuple(v * 4 for v in caixa), outline=cor, width=7)
            self.imagens[chave] = self._foto(imagem, (tamanho, tamanho))
        return self.imagens[chave]
