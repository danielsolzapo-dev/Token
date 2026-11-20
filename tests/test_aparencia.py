from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
from tkinter import ttk
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

    def test_saida_quando_sozinho_vem_ligada_e_persiste_ao_alternar_no_painel(self):
        painel = self.painel
        ajustes = Path(self.arquivos.name) / "ajustes.json"
        ajustes.write_text('{"sair_por_tempo": false}', encoding="utf-8")
        self.assertTrue(carregar_config().sair_quando_sozinho)
        painel.fluxo = Mock(config=painel.config)
        botoes = [widget for grupo in painel.conteudo.winfo_children()
                  for card in grupo.winfo_children() for widget in card.winfo_children()
                  if isinstance(widget, ttk.Checkbutton)]
        switch = next(botao for botao in botoes
                      if str(botao.cget("variable")) == str(painel.opcoes["sair_quando_sozinho"]))
        self.assertTrue(switch.instate(["selected"]))
        for habilitada in (False, True):
            switch.invoke()
            painel.salvamento.submit(lambda: None).result()
            self.assertEqual(carregar_config().sair_quando_sozinho, habilitada)
            self.assertEqual(painel.ler_opcoes().sair_quando_sozinho, habilitada)
            self.assertEqual(painel.fluxo.config.sair_quando_sozinho, habilitada)

    def test_switch_pausar_token_salva_sem_url_e_atualiza_sessao(self):
        painel = self.painel
        (Path(self.arquivos.name) / "ajustes.json").write_text("{}", encoding="utf-8")
        self.assertFalse(carregar_config().pausar_ao_obter_token)
        painel.fluxo = Mock(config=painel.config)
        painel.mostrar_webhook()
        formulario, = painel.janela_webhook.winfo_children()
        switch = next(w for w in formulario.winfo_children() if isinstance(w, ttk.Checkbutton)
                      and w.cget("text") == "Pausar ao obter o token da Loja Pirata")
        salvar = next(b for linha in formulario.winfo_children() for b in linha.winfo_children()
                      if isinstance(b, ttk.Button) and b.cget("text") == "Salvar")
        self.assertFalse(switch.instate(["selected"]))
        for ligada in (True, False):
            switch.invoke()
            salvar.invoke()
            painel.salvamento.submit(lambda: None).result()
            self.assertEqual(painel.fluxo.config.pausar_ao_obter_token, ligada)
            self.assertEqual(carregar_config().pausar_ao_obter_token, ligada)
            self.assertEqual(painel.opcoes["pausar_ao_obter_token"].get(), ligada)

    def test_pausa_automatica_exibe_motivo_e_entrega_captura_ja_enfileirada(self):
        painel = self.painel
        url = "https://exemplo.invalid/webhook/teste"
        painel.salvar_webhook(url, False)
        painel.iniciar_envio_webhook = Mock()
        painel.parar = Event()
        painel.parar.set()
        painel.worker = Mock()
        painel.worker.is_alive.return_value = False
        quadro = object()
        painel.eventos.put(("aviso_webhook", (url, "token_loja_pirata", "Acesso à Loja Pirata", quadro)))
        painel.eventos.put(("pausa_token", painel.parar))
        painel.atualizar()
        painel.iniciar_envio_webhook.assert_called_once_with(
            url, "Acesso à Loja Pirata", quadro, aviso="token_loja_pirata")
        self.assertEqual(painel.status.get(), "Pausado")
        self.assertIn("Token da Loja Pirata", painel.atividade.get())

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
