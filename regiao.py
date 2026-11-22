"""Programação de Brasília e navegação visual das opções de pareamento."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


BRASILIA = timezone(timedelta(hours=-3))
MANHA = ("Ásia", "Oceania")
AMERICA_DO_NORTE = "América do Norte"
NOITE = ("Brasil", AMERICA_DO_NORTE)
NORTE_LEGADO = ("NA-Leste", "NA-Central", "NA-Oeste")
NOMES = {
    "Automática": ("AUTOMATICA", "AUTOMATICO", "AUTO", "AUTOMATIC"),
    "Ásia": ("ASIA",),
    "Oceania": ("OCEANIA", "OCEANIC"),
    "Europa": ("EUROPA", "EUROPE"),
    "Brasil": ("BRASIL", "BRAZIL"),
    AMERICA_DO_NORTE: ("AMERICA DO NORTE", "MERICA DO NORTE", "NERICA DO NORTE",
                       "NORTH AMERICA", "NORTE", "JORTE", "NA"),
    "NA-Leste": ("AN LESTE", "NA LESTE", "NA EAST", "LESTE", "EAST", "US EAST"),
    "NA-Central": ("AN CENTRAL", "NA CENTRAL", "CENTRAL", "US CENTRAL"),
    "NA-Oeste": ("AN OESTE", "NA OESTE", "NA WEST", "OESTE", "WEST", "US WEST"),
    "Virginia": ("VIRGINIA",),
    "Ohio": ("OHIO", "OHI0"),
    "Iowa": ("IOWA",),
    "Texas": ("TEXAS",),
    "México": ("MEXICO",),
    "Norte da Califórnia": ("NORTE DA CALIFORNIA", "NORTHERN CALIFORNIA"),
    "Oregon": ("OREGON", "OREG0N"),
    "Oriente Médio": ("ORIENTE MEDIO", "MIDDLE EAST"),
}


def regiao_principal(regiao):
    return AMERICA_DO_NORTE if regiao in NORTE_LEGADO else regiao


def regiao_por_horario(manha=MANHA[0], noite=NOITE[0], instante=None):
    hora = (instante or datetime.now(BRASILIA)).astimezone(BRASILIA).hour
    if hora < 6:
        return AMERICA_DO_NORTE
    if hora < 11:
        return manha if manha in MANHA else MANHA[0]
    if hora < 18:
        return "Europa"
    noite = regiao_principal(noite)
    return noite if noite in NOITE else NOITE[0]


def identificar_regiao(texto):
    from texto_tela import normalizar

    valor = normalizar(re.split(r"\(|\s+\d", texto, maxsplit=1)[0])
    return next((nome for nome, aliases in NOMES.items() if valor in aliases), None)


@dataclass(frozen=True)
class LinhaRegiao:
    caixa: tuple[int, int, int, int]
    valor: str | None
    direita: tuple | None = None
    esquerda: tuple | None = None
    focada: bool = False


@dataclass(frozen=True)
class TelaRegiao:
    social: bool = False
    configuracoes: bool = False
    engrenagem: tuple | None = None
    aba_jogo: tuple | None = None
    pareamento: LinhaRegiao | None = None
    subregiao: LinhaRegiao | None = None
    aplicar: tuple | None = None
    voltar: tuple | None = None
    descartar: tuple | None = None
    salvar: tuple | None = None
    dialogo_alteracoes: bool = False


def ler_tela_regiao(linhas, largura, altura):
    from texto_tela import normalizar

    rotulos = [(linha, normalizar(linha.texto)) for linha in linhas]
    rodape = [(linha, texto) for linha, texto in rotulos if linha.centro[1] >= 0.86 * altura]
    rodape_direito = [(linha, texto) for linha, texto in rodape if linha.centro[0] >= 0.60 * largura]
    aplicar = next((l.caixa for l, t in rodape
                    if t in {"APLICAR", "A APLICAR", "AAPLICAR", "APPLY", "A APPLY", "AAPPLY"}), None)
    voltar = next((l.caixa for l, t in rodape if t in {"VOLTAR", "ESC VOLTAR", "BACK", "ESC BACK"}), None)
    restaurar = any(re.search(r"\b(?:RESTAURAR (?:O )?PADR(?:AO|A0)|RESTORE TO DEFAULT)\b", t)
                    for _, t in rodape_direito)
    if restaurar and not voltar:
        voltar = next((l.caixa for l, t in rodape_direito
                       if re.fullmatch(r"(?:ES|SC|E5C)? ?(?:VOLTAR|BACK)", t)), None)
    titulo = any(t in {"IDIOMA E REGIAO", "LANGUAGE AND REGION"} and l.centro[1] < 0.30 * altura
                 for l, t in rotulos)
    a_direita = [(l, t) for l, t in rotulos if l.centro[0] > 0.65 * largura]
    menu_lobby = {"FECHAR O FORTNITE", "SAIR DO GRUPO", "ENTRAR NO MODO DE SUSPENSAO",
                  "CONTROLE DOS PAIS", "GERENCIAR CONTEUDO DESBLOQUEADO", "SUPORTE E REEMBOLSO",
                  "CLOSE FORTNITE", "LEAVE PARTY", "ENTER SLEEP MODE", "PARENTAL CONTROLS",
                  "MANAGE UNLOCKED CONTENT", "SUPPORT AND REFUNDS"}
    social = (any(l.centro[1] < 0.35 * altura and t in
                  {"SOCIAL", "EPIC ONLINE", "ONLINE NA EPIC", "AMIGOS EPIC", "AMIGOS", "FRIENDS"}
                  for l, t in a_direita)
              or len({t for l, t in a_direita if 0.10 * altura < l.centro[1] < 0.72 * altura
                      and t in menu_lobby}) >= 2)
    engrenagem = next((l.caixa for l, t in rotulos if l.centro[0] > 0.58 * largura
                       and t in {"CONFIGURACOES", "SETTINGS"}), None)
    tem_dialogo = any(any(p in t for p in ("CONFIGURACOES MODIFICADAS", "ALTERACOES NAO SALVAS",
                                           "SALVAR ALTERACOES", "APLICAR ALTERACOES", "SETTINGS CHANGED",
                                           "DISCARD CHANGES", "UNSAVED CHANGES"))
                      and 0.2 * altura < l.centro[1] < 0.65 * altura for l, t in rotulos)
    botoes = [(l, t) for l, t in rotulos if 0.15 * largura < l.centro[0] < 0.85 * largura
              and 0.45 * altura < l.centro[1] < 0.90 * altura]
    for salvar, texto in botoes:
        if texto not in {"SALVAR", "SAVE", "SIM", "YES"}:
            continue
        descartar = next((l for l, t in botoes if t in {"NAO SALVAR", "DONT SAVE", "DO NOT SAVE",
                          "DESCARTAR", "DESCARTAR ALTERACOES", "NAO", "DISCARD", "NO"}
                          and salvar.centro[0] < l.centro[0]
                          and abs(salvar.centro[1] - l.centro[1]) <= 0.055 * altura), None)
        if descartar:
            return TelaRegiao(descartar=descartar.caixa, salvar=salvar.caixa, dialogo_alteracoes=True)
    if tem_dialogo:
        return TelaRegiao(dialogo_alteracoes=True)
    configuracoes = titulo or bool(voltar and restaurar)

    def linha_regiao(predicado):
        focada = any(0.55 * largura <= l.caixa[0] and 0.12 * altura <= l.centro[1] <= 0.40 * altura
                     and predicado(t) is not None for l, t in rotulos)
        linhas_sem_valor = []
        for rotulo, sufixo in ((l, predicado(t)) for l, t in rotulos):
            if (sufixo is None or not 0.14 * altura <= rotulo.centro[1] <= 0.46 * altura
                    or not 0.10 * largura <= rotulo.caixa[0] <= 0.44 * largura):
                continue
            direita = [(l, identificar_regiao(l.texto)) for l, _ in rotulos
                       if rotulo.caixa[0] + 0.13 * largura < l.caixa[0] < 0.67 * largura
                       and abs(l.centro[1] - rotulo.centro[1]) < 0.028 * altura]
            for linha, valor in direita:
                if valor:
                    return LinhaRegiao(linha.caixa, valor, focada=focada)
            # A linha pode virar uma só caixa ao ganhar destaque. Mantém a posição
            # do seletor ancorada no rótulo mesmo quando o texto do valor se perde.
            x, y, w, h = rotulo.caixa
            valor = identificar_regiao(sufixo)
            caixa_valor = round(x + 0.17 * largura), y, round(0.12 * largura), h
            linha = LinhaRegiao(caixa_valor, valor, focada=focada)
            if valor:
                return linha
            linhas_sem_valor.append(linha)
        return linhas_sem_valor[0] if linhas_sem_valor else None

    def rotulo_pareamento(texto):
        trecho = re.match(r"(?:R?EGIAO (?:DE |DO )?PAREAMENT[O0]?|MATCHMAKING REGION)\b\s*(.*)", texto)
        return trecho[1] if trecho else None

    def rotulo_subregiao(texto):
        trecho = re.match(r"(?:.*?DE SUBREGI(?:A[O0]?)?|SUBREGION PREFERENCE)\b\s*(.*)", texto)
        return trecho[1] if trecho else None

    pareamento = linha_regiao(rotulo_pareamento) if configuracoes else None
    subregiao = linha_regiao(rotulo_subregiao) if configuracoes else None
    aba_jogo = (round(largura / 2 - altura * 0.19), round(altura * 0.018),
                round(altura * 0.06), round(altura * 0.05))
    return TelaRegiao(social, configuracoes, engrenagem, aba_jogo if configuracoes and not (titulo or pareamento) else None,
                      pareamento, subregiao, aplicar, voltar)


@dataclass(frozen=True)
class OrdemRegiao:
    tipo: str
    etapa: str
    caixa: tuple | None = None
    tecla: int | None = None
    tentativa: int = 0


class RegiaoLobby:
    def __init__(self):
        self.alvo = self.confirmada = self.falhou = None
        self.repetir_em = 0.0
        self.ultima_submissao = self.fechando = None
        self.valor_anterior = None
        self.tentativas = 0
        self.visitados = set()
        self.sentido = "direita"
        self.alterou = False
        self._alvo_confirmado = False
        self._prazo_confirmacao_prorrogado = False
        self.proxima = self.prazo = 0.0
        self._assinatura = None
        self._ultima_mudanca = 0.0
        self._apontou = self._selecionou = False
        self._esc_social = 0
        self.ultima_tela = None
        self._etapa_anterior = None
        self._tentativas_etapa = 0

    def iniciar(self, alvo, agora, *, perfil=None):
        alvo = regiao_principal(alvo)
        if alvo == self.confirmada or (alvo == self.falhou and agora < self.repetir_em):
            return None
        self.confirmada = None
        self.alvo = alvo
        self.proxima, self.prazo = agora + 0.8, agora + 95
        self.ultima_submissao = self.fechando = None
        self.valor_anterior = None
        self.tentativas = 0
        self.visitados.clear()
        self.sentido = "direita"
        self.alterou = False
        self._alvo_confirmado = False
        self._prazo_confirmacao_prorrogado = False
        self._assinatura, self._ultima_mudanca = None, agora
        self._apontou = self._selecionou = False
        self._esc_social = 1
        self.ultima_tela = None
        self._etapa_anterior = None
        self._tentativas_etapa = 0
        if perfil:
            return OrdemRegiao("clicar", "abrir_social", perfil)
        return OrdemRegiao("esc", "abrir_social")

    def pronto(self, agora):
        return self.alvo is not None and agora >= self.proxima

    def cancelar(self, agora):
        self.fechando = False
        self.prazo = agora

    def _ordem(self, agora, tipo, etapa, caixa=None, tecla=None):
        if etapa != self._etapa_anterior:
            self._etapa_anterior, self._tentativas_etapa = etapa, 0
        tentativa = self._tentativas_etapa
        self._tentativas_etapa += 1
        self.proxima = agora + (0.65 if tipo == "apontar" else 0.85)
        return OrdemRegiao(tipo, etapa, caixa, tecla, tentativa)

    def _terminar(self, agora, ok):
        if ok:
            self.confirmada = self.alvo
        else:
            self.falhou, self.repetir_em = self.alvo, agora + 20 * 60
        self.alvo = None
        return OrdemRegiao("ok" if ok else "falhou", "fim")

    def passo(self, tela, agora, *, lobby=False):
        if not self.pronto(agora):
            return None
        self.ultima_tela = tela
        principal = tela.pareamento
        assinatura = (tela.social, tela.configuracoes, principal and (principal.valor, principal.focada),
                      bool(tela.aplicar), tela.dialogo_alteracoes, lobby)
        if assinatura != self._assinatura:
            self._assinatura, self._ultima_mudanca = assinatura, agora
        if self.fechando is None and (agora >= self.prazo or agora - self._ultima_mudanca >= 14):
            self.fechando = self._alvo_confirmado
            self.prazo = agora
        if self.fechando is not None:
            if agora >= self.prazo + 25:
                return self._terminar(agora, False)
            if tela.dialogo_alteracoes:
                caixa = tela.salvar if self._alvo_confirmado else tela.descartar
                return self._ordem(agora, "clicar", "salvar" if self.fechando else "descartar", caixa) if caixa else None
            if tela.configuracoes:
                if tela.voltar:
                    return self._ordem(agora, "clicar", "fechar_configuracoes", tela.voltar)
                return self._ordem(agora, "esc", "fechar_configuracoes")
            if tela.social:
                return self._ordem(agora, "esc", "fechar_social")
            if lobby:
                return self._terminar(agora, bool(self.fechando and self._alvo_confirmado))
            return None

        if principal:
            if regiao_principal(principal.valor) == self.alvo:
                self._alvo_confirmado = True
                if self.alterou and not self._prazo_confirmacao_prorrogado:
                    # A leitura do destino confirma que o seletor chegou à
                    # opção pedida; reserva tempo para aplicar, salvar e
                    # reconhecer o retorno ao lobby em máquinas lentas.
                    self.prazo = max(self.prazo, agora + 60)
                    self._prazo_confirmacao_prorrogado = True
                if self.alterou and self.ultima_submissao is None:
                    self.ultima_submissao = agora
                    self.prazo = max(self.prazo, agora + 14)
                    return self._ordem(agora, "tecla", "aplicar", tecla=0x1E)
                if self.alterou and tela.aplicar:
                    return self._ordem(agora, "clicar", "aplicar", tela.aplicar)
                self.fechando = True
                self.prazo = min(self.prazo, agora + 8)
                if tela.voltar:
                    return self._ordem(agora, "clicar", "fechar_configuracoes", tela.voltar)
                return self._ordem(agora, "esc", "fechar_configuracoes")
            return self._ajustar(agora, principal)
        if tela.aba_jogo:
            return self._ordem(agora, "clicar", "abrir_aba_jogo", tela.aba_jogo)
        if tela.social and tela.engrenagem:
            return self._ordem(agora, "clicar", "abrir_configuracoes", tela.engrenagem)
        if lobby and not (tela.social or tela.configuracoes) and self._esc_social < 2:
            self._esc_social += 1
            return self._ordem(agora, "esc", "abrir_social")
        return None

    def _ajustar(self, agora, linha):
        if linha.valor != self.valor_anterior:
            self.valor_anterior = linha.valor
            self.tentativas = 0
        seta = getattr(linha, self.sentido)
        if linha.valor and (self.sentido, linha.valor) in self.visitados and self.tentativas != 1:
            self.sentido = "esquerda" if self.sentido == "direita" else "direita"
            seta = getattr(linha, self.sentido)
        if not seta:
            seta = linha.esquerda if self.sentido == "direita" else linha.direita
            if seta:
                self.sentido = "esquerda" if self.sentido == "direita" else "direita"
        if seta is None:
            if not self._apontou:
                self._apontou = True
                return self._ordem(agora, "apontar", "pareamento", linha.caixa)
            if not linha.focada:
                if not self._selecionou:
                    self._selecionou = True
                    return self._ordem(agora, "clicar", "selecionar_pareamento", linha.caixa)
                return None
        if linha.valor:
            self.visitados.add((self.sentido, linha.valor))
        self.tentativas += 1
        self.alterou = True
        if seta:
            return self._ordem(agora, "clicar", "pareamento", seta)
        tecla = 0xE04D if self.sentido == "direita" else 0xE04B
        return self._ordem(agora, "tecla", "pareamento", tecla=tecla)
