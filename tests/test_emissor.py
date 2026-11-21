from datetime import date, timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import emissor
import licenca


class EmissaoTest(unittest.TestCase):
    def setUp(self):
        pasta = TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.pasta = Path(pasta.name)
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": pasta.name}))
        # Material sintético destinado exclusivamente ao teste.
        self.simulada = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.publica = self.simulada.public_key().public_bytes_raw()
        self.enterContext(patch.object(licenca, "CHAVE_PUBLICA", self.publica))
        self.pc = "01AB" * 8

    def test_sem_segredo_nao_emite_nem_cria_um_substituto(self):
        with self.assertRaises(FileNotFoundError):
            emissor.emitir(self.pc, None)
        with self.assertRaisesRegex(ValueError, "backup"):
            emissor.provisionar()
        self.assertFalse(emissor._cofre().exists())

    def test_provisiona_uma_vez_e_emite_reconhecida_pelo_cliente(self):
        with patch.object(licenca, "CHAVE_PUBLICA", b""), patch.object(
                Ed25519PrivateKey, "generate", return_value=self.simulada) as gerar:
            self.assertEqual(emissor.provisionar(), self.publica)
            self.assertEqual(emissor.provisionar(), self.publica)
            gerar.assert_called_once()
        self.assertNotIn(self.simulada.private_bytes_raw(), emissor._cofre().read_bytes())
        for fim in (None, date.today() + timedelta(days=5)):
            token = emissor.emitir(self.pc.lower(), fim)
            self.assertEqual(licenca.validar_chave(token, self.pc).expira, fim)
            with self.assertRaisesRegex(ValueError, "outro PC"):
                licenca.validar_chave(token, "12AB" * 8)
        with self.assertRaisesRegex(ValueError, "passou"):
            emissor.emitir(self.pc, date.today() - timedelta(days=1))

    def test_backup_protegido_recupera_assinatura_e_recusa_senha_ou_emissor_errado(self):
        emissor._guardar_no_perfil(self.simulada)
        backup = self.pasta / "copia.pem"
        senha = "somente-nos-testes-01"
        with self.assertRaisesRegex(ValueError, "12 caracteres"):
            emissor.exportar_backup(backup, "curta")
        self.assertFalse(backup.exists())
        emissor.exportar_backup(backup, senha)
        original = backup.read_bytes()
        self.assertIn(b"ENCRYPTED PRIVATE KEY", original)
        with self.assertRaisesRegex(ValueError, "Já existe"):
            emissor.exportar_backup(backup, senha + "!")
        self.assertEqual(backup.read_bytes(), original)
        cofre_original = emissor._cofre().read_bytes()
        outro_backup = self.pasta / "outro.pem"
        estrangeira = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
        with patch.object(licenca, "CHAVE_PUBLICA", estrangeira.public_key().public_bytes_raw()), patch.object(
                emissor, "_abrir_cofre", return_value=estrangeira):
            emissor.exportar_backup(outro_backup, senha)
        with self.assertRaisesRegex(ValueError, "outro aplicativo"):
            emissor.restaurar_backup(outro_backup, senha)
        with self.assertRaisesRegex(ValueError, "senha"):
            emissor.restaurar_backup(backup, senha + "!")
        self.assertEqual(emissor._cofre().read_bytes(), cofre_original)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.pasta / "outro-perfil")}):
            with self.assertRaisesRegex(ValueError, "senha"):
                emissor.restaurar_backup(backup, senha + "!")
            self.assertFalse(emissor._cofre().exists())
            emissor.restaurar_backup(backup, senha)
            token = emissor.emitir(self.pc, None)
            self.assertEqual(licenca.validar_chave(token, self.pc).pc, self.pc)

    def test_prazos_incluem_o_dia_da_emissao(self):
        hoje = date(2030, 12, 31)
        self.assertEqual(emissor.vencimento("Personalizado", "1", hoje), hoje)
        self.assertEqual(emissor.vencimento("30 dias", "", hoje), date(2031, 1, 29))
        self.assertIsNone(emissor.vencimento("Vitalícia", "", hoje))
        for invalido in ("", "x", "-2", "0", "36501"):
            with self.assertRaises(ValueError):
                emissor.vencimento("Personalizado", invalido, hoje)

    def test_editar_cliente_ou_prazo_invalida_a_licenca_exibida(self):
        emissor._guardar_no_perfil(self.simulada)
        raiz = tk.Tk()
        raiz.withdraw()
        self.addCleanup(raiz.destroy)
        janela = emissor.Emissor(raiz)
        janela.pc.set(self.pc)
        janela.gerar()
        self.assertEqual(licenca.validar_chave(janela.resultado.get(), self.pc).pc, self.pc)
        janela.pc.set("12ab" * 8)
        self.assertEqual(janela.resultado.get(), "")
        self.assertTrue(janela.copiar.instate(["disabled"]))
        janela.gerar()
        janela.prazo.set("Vitalícia")
        self.assertEqual(janela.resultado.get(), "")
        janela.gerar()
        self.assertIsNone(licenca.validar_chave(janela.resultado.get(), janela.pc.get()).expira)


if __name__ == "__main__":
    unittest.main()
