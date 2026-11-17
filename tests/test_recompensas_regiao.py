from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
import json
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError

import cv2
import numpy as np

from logica_autofarm import Detector
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
    def test_lobby_reconhecido_abre_o_perfil_diretamente(self):
        detector = Detector()
        quadro = np.zeros((900, 1440, 3), np.uint8)
        aba = cv2.resize(detector.templates["aba_jogar_lobby"], (82, 35))
        quadro[34:69, 155:237] = aba
        perfil = detector.perfil_lobby(quadro)
        self.assertIsNotNone(perfil)
        x, y, largura, altura = perfil
        self.assertAlmostEqual(x + largura / 2, 1358, delta=3)
        self.assertAlmostEqual(y + altura / 2, 52, delta=3)
        ordem = RegiaoLobby().iniciar("Oceania", 0, perfil=perfil)
        self.assertEqual((ordem.tipo, ordem.etapa, ordem.caixa), ("clicar", "abrir_social", perfil))

    def test_menu_de_tres_linhas_reconhece_engrenagem_na_aba_vizinha(self):
        linhas = [Linha("Fechar o Fortnite", (1098, 121, 149, 18)),
                  Linha("Sair do Grupo", (1112, 175, 120, 20)),
                  Linha("Controle dos Pais", (1100, 325, 143, 20))]
        detector = Detector(leitor=SimpleNamespace(linhas=lambda _: linhas))
        quadro = np.full((900, 1440, 3), 76, np.uint8)
        icone = detector.templates["engrenagem_menu_lobby"]
        icone = cv2.resize(icone, (30, 29))
        quadro[39:68, 1155:1185] = icone[:, :, None]
        quadro[39:68, 1205:1235] = icone[:, :, None]
        tela = detector.tela_regiao(quadro)
        self.assertTrue(tela.social)
        self.assertIsNotNone(tela.engrenagem)
        x, y, largura, altura = tela.engrenagem
        self.assertAlmostEqual(x + largura / 2, 1170, delta=5)
        self.assertAlmostEqual(y + altura / 2, 54, delta=5)
        fluxo = RegiaoLobby()
        fluxo.iniciar("Oceania", 0)
        acao = fluxo.passo(tela, 2)
        self.assertEqual((acao.tipo, acao.etapa, acao.caixa),
                         ("clicar", "abrir_configuracoes", tela.engrenagem))

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

    def test_linha_deslocada_com_mouse_mantem_o_seletor_focado(self):
        linhas = [Linha("IDIOMA E REGIÃO", (125, 123, 248, 32)),
                  Linha("Região de Pareamento", (816, 123, 235, 25)),
                  Linha("Região de Pareamento", (144, 188, 236, 25)),
                  Linha("Automático (15ms)", (501, 188, 190, 25)),
                  Linha("Preferência de Subregião", (145, 256, 263, 25)),
                  Linha("Automática", (535, 258, 120, 23))]
        tela = ler_tela_regiao(linhas, 1440, 900)
        self.assertEqual(tela.pareamento.valor, "Automática")
        self.assertTrue(tela.pareamento.focada)
        self.assertFalse(tela.subregiao.focada)
        self.assertEqual(tela.pareamento.caixa, linhas[3].caixa)

    def test_le_pareamento_e_subregiao_na_aba_jogo_com_painel_lateral(self):
        linhas = [Linha("IDIOMA E REGIÃO", (376, 122, 251, 33)),
                  Linha("egião de Pareamento", (398, 188, 221, 25)),
                  Linha("Oceania (335ms)", (655, 188, 173, 25)),
                  Linha("referência de Subregi", (398, 256, 219, 25)),
                  Linha("Automática", (678, 255, 123, 28))]
        tela = ler_tela_regiao(linhas, 1440, 900)
        self.assertIsNone(tela.aba_jogo)
        self.assertEqual(tela.pareamento.valor, "Oceania")
        self.assertEqual(tela.pareamento.caixa, linhas[2].caixa)
        self.assertEqual(tela.subregiao.valor, "Automática")

    def test_seletor_com_rotulo_e_valor_na_mesma_caixa(self):
        linhas = [Linha("IDIOMA E REGIÃO", (125, 123, 248, 32)),
                  Linha("Região de Pareamento Europa (210 ms)", (144, 188, 520, 25))]
        tela = ler_tela_regiao(linhas, 1440, 900)
        self.assertEqual(tela.pareamento.valor, "Europa")

    def test_seta_do_teclado_exige_seletor_focado(self):
        fluxo = RegiaoLobby()
        fluxo.iniciar("Europa", 0)
        linha = LinhaRegiao((501, 188, 190, 25), "Automática")
        tela = TelaRegiao(configuracoes=True, pareamento=linha)
        self.assertEqual(fluxo.passo(tela, 1).tipo, "apontar")
        self.assertEqual(fluxo.passo(tela, 2).etapa, "selecionar_pareamento")
        self.assertIsNone(fluxo.passo(tela, 3))
        focada = LinhaRegiao(linha.caixa, linha.valor, focada=True)
        self.assertEqual(fluxo.passo(TelaRegiao(pareamento=focada), 4).tecla, 0xE04D)

    def test_sem_mudanca_fecha_configuracoes_e_libera_lobby(self):
        fluxo = RegiaoLobby()
        fluxo.iniciar("Europa", 0)
        voltar = (1281, 847, 81, 23)
        tela = TelaRegiao(configuracoes=True, voltar=voltar)
        self.assertIsNone(fluxo.passo(tela, 1))
        ordem = fluxo.passo(tela, 15)
        self.assertEqual((ordem.tipo, ordem.etapa, ordem.caixa), ("clicar", "fechar_configuracoes", voltar))
        self.assertEqual(fluxo.passo(TelaRegiao(), 16, lobby=True).tipo, "falhou")

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
        aplicar = fluxo.passo(TelaRegiao(pareamento=norte, subregiao=oeste, aplicar=caixa), 5)
        self.assertEqual((aplicar.tipo, aplicar.etapa, aplicar.tecla), ("tecla", "aplicar", 0x1E))
        self.assertEqual(fluxo.passo(TelaRegiao(configuracoes=True, pareamento=norte, subregiao=oeste), 6).tipo, "esc")
        self.assertEqual(fluxo.passo(TelaRegiao(social=True), 7).tipo, "esc")
        self.assertEqual(fluxo.passo(TelaRegiao(), 8, lobby=True).tipo, "ok")
        self.assertIsNone(fluxo.iniciar("NA-Oeste", 9))

    def test_na_oeste_mantem_subregiao_quando_pareamento_fica_ilegivel(self):
        fluxo = RegiaoLobby()
        fluxo.iniciar("NA-Oeste", 0)
        caixa = (501, 188, 190, 25)
        norte = LinhaRegiao(caixa, AMERICA_DO_NORTE, direita=caixa)
        automatico = LinhaRegiao(caixa, "Automática")
        self.assertEqual(fluxo.passo(TelaRegiao(pareamento=norte, subregiao=automatico), 1).etapa, "subregiao")
        ilegivel = LinhaRegiao(caixa, None, direita=caixa)
        automatico_focado = LinhaRegiao(caixa, "Automática", direita=caixa, focada=True)
        self.assertEqual(fluxo.passo(TelaRegiao(pareamento=ilegivel, subregiao=automatico_focado), 2).etapa,
                         "subregiao")
        oeste = LinhaRegiao(caixa, "NA-Oeste", focada=True)
        tecla = fluxo.passo(TelaRegiao(pareamento=ilegivel, subregiao=oeste), 3)
        self.assertEqual(tecla.tecla, 0x1E)

    def test_dialogo_salva_apenas_quando_regiao_desejada_foi_confirmada(self):
        linhas = [Linha("CONFIGURAÇÕES MODIFICADAS", (204, 216, 461, 40)),
                  Linha("Você tem alterações não salvas. Gostaria de salvá-las antes de sair?", (206, 296, 601, 22)),
                  Linha("SALVAR", (323, 599, 84, 23)), Linha("NÃO SALVAR", (655, 598, 136, 24))]
        tela = ler_tela_regiao(linhas, 1160, 827)
        self.assertTrue(tela.dialogo_alteracoes)
        self.assertEqual(tela.salvar, linhas[2].caixa)
        self.assertEqual(tela.descartar, linhas[3].caixa)
        for selecionou, acao, caixa in ((True, "salvar", tela.salvar), (False, "descartar", tela.descartar)):
            with self.subTest(selecionou=selecionou):
                fluxo = RegiaoLobby()
                fluxo.iniciar("Europa", 0)
                if selecionou:
                    automatico = LinhaRegiao((500, 188, 190, 25), "Automática", direita=(728, 191, 14, 19))
                    fluxo.passo(TelaRegiao(pareamento=automatico), 1)
                    europa = LinhaRegiao(automatico.caixa, "Europa")
                    self.assertEqual(fluxo.passo(TelaRegiao(pareamento=europa), 2).tecla, 0x1E)
                    self.assertEqual(fluxo.passo(TelaRegiao(pareamento=europa), 3).etapa, "fechar_configuracoes")
                else:
                    fluxo.cancelar(3)
                ordem = fluxo.passo(tela, 4)
                self.assertEqual((ordem.tipo, ordem.etapa, ordem.caixa), ("clicar", acao, caixa))
        self.assertIsNone(ler_tela_regiao(linhas[:-1], 1160, 827).salvar)

    def test_falha_segue_lobby_e_agenda_nova_tentativa(self):
        fluxo = RegiaoLobby()
        fluxo.iniciar("Europa", 0)
        self.assertEqual(fluxo.passo(TelaRegiao(), 96, lobby=True).tipo, "falhou")
        self.assertIsNone(fluxo.iniciar("Europa", 100))
        self.assertEqual(fluxo.iniciar("Europa", 1296).tipo, "esc")
