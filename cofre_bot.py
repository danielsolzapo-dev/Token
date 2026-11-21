"""Credenciais do bot no Gerenciador de Credenciais do usuário do Windows."""

from win32ctypes.pywin32 import pywintypes, win32cred


TOKEN = "AutoFarm/BotDiscord/Discord"
SERVICO = "AutoFarm/BotDiscord/Ativacao"


def obter(alvo):
    try:
        registro = win32cred.CredRead(alvo, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error as erro:
        if erro.winerror == 1168:
            return ""
        raise
    return registro["CredentialBlob"].decode("utf-16-le")


def guardar(alvo, segredo):
    segredo = segredo.strip()
    if not segredo or not segredo.isascii() or not segredo.isprintable() or any(c.isspace() for c in segredo):
        raise ValueError("Credencial vazia ou com formato inválido.")
    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": alvo,
                         "UserName": "Auto Farm", "CredentialBlob": segredo,
                         "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE})
