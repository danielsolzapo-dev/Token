"""Compila o leitor offline em Windows e prepara a fonte correspondente para a release."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


SDK = "10.0.404"
RUNTIME = "10.0.15"
ORIGEM = "https://github.com/Loukious/FortniteChestTracker.git"
REVISAO = "51815e626214c7ac8fb9b0000da00abcd4b81d2e"
PASTA = Path(__file__).resolve().parent
ARQUIVOS_LEITOR = ("LeitorBaus.csproj", "Program.cs", "compilar.py", "deduplicar.patch", "LEIA-ME.txt")
FONTES_TRACKER = (
    "LICENSE", "COPYING", "THIRD_PARTY_NOTICES.md", "Directory.Build.props",
    "src/FortniteReplayReader", "src/Unreal.Core", "src/Unreal.Encryption", "src/OozSharp",
)


def preparar_fontes(temporaria, checkout):
    fontes = temporaria / "fonte"
    fontes.mkdir()
    tracker = fontes / "tracker"
    # A cópia do ZIP já inclui a correção descrita em deduplicar.patch.
    if checkout is None and (PASTA / "tracker").is_dir():
        shutil.copytree(PASTA / "tracker", tracker)
    else:
        if checkout is None:
            checkout = temporaria / "git"
            subprocess.run(["git", "init", "--quiet", checkout], check=True)
            subprocess.run(["git", "-C", checkout, "fetch", "--depth=1", ORIGEM, REVISAO], check=True)
        arquivo = temporaria / "parser.zip"
        subprocess.run(["git", "-C", checkout, "archive", "-o", arquivo, REVISAO, "--", *FONTES_TRACKER],
                       check=True)
        with ZipFile(arquivo) as pacote:
            pacote.extractall(tracker)
        subprocess.run(["git", "apply", "--whitespace=nowarn", PASTA / "deduplicar.patch"],
                       cwd=tracker, check=True)
    for nome in ARQUIVOS_LEITOR:
        shutil.copyfile(PASTA / nome, fontes / nome)
    (fontes / "global.json").write_text(json.dumps({"sdk": {"version": SDK, "rollForward": "disable"}}),
                                       encoding="utf-8")
    return fontes


def compilar(dotnet, checkout):
    with TemporaryDirectory() as inicial:
        temporaria = Path(inicial)
        fontes = preparar_fontes(temporaria, checkout)
        tracker = fontes / "tracker"
        dist = PASTA.parent / "dist"
        dist.mkdir(exist_ok=True)
        # Gera o arquivo antes da compilação, para não incluir bin, obj ou caches de pacotes.
        arquivo_fonte = temporaria / "LeitorBaus-fonte.zip"
        with ZipFile(arquivo_fonte, "w", ZIP_DEFLATED) as pacote:
            for caminho in sorted(fontes.rglob("*")):
                if caminho.is_file():
                    # O ZIP independe de fuso, plataforma e horário da compilação.
                    info = ZipInfo(caminho.relative_to(fontes).as_posix())
                    pacote.writestr(info, caminho.read_bytes(), ZIP_DEFLATED)

        publicado = temporaria / "publicado"
        subprocess.run([
            dotnet, "publish", "LeitorBaus.csproj", "-c", "Release", "-r", "win-x64", "--self-contained", "true",
            "-o", publicado, f"-p:TrackerDir={tracker}", "-p:PublishSingleFile=true",
            "-p:IncludeNativeLibrariesForSelfExtract=true", "-p:EnableCompressionInSingleFile=true",
            f"-p:RuntimeFrameworkVersion={RUNTIME}", f"-p:PathMap={fontes}=/_/src", "-p:PublishTrimmed=false",
            "-p:DebugType=None", "-p:DebugSymbols=false",
        ], cwd=fontes, check=True)
        executavel = publicado / "LeitorBaus.exe"
        teste = subprocess.run([executavel, "--verificar-build"], capture_output=True, check=True, timeout=60)
        if json.loads(teste.stdout) != {"protocolo": 1}:
            raise RuntimeError("O leitor publicado respondeu com um protocolo inesperado.")

        binario = PASTA / "binario"
        licencas = binario / "licencas"
        licencas.mkdir(parents=True, exist_ok=True)
        for origem in ("COPYING", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(tracker / origem, licencas / origem)
        pacotes = json.loads((fontes / "obj/project.assets.json").read_text(encoding="utf-8-sig"))
        locais = [Path(p) / "microsoft.netcore.app.runtime.win-x64" / RUNTIME for p in pacotes["packageFolders"]]
        locais.append(Path(dotnet).parent / "packs/Microsoft.NETCore.App.Runtime.win-x64" / RUNTIME)
        dotnet_licencas = next((local for local in locais if (local / "LICENSE.TXT").is_file()), None)
        if dotnet_licencas is None:
            raise RuntimeError("Licença ausente no pacote do runtime .NET restaurado.")
        avisos_dotnet = (("LICENSE.TXT", "DOTNET-MIT.txt"),
                        ("THIRD-PARTY-NOTICES.TXT", "DOTNET-THIRD-PARTY-NOTICES.txt"))
        with ZipFile(arquivo_fonte, "a") as pacote:
            for origem, destino in avisos_dotnet:
                shutil.copy2(dotnet_licencas / origem, licencas / destino)
                pacote.writestr(ZipInfo("licencas/" + destino), (licencas / destino).read_bytes(), ZIP_DEFLATED)
        shutil.copy2(fontes / "LEIA-ME.txt", licencas / "LEIA-ME.txt")
        shutil.copy2(executavel, binario / executavel.name)
        shutil.copy2(arquivo_fonte, dist / arquivo_fonte.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dotnet", default="dotnet", help="Caminho do dotnet.exe com o SDK " + SDK)
    parser.add_argument("--tracker", type=Path, help="Checkout Git local que contém a revisão fixada do parser")
    opcoes = parser.parse_args()
    dotnet = shutil.which(opcoes.dotnet)
    if dotnet is None:
        parser.error("Instale o SDK .NET " + SDK + " ou informe o caminho de dotnet.exe.")
    compilar(str(Path(dotnet).resolve()), opcoes.tracker)
