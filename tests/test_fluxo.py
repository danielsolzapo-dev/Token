from threading import Event
import unittest

import numpy as np

from logica_autofarm import Acao, Alvo, Config, Detector, Fluxo
from texto_tela import Linha, identificar
from windows_game import Janela, Windows


class TelaSimulada:
    config = Config(minutos_partida=0.1, timeout_lobby=8, anti_afk=False)
    nome = None

    def procurar(self, _, nomes):
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

    def passo(self, instante, nome=None, **kwargs):
        self.detector.nome = nome
        return self.fluxo.passo(self.quadro, instante, **kwargs)

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

    def test_hud_confirma_sem_ocr_de_fila(self):
        self.iniciar_clique("jogar")
        self.passo(2)
        self.passo(2.2)
        self.assertIsNone(self.passo(3, partida=True))
        self.assertEqual(self.passo(3.2, partida=True).tipo, "partida_confirmada")
        self.assertEqual(self.fluxo.partidas, 1)

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

    def test_tela_desconhecida_gera_aviso_e_busca_continua(self):
        self.assertIsNone(self.passo(0))
        self.assertEqual(self.passo(8).tipo, "tela_nao_reconhecida")
        self.assertIsNone(self.passo(9))
        self.assertIsNone(self.passo(10, "jogar"))
        self.assertEqual(self.passo(10.2, "jogar").alvo.nome, "jogar")


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
