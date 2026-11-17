from dataclasses import replace
import os
from pathlib import Path
from queue import SimpleQueue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app import Painel, monitorar
from logica_autofarm import Acao, Alvo, Config, Detector, Fluxo, TEMPLATES
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
            self.fluxo.registrar_clique(acao, enviado, instante, no_onibus=kwargs.get("no_onibus", False))
        return acao

    def iniciar_clique(self, nome):
        self.assertIsNone(self.passo(0, nome))
        clique = self.passo(0.2, nome)
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

    def test_partida_ja_em_andamento_permite_andar_sem_iniciar_cronometro(self):
        self.fluxo.config = replace(self.fluxo.config, anti_afk=True)
        self.assertIsNone(self.passo(0, partida=True))
        self.assertIsNone(self.passo(0.3, partida=True))
        self.assertEqual(self.passo(0.6, partida=True, cursor=True).passos, (("teclas", (17,), 1.45),))
        self.assertIsNone(self.fluxo.inicio_partida)
        self.assertEqual(self.fluxo.partidas, 0)

    def test_anti_afk_aguarda_transicao_apos_clique_de_fila(self):
        self.fluxo.config = replace(self.fluxo.config, anti_afk=True)
        self.iniciar_clique("jogar")
        self.assertIsNone(self.passo(2, partida=True))
        self.assertEqual(self.passo(2.2, partida=True).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(2.5, partida=True))
        self.assertEqual(self.fluxo.motivo_anti_afk, "aguardando_transicao_da_fila")
        self.assertEqual(self.passo(11, partida=True).tipo, "partida_nao_confirmada")
        self.assertIsNone(self.passo(11.5, partida=True))
        self.assertEqual(self.fluxo.motivo_anti_afk, "aguardando_transicao_da_fila")

    def test_fila_confirmada_dispara_rotina_aerea_uma_vez(self):
        self.iniciar_clique("lobby_jogar")
        self.passo(2)
        self.passo(2.2)
        self.passo(2.4, "fila")
        self.assertEqual(self.passo(3.5, "fila").tipo, "fila_confirmada")
        self.assertIsNone(self.passo(4, no_onibus=True))
        salto = self.passo(4.3, no_onibus=True)
        self.assertEqual(salto.tipo, "saltar_onibus")
        self.assertEqual(salto.passos, (("teclas", (57,), 0.16),))
        self.fluxo.embarque.registrar(salto.tipo, True, 4.8)
        self.assertIsNone(self.passo(5.4, no_onibus=True))
        self.assertIsNone(self.passo(6, asa_delta=True))
        fechar = self.passo(14, asa_delta=True)
        self.assertEqual(fechar.tipo, "fechar_asa")
        self.assertEqual(self.fluxo.partidas, 1)

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

    def test_pronto_nao_e_clicado_quando_hud_aparece_no_segundo_quadro(self):
        self.assertIsNone(self.passo(0, "lobby_pronto", cursor=True))
        self.assertIsNone(self.passo(0.2, "lobby_pronto", cursor=True, partida=True))
        self.assertIsNone(self.passo(0.4, "lobby_pronto", cursor=True))
        self.assertEqual(self.passo(0.6, "lobby_pronto", cursor=True).alvo.nome, "lobby_pronto")

    def test_retomar_descarta_fila_nao_confirmada_e_reconhece_partida_manual(self):
        self.fluxo.config = replace(self.fluxo.config, anti_afk=True)
        self.iniciar_clique("lobby_pronto")
        self.assertIsNone(self.passo(2, partida=True))
        self.assertEqual(self.passo(2.2, partida=True).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(2.4, partida=True))
        self.assertTrue(self.fluxo.rearmar_fila())
        self.assertIsNone(self.passo(3, partida=True))
        self.assertEqual(self.passo(3.4, partida=True).tipo, "movimento")
        self.assertEqual(self.fluxo.partidas, 0)

    def test_retomar_preserva_fila_ja_confirmada(self):
        self.iniciar_clique("lobby_jogar")
        self.passo(2)
        self.passo(2.2)
        self.passo(2.4, "fila")
        self.assertEqual(self.passo(3.5, "fila").tipo, "fila_confirmada")
        self.assertFalse(self.fluxo.rearmar_fila())
        self.assertIsNone(self.passo(4.5, "lobby_pronto"))
        self.assertEqual(self.fluxo.partidas, 1)

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
        self.iniciar_clique("jogar")
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
        acao = self.passo(0.3, "menu_aba", partida=True, cursor=True)
        self.assertEqual(acao.tipo, "movimento")
        self.assertEqual(acao.passos, (("teclas", (17,), 1.45),))

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
        self.assertEqual(self.passo(0.3, partida=True, cursor=True).passos, (("teclas", (17,), 1.45),))
        with patch("logica_autofarm.plano_anti_afk", return_value=([("mouse", 90, 0, 0.2)], (0, 0.8, 0))):
            self.assertEqual(self.passo(2, partida=True).passos, (("mouse", 90, 0, 0.2),))
            self.assertEqual(self.passo(3, partida=True, cursor=True).passos, (("teclas", (17,), 1.45),))

    def test_caminhada_gira_camera_e_equipa_picareta_antes_dos_cliques(self):
        self.habilitar_movimento()
        self.fluxo.config = replace(self.fluxo.config, tecla_picareta="1")
        self.assertIsNone(self.passo(0, partida=True))
        passos = self.passo(0.3, partida=True).passos
        self.assertEqual(passos[0][:3], ("andar_mouse", (17,), 1.45))
        self.assertNotEqual(passos[0][3], 0)
        self.assertEqual(passos[1], ("teclas", (2,), 0.10))
        self.assertEqual([p for p in passos if p[0] == "clique"], [("clique", 0.18)] * 2)

    def test_picareta_desligada_preserva_movimento_de_camera(self):
        self.habilitar_movimento()
        self.fluxo.config = replace(self.fluxo.config, tecla_picareta="")
        self.assertIsNone(self.passo(0, partida=True))
        passos = self.passo(0.3, partida=True).passos
        self.assertEqual(len(passos), 1)
        self.assertEqual(passos[0][0], "andar_mouse")

    def test_hud_durante_queda_livre_nunca_dispara_caminhada_para_tras(self):
        self.habilitar_movimento()
        self.fluxo.embarque.registrar("saltar_onibus", True, 0)
        self.fluxo._desvio = (0, 2, 0)
        self.assertIsNone(self.passo(0.8, partida=True, asa_delta=False))
        acao = self.passo(1.2, partida=True, asa_delta=False)
        self.assertEqual(acao.passos, (("teclas", (32,), 1.45),))

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


class MonitorTest(unittest.TestCase):
    def test_cliques_recusados_pelo_windows_nao_consomem_tentativas(self):
        detector = TelaSimulada()
        detector.nome = "jogar"
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
            return False

        windows = SimpleNamespace(
            fortnite_em_foco=lambda: 42, capturar=lambda _: quadro.copy(),
            disponivel=lambda *_: True, cursor_visivel=lambda: False, executar=executar,
        )
        with patch("app.time", SimpleNamespace(monotonic=lambda: next(instantes))):
            monitorar(windows, fluxo, eventos, parar)
        self.assertEqual(tentativas, [0, 0, 0, 0])
        self.assertEqual(fluxo.partidas, 0)


class WindowsTest(unittest.TestCase):
    def test_golpe_cancelado_se_cursor_reaparece(self):
        windows = object.__new__(Windows)
        windows.disponivel = lambda *_: True
        windows.cursor_visivel = lambda: True
        with patch.object(Windows, "_clique") as clique:
            janela = Janela(42, (0, 0, 100, 100))
            acao = Acao("movimento", passos=(("clique", 0.18),))
            self.assertFalse(windows.executar(janela, acao, Event()))
            clique.assert_not_called()

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
