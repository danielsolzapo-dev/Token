import unittest

import cv2
import numpy as np

from embarque import Embarque
from logica_autofarm import Detector
from texto_tela import Linha, identificar


class EmbarqueTest(unittest.TestCase):
    def test_salto_estavel_e_asa_temporizada_sem_repeticao(self):
        embarque = Embarque()
        self.assertIsNone(embarque.observar(0, onibus=True, asa=False))
        self.assertEqual(embarque.observar(0.3, onibus=True, asa=False), "saltar_onibus")
        embarque.registrar("saltar_onibus", True, 0.8)
        self.assertIsNone(embarque.observar(1, onibus=True, asa=False))
        self.assertIsNone(embarque.observar(4, onibus=False, asa=True))
        self.assertIsNone(embarque.observar(11.9, onibus=False, asa=True))
        self.assertEqual(embarque.observar(12, onibus=False, asa=True), "fechar_asa")
        embarque.registrar("fechar_asa", True, 12.2)
        self.assertIsNone(embarque.observar(13, onibus=False, asa=True))

    def test_perda_de_foco_quebra_confirmacao_do_onibus(self):
        embarque = Embarque()
        embarque.observar(0, onibus=True, asa=False)
        embarque.pausar()
        self.assertIsNone(embarque.observar(30, onibus=True, asa=False))
        self.assertEqual(embarque.observar(30.3, onibus=True, asa=False), "saltar_onibus")


class LeituraDiagnosticoTest(unittest.TestCase):
    def test_esquadrao_preenchido_com_botao_direito(self):
        jogar = Linha("JOGAR", (960, 750, 140, 28))
        modo = Linha("ESQUADRÃO", (920, 278, 170, 24))
        preencher = Linha("PREENCHER", (925, 382, 150, 24))
        self.assertEqual(identificar([modo, preencher, jogar], 1440, 860, "jogar_modo"), jogar)
        vazio = Linha("NÃO PREENCHER", (925, 382, 180, 24))
        self.assertIsNone(identificar([modo, vazio, jogar], 1440, 860, "jogar_modo"))

    def test_regiao_reconhece_rotulo_cortado_sem_inferir_regiao(self):
        regiao = Linha("Região de Pareament", (400, 194, 212, 16))
        self.assertEqual(identificar([regiao], 1440, 860, "tela_regiao"), regiao)

    def test_pronto_de_lobby_rejeita_indicacao_de_esc(self):
        pronto = Linha("PRONTO", (30, 5, 65, 20))
        esc = Linha("ESC", (5, 6, 20, 18))
        self.assertEqual(identificar([pronto], 140, 35, "pronto_lobby"), pronto)
        self.assertIsNone(identificar([esc, pronto], 140, 35, "pronto_lobby"))
        self.assertIsNone(identificar([Linha("NÃO PRONTO", (28, 3, 90, 20))], 140, 35, "pronto_lobby"))

    def test_barras_do_esquadrao_exigem_pares_acima_do_hud_proprio(self):
        quadro = np.zeros((860, 1440, 3), dtype=np.uint8)
        for y in (680, 720):
            cv2.rectangle(quadro, (43, y), (169, y + 4), (235, 195, 0), -1)
            cv2.rectangle(quadro, (44, y + 6), (169, y + 10), (10, 215, 95), -1)
        self.assertEqual(Detector().barras_esquadrao(quadro), 2)
        self.assertIsNone(Detector().barras_esquadrao(np.zeros_like(quadro)))
