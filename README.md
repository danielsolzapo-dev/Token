# Auto Farm para Fortnite

Aplicativo portátil para Windows x64, baseado na lógica reconstruída do AutoFarmFN v59. [Release de referência](https://github.com/guifqz/AutoFarmFN/releases/tag/v59)

[Baixar AutoFarmTokenPirata.exe para Windows](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

1. Abra o executável e ajuste as opções antes de iniciar.
2. Clique em **Iniciar** e deixe o Fortnite em primeiro plano, em modo janela ou tela cheia em janela.
3. Use **F6** para iniciar ou pausar. **Testar imagem** abre um PNG, JPG ou BMP e marca o botão detectado.

O app procura **Jogar Novamente**, **Continuar** e os botões do lobby. A detecção usa imagens de referência em múltiplas escalas. A alternativa por cor para **Jogar Novamente** também exige o rótulo do botão. A leitura de texto em português ou inglês procura sinais de fila e o diálogo de confirmação de saída.

O contador só avança após reconhecer a fila ou a nova partida. Se uma fila confirmada demorar, o painel avisa e espera pelo início do jogo ou por uma mensagem de cancelamento. Depois de um clique para entrar na fila, o cronômetro espera uma transição de HUD ou um aviso novo de ônibus. O movimento anti-AFK depende da leitura do HUD. O painel verifica o foco e a posição da janela antes de enviar comandos. Cliques interrompidos antes do envio conservam as tentativas disponíveis. Se a confirmação de saída tiver mais de uma opção plausível, o painel avisa e aguarda.

Os ajustes ficam em `%LOCALAPPDATA%\AutoFarmToken\ajustes.json`. A detecção visual foi verificada com imagens de teste e pode variar com a versão do jogo e a escala do HUD.

## Desenvolvimento

Use o Python 3.14 no Windows.

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 preparar_ocr.py
py -3.14 app.py
py -3.14 -m unittest discover -s tests
py -3.14 app.py --verificar-build
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --collect-all rapidocr --copy-metadata rapidocr --add-data "modelos;modelos" --add-data "templates;templates" app.py
```

O executável é gerado em `dist/`. O GitHub Actions roda a verificação do pacote antes de publicá-lo.
