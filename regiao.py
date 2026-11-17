"""Programação de Brasília e navegação visual das opções de pareamento."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


BRASILIA = timezone(timedelta(hours=-3))
MANHA = ("Ásia", "Oceania")
NOITE = ("Brasil", "NA-Leste", "NA-Central")
NORTE = {"NA-Leste", "NA-Central", "NA-Oeste"}
AMERICA_DO_NORTE = "América do Norte"
NOMES = {
    "Automática": ("AUTOMATICA", "AUTOMATICO", "AUTO", "AUTOMATIC"),
    "Ásia": ("ASIA",),
    "Oceania": ("OCEANIA", "OCEANIC"),
    "Europa": ("EUROPA", "EUROPE"),
    "Brasil": ("BRASIL", "BRAZIL"),
    AMERICA_DO_NORTE: ("AMERICA DO NORTE", "NORTH AMERICA", "NORTE", "JORTE", "NA"),
    "NA-Leste": ("AN LESTE", "NA LESTE", "NA EAST", "LESTE", "EAST", "US EAST"),
    "NA-Central": ("AN CENTRAL", "NA CENTRAL", "CENTRAL", "US CENTRAL"),
    "NA-Oeste": ("AN OESTE", "NA OESTE", "NA WEST", "OESTE", "WEST", "US WEST"),
    "Oriente Médio": ("ORIENTE MEDIO", "MIDDLE EAST"),
}


def regiao_por_horario(manha=MANHA[0], noite=NOITE[0], instante=None):
    hora = (instante or datetime.now(BRASILIA)).astimezone(BRASILIA).hour
    if hora < 6:
        return "NA-Oeste"
    if hora < 11:
        return manha if manha in MANHA else MANHA[0]
    if hora < 18:
        return "Europa"
    return noite if noite in NOITE else NOITE[0]


def identificar_regiao(texto):
    from texto_tela import normalizar

    valor = normalizar(re.split(r"\(|\d", texto, maxsplit=1)[0])
    return next((nome for nome, aliases in NOMES.items() if valor in aliases), None)


@dataclass(frozen=True)
class LinhaRegiao:
    caixa: tuple[int, int, int, int]
    valor: str
    direita: tuple | None = None
    esquerda: tuple | None = None


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


def ler_tela_regiao(linhas, largura, altura):
    from texto_tela import normalizar

    rotulos = [(linha, normalizar(linha.texto)) for linha in linhas]
    rodape = [(linha, texto) for linha, texto in rotulos if linha.centro[1] >= 0.86 * altura]
    aplicar = next((l.caixa for l, t in rodape if t in {"APLICAR", "A APLICAR", "APPLY", "A APPLY"}), None)
    voltar = next((l.caixa for l, t in rodape if t in {"VOLTAR", "ESC VOLTAR", "BACK", "ESC BACK"}), None)
    restaurar = any("RESTAURAR PADRAO" in t or "RESTORE TO DEFAULT" in t for _, t in rodape)
    titulo = any(t in {"IDIOMA E REGIAO", "LANGUAGE AND REGION"} and l.centro[1] < 0.30 * altura
                 for l, t in rotulos)
    social = any(l.centro[0] > 0.65 * largura and l.centro[1] < 0.35 * altura
                 and t in {"SOCIAL", "EPIC ONLINE", "ONLINE NA EPIC", "AMIGOS EPIC"} for l, t in rotulos)
    engrenagem = next((l.caixa for l, t in rotulos if l.centro[0] > 0.58 * largura
                       and t in {"CONFIGURACOES", "SETTINGS"}), None)
    tem_dialogo = any(any(p in t for p in ("SALVAR ALTERACOES", "APLICAR ALTERACOES",
                                           "DISCARD CHANGES", "UNSAVED CHANGES"))
                      and 0.2 * altura < l.centro[1] < 0.65 * altura for l, t in rotulos)
    descartar = next((l.caixa for l, t in rotulos if tem_dialogo and 0.35 * altura < l.centro[1] < 0.90 * altura
                       and t in {"DESCARTAR", "DESCARTAR ALTERACOES", "NAO", "DISCARD", "NO"}), None)
    configuracoes = titulo or bool(voltar and restaurar)

    def linha_regiao(predicado):
        for rotulo, texto in rotulos:
            if not (0.14 * altura <= rotulo.centro[1] <= 0.46 * altura and
                    0.20 * largura < rotulo.centro[0] <= 0.50 * largura and predicado(texto)):
                continue
            direita = [(l, identificar_regiao(l.texto)) for l, _ in rotulos
                       if rotulo.caixa[0] + 0.13 * largura < l.caixa[0] < 0.65 * largura
                       and abs(l.centro[1] - rotulo.centro[1]) < 0.028 * altura]
            for linha, valor in direita:
                if valor:
                    return LinhaRegiao(linha.caixa, valor)
        return None

    pareamento = linha_regiao(lambda t: t.startswith(("REGIAO DE PAREAMENT", "MATCHMAKING REGION"))) if titulo else None
    subregiao = linha_regiao(lambda t: "DE SUBREGI" in t or "SUBREGION PREFERENCE" in t) if titulo else None
    aba_jogo = (round(largura * 0.38), round(altura * 0.023), round(largura * 0.04), round(altura * 0.04))
    return TelaRegiao(social, configuracoes, engrenagem, aba_jogo if configuracoes and not titulo else None,
                      pareamento, subregiao, aplicar, voltar, descartar)


@dataclass(frozen=True)
class OrdemRegiao:
    tipo: str
    etapa: str
    caixa: tuple | None = None


class RegiaoLobby:
    def __init__(self):
        self.alvo = self.confirmada = self.falhou = None
        self.repetir_em = 0.0
        self.ultima_submissao = self.fechando = None
        self.linha = self.valor_anterior = None
        self.tentativas = 0
        self.visitados = set()
        self.sentido = "direita"
        self.alterou = False
        self.proxima = self.prazo = 0.0

    def iniciar(self, alvo, agora):
        if alvo == self.confirmada or (alvo == self.falhou and agora < self.repetir_em):
            return None
        self.confirmada = None
        self.alvo = alvo
        self.proxima, self.prazo = agora + 0.8, agora + 95
        self.ultima_submissao = self.fechando = None
        self.linha = self.valor_anterior = None
        self.tentativas = 0
        self.visitados.clear()
        self.sentido = "direita"
        self.alterou = False
        return OrdemRegiao("esc", "abrir_social")

    def pronto(self, agora):
        return self.alvo is not None and agora >= self.proxima

    def cancelar(self, agora):
        self.fechando = False
        self.prazo = agora

    def _ordem(self, agora, tipo, etapa, caixa=None):
        self.proxima = agora + (0.65 if tipo == "apontar" else 0.85)
        return OrdemRegiao(tipo, etapa, caixa)

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
        if agora >= self.prazo and self.fechando is None:
            self.fechando = False
        if self.fechando is not None:
            if agora >= self.prazo + 12:
                return self._terminar(agora, False)
            if tela.descartar:
                return self._ordem(agora, "clicar", "descartar", tela.descartar)
            if tela.configuracoes:
                return self._ordem(agora, "esc", "fechar_configuracoes")
            if tela.social:
                return self._ordem(agora, "esc", "fechar_social")
            if lobby:
                return self._terminar(agora, self.fechando)
            return None

        principal, sub = tela.pareamento, tela.subregiao
        if principal:
            alvo_na = self.alvo in NORTE
            concluido = (principal.valor == self.alvo or
                          (alvo_na and principal.valor == AMERICA_DO_NORTE and sub and sub.valor == self.alvo))
            if concluido:
                if self.alterou and tela.aplicar:
                    self.ultima_submissao = agora
                    return self._ordem(agora, "clicar", "aplicar", tela.aplicar)
                if self.alterou and self.ultima_submissao is None:
                    return None
                self.fechando = True
                self.prazo = min(self.prazo, agora + 8)
                return self._ordem(agora, "esc", "fechar_configuracoes")
            nome = "subregiao" if alvo_na and principal.valor == AMERICA_DO_NORTE else "pareamento"
            linha = sub if nome == "subregiao" else principal
            if linha is None:
                return None
            return self._ajustar(agora, nome, linha)
        if tela.aba_jogo:
            return self._ordem(agora, "clicar", "abrir_aba_jogo", tela.aba_jogo)
        if tela.social and tela.engrenagem:
            return self._ordem(agora, "clicar", "abrir_configuracoes", tela.engrenagem)
        if lobby and not (tela.social or tela.configuracoes):
            return self._ordem(agora, "esc", "abrir_social")
        return None

    def _ajustar(self, agora, nome, linha):
        if self.linha != nome:
            self.linha, self.valor_anterior = nome, None
            self.visitados.clear()
            self.tentativas, self.sentido = 0, "direita"
        if linha.valor != self.valor_anterior:
            self.valor_anterior = linha.valor
            self.tentativas = 0
        seta = getattr(linha, self.sentido)
        if (self.sentido, linha.valor) in self.visitados and self.tentativas != 1:
            self.sentido = "esquerda" if self.sentido == "direita" else "direita"
            seta = getattr(linha, self.sentido)
        if not seta:
            seta = linha.esquerda if self.sentido == "direita" else linha.direita
            if seta:
                self.sentido = "esquerda" if self.sentido == "direita" else "direita"
        if seta is None:
            return self._ordem(agora, "apontar", nome, linha.caixa)
        self.visitados.add((self.sentido, linha.valor))
        self.tentativas += 1
        self.alterou = True
        return self._ordem(agora, "clicar", nome, seta)
