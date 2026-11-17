import random
import unittest

import cv2
import numpy as np

from embarque import Embarque
from logica_autofarm import Detector, HUMORES, plano_anti_afk
from texto_tela import Linha, identificar


class EmbarqueTest(unittest.TestCase):
    def test_salto_e_fechamento_da_asa_confirmados_sem_repeticao(self):
        embarque = Embarque()
        self.assertIsNone(embarque.observar(onibus=True, asa=False))
        self.assertEqual(embarque.observar(onibus=True, asa=False), "saltar_onibus")
        embarque.registrar("saltar_onibus", True, 0.8)
        self.assertIsNone(embarque.observar(onibus=True, asa=False))
        self.assertIsNone(embarque.observar(onibus=False, asa=True))
        self.assertEqual(embarque.observar(onibus=False, asa=True), "fechar_asa")
        embarque.registrar("fechar_asa", True, 4.2)
        self.assertIsNone(embarque.observar(onibus=False, asa=True))

    def test_perda_de_foco_quebra_confirmacao_do_onibus(self):
        embarque = Embarque()
        embarque.observar(onibus=True, asa=False)
        embarque.pausar()
        self.assertIsNone(embarque.observar(onibus=True, asa=False))
        self.assertEqual(embarque.observar(onibus=True, asa=False), "saltar_onibus")

    def test_planejador_aleatorio_nao_envia_s(self):
        rng = random.Random(17)
        desvio = (0.0, 0.0, 0.0)
        for humor in HUMORES:
            for camera in (False, True):
                for _ in range(100):
                    passos, desvio = plano_anti_afk(desvio, camera=camera, humor=humor, rng=rng)
                    for passo in passos:
                        if passo[0] in ("teclas", "andar_mouse"):
                            self.assertNotIn(31, passo[1])


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

    def test_le_aviso_do_onibus_com_texto_do_template(self):
        aviso = Linha("ESPAÇO PARA PULAR", (32, 8, 163, 24))
        self.assertEqual(identificar([aviso], 300, 90, "pular_onibus"), aviso)
        outro = Linha("ESPAÇO PARA ABRIR ASA-DELTA", (32, 8, 240, 24))
        self.assertIsNone(identificar([outro], 300, 90, "pular_onibus"))

    def test_fechar_asa_reconhece_queda_livre_sem_abrir_asa(self):
        queda = Linha("ESPAÇO PARA ENTRAR EM QUEDA LIVRE", (8, 8, 284, 24))
        abrir = Linha("ESPAÇO PARA ABRIR ASA-DELTA", (32, 8, 240, 24))
        self.assertEqual(identificar([queda], 300, 90, "fechar_asa"), queda)
        self.assertIsNone(identificar([abrir], 300, 90, "fechar_asa"))

    def test_barras_do_esquadrao_exigem_pares_acima_do_hud_proprio(self):
        quadro = np.zeros((860, 1440, 3), dtype=np.uint8)
        for y in (680, 720):
            cv2.rectangle(quadro, (43, y), (169, y + 4), (235, 195, 0), -1)
            cv2.rectangle(quadro, (44, y + 6), (169, y + 10), (10, 215, 95), -1)
        self.assertEqual(Detector().barras_esquadrao(quadro), 2)
        self.assertIsNone(Detector().barras_esquadrao(np.zeros_like(quadro)))
