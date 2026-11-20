import unittest

import cv2
import numpy as np

from contagem_partida import ContadorPartida


class ContagemPartidaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contador = ContadorPartida()

    def hud(self, numero, primeiro=255, separacao=1, icone=True):
        # Apenas a linha pública do HUD. A borda direita do valor é fixa.
        quadro = np.full((860, 1440, 3), 64, np.uint8)
        if icone:
            modelo = self.contador.icones[0]
            quadro[72:89, 1243:1260] = np.where(modelo > 0, 167 + modelo / 3, 64)[:, :, None]
        fim = 1237
        for indice in reversed(range(len(numero))):
            n = int(numero[indice])
            glifo = self.contador.digitos[n][2:22]
            x, _, w, _ = cv2.boundingRect((glifo >= 80).astype(np.uint8))
            largura = max(3, round(w * .45))
            img = cv2.resize(glifo[:, x:x+w], (largura, 9), interpolation=cv2.INTER_AREA)
            brilho = primeiro if indice == 0 else 255
            pixels = np.where(img > 0, 167 + img / 3, 64)
            quadro[75:84, fim-largura:fim] = (64 + (pixels - 64) * (brilho - 64) / 188)[:, :, None]
            fim -= largura + separacao
        return quadro

    def test_um_jogador_confirmado_e_dois_digitos(self):
        for numero in ("1", "11", "21", "31", "80"):
            quadro = self.hud(numero)
            for tamanho in ((1440, 860), (1440, 900), (1280, 720), (1920, 1080)):
                with self.subTest(numero=numero, tamanho=tamanho):
                    resultado = self.contador.ler(cv2.resize(quadro, tamanho, interpolation=cv2.INTER_AREA))
                    if numero == "1":
                        self.assertEqual(resultado, 1)
                    else:
                        self.assertIn(resultado, (int(numero), None))

    def test_primeiro_digito_fraco_ou_separado_nao_e_ultimo_jogador(self):
        for numero in ("11", "21", "31", "51"):
            for brilho in (255, 173, 141):
                for separacao in (1, 4, 8):
                    with self.subTest(numero=numero, brilho=brilho, separacao=separacao):
                        quadro = self.hud(numero, brilho, separacao)
                        for tamanho in ((1440, 860), (1280, 720), (1920, 1080)):
                            ajustado = cv2.resize(quadro, tamanho, interpolation=cv2.INTER_AREA)
                            self.assertNotEqual(self.contador.ler(ajustado), 1)

    def test_um_isolado_em_outra_linha_ou_sem_icone_de_pessoa(self):
        quadro = self.hud("1", icone=False)
        self.assertIsNone(self.contador.ler(quadro))
        quadro[32:49, 1243:1260] = self.hud("1")[72:89, 1243:1260]
        self.assertIsNone(self.contador.ler(quadro))

    def test_tela_escura_ou_icone_sem_numero(self):
        self.assertIsNone(self.contador.ler(np.zeros((540, 960, 3), np.uint8)))
        self.assertIsNone(self.contador.ler(self.hud("")))
