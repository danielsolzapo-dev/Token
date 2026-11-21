"""Ativação da licença antes de abrir o painel do Auto Farm."""

from concurrent.futures import Future
from threading import Thread
import tkinter as tk
from tkinter import messagebox, ttk

import licenca
from licenca import codigo_pc, ler_chave, salvar_chave, validar_chave


def _solicitar_ativacao(resultado, chave, pc):
    try:
        resultado.set_result(licenca.ativar_venda(chave, pc))
    except Exception as erro:
        resultado.set_exception(erro)


class JanelaAtivacao(tk.Toplevel):
    def __init__(self, pai, pc, aviso=""):
        super().__init__(pai)
        self.title("Ativar Auto Farm")
        self.resizable(True, False)
        self.pc = pc
        self.licenca = None
        self.pedido = None
        self.agendamento = None
        self.chave = tk.StringVar(self)
        self.aviso = tk.StringVar(self, aviso)

        painel = ttk.Frame(self, padding=20)
        painel.pack(fill="both", expand=True)
        painel.columnconfigure(0, weight=1)
        ttk.Label(painel, text="Ativar Auto Farm", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(painel, text="Cole a chave recebida do vendedor. A primeira ativação usa a internet "
                  "e vincula a chave a este PC. Depois você pode usar o app offline.",
                  wraplength=420).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 16))
        ttk.Label(painel, text="Chave de licença").grid(row=2, column=0, sticky="w")
        self.entrada = ttk.Entry(painel, textvariable=self.chave, width=38)
        self.entrada.grid(row=3, column=0, sticky="ew", pady=(3, 4))
        self.botao_colar = ttk.Button(painel, text="Colar chave", command=self.colar)
        self.botao_colar.grid(row=3, column=1, padx=(8, 0), pady=(3, 4), sticky="ew")
        ttk.Label(painel, textvariable=self.aviso, wraplength=420).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 8))
        self.botao_ativar = ttk.Button(painel, text="Ativar neste PC", command=self.ativar)
        self.botao_ativar.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Button(painel, text="Copiar código do PC para emissão offline", command=self.copiar).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.entrada.bind("<Return>", lambda _: self.ativar())
        self.entrada.focus_set()

    def destroy(self):
        if self.agendamento is not None:
            self.after_cancel(self.agendamento)
            self.agendamento = None
        super().destroy()

    def copiar(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.pc)
        except tk.TclError:
            messagebox.showinfo("Código deste PC", self.pc, parent=self)
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
        if self.pedido is not None:
            return
        chave = self.chave.get().strip()
        if not chave:
            self.aviso.set("Cole sua chave de licença para ativar.")
            return
        if chave.startswith("AFV1."):
            self.pedido = Future()
            self._habilitar_entrada(False)
            self.aviso.set("Vinculando a chave a este PC…")
            Thread(target=_solicitar_ativacao, args=(self.pedido, chave, self.pc), daemon=True).start()
            self.agendamento = self.after(80, self._receber_ativacao)
        else:
            self._validar_e_salvar(chave)

    def _habilitar_entrada(self, habilitar):
        for controle in (self.entrada, self.botao_colar, self.botao_ativar):
            controle.state(["!disabled" if habilitar else "disabled"])

    def _receber_ativacao(self):
        self.agendamento = None
        if not self.pedido.done():
            self.agendamento = self.after(80, self._receber_ativacao)
            return
        pedido, self.pedido = self.pedido, None
        self._habilitar_entrada(True)
        try:
            recibo = pedido.result()
        except ValueError as erro:
            self.aviso.set(str(erro))
        except OSError as erro:
            self.aviso.set(str(erro) or "Não foi possível contatar o servidor. Tente a mesma chave novamente.")
        except Exception:
            self.aviso.set("Ocorreu uma falha na ativação. Tente novamente com a mesma chave.")
        else:
            if isinstance(recibo, str) and recibo.startswith("AFA1."):
                self._validar_e_salvar(recibo)
            else:
                self.aviso.set("O servidor devolveu uma resposta de ativação inválida.")

    def _validar_e_salvar(self, chave):
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
