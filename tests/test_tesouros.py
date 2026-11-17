from contextlib import nullcontext
from email.parser import BytesParser
from email.policy import default
import json
from queue import SimpleQueue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np

from logica_autofarm import Config
from tesouros import AvisosTesouros, DESCONHECIDO, DetectorTesouros, TESOUROS, monitorar_tesouros
from webhook import enviar_webhook


class TesourosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = DetectorTesouros()

    def test_identifica_os_cinco_icones_somente_com_aviso(self):
        quadro = np.full((900, 1440, 3), 64, np.uint8)
        aviso = quadro[301:501, 801:1065]
        titulo = self.detector._ler("encontrou")
        subtitulo = self.detector._ler("elemental")
        aviso[95:114, 50:195] = titulo
        aviso[116:160, 56:193] = subtitulo
        for chave, nome in TESOUROS.items():
            with self.subTest(nome=nome):
                aviso[14:92, 83:174] = (24, 165, 203)
                icone = self.detector.icones[chave]
                altura, largura = icone.shape[:2]
                y, x = 53 - altura // 2, 124 - largura // 2
                regiao = aviso[y:y + altura, x:x + largura]
                mascara = icone[:, :, 3] >= 200
                regiao[mascara] = icone[:, :, :3][mascara]
                self.assertEqual(self.detector.reconhecer(quadro), nome)
        self.assertIsNone(self.detector.reconhecer(quadro[301:393]))

    def test_repete_aviso_so_quando_item_reaparece(self):
        avisos = AvisosTesouros()
        self.assertTrue(avisos.novo("Extrator Portátil", 1))
        self.assertFalse(avisos.novo("Extrator Portátil", 2))
        self.assertFalse(avisos.novo(DESCONHECIDO, 2.1))
        self.assertFalse(avisos.novo(None, 3))
        self.assertTrue(avisos.novo("Extrator Portátil", 5))
        self.assertTrue(avisos.novo("Acelerador de Extração", 5.1))

    def test_monitor_desativado_nao_captura_tela(self):
        parar = Event()
        parar.wait = lambda _: parar.set()
        windows = Mock()
        config = Config(webhook_url="https://exemplo.invalid/webhook")
        monitorar_tesouros(windows, SimpleNamespace(config=config), SimpleQueue(), parar)
        windows.fortnite_em_foco.assert_not_called()

    def test_webhook_identifica_aviso_de_tesouro(self):
        def abrir(pedido, timeout):
            tipo = pedido.get_header("Content-type").encode("ascii")
            multipart = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + tipo + b"\r\n\r\n" + pedido.data)
            mensagem, anexo = multipart.iter_parts()
            self.assertEqual(json.loads(mensagem.get_content())["content"],
                             "Tesouro elemental encontrado — Extrator Portátil")
            self.assertEqual(anexo.get_filename(), "captura.jpg")
            return nullcontext(SimpleNamespace(status=200))

        enviar_webhook("https://exemplo.invalid/webhook", np.zeros((60, 80, 3), np.uint8),
                       "Extrator Portátil", tesouro=True, abrir=abrir)
