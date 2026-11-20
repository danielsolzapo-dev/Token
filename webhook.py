"""Envia uma captura a um webhook compatível com anexos do Discord."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

import cv2


class ErroWebhook(ValueError):
    pass


class SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validar_url(url):
    url = url.strip()
    try:
        partes = urlsplit(url)
        porta = partes.port
    except ValueError:
        raise ErroWebhook("Informe uma URL HTTPS válida.") from None
    if (partes.scheme != "https" or not partes.hostname or not partes.path or partes.username
            is not None or partes.fragment or any(c.isspace() or ord(c) < 32 for c in url)
            or porta == 0):
        raise ErroWebhook("Informe uma URL HTTPS de webhook válida.")
    if partes.hostname in {"discord.com", "canary.discord.com", "ptb.discord.com", "discordapp.com"}:
        parametros = [(chave, valor) for chave, valor in parse_qsl(partes.query) if chave != "wait"]
        parametros.append(("wait", "true"))
        return urlunsplit(partes._replace(query=urlencode(parametros)))
    return url


def enviar_webhook(url, quadro, nome, *, teste=False, texto_teste="", tesouro=False, aviso=None, abrir=None):
    url = validar_url(url)
    altura, largura = quadro.shape[:2]
    if max(altura, largura) > 1920:
        escala = 1920 / max(altura, largura)
        quadro = cv2.resize(quadro, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    try:
        ok, dados = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 88])
    except cv2.error:
        raise ErroWebhook("Não foi possível preparar a captura.") from None
    if not ok:
        raise ErroWebhook("Não foi possível preparar a captura.")

    titulo = "Teste de webhook" if teste else "Recompensa resgatada"
    if tesouro and not teste:
        titulo = "Tesouro elemental encontrado"
    elif aviso and not teste:
        titulo = {"conta_banida": "Aviso de banimento no Fortnite",
                  "token_loja_pirata": "Token da Loja Pirata desbloqueado"}[aviso]
    nome = " ".join((nome or "Nome indisponível na captura").split())[:180]
    conteudo = f"{titulo} — {nome}"
    if teste and texto_teste.strip():
        conteudo += "\n" + texto_teste.strip()[:500]
    mensagem = json.dumps({
        "content": conteudo,
        "allowed_mentions": {"parse": []},
        "attachments": [{"id": 0, "filename": "captura.jpg"}],
    }, ensure_ascii=False).encode("utf-8")
    limite = uuid4().hex
    corpo = (
        f'--{limite}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        'Content-Type: application/json\r\n\r\n'
    ).encode("ascii") + mensagem + (
        f'\r\n--{limite}\r\nContent-Disposition: form-data; name="files[0]"; filename="captura.jpg"\r\n'
        'Content-Type: image/jpeg\r\n\r\n'
    ).encode("ascii") + dados.tobytes() + f"\r\n--{limite}--\r\n".encode("ascii")
    pedido = Request(url, data=corpo, headers={
        "Content-Type": f"multipart/form-data; boundary={limite}",
        "User-Agent": "AutoFarmToken-Webhook",
    }, method="POST")
    abrir = abrir or build_opener(SemRedirecionamento()).open
    try:
        with abrir(pedido, timeout=12) as resposta:
            if not 200 <= resposta.status < 300:
                raise ErroWebhook(f"Webhook respondeu com HTTP {resposta.status}.")
    except HTTPError as erro:
        erro.close()
        raise ErroWebhook(f"Webhook respondeu com HTTP {erro.code}.") from None
    except (OSError, URLError):
        raise ErroWebhook("Não foi possível conectar ao webhook.") from None
