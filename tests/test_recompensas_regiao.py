from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
import json
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError

import cv2
import numpy as np

from regiao import AMERICA_DO_NORTE, LinhaRegiao, RegiaoLobby, TelaRegiao, ler_tela_regiao, regiao_por_horario
from texto_tela import Linha, identificar
from webhook import ErroWebhook, enviar_webhook, validar_url


class RecompensaTest(unittest.TestCase):
    def test_nome_de_item_e_botao_em_tela_de_recompensa(self):
        titulo = Linha("ITENS ADQUIRIDOS", (280, 85, 370, 41))
        item = Linha("Cetro Congelante", (910, 330, 325, 48))
        botao = Linha("RESGATAR", (680, 752, 125, 32))
        linhas = [titulo, item, botao, Linha("RARO", (910, 298, 60, 24)),
                  Linha("Obrigado por jogar Fortnite!", (290, 140, 300, 25)),
                  Linha("Perfeito para uma revanche.", (910, 385, 280, 24))]
        self.assertEqual(identificar(linhas, 1440, 860, "recompensa"), botao)
        self.assertEqual(identificar(linhas, 1440, 860, "nome_recompensa"), item)
        self.assertIsNone(identificar(linhas[1:], 1440, 860, "recompensa"))

    def test_sem_nome_legivel_preserva_o_botao(self):
        linhas = [Linha("ITEMS ACQUIRED", (275, 90, 380, 40)),
                  Linha("CLAIM ALL", (700, 744, 108, 32))]
        self.assertEqual(identificar(linhas, 1440, 860, "recompensa"), linhas[1])
        self.assertIsNone(identificar(linhas, 1440, 860, "nome_recompensa"))


class WebhookTest(unittest.TestCase):
    def test_anexa_jpeg_e_nome_ao_teste(self):
        def abrir(pedido, timeout):
            self.assertEqual(pedido.method, "POST")
            self.assertTrue(pedido.full_url.endswith("/fake?thread_id=91&wait=true"))
            tipo = pedido.get_header("Content-type").encode("ascii")
            multiparte = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + tipo + b"\r\n\r\n" + pedido.data
            )
            mensagem, imagem = list(multiparte.iter_parts())
            self.assertEqual(json.loads(mensagem.get_content())["content"],
                             "Teste de webhook — Cetro Ártico\nMensagem de exemplo.")
            self.assertEqual(imagem.get_filename(), "captura.jpg")
            dados = np.frombuffer(imagem.get_payload(decode=True), np.uint8)
            self.assertEqual(cv2.imdecode(dados, cv2.IMREAD_COLOR).shape, (60, 80, 3))

            class Resposta:
                def __enter__(self):
                    return SimpleNamespace(status=200)

                def __exit__(self, *_):
                    return False

            return Resposta()

        enviar_webhook("https://discord.com/api/webhooks/123/fake?thread_id=91", np.zeros((60, 80, 3), np.uint8),
                       "Cetro Ártico", teste=True, texto_teste="Mensagem de exemplo.", abrir=abrir)

    def test_erro_nao_mostra_a_url(self):
        def abrir(pedido, timeout):
            raise HTTPError(pedido.full_url, 403, "proibido", {}, None)

        with self.assertRaisesRegex(ErroWebhook, r"^Webhook respondeu com HTTP 403\.$"):
            enviar_webhook("https://exemplo.invalid/webhook/chave", np.zeros((20, 20, 3), np.uint8), None, abrir=abrir)
        with self.assertRaises(ErroWebhook):
            validar_url("http://discord.com/api/webhooks/123/segredo")


class RegiaoTest(unittest.TestCase):
    def test_programacao_usa_fuso_de_brasilia_e_preferencias(self):
        for hora_utc, regiao in ((3, "NA-Oeste"), (8, "NA-Oeste"), (9, "Oceania"),
                                 (13, "Oceania"), (14, "Europa"), (20, "Europa"),
                                 (21, "NA-Central"), (2, "NA-Central")):
            instante = datetime(2026, 11, 17, hora_utc, tzinfo=timezone.utc)
            self.assertEqual(regiao_por_horario("Oceania", "NA-Central", instante), regiao)

    def test_le_regiao_truncada_sem_confundir_com_torneio(self):
        linhas = [Linha("IDIOMA E REGIÃO", (376, 122, 251, 33)),
                  Linha("Região de Pareament", (398, 188, 221, 25)),
                  Linha("Jorte (150-210 ms)", (646, 188, 187, 25)),
                  Linha("erência de Subregião", (398, 256, 219, 25)),
                  Linha("Automática", (678, 255, 123, 28)),
                  Linha("Região do Torneio", (397, 326, 185, 25)),
                  Linha("AN – Oeste", (679, 325, 122, 25))]
        tela = ler_tela_regiao(linhas, 1440, 860)
        self.assertEqual(tela.pareamento.valor, AMERICA_DO_NORTE)
        self.assertEqual(tela.subregiao.valor, "Automática")

    def test_escolhe_subregiao_confirma_aplicar_e_volta_ao_lobby(self):
        fluxo = RegiaoLobby()
        caixa = (10, 20, 30, 40)
        self.assertEqual(fluxo.iniciar("NA-Oeste", 0).tipo, "esc")
        self.assertEqual(fluxo.passo(TelaRegiao(social=True, engrenagem=caixa), 1).etapa, "abrir_configuracoes")
        self.assertEqual(fluxo.passo(TelaRegiao(configuracoes=True, aba_jogo=caixa), 2).etapa, "abrir_aba_jogo")
        norte = LinhaRegiao(caixa, AMERICA_DO_NORTE, direita=caixa)
        auto = LinhaRegiao(caixa, "Automática")
        oeste = LinhaRegiao(caixa, "NA-Oeste")
        self.assertEqual(fluxo.passo(TelaRegiao(pareamento=norte, subregiao=auto), 3).tipo, "apontar")
        auto = LinhaRegiao(caixa, "Automática", direita=caixa)
        self.assertEqual(fluxo.passo(TelaRegiao(pareamento=norte, subregiao=auto), 4).etapa, "subregiao")
        self.assertEqual(fluxo.passo(TelaRegiao(pareamento=norte, subregiao=oeste, aplicar=caixa), 5).etapa, "aplicar")
        self.assertEqual(fluxo.passo(TelaRegiao(configuracoes=True, pareamento=norte, subregiao=oeste), 6).tipo, "esc")
        self.assertEqual(fluxo.passo(TelaRegiao(social=True), 7).tipo, "esc")
        self.assertEqual(fluxo.passo(TelaRegiao(), 8, lobby=True).tipo, "ok")
        self.assertIsNone(fluxo.iniciar("NA-Oeste", 9))

    def test_falha_segue_lobby_e_agenda_nova_tentativa(self):
        fluxo = RegiaoLobby()
        fluxo.iniciar("Europa", 0)
        self.assertEqual(fluxo.passo(TelaRegiao(), 96, lobby=True).tipo, "falhou")
        self.assertIsNone(fluxo.iniciar("Europa", 100))
        self.assertEqual(fluxo.iniciar("Europa", 1296).tipo, "esc")
