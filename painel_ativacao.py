"""Ativação local da licença antes de abrir o painel do Auto Farm."""

import tkinter as tk
from tkinter import messagebox, ttk

from licenca import codigo_pc, ler_chave, salvar_chave, validar_chave


class JanelaAtivacao(tk.Toplevel):
    def __init__(self, pai, pc, aviso=""):
        super().__init__(pai)
        self.title("Ativar Auto Farm")
        self.resizable(True, False)
        self.pc = pc
        self.licenca = None
        self.chave = tk.StringVar(self)
        self.aviso = tk.StringVar(self, aviso)

        painel = ttk.Frame(self, padding=20)
        painel.pack(fill="both", expand=True)
        painel.columnconfigure(0, weight=1)
        ttk.Label(painel, text="Ativar Auto Farm", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(painel, text="Envie o código deste PC ao vendedor. Depois, cole a chave recebida.",
                  wraplength=420).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 16))
        ttk.Label(painel, text="Código deste PC").grid(row=2, column=0, sticky="w")
        self.codigo = tk.StringVar(self, pc)
        ttk.Entry(painel, textvariable=self.codigo, state="readonly", width=38).grid(
            row=3, column=0, sticky="ew", pady=(3, 12))
        ttk.Button(painel, text="Copiar código", command=self.copiar).grid(
            row=3, column=1, padx=(8, 0), pady=(3, 12))
        ttk.Label(painel, text="Chave de licença").grid(row=4, column=0, sticky="w")
        entrada = ttk.Entry(painel, textvariable=self.chave, width=38)
        entrada.grid(row=5, column=0, sticky="ew", pady=(3, 4))
        ttk.Button(painel, text="Colar chave", command=self.colar).grid(
            row=5, column=1, padx=(8, 0), pady=(3, 4), sticky="ew")
        ttk.Label(painel, textvariable=self.aviso, wraplength=420).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(4, 8))
        ttk.Button(painel, text="Ativar", command=self.ativar).grid(
            row=7, column=0, columnspan=2, sticky="ew")
        entrada.bind("<Return>", lambda _: self.ativar())
        entrada.focus_set()

    def copiar(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.pc)
        except tk.TclError:
            self.aviso.set("Selecione o código e pressione Ctrl+C para copiá-lo.")
        else:
            self.aviso.set("Código copiado.")

    def colar(self):
        try:
            self.chave.set(self.clipboard_get().strip())
        except tk.TclError:
            self.aviso.set("Copie a chave recebida do vendedor primeiro.")
        else:
            self.aviso.set("")

    def ativar(self):
        chave = self.chave.get().strip()
        if not chave:
            self.aviso.set("Cole sua chave de licença para ativar.")
            return
        try:
            licenca = validar_chave(chave, self.pc)
            salvar_chave(chave)
        except ValueError as erro:
            self.aviso.set(str(erro))
        except OSError:
            self.aviso.set("Não foi possível salvar a licença. Confira a permissão da pasta de dados e tente novamente.")
        else:
            self.licenca = licenca
            self.destroy()


def obter_licenca(janela):
    try:
        pc = codigo_pc()
    except (OSError, ValueError):
        messagebox.showerror("Ativar Auto Farm", "O Windows não forneceu o código deste PC. "
                             "Reabra o aplicativo para tentar novamente.", parent=janela)
        return None

    aviso = ""
    try:
        chave = ler_chave()
        if chave:
            return validar_chave(chave, pc)
    except ValueError as erro:
        aviso = str(erro)
    except OSError:
        aviso = "Não foi possível ler a licença salva. Cole a chave novamente."
    tela = JanelaAtivacao(janela, pc, aviso)
    janela.wait_window(tela)
    return tela.licenca
