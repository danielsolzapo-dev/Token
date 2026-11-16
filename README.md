# Auto Farm para Windows

Aplicativo desktop independente para Windows x64. Usa capturas da tela, imagens de referência locais e OCR para reconhecer estados visíveis do Fortnite; não lê memória do jogo, injeta DLLs nem tenta ocultar entradas do anti-cheat.

[Baixar AutoFarmTokenPirata.exe para Windows](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

## Uso

1. Abra o executável e ajuste as opções antes de iniciar.
2. Deixe o Fortnite em primeiro plano, em modo janela ou tela cheia em janela, e clique em **Iniciar**. **F6** inicia ou pausa.
3. Use **Testar imagem** para inspecionar um PNG, JPG ou BMP. O diagnóstico marca a caixa e o centro detectados e exibe método e score; essa função nunca envia teclado ou mouse.

O app procura **Jogar Novamente**, **Continuar** e os botões do lobby. A detecção usa imagens de referência em múltiplas escalas; a alternativa amarelo+OCR para **Jogar Novamente** só aceita o rótulo dentro do controle. A leitura em português ou inglês identifica fila e diálogo de saída, e não confirma quando há mais de um diálogo plausível.

O contador avança uma vez por fila reconhecida. O cronômetro e o movimento anti-AFK só começam depois de um período estável sem HUD/ônibus e do reconhecimento estável do HUD de uma partida nova; um HUD antigo, uma falha isolada de leitura ou um ônibus já visível não confirmam uma nova partida. Um botão de lobby reaparecendo não reinicia a fila sozinho: depois do timeout, recomece com **Iniciar/F6** ou aguarde o reconhecimento explícito de cancelamento.

O anti-AFK fica bloqueado sem uma partida recém-confirmada, no ônibus, inventário, espectador, tela desconhecida, pausa ou perda de foco. A janela e suas coordenadas são validadas antes de cada ação e entre segmentos de entrada. O Windows recebe entradas globais; essas verificações reduzem o risco de enviar comandos fora do jogo, mas não eliminam a corrida entre a última validação e o envio.

Os ajustes ficam em `%LOCALAPPDATA%\AutoFarmToken\ajustes.json`. A detecção depende da resolução, escala e idioma da interface do jogo e pode precisar de ajustes após atualizações do Fortnite. Confirme se automação de entradas é permitida pelas regras do jogo; não use o aplicativo se isso violar as regras ou políticas aplicáveis.

## Desenvolvimento

Use Python 3.14 no Windows. Instale as dependências e prepare os modelos OCR verificados:

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 preparar_ocr.py
```

Inicie, teste e compile:

```powershell
py -3.14 app.py
py -3.14 -m unittest discover -s tests -v
py -3.14 -m py_compile app.py logica_autofarm.py texto_tela.py windows_game.py
py -3.14 app.py --verificar-build
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --collect-all rapidocr --copy-metadata rapidocr --add-data "modelos;modelos" --add-data "templates;templates" app.py
```

O executável é gerado em `dist/`. O fluxo do GitHub Actions inclui os modelos OCR e as imagens de referência e executa verificações positivas e negativas no executável empacotado. Os testes usam detector, relógio e janela simulados e imagens sintéticas; não exigem Fortnite aberto, rede ou esperas reais. A confirmação final de foco, geometria e reconhecimento visual ainda precisa ser feita manualmente com Fortnite aberto.
