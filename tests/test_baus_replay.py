import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from baus_replay import analisar_replay, ultimo_replay


def cabecalho(versao=7, ativa=False, utf16=True):
    nome = "Partida\x00".encode("utf-16le" if utf16 else "utf-8")
    prefixo = struct.pack("<II", 0x1CA2E27F, versao)
    if versao == 7:
        prefixo += struct.pack("<i", 1) + bytes(20)
    return prefixo + bytes(12) + struct.pack("<i", -len(nome) // 2 if utf16 else len(nome)) + nome + struct.pack("<i", ativa)


class BausReplayTest(unittest.TestCase):
    def setUp(self):
        arquivos = TemporaryDirectory()
        self.addCleanup(arquivos.cleanup)
        self.pasta = Path(arquivos.name)
        pasta = patch("baus_replay.pasta_replays", return_value=self.pasta)
        pasta.start()
        self.addCleanup(pasta.stop)

    def arquivo(self, nome, dados, instante):
        arquivo = self.pasta / nome
        arquivo.write_bytes(dados)
        os.utime(arquivo, (instante, instante))
        return arquivo

    def test_ultimo_replay_finalizado_exclui_gravacao_e_arquivo_truncado(self):
        for versao in range(4, 8):
            with self.subTest(versao=versao):
                self.arquivo("antigo.replay", cabecalho(), 10)
                concluido = self.arquivo("finalizado.replay", cabecalho(versao, utf16=versao == 7), 20)
                self.arquivo("gravando.replay", cabecalho(ativa=True), 30)
                self.arquivo("incompleto.replay", cabecalho()[:-2], 40)
                self.assertEqual(ultimo_replay(), concluido)

    def test_sem_arquivos_e_formatos_incompativeis(self):
        with self.assertRaisesRegex(ValueError, "Nenhum replay"):
            ultimo_replay()
        for dados in (b"", b"xxxx", cabecalho(8), cabecalho()[:-4], cabecalho(ativa=True)):
            arquivo = self.arquivo("invalido.replay", dados, 10)
            with patch("baus_replay._executar") as executar, self.assertRaises(ValueError):
                analisar_replay(arquivo)
            executar.assert_not_called()

    def test_distingue_zero_de_autoria_indisponivel(self):
        arquivo = self.arquivo("partida.replay", cabecalho(), 10)
        for voce, time in ((0, 7), (4, 4), (None, None), (1, None)):
            with patch("baus_replay._executar", return_value=dict(voce=voce, esquadrao=time, detalhe="Cobertura.")):
                resultado = analisar_replay(arquivo)
                self.assertEqual((resultado.voce, resultado.esquadrao), (voce, time))
        for dado in (-1, True, "1"):
            with patch("baus_replay._executar", return_value=dict(voce=dado, esquadrao=4, detalhe="X")), self.assertRaises(ValueError):
                analisar_replay(arquivo)
        with patch("baus_replay._executar", return_value=dict(voce=4, esquadrao=3, detalhe="X")), self.assertRaises(ValueError):
            analisar_replay(arquivo)

    def test_descarta_resultado_se_arquivo_mudou_durante_a_leitura(self):
        arquivo = self.arquivo("partida.replay", cabecalho(), 10)

        def executar(caminho):
            with caminho.open("ab") as f:
                f.write(b"mais um quadro")
            return dict(voce=0, esquadrao=3, detalhe="Contagem")

        with patch("baus_replay._executar", side_effect=executar), self.assertRaisesRegex(ValueError, "mudou"):
            analisar_replay(arquivo)
