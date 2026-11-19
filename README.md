# Token · Auto Farm para Windows

Aplicativo desktop independente para Windows x64. Usa capturas da tela, imagens de referência locais e OCR para reconhecer estados visíveis do Fortnite; não lê memória do jogo, injeta DLLs nem tenta ocultar entradas do anti-cheat.

[Baixar AutoFarmTokenPirata.exe para Windows](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

## Uso

1. Abra o executável e ajuste as opções antes de iniciar.
2. Deixe o Fortnite em primeiro plano, em modo janela ou tela cheia em janela, e clique em **Iniciar**. **F6** inicia ou pausa.
3. Use **Testar imagem** para inspecionar um PNG, JPG ou BMP. O diagnóstico marca a caixa e o centro detectados e exibe método e score; essa função nunca envia teclado ou mouse.

O seletor **Aparência** oferece **Padrão (Azul)**, **Escuro (Preto)**, **Oceano (Azul-marinho)**, **Claro (Rosa bebê)**, **Floresta (Verde escuro)**, **Pôr do sol (Roxo)** e **Abóbora (Halloween)**. A troca é imediata durante a sessão e a escolha é restaurada na próxima abertura. A primeira abertura usa Padrão (Azul). Use a barra de rolagem para acessar o rodapé em janelas baixas.

O app procura **Jogar Novamente**, **Continuar** e os botões do lobby. A detecção usa imagens de referência em múltiplas escalas; a alternativa amarelo+OCR para **Jogar Novamente** só aceita o rótulo dentro do controle. A leitura em português ou inglês identifica fila e diálogo de saída, e não confirma quando há mais de um diálogo plausível.

Na tela de seleção de modo, o botão amarelo **Jogar** à direita só é aceito se o OCR ler **Esquadrão** e **Preencher**. **Testar imagem** também reconhece a opção **Região de Pareamento** na aba Jogo quando o rótulo aparece cortado. A região selecionada é definida no Fortnite.

O contador avança uma vez por fila reconhecida. Depois que o app tenta entrar na fila, ele aguarda uma transição de HUD antes de iniciar o cronômetro e liberar o movimento. Se você abrir o painel durante uma partida em andamento, o HUD estável libera o anti-AFK com o cronômetro de saída desarmado. Um botão de lobby reaparecendo não reinicia a fila sozinho: depois do timeout, recomece com **Iniciar/F6** ou aguarde o reconhecimento explícito de cancelamento.

**Pronto** exige confirmação do texto no botão amarelo. Em uma partida reconhecida, o app bloqueia os cliques normais de lobby. Se pausar e retomar com **F6**, o app faz uma nova leitura da tela e descarta uma tentativa de fila ainda sem confirmação.

O anti-AFK fica bloqueado no ônibus, no inventário, em modo espectador, com HUD indisponível ou durante pausa ou perda de foco. A janela e suas coordenadas são validadas antes de cada ação e entre segmentos de entrada. O Windows recebe entradas globais; essas verificações reduzem o risco de enviar comandos fora do jogo, mas não eliminam a corrida entre a última validação e o envio.

A rotina aérea opcional salta com **Espaço** após duas leituras do aviso do ônibus. O reconhecimento usa a imagem de referência ou o texto do aviso. Funciona também ao iniciar o app já no ônibus. Duas leituras de **Entrar em queda livre** enviam **Espaço** para fechar a asa-delta uma vez por descida.

O anti-AFK mantém **W** nas caminhadas e alterna diagonais com **A** e **D**. Com o cursor capturado e fora da transição aérea reconhecida, gira a câmera e envia dois cliques esquerdos com o item que já está na mão.

O tempo padrão é 7,5 minutos. O painel sinaliza modo espectador e registra pares de barras de companheiros após três leituras estáveis, sem usar uma ausência de barras para decidir sair.

**Próxima saída** mostra a contagem regressiva do prazo usado pela saída automática. O painel mostra um traço quando a automação está pausada ou não há saída programada. **Farmando** soma o tempo ativo desde que o app foi aberto, incluindo lobby e fila, e congela durante as pausas.

**Atualizar automaticamente** consulta as releases do GitHub ao abrir e a cada hora. Quando o app fica pausado, o atualizador valida o tamanho e o SHA-256 do executável, guarda a versão anterior como `.previous` e reinicia o app. Use **Verificar** para consultar manualmente.

Em **Recompensas e webhook**, você pode ativar o resgate quando a tela de itens adquiridos aparecer antes de uma nova fila. Cole a URL HTTPS do Discord ou de um endpoint compatível com seus anexos e clique em **Salvar**. Depois que o botão de resgate some, o app envia a captura do Fortnite feita antes do clique e o nome lido na tela. Se o nome estiver ilegível, o aviso informa isso e envia a captura. **Testar com tela atual** aguarda três segundos e envia a imagem do Fortnite em primeiro plano ou do monitor principal, com o nome de teste escolhido. [Formato do webhook do Discord](https://docs.discord.com/developers/resources/webhook#execute-webhook)

Marque **Notificar tesouros elementais encontrados** para receber avisos de descoberta no mesmo webhook. O alerta inclui uma captura do Fortnite e identifica o Acelerador de Extração, o Extrator Portátil, os Fogos de Artifício Dourados, o Localizador de Elementais ou o Localizador da Sorte quando o ícone está legível.

Em **Regiões por horário**, ative a programação para Construção e Zero Build. O app usa Brasília (UTC−3) e tenta ajustar a região antes de entrar na fila pelo lobby. Das 00h às 06h, usa América do Norte. Das 06h às 11h, você pode escolher Ásia ou Oceania. Das 11h às 18h, usa Europa. Das 18h à meia-noite, você pode escolher Brasil ou América do Norte. A preferência de sub-região fica a cargo da configuração do Fortnite. [Configurações de pareamento da Epic](https://www.epicgames.com/help/c-ategory_fortnite/c-fortnite_gameplay/a10221394)

## Enviar um diagnóstico

1. Reproduza a falha e pressione **F7**. Isso marca o horário no registro da sessão.
2. Clique em **Copiar diagnóstico** no painel e cole o texto ao relatar a falha.

O registro fica em `%LOCALAPPDATA%\AutoFarmToken\diagnostico.log`, com até duas cópias rotativas. Ele registra estados do jogo, decisões e os comandos que o app tentou enviar. O resultado `enviada` indica que a rotina de entrada do Windows terminou. Em caso de falha na troca de região, a última captura do menu lateral ou das configurações fica no arquivo local `debug\regiao_ultima_falha.jpg`, na mesma pasta do diagnóstico.

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
py -3.14 -m py_compile app.py atualizador.py diagnostico.py embarque.py logica_autofarm.py painel_tema.py regiao.py relogio_painel.py tesouros.py texto_tela.py webhook.py windows_game.py
py -3.14 app.py --verificar-build
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --collect-all rapidocr --copy-metadata rapidocr --add-data "modelos;modelos" --add-data "templates;templates" --add-data "fontes;fontes" app.py
```

A interface usa Inter 4.1. As fontes incluídas contêm o conjunto de caracteres do painel e a versão em negrito usa algarismos tabulares. A licença SIL OFL está em `fontes/LICENSE.txt`. [Projeto Inter](https://github.com/rsms/inter)

O executável é gerado em `dist/`. O fluxo do GitHub Actions inclui os modelos OCR e as imagens de referência e executa verificações positivas e negativas no executável empacotado. Os testes usam detector, relógio e janela simulados e imagens sintéticas; não exigem Fortnite aberto, rede ou esperas reais. A confirmação final de foco, geometria e reconhecimento visual ainda precisa ser feita manualmente com Fortnite aberto.
