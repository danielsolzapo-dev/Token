from pathlib import Path
import unittest

import cv2
import numpy as np

from hud_esquadrao import LeituraEsquadrao, aguardando_jogadores, ler_esquadrao


def tela_companheiros(estados):
    quadro = np.full((860, 1440, 3), 48, np.uint8)
    caminho = Path(__file__).resolve().parents[1] / "templates" / "cartao_reinicio_esquadrao.png"
    referencia = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    for i, estado in enumerate(estados):
        y = 671 + i * 33
        cv2.circle(quadro, (44, y-12), 3, (30, 205, 230), -1)
        cor = (90, 38, 220) if estado in ("eliminado", "sem_cartao", "escudo") else (240, 240, 240)
        cv2.putText(quadro, "ALIADO", (51, y-10), cv2.FONT_HERSHEY_SIMPLEX, .35, cor, 1)
        quadro[y:y+6, 41:166] = (66, 66, 66)
        if estado in ("vivo", "derrubado"):
            quadro[y:y+6, 41:100] = (30, 200, 80) if estado == "vivo" else (80, 30, 200)
        if estado in ("eliminado", "cartao_sem_nome_vermelho"):
            h, w = referencia.shape
            quadro[y-9:y-9+h, 169:169+w, 0] = referencia
            quadro[y-9:y-9+h, 169:169+w, 1] = referencia
            quadro[y-9:y-9+h, 169:169+w, 2] = 0
        if estado == "escudo":
            vertices = np.array([(170, y-3), (179, y-3), (178, y+3), (175, y+6), (171, y+3)])
            cv2.fillConvexPoly(quadro, vertices, (230, 224, 50))
    return quadro


class HudEsquadraoTest(unittest.TestCase):
    def test_tres_eliminados_em_escalas_diferentes(self):
        quadro = tela_companheiros(["eliminado"] * 3)
        for tamanho in ((1440, 860), (1920, 1080), (1440, 900), (1280, 720), (960, 540)):
            with self.subTest(tamanho=tamanho):
                self.assertEqual(ler_esquadrao(cv2.resize(quadro, tamanho)), LeituraEsquadrao(3, 0, 3))

    def test_distingue_derrubado_vivo_sem_escudo_e_eliminado(self):
        quadro = tela_companheiros(["eliminado", "derrubado", "vivo"])
        self.assertEqual(ler_esquadrao(quadro), LeituraEsquadrao(3, 2, 1))

    def test_nao_conclui_eliminacao_com_um_so_sinal_ou_com_icone_de_escudo(self):
        quadro = tela_companheiros(["sem_cartao", "cartao_sem_nome_vermelho", "escudo"])
        self.assertEqual(ler_esquadrao(quadro), LeituraEsquadrao(3, 0, 0))

    def test_ausencia_de_hud_e_barra_propria_sao_inconclusivas(self):
        quadro = tela_companheiros([])
        quadro[790:820, 43:265] = (40, 190, 65)
        self.assertEqual(ler_esquadrao(quadro), LeituraEsquadrao())
        self.assertEqual(ler_esquadrao(quadro[:90, :160]), LeituraEsquadrao())

    def test_pre_jogo_com_contador_variavel_e_fundo_diferente(self):
        caminho = Path(__file__).resolve().parents[1] / "templates" / "aguardando_jogadores.png"
        letras = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
        for segundos, cor, tamanho in [(48, (20, 80, 90), (1440, 900)), (3, (103, 39, 19), (960, 540))]:
            with self.subTest(segundos=segundos):
                quadro = np.full((860, 1440, 3), cor, np.uint8)
                cv2.putText(quadro, f"{segundos} s", (695, 89), 0, .82, (240, 240, 240), 2)
                self.assertFalse(aguardando_jogadores(quadro))
                h, w = letras.shape
                quadro[99:99+h, 632:632+w] += letras[:, :, None]
                self.assertTrue(aguardando_jogadores(cv2.resize(quadro, tamanho)))
