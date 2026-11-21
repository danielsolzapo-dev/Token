"""Janela de contagem dos baús registrados em um replay do Fortnite."""

from pathlib import Path
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk

import baus_replay


class JanelaBaus(tk.Toplevel):
    def __init__(self, pai, eventos):
        super().__init__(pai)
        self.title("Baús do replay")
        self.transient(pai)
        self.protocol("WM_DELETE_WINDOW", self.ocultar)
        self.eventos = eventos
        self.analise = None
        self.pedido_manual = None
        self.assinatura_ultimo = None
        self.agendamento = None
        self.aberta = False
        self.arquivo = tk.StringVar(self)
        self.voce = tk.StringVar(self, "—")
        self.esquadrao = tk.StringVar(self, "—")
        self.detalhe = tk.StringVar(self, "Procurando o último replay concluído…")

        painel = ttk.Frame(self, padding=18)
        painel.pack(fill="both", expand=True)
        acoes = ttk.Frame(painel)
        acoes.pack(fill="x")
        self.ultimo = ttk.Button(acoes, text="Analisar último replay", command=self.iniciar)
        self.ultimo.pack(side="left")
        self.escolher = ttk.Button(acoes, text="Escolher arquivo…", command=self.escolher_arquivo)
        self.escolher.pack(side="left", padx=(8, 0))
        ttk.Label(painel, textvariable=self.arquivo, wraplength=400).pack(anchor="w", pady=(10, 6))

        contagens = ttk.Frame(painel)
        contagens.pack(fill="x")
        for coluna, (rotulo, valor) in enumerate((("Você", self.voce), ("Esquadrão (inclui você)", self.esquadrao))):
            contagens.columnconfigure(coluna, weight=1, uniform="totais")
            card = ttk.Frame(contagens, style="Metrica.Card.TFrame", padding=(12, 8))
            card.grid(row=0, column=coluna, sticky="ew", padx=(0 if coluna == 0 else 6, 0))
            ttk.Label(card, text=rotulo, style="MetricaInfo.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=valor, style="MetricaCard.TLabel").pack(anchor="w")
        ttk.Label(painel, textvariable=self.detalhe, style="Info.TLabel", wraplength=400,
                  justify="left").pack(anchor="w", pady=(10, 0))
        ttk.Label(painel, text="Novas partidas são analisadas enquanto esta janela estiver aberta.",
                  style="Info.TLabel", wraplength=400).pack(anchor="w", pady=(8, 0))

    def abrir(self):
        self.deiconify()
        self.lift()
        if not self.aberta:
            self.aberta = True
            self.iniciar(automatica=True)

    def ocultar(self):
        self.aberta = False
        self.cancelar_agendamento()
        self.withdraw()

    def cancelar_agendamento(self):
        if self.agendamento is not None:
            self.after_cancel(self.agendamento)
            self.agendamento = None

    def destroy(self):
        self.cancelar_agendamento()
        super().destroy()

    def escolher_arquivo(self):
        arquivo = filedialog.askopenfilename(parent=self, title="Escolher replay do Fortnite",
                                             initialdir=baus_replay.pasta_replays(),
                                             filetypes=[("Replay do Fortnite", "*.replay")])
        if arquivo:
            self.iniciar(Path(arquivo))

    def iniciar(self, caminho=None, *, automatica=False):
        if self.analise is not None:
            if not automatica:
                self.pedido_manual = (caminho,)
            return
        self.cancelar_agendamento()
        self.analise = object()
        if not automatica:
            self.mostrar_andamento(self.analise, caminho)
        Thread(target=self._ler, args=(caminho, self.analise, self.eventos, self.assinatura_ultimo,
                                      automatica), daemon=True).start()

    @staticmethod
    def _ler(caminho, analise, eventos, assinatura, automatica):
        resultado = detalhe = None
        try:
            # Ao escolher uma gravação antiga, guarda o último replay atual para
            # trocar de resultado somente quando o jogo salvar uma nova partida.
            try:
                ultimo = baus_replay.ultimo_replay()
                dados = ultimo.stat()
                atual = (ultimo, dados.st_size, dados.st_mtime_ns)
            except (ValueError, OSError):
                if caminho is None:
                    raise
                atual = None
            if caminho is None:
                if automatica and atual == assinatura:
                    return
                caminho = ultimo
            assinatura = atual
            eventos.put(("lendo_replay", (analise, caminho)))
            resultado = baus_replay.analisar_replay(caminho)
            detalhe = resultado.detalhe
        except (ValueError, OSError) as erro:
            detalhe = str(erro)
        except Exception:
            detalhe = "Falha ao analisar o replay. Tente outra gravação."
        finally:
            eventos.put(("baus_replay", (analise, caminho, resultado, detalhe, assinatura, automatica)))

    def mostrar_andamento(self, analise, caminho):
        if analise is self.analise and self.pedido_manual is None:
            self.ultimo.state(["disabled"])
            self.escolher.state(["disabled"])
            self.voce.set("—")
            self.esquadrao.set("—")
            self.arquivo.set(caminho.name if caminho else "")
            self.detalhe.set("Analisando o replay…" if caminho else "Procurando o último replay concluído…")

    def mostrar_resultado(self, analise, caminho, resultado, detalhe, assinatura, automatica):
        if analise is not self.analise:
            return
        self.analise = None
        self.assinatura_ultimo = assinatura
        self.ultimo.state(["!disabled"])
        self.escolher.state(["!disabled"])
        if self.pedido_manual is not None:
            caminho_pedido, = self.pedido_manual
            self.pedido_manual = None
            self.iniciar(caminho_pedido)
            return
        if detalhe is not None and (caminho is not None or not automatica or not self.arquivo.get()):
            self.arquivo.set(caminho.name if caminho else "")
            if resultado is not None:
                self.voce.set("—" if resultado.voce is None else str(resultado.voce))
                self.esquadrao.set("—" if resultado.esquadrao is None else str(resultado.esquadrao))
            if self.detalhe.get() != detalhe:
                self.detalhe.set(detalhe)
        if self.aberta:
            self.agendamento = self.after(10_000, lambda: self.iniciar(automatica=True))
