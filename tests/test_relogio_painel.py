import unittest

from relogio_painel import RelogioPainel


class RelogioPainelTest(unittest.TestCase):
    def test_farmando_conta_tempo_ativo_e_congela_ao_pausar(self):
        relogio = RelogioPainel()
        self.assertEqual(relogio.valores(5), ("—", "—"))
        relogio.iniciar(10)
        self.assertEqual(relogio.valores(22.25), ("—", "00:12"))
        relogio.pausar(22.75)
        self.assertEqual(relogio.valores(95), ("—", "00:12"))
        relogio.iniciar(100)
        self.assertEqual(relogio.valores(107.25), ("—", "00:20"))

    def test_mostra_o_prazo_real_ao_rodar_sem_segundos_negativos(self):
        relogio = RelogioPainel()
        relogio.iniciar(0)
        relogio.prazo_saida = 450
        self.assertEqual(relogio.valores(0), ("07:30", "00:00"))
        self.assertEqual(relogio.valores(449.4)[0], "00:01")
        self.assertEqual(relogio.valores(460)[0], "00:00")
        relogio.pausar(460)
        self.assertEqual(relogio.valores(500), ("—", "07:40"))
        relogio.prazo_saida = None
        relogio.iniciar(500)
        self.assertEqual(relogio.valores(500), ("—", "07:40"))

    def test_formata_horas_de_sessao(self):
        relogio = RelogioPainel()
        relogio.iniciar(10)
        self.assertEqual(relogio.valores(3671), ("—", "01:01:01"))
