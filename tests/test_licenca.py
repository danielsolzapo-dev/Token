import base64
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import licenca


PC = "C0FFEE0123456789" * 2
OUTRO_PC = "1234567890ABCDEF" * 2


class TesteLicenca(unittest.TestCase):
    def setUp(self):
        self.segredo = Ed25519PrivateKey.generate()
        self.enterContext(patch.object(licenca, "CHAVE_PUBLICA", self.segredo.public_key().public_bytes_raw()))

    def emitir(self, pc=PC, expira=None):
        carga = licenca.carga_licenca(pc, expira)
        return licenca.montar_chave(carga, self.segredo.sign(carga))

    def test_vitalicia_aceita_codigo_agrupado_no_emissor(self):
        pc_formatado = "-".join(PC[i:i + 4].lower() for i in range(0, len(PC), 4))
        chave = self.emitir(pc_formatado)
        self.assertEqual(licenca.validar_chave(chave, PC), licenca.Licenca(PC, None))
        with self.assertRaisesRegex(ValueError, "outro PC"):
            licenca.validar_chave(chave, OUTRO_PC)

    def test_data_final_inclusiva(self):
        hoje = date.today()
        self.assertEqual(licenca.validar_chave(self.emitir(expira=hoje), PC).expira, hoje)
        with self.assertRaisesRegex(ValueError, "venceu"):
            licenca.validar_chave(self.emitir(expira=hoje - timedelta(days=1)), PC)

    def test_assinatura_cobre_pc_e_vencimento(self):
        carga = licenca.carga_licenca(PC, date.today())
        assinatura = self.segredo.sign(carga)
        for pc, data in ((OUTRO_PC, date.today()), (PC, None)):
            with self.subTest(pc=pc, data=data), self.assertRaisesRegex(ValueError, "inválida"):
                licenca.validar_chave(licenca.montar_chave(licenca.carga_licenca(pc, data), assinatura), pc)
        assinatura_estranha = Ed25519PrivateKey.generate().sign(carga)
        with self.assertRaisesRegex(ValueError, "inválida"):
            licenca.validar_chave(licenca.montar_chave(carga, assinatura_estranha), PC)

    def test_chaves_truncadas_malformadas_e_versoes_desconhecidas(self):
        chave = self.emitir()
        for entrada in ("", "desconhecida", "x" * 201, "AF1.Q", chave[:-1], chave + "=", chave + "0",
                        chave.replace("AF1.", "AF2."), "AF1." + base64.urlsafe_b64encode(b"\0" * 98).decode()):
            with self.subTest(entrada=entrada[:4]), self.assertRaises(ValueError):
                licenca.validar_chave(entrada, PC)

    def test_codigo_estavel_e_especifico_do_windows(self):
        guid = "abcde123-1234-5678-9789-123456789abc"
        codigo = licenca._codigo_do_guid(guid)
        self.assertRegex(codigo, r"^[A-F0-9]{32}$")
        self.assertEqual(codigo, licenca._codigo_do_guid("{" + guid.upper() + "}"))
        self.assertNotEqual(codigo, licenca._codigo_do_guid(guid[:-1] + "d"))
        self.assertNotEqual(codigo, guid.upper().replace("-", ""))
        with self.assertRaises(ValueError):
            licenca._codigo_do_guid("0" * 32)

    def test_ativacao_reabre_e_falha_na_troca_preserva_licenca(self):
        with tempfile.TemporaryDirectory() as pasta, patch.dict("os.environ", LOCALAPPDATA=pasta):
            self.assertEqual(licenca.ler_chave(), "")
            chave = self.emitir()
            licenca.salvar_chave(chave)
            self.assertEqual(licenca.validar_chave(licenca.ler_chave(), PC).pc, PC)
            with patch("licenca.os.replace", side_effect=PermissionError), self.assertRaises(PermissionError):
                licenca.salvar_chave(self.emitir(expira=date.today()))
            self.assertEqual(licenca.ler_chave(), chave)
            self.assertEqual(list(Path(pasta).rglob("*.tmp")), [])

    def emitir_venda(self, dias=30):
        carga = licenca.carga_venda(dias)
        return licenca.montar_chave(carga, self.segredo.sign(carga))

    def test_venda_e_assinada_distinta_e_nao_libera_offline(self):
        chave = self.emitir_venda()
        self.assertNotEqual(chave, self.emitir_venda())
        self.assertEqual(licenca.verificar_venda(chave), 30)
        with self.assertRaises(ValueError):
            licenca.validar_chave(chave, PC)
        for dias in (-1, True, 36501):
            with self.assertRaises(ValueError):
                licenca.carga_venda(dias)

    def test_cliente_confere_venda_e_pc_do_recibo_antes_de_aceitar(self):
        chave = self.emitir_venda(1)
        servidor = Ed25519PrivateKey.generate()
        self.enterContext(patch.object(licenca, "CHAVE_SERVIDOR", servidor.public_key().public_bytes_raw()))
        data = licenca.hoje_licenca(True)

        def responder(venda, pc):
            carga = (licenca._RECIBO + hashlib.sha256(venda.encode("ascii")).digest()
                     + bytes.fromhex(pc) + data.toordinal().to_bytes(4, "big"))
            recibo = licenca.montar_chave(carga, servidor.sign(carga))
            resposta = MagicMock()
            resposta.read.return_value = json.dumps({"licenca": recibo}).encode()
            resposta.headers.get_content_type.return_value = "application/json"
            abrir.return_value.__enter__.return_value = resposta
            return recibo

        abrir = self.enterContext(patch("licenca.build_opener")).return_value.open
        recibo = responder(chave, PC)
        self.assertEqual(licenca.ativar_venda(chave, PC), recibo)
        req = abrir.call_args.args[0]
        self.assertEqual(json.loads(req.data), {"chave": chave, "pc": PC})
        self.assertEqual(req.full_url, licenca.URL_ATIVACAO)
        with tempfile.TemporaryDirectory() as pasta, patch.dict("os.environ", LOCALAPPDATA=pasta):
            licenca.salvar_chave(recibo)
            self.assertEqual(licenca.validar_chave(licenca.ler_chave(), PC), licenca.Licenca(PC, data, True))
        with self.assertRaisesRegex(ValueError, "outro PC"):
            licenca.validar_chave(recibo, OUTRO_PC)
        responder(self.emitir_venda(1), PC)
        with self.assertRaisesRegex(ValueError, "comprovante"):
            licenca.ativar_venda(chave, PC)
        responder(chave, OUTRO_PC)
        with self.assertRaisesRegex(ValueError, "outro PC"):
            licenca.ativar_venda(chave, PC)

    def test_recusa_concorrencia_expiracao_e_servidor_privado(self):
        venda = self.emitir_venda()
        abrir = self.enterContext(patch("licenca.build_opener")).return_value.open
        for codigo, excecao, mensagem in ((409, ValueError, "outro PC"), (410, ValueError, "venceu"),
                                          (302, OSError, "indisponível"), (403, OSError, "indisponível")):
            with self.subTest(codigo=codigo):
                abrir.side_effect = HTTPError(licenca.URL_ATIVACAO, codigo, "", {}, None)
                with self.assertRaisesRegex(excecao, mensagem):
                    licenca.ativar_venda(venda, PC)
