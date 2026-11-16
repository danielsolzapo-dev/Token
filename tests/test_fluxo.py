from dataclasses import replace
from queue import SimpleQueue
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from app import monitorar
from logica_autofarm import Acao, Alvo, Config, Detector, Fluxo, TEMPLATES
from texto_tela import Linha, identificar
from windows_game import Janela, Windows


class TelaSimulada:
    config = Config(minutos_partida=0.1, timeout_lobby=8, anti_afk=False)
    nome = None
    dialogo_ambiguo = False

    def procurar(self, _, nomes, limiar=None):
        if self.nome in nomes:
            return Alvo(self.nome, 1, (10, 10, 20, 20), 1)
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

    def test_botao_ausente_sem_fila_nao_conta(self):
        self.iniciar_clique("jogar")
        self.assertIsNone(self.passo(2))
        self.assertEqual(self.passo(2.2).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(4))
        self.assertEqual(self.passo(11).tipo, "partida_nao_confirmada")
        self.assertEqual(self.fluxo.partidas, 0)
        self.assertIsNone(self.fluxo.inicio_partida)

    def test_fila_contada_uma_vez_cronometro_so_no_jogo(self):
        self.iniciar_clique("lobby_jogar")
        self.assertIsNone(self.passo(2))
        self.assertEqual(self.passo(2.2).tipo, "aguardando_fila")
        self.assertIsNone(self.passo(2.4, "fila"))
        self.assertEqual(self.passo(3.5, "fila").tipo, "fila_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)
        self.assertIsNone(self.fluxo.inicio_partida)
        self.assertIsNone(self.passo(4, no_onibus=True))
        self.assertEqual(self.passo(4.3, no_onibus=True).tipo, "partida_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)
        self.assertEqual(self.fluxo.inicio_partida, 4.3)

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
        self.assertIsNone(self.passo(12, partida=True))
        self.assertEqual(self.passo(12.2, partida=True).tipo, "partida_confirmada")
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
        self.assertIsNone(self.passo(3, partida=True))
        self.assertEqual(self.passo(3.2, partida=True).tipo, "partida_confirmada")
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
        self.passo(3, hud_visivel=True)
        self.passo(3.2, partida=True)
        self.assertEqual(self.fluxo.partidas, 0)
        self.passo(4)
        self.passo(4.2)
        self.assertIsNone(self.passo(5, partida=True))
        self.assertEqual(self.passo(5.2, partida=True).tipo, "partida_confirmada")

    def test_pronto_substitui_jogar_sem_esperar_timeout(self):
        self.iniciar_clique("lobby_jogar")
        self.passo(2, "lobby_pronto")
        aviso = self.passo(2.2, "lobby_pronto")
        self.assertEqual(aviso.tipo, "aguardando_fila")
        self.assertIsNone(self.passo(2.5, "lobby_pronto"))
        self.assertEqual(self.passo(2.7, "lobby_pronto").alvo.nome, "lobby_pronto")
        self.passo(5, "lobby_jogar")
        self.passo(5.2, "lobby_jogar")
        self.assertIsNone(self.passo(5.5, "lobby_jogar"))
        self.assertIsNone(self.passo(5.7, "lobby_jogar"))
        self.assertEqual(self.fluxo.partidas, 0)

    def test_saida_por_tempo_e_confirmacao(self):
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
    def test_geometria_mudou_antes_da_entrada(self):
        janela = Janela(42, (0, 0, 100, 100))
        windows = object.__new__(Windows)
        windows.user = type("Api", (), {"GetForegroundWindow": lambda _: 42})()
        windows._area = lambda _: (0, 0, 200, 200)
        self.assertFalse(windows.executar(janela, Acao("esc"), Event()))

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


if __name__ == "__main__":
    unittest.main()
