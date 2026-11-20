"""Decisões do lobby que têm prioridade sobre fila, menus e movimento."""

import time

from avisos_lobby import DetectorAvisosLobby
from logica_autofarm import Acao, Alvo
from pesquisa_lobby import DetectorPesquisa
from restricao_pareamento import RestricaoPareamento, botao_lobby_liberado


class MonitorLobby:
    def __init__(self):
        self.avisos = DetectorAvisosLobby()
        self.pesquisas = DetectorPesquisa()
        self.restricao = RestricaoPareamento()
        self.ban_notificado = False
        self.tela = None
        self.ausencias = 0
        self.pausa_token_aplicada = False
        self.tentativas = 0
        self.proximo_clique = 0.0

    def reconhecer(self, quadro):
        return self.avisos.reconhecer(quadro) or self.pesquisas.reconhecer(quadro)

    def passo(self, quadro, fluxo, eventos, diagnostico, *, agora=None):
        """Devolve estado, clique opcional e pedido de pausa para a tela presente."""
        aviso = self.reconhecer(quadro)
        tipo = aviso.tipo if aviso else None
        modal_ban = tipo == "conta_banida"
        faixa = self.avisos.pareamento_restrito(quadro) if not aviso else False
        if aviso is None and not (faixa or self.restricao.ativa or self.tela):
            return None
        if agora is None:
            agora = time.monotonic()
        botao = (botao_lobby_liberado(quadro, fluxo.detector)
                 if self.restricao.ativa and not (aviso or faixa) else None)
        mudanca = self.restricao.observar(agora, modal=modal_ban, faixa_restrita=faixa, botao_lobby=botao)
        if mudanca:
            if diagnostico:
                diagnostico.registrar("restricao_pareamento", estado=mudanca)
            if mudanca == "inicio":
                fluxo.reconhecer_retorno_ao_lobby()
            elif mudanca == "liberada":
                self.ban_notificado = False
                eventos.put(("acao", "Pareamento liberado pelo jogo. Retomando a sessão."))

        if aviso is None:
            if self.tela:
                self.ausencias += 1
                if self.ausencias < 3:
                    return "Conferindo o lobby", None, False
                self.tela = None
            if self.restricao.ativa:
                return "Aguardando liberação do pareamento", None, False
            return None

        nova = tipo != self.tela
        self.ausencias = 0
        if nova:
            self.tela = tipo
            self.tentativas = 0
            self.proximo_clique = agora
            self.pausa_token_aplicada = False
            if tipo == "token_loja_pirata":
                fluxo.reconhecer_retorno_ao_lobby()
            if diagnostico:
                diagnostico.registrar("aviso_lobby", tipo=tipo, nome=aviso.nome)
        if (tipo == "token_loja_pirata" and nova) or (modal_ban and not self.ban_notificado):
            if fluxo.config.webhook_url:
                eventos.put(("aviso_webhook", (fluxo.config.webhook_url, tipo, aviso.nome, quadro.copy())))
            if modal_ban:
                self.ban_notificado = True

        if tipo == "token_loja_pirata":
            if fluxo.config.pausar_ao_obter_token and not self.pausa_token_aplicada:
                self.pausa_token_aplicada = True
                return "Token da Loja Pirata detectado", None, True
            estado = "Token da Loja Pirata desbloqueado"
            clicar = fluxo.config.resgatar_recompensas
            alvo = "resgatar_token"
        elif modal_ban:
            estado = "Conta banida · aguardando liberação"
            clicar = self.restricao.pode_fechar_aviso(agora)
            alvo = "continuar_aviso_ban"
        else:
            estado = "Pesquisa de feedback"
            clicar = True
            alvo = "pular_pesquisa"

        acao = None
        if clicar and aviso.centro_botao is not None and agora >= self.proximo_clique:
            x, y = aviso.centro_botao
            acao = Acao("clicar", Alvo(alvo, 1.0, (x, y, 0, 0), None), tentativa=self.tentativas)
            self.tentativas += 1
            self.proximo_clique = agora + (2 if self.tentativas <= 3 else 10)
            if modal_ban:
                self.restricao.registrar_tentativa(agora)
        return estado, acao, False
