from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app import Config, Painel, carregar_config
from painel_tema import APARENCIAS


class AparenciaTest(unittest.TestCase):
    def setUp(self):
        self.janela = tk.Tk()
        self.janela.withdraw()
        self.windows = Mock(f6_pressionado=lambda: False, f7=lambda: False)
        self.diagnostico = Mock()
        self.arquivos = TemporaryDirectory()
        self.addCleanup(self.arquivos.cleanup)
        config = patch("app.CONFIG", Path(self.arquivos.name) / "ajustes.json")
        config.start()
        self.addCleanup(config.stop)
        self.addCleanup(self.janela.destroy)
        self.painel = Painel(self.janela, self.windows, Config(atualizar_auto=False), self.diagnostico)
        self.addCleanup(self.painel.salvamento.shutdown)

    def selecionar(self, nome):
        self.painel.aparencia.set(APARENCIAS[nome])
        self.painel.trocar_aparencia()

    def test_troca_pausado_e_rodando_preserva_controles_e_salva_escolha(self):
        painel = self.painel
        self.assertEqual(carregar_config().aparencia, "azul")
        painel.minutos.set("6,75")
        painel.opcoes["anti_afk"].set(False)
        painel.total.set("12")
        painel.farmando.set("10:51")
        painel.proxima_saida.set("02:13")
        self.selecionar("rosa")
        self.assertEqual(painel.status.get(), "Pausado")
        painel.worker = Mock()
        painel.parar = Event()
        painel.status.set("Em partida")
        painel.botao.configure(text="Pausar")
        painel.botao_testar.state(["disabled"])
        relogio, eventos, sessao = painel.relogio, painel.eventos, painel.parar
        controles = painel.botao, painel.botao_testar, painel.botao_diagnostico
        for nome in (*APARENCIAS, *APARENCIAS, "rosa"):
            self.selecionar(nome)
            self.assertEqual(painel.botao.cget("text"), "Pausar")
            self.assertTrue(painel.botao_testar.instate(["disabled"]))
            self.assertEqual((painel.botao, painel.botao_testar, painel.botao_diagnostico), controles)
        self.assertEqual(painel.status.get(), "Em partida")
        self.assertEqual(painel.minutos.get(), "6,75")
        self.assertFalse(painel.opcoes["anti_afk"].get())
        self.assertEqual((painel.total.get(), painel.farmando.get(), painel.proxima_saida.get()), ("12", "10:51", "02:13"))
        self.assertIs(painel.relogio, relogio)
        self.assertIs(painel.eventos, eventos)
        self.assertIs(painel.parar, sessao)
        painel.salvamento.shutdown()
        self.assertEqual(carregar_config().aparencia, "rosa")
        outra = tk.Tk()
        outra.withdraw()
        try:
            reaberto = Painel(outra, self.windows, carregar_config())
            self.assertEqual(reaberto.aparencia.get(), APARENCIAS["rosa"])
            reaberto.salvamento.shutdown()
        finally:
            outra.destroy()

    def test_atalhos_disparam_uma_vez_apos_varias_trocas(self):
        painel = self.painel
        agendados = self.janela.tk.call("after", "info")
        for nome in (*APARENCIAS, *APARENCIAS):
            self.selecionar(nome)
        self.assertEqual(self.janela.tk.call("after", "info"), agendados)
        painel.worker = Mock()
        painel.parar = Event()
        painel.alternar = Mock()
        self.windows.f6_pressionado = Mock(side_effect=[True, False, False, False, False, False])
        self.windows.f7 = Mock(side_effect=[True, True, False, False, False, False])
        self.janela.after(175, self.janela.quit)
        self.janela.mainloop()
        painel.salvamento.shutdown()
        painel.alternar.assert_called_once_with("f6")
        self.diagnostico.registrar.assert_called_once_with("falha_marcada_pelo_usuario", estado="Pausado")
