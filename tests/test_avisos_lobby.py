import unittest

import cv2
import numpy as np

from avisos_lobby import DetectorAvisosLobby


class AvisosLobbyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = DetectorAvisosLobby()

    def inserir_rotulo(self, fundo, nome, x, y):
        rotulo = self.detector.modelos[nome]
        h, w = rotulo.shape
        fundo[y:y + h, x:x + w] = cv2.cvtColor(rotulo, cv2.COLOR_GRAY2BGR)

    def test_desbloqueio_com_botao_resgatar_em_varias_resolucoes(self):
        fundo = np.full((1032, 1920, 3), (160, 55, 8), np.uint8)
        self.inserir_rotulo(fundo, "loja_pirata", 73, 392)
        self.inserir_rotulo(fundo, "acesso_loja", 1282, 312)
        self.inserir_rotulo(fundo, "resgatar_tudo", 847, 929)
        for w, h in ((1920, 1032), (1440, 900), (1280, 720)):
            with self.subTest(w=w, h=h):
                quadro = cv2.resize(fundo, (w, h), interpolation=cv2.INTER_AREA)
                aviso = self.detector.reconhecer(quadro)
                self.assertEqual(aviso.tipo, "token_loja_pirata")
                self.assertEqual(aviso.nome, "Acesso à Loja Pirata")
                self.assertAlmostEqual(aviso.centro_botao[0], w * .50, delta=3)
                self.assertAlmostEqual(aviso.centro_botao[1], h * .915, delta=3)
        fundo[900:] = (160, 55, 8)
        self.assertIsNone(self.detector.reconhecer(fundo).centro_botao)

    def test_tela_azul_com_resgatar_ou_titulo_isolado_nao_indica_token(self):
        fundo = np.full((1032, 1920, 3), (160, 55, 8), np.uint8)
        self.inserir_rotulo(fundo, "resgatar_tudo", 847, 929)
        self.inserir_rotulo(fundo, "acesso_loja", 1282, 312)
        self.assertIsNone(self.detector.reconhecer(fundo))
        fundo.fill(0)
        self.inserir_rotulo(fundo, "loja_pirata", 73, 392)
        self.assertIsNone(self.detector.reconhecer(fundo))

    def test_modal_com_titulo_e_icone_antes_de_localizar_continuar(self):
        fundo = np.full((1030, 1918, 3), 32, np.uint8)
        self.inserir_rotulo(fundo, "continuar", 874, 735)
        cv2.circle(fundo, (959, 260), 24, (35, 74, 247), -1)
        self.assertIsNone(self.detector.reconhecer(fundo))
        self.inserir_rotulo(fundo, "conta_banida", 833, 311)
        quadro = cv2.resize(fundo, (1440, 900), interpolation=cv2.INTER_AREA)
        aviso = self.detector.reconhecer(quadro)
        self.assertEqual(aviso.tipo, "conta_banida")
        self.assertAlmostEqual(aviso.centro_botao[0], 720, delta=3)
        self.assertAlmostEqual(aviso.centro_botao[1], 660, delta=3)
        fundo[700:] = 32
        self.assertIsNone(self.detector.reconhecer(fundo).centro_botao)
        fundo[200:290] = 32
        self.assertIsNone(self.detector.reconhecer(fundo))

    def test_faixa_restrita_independe_de_duracao_e_do_modal(self):
        fundo = np.full((1030, 1918, 3), 32, np.uint8)
        cv2.putText(fundo, "55 m", (324, 907), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255))
        self.assertFalse(self.detector.pareamento_restrito(fundo))
        self.inserir_rotulo(fundo, "pareamento_restrito", 96, 890)
        quadro = cv2.resize(fundo, (1280, 720), interpolation=cv2.INTER_AREA)
        self.assertTrue(self.detector.pareamento_restrito(quadro))
        self.assertIsNone(self.detector.reconhecer(quadro))
