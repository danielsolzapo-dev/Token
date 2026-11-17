from dataclasses import replace
import json
import os
from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app import Painel, carregar_config, configurar_logger, monitorar, salvar_config
from logica_autofarm import (
    Acao, Alvo, Config, Detector, DetectorBau, Fluxo, ObservadorBau, TEMPLATES,
)
from notificacoes import NIM_ADD, NIM_DELETE, NIM_MODIFY, NotificadorWindows
from texto_tela import Linha, Reconhecedor, identificar
from windows_game import Janela, Windows


class TelaSimulada:
    config = Config(minutos_partida=0.1, timeout_lobby=8, anti_afk=False)
    nome = None
    dialogo_ambiguo = False
    inventario = False

    def procurar(self, _, nomes, limiar=None):
        nome = "inventario" if self.inventario else self.nome
        if nome in nomes:
            return Alvo(nome, 1, (10, 10, 20, 20), 1)
        return None

    def detectar(self, quadro):
        return self.procurar(quadro, ("jogar", "continuar"))

    def ler_contexto(self, quadro, tipo):
        return self.procurar(quadro, (tipo,))

    def fora_de_partida(self, quadro):
        return self.procurar(quadro, ("lobby_jogar", "voltar_lobby")) is not None


class FluxoTest(unittest.TestCase):
    def setUp(self):
        self.detector = TelaSimulada()
        self.fluxo = Fluxo(self.detector)
        self.quadro = np.zeros((540, 960, 3), dtype=np.uint8)

    def passo(self, instante, nome=None, *, enviado=True, **kwargs):
        self.detector.nome = nome
        acao = self.fluxo.passo(self.quadro, instante, **kwargs)
        if acao and acao.tipo == "clicar":
            hud_visivel = kwargs.get("hud_visivel", kwargs.get("partida", False))
            self.fluxo.registrar_clique(acao, enviado, instante, hud_visivel=hud_visivel)
        return acao

    def iniciar_clique(self, nome, **kwargs):
        self.assertIsNone(self.passo(0, nome, **kwargs))
        clique = self.passo(0.2, nome, **kwargs)
        self.assertEqual(clique.alvo.nome, nome)
        self.assertEqual(clique.tentativa, 0)

    def test_limite_de_tentativas_mesmo_com_perda_de_foco(self):
        for nome in ("jogar", "continuar", "lobby_jogar"):
            with self.subTest(nome=nome):
                self.fluxo = Fluxo(self.detector)
                self.iniciar_clique(nome)
                self.assertIsNone(self.passo(1, nome, foco=False))
                self.assertEqual(self.passo(2, nome).tentativa, 1)
                self.assertEqual(self.passo(4, nome).tentativa, 2)
                self.assertEqual(self.passo(6, nome).tipo, "clique_ignorado")
                self.assertIsNone(self.passo(60, nome))
                self.assertEqual(self.fluxo.partidas, 0)
                self.assertIsNone(self.fluxo.inicio_partida)

    def test_hud_ao_abrir_app_nao_inicia_cronometro_ou_anti_afk(self):
                self.habilitar_movimento()
                self.fluxo.inicio_partida = None
                for instante in (0, 0.3, 0.6, 1.0, 1.5):
                    self.assertIsNone(self.passo(instante, partida=True))
                self.assertIsNone(self.fluxo.inicio_partida)

    def test_onibus_antigo_e_falha_isolada_de_leitura_nao_confirmam_partida(self):
                self.assertIsNone(self.passo(0, "jogar", no_onibus=True))
                self.assertEqual(self.passo(0.2, "jogar", no_onibus=True).tentativa, 0)
                self.passo(2)
                self.passo(2.2)
                for instante in (2.4, 2.6, 2.8, 3.0):
                    self.assertIsNone(self.passo(instante, no_onibus=True))
                self.assertEqual(self.fluxo.partidas, 0)
                self.assertIsNone(self.fluxo.inicio_partida)
                self.assertIsNone(self.passo(3.2))
                self.assertIsNone(self.passo(3.4, partida=True))
                self.assertIsNone(self.passo(3.6))
                self.assertEqual(self.fluxo.partidas, 0)
                for instante in (4.0, 4.2, 4.4, 4.7):
                    self.assertIsNone(self.passo(instante))
                for instante in (4.9, 5.1, 5.3):
                    acao = self.passo(instante, partida=True)
                self.assertEqual(acao.tipo, "partida_confirmada")

    def test_botao_ausente_sem_fila_nao_conta(self):
        self.iniciar_clique("jogar")
        self.assertIsNone(self.passo(2))
        self.assertEqual(self.passo(2.2).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(4))
        self.assertEqual(self.passo(11).tipo, "partida_nao_confirmada")
        self.assertEqual(self.fluxo.partidas, 0)
        self.assertIsNone(self.fluxo.inicio_partida)

    def test_clique_aceito_e_perda_de_foco_conta_uma_unica_tentativa(self):
        self.assertIsNone(self.passo(0, "jogar"))
        acao = self.passo(0.2, "jogar")
        self.assertEqual(acao.tentativa, 0)
        self.assertEqual(self.fluxo._tentativas, 1)
        self.assertIsNone(self.passo(0.4, "jogar", foco=False))
        self.assertEqual(self.fluxo._tentativas, 1)
        nova = self.passo(2.0, "jogar")
        self.assertEqual(nova.tentativa, 1)
        self.assertEqual(self.fluxo._tentativas, 2)

    def test_fila_contada_uma_vez_cronometro_so_no_jogo(self):
        self.iniciar_clique("lobby_jogar")
        self.assertIsNone(self.passo(2))
        self.assertEqual(self.passo(2.2).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(2.4, "fila"))
        self.assertEqual(self.passo(3.5, "fila").tipo, "fila_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)
        self.assertIsNone(self.fluxo.inicio_partida)
        for instante in (4.0, 4.2, 4.4, 4.7):
            self.assertIsNone(self.passo(instante))
        for instante in (4.9, 5.1, 5.3):
            acao = self.passo(instante, partida=True)
        self.assertEqual(acao.tipo, "partida_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)
        self.assertEqual(self.fluxo.inicio_partida, 5.3)

    def confirmar_fila_e_expirar(self):
        self.iniciar_clique("lobby_jogar")
        self.passo(2)
        self.passo(2.2)
        self.passo(2.4, "fila")
        self.assertEqual(self.passo(3.5, "fila").tipo, "fila_confirmada")
        self.assertIsNone(self.passo(5, "lobby_jogar"))
        self.assertEqual(self.passo(10.3, "lobby_jogar").tipo, "fila_sem_partida")
        self.assertIsNone(self.passo(10.6, "lobby_jogar"))
        self.assertIsNone(self.passo(11, "lobby_jogar"))
        self.assertEqual(self.fluxo.partidas, 1)

    def test_fila_confirmada_ainda_aceita_partida_apos_timeout(self):
        self.confirmar_fila_e_expirar()
        for instante in (11.2, 11.4, 11.6):
            self.assertIsNone(self.passo(instante))
        for instante in (11.8, 12.0, 12.2):
            acao = self.passo(instante, partida=True)
        self.assertEqual(acao.tipo, "partida_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)

    def test_nova_fila_exige_cancelamento_explicito_apos_timeout(self):
        self.confirmar_fila_e_expirar()
        self.assertIsNone(self.passo(12.2, "fila_cancelada"))
        self.assertEqual(self.passo(13.4, "fila_cancelada").tipo, "fila_cancelada")
        self.assertIsNone(self.passo(14, "lobby_jogar"))
        self.assertEqual(self.passo(14.2, "lobby_jogar").alvo.nome, "lobby_jogar")
        self.assertEqual(self.fluxo.partidas, 1)

    def test_hud_confirma_sem_ocr_de_fila(self):
        self.iniciar_clique("jogar")
        self.passo(2)
        self.passo(2.2)
        for instante in (2.4, 2.6, 2.8, 3.0):
            self.assertIsNone(self.passo(instante))
        for instante in (3.2, 3.4, 3.6):
            acao = self.passo(instante, partida=True)
        self.assertEqual(acao.tipo, "partida_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)

    def test_hud_antigo_persistente_nao_conta_ou_inicia_cronometro(self):
        self.assertIsNone(self.passo(0, "jogar", partida=True))
        self.assertEqual(self.passo(0.2, "jogar", partida=True).tipo, "clicar")
        self.assertIsNone(self.passo(2, partida=True))
        self.assertEqual(self.passo(2.2, partida=True).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(3, partida=True))
        self.assertIsNone(self.passo(3.2, partida=True))
        self.assertEqual(self.fluxo.partidas, 0)
        self.assertIsNone(self.fluxo.inicio_partida)
        self.assertEqual(self.passo(11, partida=True).tipo, "partida_nao_confirmada")
        self.assertIsNone(self.passo(11.2, partida=True))
        self.assertIsNone(self.fluxo.inicio_partida)

    def test_hud_so_confirma_depois_de_intervalo_sem_sinais(self):
        self.iniciar_clique("jogar", partida=True)
        self.passo(2, partida=True)
        self.passo(2.2, partida=True)
        self.passo(3, partida=True)
        self.passo(3.2, partida=True)
        self.assertEqual(self.fluxo.partidas, 0)
        for instante in (4.0, 4.2, 4.4, 4.7):
            self.passo(instante)
        for instante in (4.9, 5.1, 5.3):
            acao = self.passo(instante, partida=True)
        self.assertEqual(acao.tipo, "partida_confirmada")

    def test_hud_novo_estavel_apos_onibus_presente_ativa_anti_afk(self):
        self.fluxo.config = replace(self.fluxo.config, anti_afk=True, sair_por_tempo=False)
        self.iniciar_clique("jogar", no_onibus=True)
        self.passo(2)
        self.passo(2.2)
        for instante in (2.4, 2.6, 2.8, 3.0):
            self.assertIsNone(self.passo(instante, no_onibus=True))
        for instante in (3.2, 3.4, 3.6):
            acao = self.passo(instante, partida=True, no_onibus=True)
        self.assertEqual(acao.tipo, "partida_confirmada")
        self.assertEqual(self.fluxo.inicio_partida, 3.6)
        self.assertEqual(self.fluxo.partidas, 1)
        self.assertIsNone(self.passo(3.8, partida=True))
        self.assertEqual(self.passo(4.0, partida=True).tipo, "movimento")

    def test_pronto_substitui_jogar_sem_esperar_timeout(self):
        self.iniciar_clique("lobby_jogar")
        self.passo(2, "lobby_pronto")
        aviso = self.passo(2.2, "lobby_pronto")
        self.assertEqual(aviso.tipo, "aguardando_fila")
        self.assertIsNone(self.passo(2.5, "lobby_pronto"))
        self.assertIsNone(self.passo(2.7, "lobby_pronto"))
        self.passo(5, "lobby_jogar")
        self.passo(5.2, "lobby_jogar")
        self.assertIsNone(self.passo(5.5, "lobby_jogar"))
        self.assertIsNone(self.passo(5.7, "lobby_jogar"))
        self.assertEqual(self.fluxo.partidas, 0)
        self.assertEqual(self.passo(10.3, "lobby_jogar").tipo, "partida_nao_confirmada")
        self.assertIsNone(self.passo(10.6, "lobby_jogar"))
        self.fluxo.rearmar_fila()
        self.assertIsNone(self.passo(11.0, "lobby_jogar"))
        self.assertEqual(self.passo(11.2, "lobby_jogar").alvo.nome, "lobby_jogar")

    def test_saida_por_tempo_e_confirmacao(self):
        self.fluxo._iniciar_partida(0)
        self.assertIsNone(self.passo(0, partida=True))
        self.assertEqual(self.passo(6, partida=True).tipo, "esc")
        self.assertIsNone(self.passo(7.1, "voltar_lobby"))
        self.assertEqual(self.passo(7.4, "voltar_lobby").alvo.nome, "voltar_lobby")
        self.assertIsNone(self.passo(9, "confirmar_sair"))
        self.assertEqual(self.passo(9.2, "confirmar_sair").tipo, "clique_confirmado")
        self.assertIsNone(self.passo(9.5, "confirmar_sair"))
        self.assertEqual(self.passo(9.8, "confirmar_sair").alvo.nome, "confirmar_sair")
        self.assertEqual(self.fluxo.partidas, 0)

    def test_ambiguidade_impede_repetir_clique_no_menu_de_fundo(self):
        self.passo(0, partida=True)
        self.fluxo.inicio_partida = 0
        self.passo(6, partida=True)
        self.passo(7.1, "voltar_lobby")
        self.assertEqual(self.passo(7.4, "voltar_lobby").tipo, "clicar")
        self.detector.dialogo_ambiguo = True
        self.assertIsNone(self.passo(9, "voltar_lobby"))
        self.assertIsNone(self.passo(11, "voltar_lobby"))
        self.detector.dialogo_ambiguo = False
        self.assertEqual(self.passo(13, "voltar_lobby").tentativa, 1)

    def test_tela_desconhecida_gera_aviso_e_busca_continua(self):
        self.assertIsNone(self.passo(0))
        self.assertEqual(self.passo(8).tipo, "tela_nao_reconhecida")
        self.assertIsNone(self.passo(9))
        self.assertIsNone(self.passo(10, "jogar"))
        self.assertEqual(self.passo(10.2, "jogar").alvo.nome, "jogar")

    def habilitar_movimento(self):
        self.fluxo.config = replace(self.fluxo.config, anti_afk=True, sair_por_tempo=False)
        self.fluxo._iniciar_partida(0)

    def test_icone_do_menu_isolado_nao_bloqueia_caminhada(self):
        self.habilitar_movimento()
        self.detector.fora_de_partida = lambda _: True
        self.assertIsNone(self.passo(0, "menu_aba", partida=True))
        acao = self.passo(0.3, "menu_aba", partida=True)
        self.assertEqual(acao.tipo, "movimento")
        self.assertEqual(acao.passos, (("teclas", (17,), 0.8),))

    def test_menu_de_saida_bloqueia_caminhada(self):
        self.habilitar_movimento()
        for instante in (0, 0.3):
            self.assertEqual(self.passo(instante, "voltar_lobby", partida=True, cursor=True).tipo,
                             "movimento_menu")
        self.assertIsNone(self.passo(0.6, partida=True))
        self.assertEqual(self.passo(0.9, partida=True).tipo, "movimento")

    def test_anti_afk_bloqueado_no_onibus_e_no_inventario(self):
        self.habilitar_movimento()
        self.assertIsNone(self.passo(0, partida=True, no_onibus=True))
        self.detector.inventario = True
        self.assertIsNone(self.passo(0.3, partida=True, cursor=True))
        self.assertEqual(self.passo(0.6, partida=True, foco=False), None)

    def test_anti_afk_reenvia_caminhada_mesmo_se_plano_so_girar_camera(self):
        self.habilitar_movimento()
        self.passo(0, partida=True)
        self.assertEqual(self.passo(0.3, partida=True).passos, (("teclas", (17,), 0.8),))
        with patch("logica_autofarm.plano_anti_afk", return_value=([("mouse", 90, 0, 0.2)], (0, 0.8, 0))):
            self.assertEqual(self.passo(2, partida=True).passos, (("mouse", 90, 0, 0.2),))
            self.assertEqual(self.passo(6, partida=True).passos, (("teclas", (17,), 0.8),))

    def test_perda_de_foco_exige_hud_reconfirmado_para_mover(self):
        self.habilitar_movimento()
        self.assertIsNone(self.passo(0, partida=True))
        self.assertIsNone(self.passo(0.3, partida=True, foco=False))
        self.assertIsNone(self.passo(0.6, partida=True))
        self.assertEqual(self.passo(0.9, partida=True).tipo, "movimento")


class DetectorTest(unittest.TestCase):
    def test_amarelo_sozinho_nao_autoriza_clique(self):
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        quadro[225:270, 690:890] = (0, 255, 255)
        quadro[243:252, 730:850] = 0
        class LeitorSemRotulo:
            def ler(self, quadro, tipo):
                self.tipo = tipo
                return identificar([Linha("Avançar", (20, 10, 80, 20))], *quadro.shape[1::-1], tipo)

        leitor = LeitorSemRotulo()
        detector = Detector(leitor=leitor)
        self.assertIsNotNone(detector.buscar_por_cor(quadro))
        self.assertIsNone(detector.detectar(quadro))
        self.assertEqual(leitor.tipo, "jogar")
        self.assertIsNotNone(identificar([Linha("Jogar novamente", (20, 10, 120, 20))], 200, 45, "jogar"))

    def test_modal_exige_contexto_e_confirmacao(self):
        titulo = Linha("Deseja voltar ao lobby?", (320, 180, 310, 30))
        sim = Linha("Confirmar", (295, 320, 140, 30))
        nao = Linha("Cancelar", (540, 320, 140, 30))
        self.assertIs(identificar([titulo, sim, nao], 960, 540, "confirmar_sair"), sim)
        self.assertIsNone(identificar([sim, nao], 960, 540, "confirmar_sair"))
        self.assertIsNone(identificar([titulo, sim], 960, 540, "confirmar_sair"))

    def test_modal_prefere_par_de_botoes_alinhado_ao_titulo(self):
        linha1 = Linha("RETURN TO", (390, 170, 180, 25))
        linha2 = Linha("LOBBY?", (425, 200, 110, 25))
        fundo = Linha("RETURN TO LOBBY", (210, 255, 190, 25))
        confirmar = Linha("CONFIRM", (305, 310, 110, 25))
        cancelar = Linha("CANCEL", (555, 313, 110, 25))
        linhas = [linha1, linha2, fundo, confirmar, cancelar]
        self.assertIs(identificar(linhas, 960, 540, "confirmar_sair"), confirmar)
        self.assertIsNone(identificar([linha1, linha2, fundo, cancelar], 960, 540, "confirmar_sair"))

    def test_dois_dialogos_plausiveis_nao_tem_alvo(self):
        linhas = [
            Linha("LEAVE MATCH?", (220, 174, 165, 24)),
            Linha("CONFIRM", (223, 302, 65, 24)), Linha("CANCEL", (318, 302, 65, 24)),
            Linha("RETURN TO LOBBY?", (514, 174, 224, 24)),
            Linha("CONFIRM", (536, 302, 65, 24)), Linha("CANCEL", (654, 302, 65, 24)),
        ]
        self.assertIsNone(identificar(linhas, 960, 540, "confirmar_sair"))
        linhas[-2] = Linha("RETURN TO LOBBY", (500, 302, 137, 24))
        self.assertIsNone(identificar(linhas, 960, 540, "confirmar_sair"))

    def test_modal_empilhado_nos_dois_ordenamentos(self):
        titulo = Linha("RETURN TO LOBBY?", (380, 170, 200, 25))
        for y_sim, y_nao in ((260, 320), (320, 260)):
            sim = Linha("CONFIRM", (430, y_sim, 100, 24))
            nao = Linha("CANCEL", (435, y_nao, 90, 24))
            self.assertEqual(identificar([titulo, sim, nao], 960, 540, "confirmar_sair"), sim)

    def test_cancelar_pareamento_nao_e_confirmacao_de_cancelamento(self):
        botao = Linha("CANCELAR PAREAMENTO", (400, 430, 180, 20))
        aviso = Linha("PAREAMENTO CANCELADO", (390, 430, 190, 20))
        self.assertIsNone(identificar([botao], 960, 540, "fila_cancelada"))
        self.assertIs(identificar([aviso], 960, 540, "fila_cancelada"), aviso)

    def test_reune_palavras_proximas_sem_unir_controles_distantes(self):
        jogar = Linha("JOGAR", (15, 10, 60, 23))
        novamente = Linha("NOVAMENTE", (95, 10, 118, 23))
        unido = identificar([jogar, novamente], 250, 50, "jogar")
        self.assertEqual(unido.caixa, (15, 10, 198, 23))
        separado = Linha("NOVAMENTE", (135, 10, 110, 23))
        self.assertIsNone(identificar([jogar, separado], 250, 50, "jogar"))


class DetectorBauTest(unittest.TestCase):
    @staticmethod
    def referencia_sintetica():
        imagem = np.full((48, 56, 3), (38, 29, 24), dtype=np.uint8)
        cv2.rectangle(imagem, (5, 9), (50, 39), (10, 115, 218), -1)
        cv2.rectangle(imagem, (9, 14), (46, 34), (24, 177, 245), 2)
        cv2.line(imagem, (8, 24), (48, 24), (55, 215, 255), 3)
        cv2.circle(imagem, (28, 29), 3, (20, 45, 80), -1)
        return imagem

    def test_detecta_referencia_visivel_e_rejeita_imagem_diferente(self):
        referencia = self.referencia_sintetica()
        detector = DetectorBau(imagem=referencia)
        quadro = np.zeros((180, 260, 3), dtype=np.uint8)
        quadro[71:119, 102:158] = referencia
        alvo = detector.detectar(quadro)
        self.assertIsNotNone(alvo)
        self.assertEqual(alvo.nome, "bau")
        self.assertEqual(alvo.metodo, "referencia")
        self.assertAlmostEqual(alvo.centro[0], 130, delta=3)
        self.assertAlmostEqual(alvo.centro[1], 95, delta=3)
        diferente = np.zeros_like(quadro)
        cv2.rectangle(diferente, (102, 71), (158, 119), (0, 230, 0), -1)
        self.assertIsNone(detector.detectar(diferente))

    def test_recusa_referencia_sem_detalhes_ou_grande_demais(self):
        with self.assertRaisesRegex(ValueError, "detalhes"):
            DetectorBau(imagem=np.zeros((40, 40, 3), dtype=np.uint8))
        with self.assertRaisesRegex(ValueError, "20 a 512"):
            DetectorBau(imagem=self.referencia_sintetica().repeat(12, axis=0))

    def test_aviso_exige_deteccao_estavel_e_nao_repete_ate_sumir(self):
        observador = ObservadorBau()
        alvo = Alvo("bau", 0.98, (80, 60, 50, 40), 1.0, "referencia")
        self.assertFalse(observador.observar(alvo, 540))
        self.assertTrue(observador.observar(alvo, 540))
        self.assertFalse(observador.observar(alvo, 540))
        self.assertFalse(observador.observar(None, 540))
        self.assertFalse(observador.observar(None, 540))
        self.assertFalse(observador.observar(alvo, 540))
        self.assertTrue(observador.observar(alvo, 540))


MODELOS = Path(__file__).resolve().parents[1] / "modelos"
OCR_DISPONIVEL = all((MODELOS / nome).is_file() for nome in (
    "PP-OCRv6_det_small.onnx", "latin_PP-OCRv5_rec_mobile.onnx",
))


@unittest.skipUnless(OCR_DISPONIVEL, "modelos OCR não preparados")
class OcrRealTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.leitor = Reconhecedor()
        cls.fonte_titulo = ImageFont.truetype(
            str(Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts" / "arialbd.ttf"), 32
        )
        cls.fonte_botao = ImageFont.truetype(
            str(Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts" / "arialbd.ttf"), 24
        )

    @staticmethod
    def quadro(imagem):
        return cv2.cvtColor(np.asarray(imagem), cv2.COLOR_RGB2BGR)

    def test_ocr_real_associa_titulo_em_linhas_a_botoes_lado_a_lado(self):
        imagem = Image.new("RGB", (960, 540), "#182638")
        desenho = ImageDraw.Draw(imagem)
        desenho.text((480, 165), "RETURN TO", font=self.fonte_titulo, anchor="mm", fill="white")
        desenho.text((480, 205), "LOBBY?", font=self.fonte_titulo, anchor="mm", fill="white")
        desenho.text((350, 325), "CANCEL", font=self.fonte_botao, anchor="mm", fill="white")
        desenho.text((610, 325), "CONFIRM", font=self.fonte_botao, anchor="mm", fill="white")
        desenho.text((480, 260), "RETURN TO LOBBY", font=self.fonte_botao, anchor="mm", fill="#526174")
        linha = self.leitor.ler(self.quadro(imagem), "confirmar_sair")
        self.assertIsNotNone(linha)
        self.assertGreater(linha.centro[0], 500)
        self.assertLess(linha.centro[1], 370)

    def test_ocr_real_aceita_botoes_empilhados_em_qualquer_ordem(self):
        for primeiro, segundo in (("CANCEL", "CONFIRM"), ("CONFIRM", "CANCEL")):
            imagem = Image.new("RGB", (960, 540), "#182638")
            desenho = ImageDraw.Draw(imagem)
            desenho.text((480, 175), "RETURN TO LOBBY?", font=self.fonte_titulo,
                         anchor="mm", fill="white")
            desenho.text((480, 290), primeiro, font=self.fonte_botao, anchor="mm", fill="white")
            desenho.text((480, 350), segundo, font=self.fonte_botao, anchor="mm", fill="white")
            linha = self.leitor.ler(self.quadro(imagem), "confirmar_sair")
            self.assertIsNotNone(linha)
            y_confirmar = 290 if primeiro == "CONFIRM" else 350
            self.assertAlmostEqual(linha.centro[1], y_confirmar, delta=18)

    def test_ocr_real_recusa_dialogos_simultaneos(self):
        imagem = Image.new("RGB", (960, 540), "#182638")
        desenho = ImageDraw.Draw(imagem)
        for centro, titulo in ((310, "LEAVE MATCH?"), (635, "RETURN TO LOBBY?")):
            desenho.text((centro, 180), titulo, font=self.fonte_titulo, anchor="mm", fill="white")
            desenho.text((centro - 67, 315), "CONFIRM", font=self.fonte_botao, anchor="mm", fill="white")
            desenho.text((centro + 67, 315), "CANCEL", font=self.fonte_botao, anchor="mm", fill="white")
        detector = Detector(leitor=self.leitor)
        self.assertIsNone(detector.ler_contexto(self.quadro(imagem), "confirmar_sair"))
        self.assertTrue(detector.dialogo_ambiguo)

    def test_ocr_real_rejeita_cor_sem_rotulo_e_nao_funde_dois_controles(self):
        imagem = Image.new("RGB", (960, 540), "#182638")
        desenho = ImageDraw.Draw(imagem)
        desenho.rectangle((600, 220, 850, 270), fill="#ffff00")
        detector = Detector(leitor=self.leitor)
        self.assertIsNone(detector.detectar(self.quadro(imagem)))

        dois = Image.new("RGB", (960, 540), "#182638")
        desenho = ImageDraw.Draw(dois)
        for inicio, fim, rotulo in ((600, 770, "JOGAR"), (778, 948, "NOVAMENTE")):
            desenho.rectangle((inicio, 220, fim, 270), fill="#ffff00")
            desenho.text(((inicio + fim) // 2, 245), rotulo,
                         font=self.fonte_botao, anchor="mm", fill="#101010")
        self.assertIsNone(detector.detectar(self.quadro(dois)))

    def test_ocr_real_reconhece_jogar_novamente_dentro_do_alvo(self):
        imagem = Image.new("RGB", (960, 540), "#182638")
        desenho = ImageDraw.Draw(imagem)
        desenho.rectangle((600, 220, 850, 270), fill="#ffff00")
        desenho.text((690, 245), "JOGAR", font=self.fonte_botao, anchor="mm", fill="#101010")
        desenho.text((780, 245), "NOVAMENTE", font=self.fonte_botao, anchor="mm", fill="#101010")
        alvo = Detector(leitor=self.leitor).detectar(self.quadro(imagem))
        self.assertIsNotNone(alvo)
        self.assertEqual(alvo.metodo, "cor+OCR")
        x, y, largura, altura = alvo.caixa
        self.assertGreaterEqual(x, 600)
        centro_x, centro_y = alvo.centro
        self.assertLess(centro_x, 850)
        self.assertGreaterEqual(centro_y, 220)
        self.assertLess(centro_y, 270)


class PainelTest(unittest.TestCase):
    def test_configurar_referencia_salva_recorte_validado_localmente(self):
        painel = object.__new__(Painel)
        painel.janela = None
        mensagens = []
        painel.atividade = SimpleNamespace(set=mensagens.append)
        referencia = DetectorBauTest.referencia_sintetica()

        with TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "referencia_bau.png"
            with patch("app.CHEST_REFERENCE", caminho), \
                    patch("app.filedialog.askopenfilename", return_value="recorte.png"), \
                    patch("app.detectar_arquivo", return_value=referencia):
                painel.selecionar_referencia_bau()
            salva = cv2.imdecode(np.frombuffer(caminho.read_bytes(), np.uint8), cv2.IMREAD_COLOR)

        self.assertTrue(np.array_equal(salva, referencia))
        self.assertIn("Referência salva", mensagens[0])

    def test_exporta_resumo_json_escolhido_pelo_usuario(self):
        painel = object.__new__(Painel)
        painel.janela = None
        painel.resumo_sessao = {"partidas_iniciadas": 2, "erros": []}
        mensagens = []
        painel.atividade = SimpleNamespace(set=mensagens.append)
        with TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "resumo.json"
            with patch("app.filedialog.asksaveasfilename", return_value=str(caminho)):
                painel.exportar_resumo()
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(dados["partidas_iniciadas"], 2)
        self.assertIn("Resumo exportado", mensagens[0])

    def test_notificacoes_delegam_para_a_api_do_windows(self):
        chamadas = []

        class FakeNotifier:
            def __init__(self, hwnd):
                chamadas.append(("criar", hwnd))

            def notificar(self, titulo, mensagem):
                chamadas.append((titulo, mensagem))

        painel = object.__new__(Painel)
        painel.fechando = False
        painel.opcoes = {"notificacoes": SimpleNamespace(get=lambda: True)}
        painel.notificador = None
        painel.janela = SimpleNamespace(winfo_id=lambda: 42)
        with patch("app.NotificadorWindows", FakeNotifier):
            painel.notificar_windows("Partida reconhecida", "Monitor ativo.")
        self.assertEqual(chamadas, [
            ("criar", 42), ("Partida reconhecida", "Monitor ativo."),
        ])

    def test_config_persiste_preferencia_de_notificacoes(self):
        config = replace(Config(), notificacoes=False, capturas_diagnostico=True)
        with TemporaryDirectory() as diretorio:
            with patch("app.CONFIG", Path(diretorio) / "ajustes.json"):
                salvar_config(config)
                carregada = carregar_config()
                self.assertFalse(carregada.notificacoes)
                self.assertTrue(carregada.capturas_diagnostico)

    def test_testar_imagem_exibe_metadados_sem_enviar_entrada(self):
        chamadas = []
        painel = object.__new__(Painel)
        painel.janela = None
        painel.windows = SimpleNamespace(executar=lambda *args: self.fail("não deve enviar entrada"))
        painel.ler_opcoes = lambda: Config()
        painel.mostrar_teste = lambda quadro, texto: chamadas.append((quadro.copy(), texto))

        class DetectorSimulado:
            dialogo_ambiguo = False

            def __init__(self, config):
                pass

            def ler_contexto(self, quadro, tipo):
                return None

            def detectar(self, quadro):
                return Alvo("jogar", 0.91, (10, 10, 40, 20), 1.0)

        with patch("app.filedialog.askopenfilename", return_value="captura.png"), \
                patch("app.detectar_arquivo", return_value=np.zeros((80, 100, 3), dtype=np.uint8)), \
                patch("app.Detector", DetectorSimulado):
            painel.testar()

        quadro, texto = chamadas[0]
        self.assertIn("centro (30, 20)", texto)
        self.assertIn("template", texto)
        self.assertIn("score 91%", texto)
        self.assertTrue(np.array_equal(quadro[20, 30], (0, 0, 255)))

    def test_testar_imagem_detecta_bau_sem_enviar_entrada(self):
        chamadas = []
        painel = object.__new__(Painel)
        painel.janela = None
        painel.windows = SimpleNamespace(executar=lambda *args: self.fail("não deve enviar entrada"))
        painel.ler_opcoes = lambda: Config()
        painel.mostrar_teste = lambda quadro, texto: chamadas.append((quadro.copy(), texto))
        referencia = DetectorBauTest.referencia_sintetica()
        captura = np.zeros((180, 260, 3), dtype=np.uint8)
        captura[71:119, 102:158] = referencia

        class DetectorSimulado:
            dialogo_ambiguo = False

            def __init__(self, config):
                pass

            def ler_contexto(self, quadro, tipo):
                return None

            def detectar(self, quadro):
                return None

            def procurar(self, quadro, nomes):
                return None

        with TemporaryDirectory() as diretorio:
            caminho = Path(diretorio) / "referencia_bau.png"
            self.assertTrue(cv2.imwrite(str(caminho), referencia))
            with patch("app.CHEST_REFERENCE", caminho), \
                    patch("app.filedialog.askopenfilename", return_value="captura.png"), \
                    patch("app.detectar_arquivo", return_value=captura.copy()), \
                    patch("app.Detector", DetectorSimulado):
                painel.testar()

        quadro, texto = chamadas[0]
        self.assertIn("Baú visível", texto)
        self.assertIn("referência de imagem", texto)
        self.assertTrue(np.array_equal(quadro[95, 130], (0, 0, 255)))


class MonitorTest(unittest.TestCase):
    def test_capturas_de_diagnostico_sao_opt_in(self):
        self.assertFalse(Config().capturas_diagnostico)

    def test_cliques_recusados_pelo_windows_nao_consomem_tentativas(self):
        detector = TelaSimulada()
        detector.nome = "jogar"
        detector.config = replace(detector.config, capturas_diagnostico=True)
        detector.templates = dict.fromkeys(TEMPLATES)
        detector.em_partida = lambda _: False
        fluxo = Fluxo(detector)
        parar = Event()
        eventos = SimpleQueue()
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        tentativas = []
        instantes = iter(range(30))

        def executar(janela, acao, sinal):
            tentativas.append(acao.tentativa)
            if len(tentativas) == 4:
                sinal.set()
                raise OSError("falha simulada")
            return False

        windows = SimpleNamespace(
            fortnite_em_foco=lambda: 42, capturar=lambda _: quadro.copy(),
            disponivel=lambda *_: True, cursor_visivel=lambda: False, executar=executar,
            aguardar=lambda _: None,
        )
        with TemporaryDirectory() as diretorio:
            logger = configurar_logger(Path(diretorio) / "autofarm.log")
            with patch("app.configurar_logger", return_value=logger), \
                    patch("app.DEBUG_DIR", Path(diretorio) / "debug"), \
                    patch("app.time", SimpleNamespace(monotonic=lambda: next(instantes))):
                monitorar(windows, fluxo, eventos, parar)
            capturas = list((Path(diretorio) / "debug").glob("*_entrada_recusada.jpg"))
            for handler in logger.handlers:
                handler.flush()
            texto = (Path(diretorio) / "autofarm.log").read_text(encoding="utf-8")
            for handler in logger.handlers:
                logger.removeHandler(handler)
                handler.close()
        eventos_lidos = []
        while not eventos.empty():
            eventos_lidos.append(eventos.get())
        self.assertEqual(tentativas, [0, 0, 0, 0])
        self.assertEqual(fluxo.partidas, 0)
        self.assertIn("Ação não concluída", texto)
        self.assertIn("motivo=entrada_recusada", texto)
        self.assertIn("Jogar Novamente (template 1.00)", texto)
        self.assertIn("centro_janela=(20,20)", texto)
        self.assertIn("via SendInput", texto)
        self.assertIn("Captura salva em", texto)
        self.assertTrue(capturas)
        self.assertIn("Erro ao executar ação", texto)
        self.assertIn(("erro", "falha simulada"), eventos_lidos)
        resumo = next(valor for evento, valor in eventos_lidos if evento == "relatorio")
        self.assertEqual(len(resumo["erros"]), 1)
        self.assertEqual(resumo["falhas_de_entrada"], 4)

    def test_resumo_e_notificacoes_registram_inicio_e_retorno_ao_lobby(self):
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        detector = SimpleNamespace(
            templates=dict.fromkeys(TEMPLATES), dialogo_ambiguo=False,
            em_partida=lambda _: True, procurar=lambda *_args, **_kwargs: None,
        )

        class FluxoSimulado:
            def __init__(self):
                self.config = Config(anti_afk=False, notificacoes=True)
                self.detector = detector
                self.inicio_partida = None
                self.partidas = 0
                self.ciclo = 0

            def passo(self, *_args, **_kwargs):
                self.ciclo += 1
                if self.ciclo == 1:
                    self.partidas = 1
                    return Acao("fila_confirmada")
                if self.ciclo == 2:
                    self.inicio_partida = 1.0
                    return Acao("partida_confirmada")
                if self.ciclo == 3:
                    return Acao("esc")
                if self.ciclo == 4:
                    self.inicio_partida = None
                return None

            def pausar(self):
                pass

        fluxo = FluxoSimulado()
        parar = Event()
        eventos = SimpleQueue()
        ciclos = [0]

        def aguardar(_):
            ciclos[0] += 1
            if ciclos[0] == 4:
                parar.set()

        windows = SimpleNamespace(
            fortnite_em_foco=lambda: 42, capturar=lambda _: quadro.copy(),
            disponivel=lambda *_: True, cursor_visivel=lambda: False,
            executar=lambda *_: True, aguardar=aguardar,
        )
        with TemporaryDirectory() as diretorio:
            logger = configurar_logger(Path(diretorio) / "autofarm.log")
            with patch("app.configurar_logger", return_value=logger), \
                    patch("app.time", SimpleNamespace(monotonic=iter(range(20)).__next__)):
                monitorar(windows, fluxo, eventos, parar)
            texto = (Path(diretorio) / "autofarm.log").read_text(encoding="utf-8")
            for handler in logger.handlers:
                logger.removeHandler(handler)
                handler.close()
        eventos_lidos = []
        while not eventos.empty():
            eventos_lidos.append(eventos.get())
        resumo = next(valor for evento, valor in eventos_lidos if evento == "relatorio")
        notificacoes = [valor[0] for evento, valor in eventos_lidos if evento == "notificacao"]
        self.assertEqual(resumo["partidas_iniciadas"], 1)
        self.assertEqual(resumo["retornos_ao_lobby"], 1)
        self.assertIn("Fila confirmada.", texto)
        self.assertIn("Partida nova reconhecida. Cronômetro iniciado", texto)
        self.assertIn("Retorno ao lobby reconhecido.", texto)
        self.assertIn("Partida reconhecida", notificacoes)
        self.assertIn("Retorno ao lobby", notificacoes)


    def test_monitor_avisa_bau_estavel_sem_enviar_entrada(self):
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        detector_tela = SimpleNamespace(
            templates=dict.fromkeys(TEMPLATES), dialogo_ambiguo=False,
            em_partida=lambda _: True, procurar=lambda *_args, **_kwargs: None,
        )
        fluxo = SimpleNamespace(
            config=Config(anti_afk=False, avisar_bau=True), detector=detector_tela,
            inicio_partida=1.0, partidas=0, passo=lambda *_args, **_kwargs: None,
            pausar=lambda: None,
        )
        alvo = Alvo("bau", 0.97, (120, 80, 40, 35), 1.0, "referencia")

        class BaúsSimulados:
            def detectar(self, _):
                return alvo

        parar = Event()
        eventos = SimpleQueue()
        ciclos = [0]
        instantes = iter(range(20))

        def aguardar(_):
            ciclos[0] += 1
            if ciclos[0] == 4:
                parar.set()

        windows = SimpleNamespace(
            fortnite_em_foco=lambda: 42, capturar=lambda _: quadro.copy(),
            disponivel=lambda *_: True, cursor_visivel=lambda: False,
            executar=lambda *_: self.fail("detecção de baú não deve enviar entrada"),
            aguardar=aguardar,
        )
        with TemporaryDirectory() as diretorio:
            logger = configurar_logger(Path(diretorio) / "autofarm.log")
            with patch("app.configurar_logger", return_value=logger), \
                    patch("app.time", SimpleNamespace(monotonic=lambda: next(instantes))):
                monitorar(windows, fluxo, eventos, parar, BaúsSimulados())
            for handler in logger.handlers:
                handler.flush()
            texto = (Path(diretorio) / "autofarm.log").read_text(encoding="utf-8")
            for handler in logger.handlers:
                logger.removeHandler(handler)
                handler.close()
        eventos_lidos = []
        while not eventos.empty():
            eventos_lidos.append(eventos.get())
        avisos = [valor for evento, valor in eventos_lidos
                  if evento == "acao" and "Baú visível detectado" in valor]
        self.assertEqual(len(avisos), 1)
        self.assertIn("bau_visivel", texto)
        self.assertIn("Nenhuma entrada enviada", avisos[0])


class NotificadorTest(unittest.TestCase):
    def test_api_do_windows_registra_mostra_e_remove_notificacao(self):
        chamadas = []

        class Shell32:
            def Shell_NotifyIconW(self, operacao, estrutura):
                dados = estrutura._obj
                chamadas.append((
                    operacao, dados.uFlags, dados.szInfoTitle, dados.szInfo,
                ))
                return 1

        class User32:
            @staticmethod
            def LoadIconW(*_):
                return 1

        notificador = NotificadorWindows(42, Shell32(), User32())
        notificador.notificar("T" * 70, "M" * 300)
        notificador.fechar()
        self.assertEqual([chamada[0] for chamada in chamadas], [NIM_ADD, NIM_MODIFY, NIM_DELETE])
        self.assertEqual(len(chamadas[1][2]), 63)
        self.assertEqual(len(chamadas[1][3]), 255)


class WindowsTest(unittest.TestCase):
    def test_geometria_mudou_antes_da_entrada(self):
        janela = Janela(42, (0, 0, 100, 100))
        windows = object.__new__(Windows)
        windows.user = type("Api", (), {"GetForegroundWindow": lambda _: 42})()
        windows._area = lambda _: (0, 0, 200, 200)
        self.assertFalse(windows.executar(janela, Acao("esc"), Event()))

    def test_coordenada_fora_da_janela_nao_e_enviada(self):
        windows = object.__new__(Windows)
        windows.disponivel = lambda *_: True
        acao = Acao("clicar", Alvo("jogar", 1, (110, 110, 20, 20), 1))
        self.assertFalse(windows.executar(Janela(42, (0, 0, 100, 100)), acao, Event()))
        self.assertEqual(windows.ultima_falha, "alvo_fora_da_janela")

    def test_recusa_de_posicionar_cursor_expoe_motivo(self):
        janela = Janela(42, (0, 0, 100, 100))
        windows = object.__new__(Windows)
        windows.disponivel = lambda *_: True
        windows.fortnite_em_foco = lambda: janela
        windows.user = SimpleNamespace(SetCursorPos=lambda *_: False)
        acao = Acao("clicar", Alvo("jogar", 1, (10, 10, 20, 20), 1))
        self.assertFalse(windows.executar(janela, acao, Event()))
        self.assertEqual(windows.ultima_falha, "posicionamento_do_cursor_recusado")

    def test_fallback_ao_soltar_tecla_e_tenta_soltar_as_demais(self):
        janela = Janela(42, (0, 0, 100, 100))
        windows = object.__new__(Windows)
        eventos = []
        windows.disponivel = lambda *_: True
        windows._esperar = lambda *_: False
        windows.user = type("Api", (), {
            "keybd_event": lambda _, vk, scan, flags, extra: eventos.append(("fallback", scan))
        })()

        def tecla(scan, soltando=False):
            eventos.append(("soltar" if soltando else "pressionar", scan))
            if scan == 32 and soltando:
                raise OSError("falha simulada")

        windows._tecla = tecla
        with self.assertRaises(OSError):
            windows._pressionar(janela, Event(), (17, 32), 1.0)
        self.assertEqual(eventos, [
            ("pressionar", 17), ("pressionar", 32), ("soltar", 32), ("fallback", 32), ("soltar", 17),
        ])

    def test_falha_no_fallback_nao_impede_soltar_outras_teclas(self):
        janela = Janela(42, (0, 0, 100, 100))
        windows = object.__new__(Windows)
        eventos = []
        windows.disponivel = lambda *_: True
        windows._esperar = lambda *_: False

        def tecla(scan, soltando=False):
            eventos.append(("soltar" if soltando else "pressionar", scan))
            if scan == 32 and soltando:
                raise OSError("falha simulada")

        def fallback(vk, scan, flags, extra):
            eventos.append(("fallback", scan))
            raise OSError("fallback indisponível")

        windows._tecla = tecla
        windows.user = SimpleNamespace(keybd_event=fallback)
        with self.assertRaises(OSError):
            windows._pressionar(janela, Event(), (17, 32), 1.0)
        self.assertIn(("soltar", 17), eventos)

    def test_relogio_e_espera_injetados_nao_usam_sleep_real(self):
        agora = [0.0]
        windows = object.__new__(Windows)
        windows.relogio = lambda: agora[0]
        windows.esperar_evento = lambda parar, duracao: agora.__setitem__(0, agora[0] + duracao)
        windows.disponivel = lambda *_: True
        self.assertTrue(windows._esperar(Janela(1, (0, 0, 100, 100)), Event(), 0.11))
        self.assertAlmostEqual(agora[0], 0.11)

    def test_clique_aceito_libera_mouse_apos_perda_de_foco(self):
        eventos = []
        windows = object.__new__(Windows)
        windows.disponivel = lambda *_: True
        windows._esperar = lambda *_: False
        windows._mouse = lambda flags, *args: eventos.append(flags)
        self.assertTrue(windows._clique(Janela(1, (0, 0, 100, 100)), Event(), 0.15))
        self.assertEqual(eventos, [2, 4])

    def test_pausa_durante_tecla_libera_a_tecla(self):
        eventos = []
        parar = Event()
        windows = object.__new__(Windows)
        windows.disponivel = lambda *_: True

        def esperar(*_):
            parar.set()
            return False

        windows._esperar = esperar
        windows._tecla = lambda scan, soltando=False: eventos.append(
            ("soltar" if soltando else "pressionar", scan)
        )
        self.assertFalse(windows._pressionar(Janela(1, (0, 0, 100, 100)), parar, (17,), 1.0))
        self.assertEqual(eventos, [("pressionar", 17), ("soltar", 17)])

    def test_fallback_de_mouse_libera_botao_e_expõe_falha(self):
        eventos = []
        windows = object.__new__(Windows)
        windows.disponivel = lambda *_: True
        windows._esperar = lambda *_: False

        def mouse(flags, *args):
            eventos.append(flags)
            if flags == 4:
                raise OSError("falha simulada")

        windows._mouse = mouse
        windows.user = SimpleNamespace(mouse_event=lambda flags, *args: eventos.append(("fallback", flags)))
        with self.assertRaises(OSError):
            windows._clique(Janela(1, (0, 0, 100, 100)), Event(), 0.15)
        self.assertEqual(eventos, [2, 4, ("fallback", 4)])


if __name__ == "__main__":
    unittest.main()
