"""Registro local e compartilhável das decisões do Auto Farm."""

from collections import deque
import json
import logging
from logging.handlers import RotatingFileHandler


class Diagnostico:
    def __init__(self, caminho, *, limite=256 * 1024, arquivos=2):
        self.caminho = caminho
        self.arquivos = arquivos
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(caminho, maxBytes=limite, backupCount=arquivos, encoding="utf-8")
        self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        self.logger = logging.Logger("autofarm.diagnostico", logging.INFO)
        self.logger.addHandler(self.handler)

    def registrar(self, evento, **dados):
        self.logger.info("%s", json.dumps({"evento": evento, **dados}, ensure_ascii=False, separators=(",", ":")))

    def texto(self, ultimas=500):
        linhas = deque(maxlen=ultimas)
        caminhos = [self.caminho.with_name(f"{self.caminho.name}.{numero}")
                    for numero in range(self.arquivos, 0, -1)]
        self.handler.acquire()
        try:
            self.handler.flush()
            for caminho in (*caminhos, self.caminho):
                if caminho.is_file():
                    with caminho.open(encoding="utf-8", errors="replace") as arquivo:
                        linhas.extend(arquivo)
        finally:
            self.handler.release()
        return "".join(linhas)

    def fechar(self):
        self.logger.removeHandler(self.handler)
        self.handler.close()
