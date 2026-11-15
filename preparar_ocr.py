"""Prepara e verifica os modelos OCR antes de compilar o executável."""
import hashlib
import importlib.util
import shutil
from pathlib import Path
from urllib.request import urlopen

PASTA = Path(__file__).resolve().with_name("modelos")
NOME = "latin_PP-OCRv5_rec_mobile.onnx"
HASH = "b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a"
URL = f"https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5/rec/{NOME}"
LIMITE = 12 * 1024 * 1024


def main():
    pacote = Path(importlib.util.find_spec("rapidocr").origin).parent
    PASTA.mkdir(exist_ok=True)
    detector = "PP-OCRv6_det_small.onnx"
    shutil.copyfile(pacote / "models" / detector, PASTA / detector)
    destino = PASTA / NOME
    if destino.is_file() and hashlib.sha256(destino.read_bytes()).hexdigest() == HASH:
        return
    with urlopen(URL, timeout=35) as resposta:
        dados = resposta.read(LIMITE + 1)
    if len(dados) > LIMITE or hashlib.sha256(dados).hexdigest() != HASH:
        raise RuntimeError("O modelo OCR latino não passou na verificação de integridade.")
    destino.write_bytes(dados)


if __name__ == "__main__":
    main()
