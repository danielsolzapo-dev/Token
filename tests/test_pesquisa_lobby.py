import unittest

import cv2
import numpy as np

from pesquisa_lobby import DetectorPesquisa


class PesquisaLobbyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = DetectorPesquisa()

    def tela(self, titulo=True, pular=True, habilitado=True):
        # Recria os controles sem capturar nomes de jogadores, fundo ou pergunta.
        quadro = np.full((1032, 1919, 3), 66, np.uint8)
        if titulo:
            mascara = self.detector.modelos["queremos_ouvir"]
            h, w = mascara.shape
            quadro[89:89+h, 625:625+w][mascara > 127] = 255
        cv2.putText(quadro, "Outra pergunta de feedback", (620, 240), 0, 1, (255, 255, 255), 2)
        for x, texto in [(740, "1"), (950, "2"), (1160, "3")]:
            cv2.circle(quadro, (x, 520), 45, (180, 0, 0), -1)
            cv2.putText(quadro, texto, (x-12, 534), 0, 1.1, (255, 255, 255), 3)
        cv2.rectangle(quadro, (971, 806), (1162, 859), (245, 245, 245), -1)
        cv2.putText(quadro, "ENVIAR", (1010, 842), 0, 1, (32, 32, 32), 4)
        if pular:
            cinza = 237 if habilitado else 150
            quadro[806:860, 757:949] = cinza
            mascara = self.detector.modelos["pular"]
            h, w = mascara.shape
            quadro[817:817+h, 804:804+w][mascara > 127] = 32
        return quadro

    def test_aponta_para_pular_independente_da_pergunta_e_do_tamanho(self):
        for w, h in ((1919, 1032), (1440, 900), (1280, 720), (960, 540)):
            with self.subTest(resolucao=(w, h)):
                quadro = cv2.resize(self.tela(), (w, h), interpolation=cv2.INTER_AREA)
                aviso = self.detector.reconhecer(quadro)
                self.assertEqual(aviso.tipo, "pesquisa")
                x, y = aviso.centro_botao
                self.assertAlmostEqual(x, 853 * w / 1919, delta=3)
                self.assertAlmostEqual(y, 833 * h / 1032, delta=3)

    def test_sem_pular_habilitado_mantem_pesquisa_sem_clique(self):
        for quadro in (self.tela(pular=False), self.tela(habilitado=False)):
            aviso = self.detector.reconhecer(quadro)
            self.assertEqual(aviso.tipo, "pesquisa")
            self.assertIsNone(aviso.centro_botao)

    def test_pular_isolado_nao_e_pesquisa(self):
        self.assertIsNone(self.detector.reconhecer(self.tela(titulo=False)))
