from contextlib import nullcontext
from dataclasses import replace
from email.parser import BytesParser
from email.policy import default
import json
from queue import SimpleQueue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from app import monitorar
from avisos_lobby import AvisoLobby
from lobby_especial import MonitorLobby
from logica_autofarm import Config, Fluxo, TEMPLATES
from webhook import enviar_webhook


class MonitorLobbyTest(unittest.TestCase):
    def setUp(self):
        self.lobby = MonitorLobby()
        self.lobby.reconhecer = Mock(return_value=None)
        self.lobby.avisos = Mock()
        self.lobby.avisos.pareamento_restrito.return_value = False
        self.url = "https://exemplo.invalid/webhook/teste"
        self.fluxo = Fluxo(SimpleNamespace(config=Config(webhook_url=self.url), templates=TEMPLATES))
        self.eventos = SimpleQueue()
        self.quadro = np.full((54, 96, 3), 150, np.uint8)
        self.token = AvisoLobby("token_loja_pirata", "Acesso à Loja Pirata", (45, 50))
        self.ban = AvisoLobby("conta_banida", "Esta conta foi banida", (47, 38))

    def passo(self, agora, aviso):
        self.lobby.reconhecer.return_value = aviso
        return self.lobby.passo(self.quadro, self.fluxo, self.eventos, None, agora=agora)

    def test_token_pausa_fluxo_real_sem_entrada_e_envia_mesmo_apos_pausa(self):
        self.fluxo._iniciar_partida(2)
        self.fluxo.partidas = 4
        self.fluxo.config = replace(self.fluxo.config, pausar_ao_obter_token=True)
        self.lobby.reconhecer.return_value = self.token
        windows = Mock()
        windows.capturar.return_value = self.quadro
        parar = Event()
        with patch("app.time.monotonic", return_value=5):
            monitorar(windows, self.fluxo, self.eventos, parar, lobby=self.lobby)
        self.assertTrue(parar.is_set())
        self.assertIsNone(self.fluxo.prazo_saida)
        self.assertEqual(self.fluxo.partidas, 4)
        windows.executar.assert_not_called()
        eventos = [self.eventos.get_nowait() for _ in range(self.eventos.qsize())]
        self.assertIn(("pausa_token", parar), eventos)
        self.assertIn(("prazo_saida", None), eventos)
        aviso, = [valor for tipo, valor in eventos if tipo == "aviso_webhook"]
        url, tipo, nome, captura = aviso
        self.assertEqual((url, tipo, nome), (self.url, self.token.tipo, self.token.nome))
        self.quadro.fill(0)
        self.assertTrue(np.all(captura == 150))
        # F6 inicia outra sessão usando o mesmo MonitorLobby.
        _, acao, pausar = self.passo(10, self.token)
        self.assertFalse(pausar)
        self.assertEqual(acao.alvo.nome, "resgatar_token")
        self.assertTrue(self.eventos.empty())

    def test_token_independe_do_resgate_webhook_e_tesouros(self):
        self.fluxo.config = replace(self.fluxo.config, resgatar_recompensas=False)
        for tempo, aviso in enumerate([self.token, None, self.token, self.token]):
            _, acao, pausar = self.passo(tempo, aviso)
            self.assertIsNone(acao)
            self.assertFalse(pausar)
        self.assertEqual(self.eventos.qsize(), 1)
        self.fluxo.config = replace(self.fluxo.config, webhook_url="", pausar_ao_obter_token=True)
        self.assertTrue(self.passo(8, self.token)[2])

    def test_ban_emite_modal_mesmo_se_a_faixa_chega_primeiro_e_espera_liberacao(self):
        self.fluxo._iniciar_espera_fila(2)
        self.lobby.avisos.pareamento_restrito.return_value = True
        self.assertIsNone(self.passo(3, None)[1])
        self.assertIsNone(self.fluxo._prazo_fila)
        self.assertTrue(self.eventos.empty())
        self.assertEqual(self.passo(4, self.ban)[1].alvo.nome, "continuar_aviso_ban")
        self.assertIsNone(self.passo(5, self.ban)[1])
        self.assertEqual(self.eventos.qsize(), 1)
        self.assertEqual(self.eventos.get_nowait()[1][1], "conta_banida")
        self.lobby.avisos.pareamento_restrito.return_value = False
        with patch("lobby_especial.botao_lobby_liberado", side_effect=[None, None, "lobby_jogar", "lobby_jogar"]):
            for tempo in (60, 1000, 1001):
                self.assertIsNotNone(self.passo(tempo, None))
                self.assertTrue(self.lobby.restricao.ativa)
            self.assertIsNone(self.passo(1002, None))
        self.assertFalse(self.lobby.restricao.ativa)

    def test_pesquisa_so_clica_em_pular_visivel_e_segura_quadro_de_transicao(self):
        self.assertIsNone(self.passo(0, AvisoLobby("pesquisa", "Pesquisa de feedback"))[1])
        pesquisa = AvisoLobby("pesquisa", "Pesquisa de feedback", (39, 41))
        _, acao, _ = self.passo(1, pesquisa)
        self.assertEqual((acao.alvo.nome, acao.alvo.centro), ("pular_pesquisa", (39, 41)))
        self.assertIsNone(self.passo(1.5, pesquisa)[1])
        self.assertIsNone(self.passo(3, None)[1])
        self.assertIsNone(self.passo(4, None)[1])
        self.assertIsNone(self.passo(5, None))
        self.assertTrue(self.eventos.empty())

    def test_webhook_de_cada_aviso_tem_titulo_e_captura_do_jogo(self):
        for aviso, titulo in ((self.token, "Token da Loja Pirata desbloqueado"),
                              (self.ban, "Aviso de banimento no Fortnite")):
            with self.subTest(tipo=aviso.tipo):
                abrir = Mock(return_value=nullcontext(SimpleNamespace(status=200)))
                enviar_webhook(self.url, self.quadro, aviso.nome, aviso=aviso.tipo, abrir=abrir)
                pedido = abrir.call_args.args[0]
                corpo = BytesParser(policy=default).parsebytes(
                    b"Content-Type: " + pedido.get_header("Content-type").encode() + b"\r\n\r\n" + pedido.data)
                mensagem, foto = list(corpo.iter_parts())
                self.assertEqual(json.loads(mensagem.get_content())["content"], f"{titulo} — {aviso.nome}")
                imagem = cv2.imdecode(np.frombuffer(foto.get_payload(decode=True), np.uint8), cv2.IMREAD_COLOR)
                np.testing.assert_array_equal(imagem, self.quadro)
