# Auto Farm para Windows

Aplicativo desktop independente para Windows x64. Usa capturas da tela, imagens de referência locais e OCR para reconhecer estados visíveis do Fortnite; não lê memória do jogo, injeta DLLs nem tenta ocultar entradas do anti-cheat.

[Baixar AutoFarmTokenPirata.exe para Windows](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

## Uso

1. Abra o executável e ajuste as opções antes de iniciar.
2. Deixe o Fortnite aberto, em modo janela ou tela cheia em janela, e clique em **Iniciar**. O app tenta restaurar e trazer a janela real do Fortnite para primeiro plano; se o Windows não permitir, clique no jogo manualmente. **F6** inicia ou pausa. Nenhuma entrada é enviada enquanto o Fortnite não estiver realmente em foco.
3. Use **Testar imagem** para inspecionar um PNG, JPG ou BMP. O diagnóstico marca a caixa e o centro detectados e exibe método e score; essa função nunca envia teclado ou mouse.
4. Opcionalmente, escolha **Configurar baú** para carregar um recorte de imagem de um baú visível (20–512 px por lado), ative **Avisar ao detectar baú visível** e inicie o monitoramento.
5. **Notificações do Windows** avisa sobre partida reconhecida, retorno ao lobby, perda/restauração de foco e erros. **Salvar capturas em falhas** é opcional e vem desligado; quando ligado, salva imagens locais de diagnósticos relevantes. Depois de pausar ou encerrar, use **Exportar resumo da sessão** para salvar um JSON.

O app procura **Jogar Novamente**, **Continuar** e os botões do lobby. A detecção usa imagens de referência em múltiplas escalas; a alternativa amarelo+OCR para **Jogar Novamente** só aceita o rótulo dentro do controle. A leitura em português ou inglês identifica fila e diálogo de saída, e não confirma quando há mais de um diálogo plausível.

O aviso de baú compara a captura com o recorte escolhido, em múltiplas escalas e com duas detecções estáveis. Só funciona com o Fortnite em foco, após reconhecer uma partida nova e fora do ônibus, inventário ou pausa; **Testar imagem** também mostra a caixa reconhecida, centro, método e score. A referência fica local em `%LOCALAPPDATA%\AutoFarmToken\referencia_bau.png` e não é enviada. Como é correspondência de imagem, mudanças de câmera, iluminação, distância ou aparência podem causar falsos negativos ou positivos; prefira um recorte nítido do baú com pouco fundo. O app não interpreta o mapa, não localiza baús fora da tela, não navega até eles e não os abre; o aviso não envia entrada ao jogo.

O contador avança uma vez por fila reconhecida. O cronômetro e o movimento anti-AFK só começam após uma transição confirmada e três leituras estáveis do HUD de uma partida nova. Se já havia HUD no clique, ele precisa desaparecer em pelo menos quatro leituras ao longo de 0,65 s antes de reaparecer; um HUD persistente ou uma falha isolada de leitura não inicia a partida. O ônibus, mesmo já visível antes do clique, não confirma partida sozinho. Um botão de lobby reaparecendo não reinicia a fila automaticamente: depois do timeout, recomece com **Iniciar/F6** ou aguarde o reconhecimento explícito de cancelamento.

O anti-AFK fica bloqueado sem uma partida recém-confirmada, no ônibus, inventário, espectador, menu de saída/pausa, tela desconhecida ou perda de foco. O status mostra o motivo do bloqueio. Ao iniciar, o app pode restaurar a janela do Fortnite e pedir foco ao Windows, mas só age depois de confirmar que o processo do jogo está de fato em primeiro plano. Não envia mensagens para janelas de jogo em segundo plano. A janela e suas coordenadas são validadas antes de cada ação e entre segmentos de entrada. O Windows recebe entradas globais; essas verificações reduzem o risco de enviar comandos fora do jogo, mas não eliminam a corrida entre a última validação e o envio.

Ao abrir, o app consulta os releases do GitHub em segundo plano. Se houver versão nova, pergunta antes de baixar; o executável e seu SHA-256 são verificados antes de substituir o arquivo atual e reiniciar o app. A instalação automática só funciona no executável Windows publicado, exige internet e permissão de escrita na pasta do app. Se estiver executando o código-fonte, o app abre a página do release para atualização manual. Um arquivo ausente ou checksum inválido bloqueia a instalação.

## Diagnóstico

O monitoramento grava estados, bloqueios do anti-AFK, ações solicitadas/concluídas/não concluídas (com motivo), confiança e coordenadas dos cliques, filas/partidas reconhecidas e erros em `%LOCALAPPDATA%\AutoFarmToken\autofarm.log`. O arquivo é rotativo (1 MB, mantendo até três cópias). Clique em **Abrir log** para acessá-lo e anexe o arquivo ao relatar uma falha. O log não contém capturas de tela nem texto bruto reconhecido por OCR; ele só é criado quando o monitoramento é iniciado. Se **Salvar capturas em falhas** estiver ligado, imagens das falhas relevantes ficam em `%LOCALAPPDATA%\AutoFarmToken\debug`; elas podem incluir qualquer conteúdo visível no jogo e não são enviadas automaticamente. O resumo exportado contém versão, horários, duração, filas/partidas reconhecidas, alertas de baú, falhas de entrada, interrupções de foco e erros, mas não inclui capturas nem OCR.

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
py -3.14 -m py_compile app.py atualizador.py logica_autofarm.py notificacoes.py texto_tela.py windows_game.py
py -3.14 app.py --verificar-build
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --collect-all rapidocr --copy-metadata rapidocr --add-data "modelos;modelos" --add-data "templates;templates" app.py
```

O executável é gerado em `dist/`. O fluxo do GitHub Actions inclui os modelos OCR e as imagens de referência, executa verificações positivas e negativas no executável empacotado e publica um arquivo SHA-256 para o atualizador. Os testes do atualizador simulam respostas HTTP e não acessam a rede. Os demais testes usam detector, relógio e janela simulados e imagens sintéticas; não exigem Fortnite aberto, rede ou esperas reais. A confirmação final de foco, geometria, atualização instalada e reconhecimento visual ainda precisa ser feita manualmente.
