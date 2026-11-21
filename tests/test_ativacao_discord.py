import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

import bot_discord as bot
import cofre_bot
from pedido_discord import LIMITE_ARQUIVO, ler_pedido, ler_recibo, novo_pedido


PC = "C0FFEE0123456789" * 2


class ArquivosTest(unittest.TestCase):
    def test_id_aleatorio_e_pedido_limitado(self):
        pedido = novo_pedido(PC.lower())
        self.assertEqual(pedido, ler_pedido(pedido.serializar()))
        self.assertNotEqual(pedido.id, novo_pedido(PC).id)
        dados = json.loads(pedido.serializar())
        for invalido in (b"x" * (LIMITE_ARQUIVO + 1), b"[]", b"\xff", b"{}", b"null",
                         json.dumps(dict(dados, pedido="../licenca")).encode(),
                         json.dumps(dict(dados, pc=True)).encode()):
            with self.subTest(invalido=invalido[:24]), self.assertRaises(ValueError):
                ler_pedido(invalido)

    def test_leitura_do_recibo_e_limitada(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "arquivo.txt"
            for dados in (b"AFA1." + b"x" * LIMITE_ARQUIVO, b"AFV1.venda", b"AFA1.\xff"):
                caminho.write_bytes(dados)
                with self.assertRaises(ValueError):
                    ler_recibo(caminho)
            caminho.write_bytes(b"AFA1.teste\r\n")
            self.assertEqual(ler_recibo(caminho), "AFA1.teste")

    def test_cofre_windows_preserva_texto_da_credencial(self):
        import uuid
        alvo = f"AutoFarm/Testes/{uuid.uuid4().hex}"
        self.assertEqual(cofre_bot.obter(alvo), "")
        cofre_bot.guardar(alvo, "teste-sintetico")
        self.addCleanup(cofre_bot.win32cred.CredDelete, alvo, cofre_bot.win32cred.CRED_TYPE_GENERIC)
        self.assertEqual(cofre_bot.obter(alvo), "teste-sintetico")


class DiscordTest(unittest.IsolatedAsyncioTestCase):
    async def test_formulario_real_e_resposta_privada(self):
        await bot.verificar_build()
        pedido = novo_pedido(PC)
        anexo = SimpleNamespace(filename=pedido.nome_arquivo, size=len(pedido.serializar()),
                                url="https://cdn.discordapp.com/attachments/1/2/pedido.json",
                                read=AsyncMock(return_value=pedido.serializar()))
        cliente = SimpleNamespace(no_destino=lambda i: i.guild_id == 1, acesso="teste", vagas=asyncio.Semaphore(1))
        modal = bot.Formulario(cliente, 2)
        modal.chave._value = "venda"
        modal.arquivo._values = [anexo]
        interacao = Mock(user=SimpleNamespace(id=2), guild_id=1)
        interacao.response = AsyncMock()
        interacao.edit_original_response = AsyncMock()
        capturados = []
        def capturar(*, attachments, content):
            capturados.append((attachments[0].filename, attachments[0].fp.read(), content))
        interacao.edit_original_response.side_effect = capturar
        with (patch("licenca.verificar_venda"), patch("licenca.ativar_venda", return_value="AFA1.sintetico") as ativar):
            await modal.on_submit(interacao)
        interacao.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        ativar.assert_called_once_with("venda", PC, acesso_servico="teste")
        self.assertEqual(capturados[0][:2], (pedido.nome_licenca, b"AFA1.sintetico\n"))
        interacao.user.id = 3
        with patch("licenca.ativar_venda") as recusado:
            await modal.on_submit(interacao)
            recusado.assert_not_called()
        interacao.response.send_message.assert_awaited_once()

    async def test_arquivo_externo_e_excessivo_nao_sao_baixados(self):
        anexo = SimpleNamespace(filename="pedido.json", size=1, read=AsyncMock(), url="https://exemplo.com/x")
        with self.assertRaises(ValueError):
            await bot.receber_pedido(anexo)
        anexo.url = "https://cdn.discordapp.com/attachments/1/2/pedido.json"
        anexo.size = LIMITE_ARQUIVO + 1
        with self.assertRaises(ValueError):
            await bot.receber_pedido(anexo)
        anexo.read.assert_not_awaited()

    async def test_valida_canal_e_reutiliza_painel_apos_reinicio(self):
        destino = bot.ids_do_link("https://discord.com/channels/111111111111111111/222222222222222222")
        with self.assertRaises(ValueError):
            bot.ids_do_link("https://outro.com/channels/111111111111111111/222222222222222222")
        canal = Mock(spec=discord.TextChannel)
        canal.id, canal.guild = destino["canal"], SimpleNamespace(id=destino["servidor"])
        msg = SimpleNamespace(id=42, author=SimpleNamespace(id=5), jump_url="https://discord.com/",
                              components=[SimpleNamespace(children=[SimpleNamespace(custom_id=bot.BOTAO)])])
        async def historico(**_):
            for item in []:
                yield item
        canal.history = historico
        canal.send = AsyncMock(return_value=msg)
        canal.fetch_message = AsyncMock(return_value=msg)
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "painel.json"
            bot.salvar_destino(arquivo, destino)
            for _ in range(2):
                cliente = bot.BotAtivacao("teste", arquivo)
                cliente._connection.user = msg.author
                self.addAsyncCleanup(cliente.close)
                self.assertTrue(cliente.no_destino(SimpleNamespace(guild_id=destino["servidor"], channel_id=canal.id)))
                self.assertFalse(cliente.no_destino(SimpleNamespace(guild_id=1, channel_id=canal.id)))
                with patch.object(cliente, "localizar_canal", return_value=canal):
                    await cliente.garantir_painel()
            canal.fetch_message.assert_awaited_once_with(42)
            canal.send.assert_awaited_once()
