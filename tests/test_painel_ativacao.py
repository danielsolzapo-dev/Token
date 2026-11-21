from datetime import date, timedelta
from threading import Event
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import app
from painel_ativacao import JanelaAtivacao, obter_licenca


class AtivacaoTest(unittest.TestCase):
    def setUp(self):
        self.janela = tk.Tk()
        self.janela.withdraw()
        self.addCleanup(self.janela.destroy)

    def test_ativar_so_libera_depois_de_validar_e_persistir(self):
        tela = JanelaAtivacao(self.janela, "PC")
        with patch("painel_ativacao.validar_chave") as validar, patch("painel_ativacao.salvar_chave") as salvar:
            tela.ativar()
            validar.assert_not_called()
            tela.chave.set("outra")
            validar.side_effect = ValueError("Chave de outro PC.")
            tela.ativar()
            self.assertEqual(tela.aviso.get(), "Chave de outro PC.")
            salvar.assert_not_called()
            self.assertIsNone(tela.licenca)

            validar.side_effect = None
            tela.chave.set("  minha  ")
            salvar.side_effect = OSError("sem acesso")
            tela.ativar()
            self.assertIsNone(tela.licenca)
            self.assertTrue(tela.winfo_exists())
            salvar.side_effect = None
            tela.ativar()
            validar.assert_called_with("minha", "PC")
            salvar.assert_called_with("minha")
            self.assertIs(tela.licenca, validar.return_value)
            self.assertFalse(tela.winfo_exists())

    def test_licenca_salva_valida_abre_sem_dialogo(self):
        with (patch("painel_ativacao.codigo_pc", return_value="PC"),
              patch("painel_ativacao.ler_chave", return_value="salva"),
              patch("painel_ativacao.validar_chave") as validar,
              patch("painel_ativacao.JanelaAtivacao") as tela):
            self.assertIs(obter_licenca(self.janela), validar.return_value)
            validar.assert_called_once_with("salva", "PC")
            tela.assert_not_called()

    def test_chave_salva_expirada_oferece_renovacao_e_permite_cancelar(self):
        estado = []

        def fechar_dialogo():
            tela, = self.janela.winfo_children()
            estado.append(tela.aviso.get())
            tela.destroy()

        self.janela.after_idle(fechar_dialogo)
        with (patch("painel_ativacao.codigo_pc", return_value="PC"),
              patch("painel_ativacao.ler_chave", return_value="vencida"),
              patch("painel_ativacao.validar_chave", side_effect=ValueError("Licença expirada."))):
            self.assertIsNone(obter_licenca(self.janela))
            self.assertEqual(estado, ["Licença expirada."])

    def test_cancelar_ativacao_nao_inicializa_atalhos_nem_painel(self):
        with (patch("app.carregar_inter"), patch.object(app.sys, "argv", ["app"]),
              patch("app.obter_licenca", return_value=None), patch("app.Windows") as windows,
              patch("app.Painel") as painel):
            app.main()
            windows.assert_not_called()
            painel.assert_not_called()

    def test_expiracao_com_sessao_ativa_para_antes_do_atalho_e_aguarda_worker(self):
        painel = app.Painel(self.janela, Mock(), app.Config(atualizar_auto=False),
                            expira=date.today() - timedelta(days=1))
        self.addCleanup(painel.salvamento.shutdown)
        janela_replay = tk.Toplevel(self.janela)
        painel.worker = Mock()
        painel.worker.is_alive.return_value = True
        painel.parar = Event()
        self.janela.after_cancel(painel._callback_interface)
        painel.atualizar()
        self.assertTrue(painel.licenca_expirada)
        self.assertTrue(painel.parar.is_set())
        self.assertFalse(janela_replay.winfo_exists())
        painel.windows.f6_pressionado.assert_not_called()
        painel.worker.is_alive.return_value = False
        with patch.object(self.janela, "destroy") as destruir:
            painel.encerrar_por_vencimento()
            destruir.assert_called_once()

    def test_app_volta_para_ativacao_so_depois_de_encerrar_sessao_vencida(self):
        licenca = SimpleNamespace(expira=date.today())
        with (patch("app.carregar_inter"), patch.object(app.sys, "argv", ["app"]),
              patch("app.tk.Tk") as raiz,
              patch("app.obter_licenca", side_effect=[licenca, None]) as obter,
              patch("app.executar_painel", return_value=True) as painel):
            app.main()
            self.assertEqual(obter.call_count, 2)
            painel.assert_called_once_with(raiz.return_value, licenca)


if __name__ == "__main__":
    unittest.main()
