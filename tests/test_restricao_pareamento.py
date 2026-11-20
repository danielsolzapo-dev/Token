from pathlib import Path
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from logica_autofarm import Detector
from restricao_pareamento import RestricaoPareamento, botao_lobby_liberado


RAIZ = Path(__file__).resolve().parents[1]


class TestRestricao(unittest.TestCase):
    def test_modal_e_faixa_iniciam_um_unico_incidente(self):
        espera = RestricaoPareamento()
        self.assertEqual(espera.observar(0, faixa_restrita=True), "inicio")
        self.assertFalse(espera.pode_fechar_aviso(0))
        self.assertIsNone(espera.observar(1, modal=True))
        self.assertTrue(espera.pode_fechar_aviso(1))
        espera.registrar_tentativa(1)
        self.assertIsNone(espera.observar(2, modal=True))
        self.assertFalse(espera.pode_fechar_aviso(2))
        self.assertTrue(espera.pode_fechar_aviso(11))
        self.assertIsNone(espera.observar(12, faixa_restrita=True, botao_lobby="lobby_pronto"))
        self.assertFalse(espera.pode_fechar_aviso(12))
        self.assertTrue(espera.ativa)

    def test_aguarda_botao_apos_tempo_e_desaparecimento_da_faixa(self):
        espera = RestricaoPareamento()
        espera.observar(0, modal=True)
        for instante, botao in ((3600, None), (3605, "continuar"), (3610, "lobby_informacoes"),
                                (3615, "lobby_jogar"), (3675, "lobby_jogar")):
            self.assertIsNone(espera.observar(instante, botao_lobby=botao))
            self.assertTrue(espera.ativa)
        self.assertEqual(espera.observar(3676, botao_lobby="lobby_jogar"), "liberada")
        self.assertFalse(espera.ativa)
        self.assertIsNone(espera.observar(3677, botao_lobby="lobby_jogar"))
        self.assertEqual(espera.observar(3678, modal=True), "inicio")

    def test_requer_leituras_estaveis_sem_modal_nem_faixa(self):
        espera = RestricaoPareamento()
        espera.observar(0, modal=True)
        for instante, botao, faixa in ((1, "lobby_jogar", False), (1.1, "lobby_jogar", False),
                                       (2, "lobby_jogar", True), (3, "lobby_pronto", False),
                                       (4, None, False), (5, "lobby_jogar", False),
                                       (6, "lobby_pronto", False)):
            self.assertIsNone(espera.observar(instante, botao_lobby=botao, faixa_restrita=faixa))
        self.assertEqual(espera.observar(7, botao_lobby="lobby_pronto"), "liberada")

    def test_informacoes_e_botao_fora_do_lobby_nao_liberam(self):
        detector = Mock()
        detector._carregar_leitor.return_value.linhas.return_value = [Mock(texto="INFORMAÇÕES")]
        quadro = np.zeros((540, 960, 3), np.uint8)
        cv2.rectangle(quadro, (40, 390), (220, 430), (0, 255, 255), -1)
        self.assertIsNone(botao_lobby_liberado(quadro, detector))
        detector._carregar_leitor.assert_called_once()
        detector.reset_mock()
        self.assertIsNone(botao_lobby_liberado(cv2.flip(quadro, 1), detector))
        self.assertIsNone(botao_lobby_liberado(quadro // 2, detector))
        detector._carregar_leitor.assert_not_called()

    @unittest.skipUnless((RAIZ / "modelos/latin_PP-OCRv5_rec_mobile.onnx").is_file()
                         and (RAIZ / "modelos/PP-OCRv6_det_small.onnx").is_file(), "modelos ausentes")
    def test_ocr_dos_botoes_do_lobby(self):
        detector = Detector()
        for nome in ("lobby_jogar", "lobby_pronto"):
            with self.subTest(botao=nome):
                botao = cv2.imdecode(np.frombuffer((RAIZ / "templates" / f"{nome}.png").read_bytes(),
                                                   np.uint8), cv2.IMREAD_COLOR)
                quadro = np.zeros((540, 960, 3), np.uint8)
                h, w = botao.shape[:2]
                quadro[390:390 + h, 40:40 + w] = botao
                self.assertEqual(botao_lobby_liberado(quadro, detector), nome)
