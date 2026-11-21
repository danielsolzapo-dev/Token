from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory
from threading import Event, get_ident
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from painel_replay import JanelaBaus


class PainelReplayTest(unittest.TestCase):
    def setUp(self):
        self.raiz = tk.Tk()
        self.raiz.withdraw()
        self.addCleanup(self.raiz.destroy)
        self.eventos = SimpleQueue()
        self.janela = JanelaBaus(self.raiz, self.eventos)
        pasta = TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.ultimo = Path(pasta.name) / "ultimo.replay"
        self.ultimo.write_bytes(b"partida")
        self.resultado = SimpleNamespace(voce=0, esquadrao=4, detalhe="Aberturas registradas.")

    def receber_resultado(self):
        while True:
            tipo, dados = self.eventos.get(timeout=3)
            if tipo == "baus_replay":
                self.janela.mostrar_resultado(*dados)
                return
            self.janela.mostrar_andamento(*dados)

    def test_reabre_durante_leitura_mostra_zero_e_time_e_ignora_arquivo_igual(self):
        leitura_iniciada, liberar = Event(), Event()
        thread_tk = get_ident()

        def analisar(caminho):
            self.assertNotEqual(get_ident(), thread_tk)
            self.assertEqual(caminho, self.ultimo)
            leitura_iniciada.set()
            liberar.wait(timeout=3)
            return self.resultado

        with patch("painel_replay.baus_replay.ultimo_replay", return_value=self.ultimo), patch(
                "painel_replay.baus_replay.analisar_replay", side_effect=analisar) as parser:
            self.janela.abrir()
            self.assertTrue(leitura_iniciada.wait(timeout=3))
            self.janela.ocultar()
            self.janela.abrir()
            liberar.set()
            self.receber_resultado()
            self.assertEqual((self.janela.voce.get(), self.janela.esquadrao.get()), ("0", "4"))
            self.assertEqual(self.janela.arquivo.get(), "ultimo.replay")
            self.assertIsNotNone(self.janela.agendamento)
            self.janela.iniciar(automatica=True)
            self.receber_resultado()
            parser.assert_called_once()
            self.janela.ocultar()
            self.assertIsNone(self.janela.agendamento)

    def test_arquivo_escolhido_preservado_ate_uma_nova_gravacao(self):
        antigo = self.ultimo.with_name("antigo.replay")
        antigo.write_bytes(b"anterior")
        parcial = SimpleNamespace(voce=2, esquadrao=None, detalhe="Equipe indisponível.")
        with patch("painel_replay.baus_replay.ultimo_replay", return_value=self.ultimo), patch(
                "painel_replay.baus_replay.analisar_replay", side_effect=[parcial, self.resultado]) as parser, patch(
                "painel_replay.filedialog.askopenfilename", return_value=str(antigo)):
            self.janela.escolher_arquivo()
            self.receber_resultado()
            self.assertEqual(self.janela.esquadrao.get(), "—")
            self.assertEqual(self.janela.detalhe.get(), "Equipe indisponível.")
            self.janela.iniciar(automatica=True)
            self.receber_resultado()
            self.assertEqual(self.janela.arquivo.get(), "antigo.replay")
            self.ultimo.write_bytes(b"proxima partida concluida")
            self.janela.iniciar(automatica=True)
            self.receber_resultado()
            self.assertEqual(self.janela.arquivo.get(), "ultimo.replay")
            self.assertEqual([chamada.args[0] for chamada in parser.call_args_list], [antigo, self.ultimo])

    def test_erro_de_leitura_descarta_totais_antigos_sem_substituir_por_zero(self):
        with patch("painel_replay.baus_replay.ultimo_replay", return_value=self.ultimo), patch(
                "painel_replay.baus_replay.analisar_replay", side_effect=[self.resultado, ValueError("Replay ilegível.")]):
            for _ in range(2):
                self.janela.iniciar()
                self.receber_resultado()
            self.assertEqual((self.janela.voce.get(), self.janela.esquadrao.get()), ("—", "—"))
            self.assertEqual(self.janela.detalhe.get(), "Replay ilegível.")
            self.assertFalse(self.janela.escolher.instate(["disabled"]))

    def test_selecao_manual_durante_consulta_automatica_tem_prioridade(self):
        evento, liberar = Event(), Event()
        antigo = self.ultimo.with_name("antigo.replay")

        def localizar():
            evento.set()
            liberar.wait(timeout=3)
            return self.ultimo

        with patch("painel_replay.baus_replay.ultimo_replay", side_effect=localizar), patch(
                "painel_replay.baus_replay.analisar_replay", return_value=self.resultado):
            self.janela.abrir()
            self.assertTrue(evento.wait(timeout=3))
            self.janela.iniciar(antigo)
            liberar.set()
            self.receber_resultado()
            self.receber_resultado()
        self.assertEqual(self.janela.arquivo.get(), "antigo.replay")
