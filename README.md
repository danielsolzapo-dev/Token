# Auto Farm para Fortnite

Aplicativo portátil para Windows x64, baseado na lógica reconstruída do AutoFarmFN v59. [Release de referência](https://github.com/guifqz/AutoFarmFN/releases/tag/v59)

[Baixar AutoFarmTokenPirata.exe para Windows](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

1. Abra o executável e ajuste as opções antes de iniciar.
2. Clique em **Iniciar** e deixe o Fortnite em primeiro plano, em modo janela ou tela cheia em janela.
3. Use **F6** para iniciar ou pausar. **Testar imagem** abre um PNG, JPG ou BMP e marca o botão detectado.

O app procura **Jogar Novamente**, **Continuar** e os botões do lobby. A detecção usa imagens de referência em múltiplas escalas, com uma alternativa por cor para **Jogar Novamente**. Se a saída por tempo estiver ativa, o cronômetro começa após a leitura do HUD ou o reinício da fila. O movimento anti-AFK também depende da leitura do HUD. O painel suspende o envio de comandos quando o jogo perde o foco.

Os ajustes ficam em `%LOCALAPPDATA%\AutoFarmToken\ajustes.json`. A detecção visual foi verificada com imagens de teste e pode variar com a versão do jogo e a escala do HUD.

## Desenvolvimento

Use o Python 3.14 no Windows.

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 app.py
py -3.14 app.py --verificar-build
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --add-data "templates;templates" app.py
```

O executável é gerado em `dist/`. O GitHub Actions roda a verificação do pacote antes de publicá-lo.
