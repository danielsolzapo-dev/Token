from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from app import monitorar
from diagnostico import Diagnostico
from logica_autofarm import Config, Fluxo, TEMPLATES


class DiagnosticoTest(unittest.TestCase):
    def test_rotacao_e_exportacao_preservam_as_ultimas_linhas(self):
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "diagnostico.log"
            log = Diagnostico(caminho, limite=150, arquivos=1)
            try:
                for numero in range(20):
                    log.registrar("falha", numero=numero)
                self.assertTrue(caminho.with_suffix(".log.1").exists())
                texto = log.texto(2)
                self.assertIn('"numero":18', texto)
                self.assertIn('"numero":19', texto)
                self.assertEqual(len(texto.splitlines()), 2)
            finally:
                log.fechar()

    def test_monitor_registra_comando_e_codigo_de_erro_da_entrada(self):
        quadro = np.zeros((540, 960, 3), dtype=np.uint8)
        detector = SimpleNamespace(
            config=Config(), templates=TEMPLATES, dialogo_ambiguo=False,
            detectar=lambda _: None, procurar=lambda *_a, **_k: None, em_partida=lambda _: True,
            barras_esquadrao=lambda _: None, aviso_onibus=lambda _: (None, 0.0),
        )
        fluxo = Fluxo(detector)
        def falhar(*_):
            erro = OSError("Falha simulada")
            erro.winerror = 5
            raise erro

        windows = SimpleNamespace(
            fortnite_em_foco=lambda: object(), capturar=lambda _: quadro,
            disponivel=lambda *_: True, cursor_visivel=lambda: True, executar=falhar,
        )
        with TemporaryDirectory() as pasta:
            log = Diagnostico(Path(pasta) / "diagnostico.log")
            try:
                instantes = iter((1.0, 1.5))
                with patch("app.time", SimpleNamespace(monotonic=lambda: next(instantes))):
                    monitorar(windows, fluxo, SimpleQueue(), Event(), log)
                texto = log.texto()
                self.assertIn('"anti_afk":"confirmando_hud"', texto)
                self.assertIn('"passos":[["teclas",[17],1.45]]', texto)
                self.assertIn('"etapa":"enviar_entrada","tipo":"OSError","codigo":5', texto)
                self.assertIn('"evento":"sessao_encerrada"', texto)
            finally:
                log.fechar()
