# Auto Farm do Token Pirata

## Abrir no Windows

Deixe o `AutoFarmTokenPirata.exe` numa pasta em que você possa gravar arquivos. O executável já inclui as bibliotecas e os modelos de leitura automática em português e inglês.

Abra o Fortnite em janela sem bordas no lobby. Clique em **Testar leitura** e volte ao jogo para conferir as detecções. Para jogar, pare essa sessão, clique em **Iniciar cliques** e volte ao Fortnite. **Atividade** mostra o envio do clique e a confirmação da fila quando ela aparece. **F8** pausa ou retoma. **F9** encerra a sessão.

## Recortes opcionais

Os controles comuns são detectados pelo texto na tela. Para corrigir uma detecção ou usar o modo de recortes, importe os PNGs em **Leitura de tela**. Use a resolução, o idioma, a escala e o filtro de cores do jogo. Salve os recortes sem o cursor sobre o botão.

| Arquivo em `botoes` | O que recortar |
|---|---|
| `jogar.png` | O botão principal Jogar ou Pronto no lobby. |
| `lobby.png` | O botão Voltar ao Lobby da tela de fim da partida. |
| `partida.png` | Um ícone fixo do HUD que só aparece em partida. Evite nome, número, cronômetro e barra variável. |
| `sair.png` | O botão Sair da Partida ou Voltar ao Lobby dentro do menu aberto com Esc. |
| `aba_saida.png` | O ícone de saída no menu, se a sua interface exigir esse passo antes de mostrar o botão. |
| `confirmar_saida.png` | O botão de confirmação junto de elementos exclusivos do aviso de saída, se houver confirmação. Mantenha o botão no centro do recorte. |
| `tesouro.png` | O título da janela Tesouro Encontrado. |
| `resgatar.png` | O botão que coleta o tesouro naquela janela. |
| `inventario.png` | Um trecho fixo e exclusivo do inventário aberto, para fechá-lo com Esc. |
| `espectando.png` | O texto ou o ícone que indica que você está assistindo. |
| `onibus.png` | O aviso com a tecla de salto do Ônibus de Batalha, para autorizar um salto. |
| `aba_tesouro.png` e `aba_jogar.png` | O sinal de que a aba Tesouro está ativa e o botão Jogar de navegação no topo. |
| `suspensao.png` | Um trecho exclusivo do aviso de suspensão, para pausar e avisar pelo webhook. |

Com a leitura automática desligada, `jogar.png` e `lobby.png` são obrigatórios. Os pares `partida.png` e `sair.png`, e `tesouro.png` e `resgatar.png`, habilitam a saída por tempo e o resgate nesse modo. Use recortes de pelo menos 12 × 12 pixels, com o controle no centro.

O cronômetro padrão dispara a saída após 8 minutos desde a primeira detecção do HUD ou do ônibus. Na ausência do botão de fim de partida, o macro abre o menu e espera o botão de saída aparecer, sem alternar o Esc continuamente. O contador aumenta quando uma partida é detectada e fica salvo em `partidas.json`. O movimento usa W/A/D, Ctrl esquerdo, Espaço e o mouse. O macro solta as teclas ao terminar cada movimento.

## Avisos no Discord

No Discord, copie a URL de um webhook do canal de texto de destino e cole-a em `webhook_discord.txt`, ao lado do executável. Como alternativa, defina a variável de ambiente `DISCORD_WEBHOOK_URL`. Trate a URL como segredo.

O OCR tenta ler os nomes das recompensas conhecidas. Para adicionar um item específico, importe o recorte da notificação em **Tesouro e Discord**. O título Tesouro Encontrado pode gerar um aviso genérico. Cada item reconhecido gera no máximo um aviso por partida.

## Atualizações

A partir da versão 1.1.0, o app consulta o GitHub ao abrir e a cada 30 minutos com a opção automática ligada. Ele espera a sessão parar, verifica o SHA-256 do download e reinicia o painel. Use **Atualizações → Verificar agora** para consultar manualmente.

## Esquadrão com preenchimento

Para exigir o modo antes de entrar na fila, adicione `esquadrao_ok.png` com um recorte que identifique o Esquadrão com Preencher ligado. Se o jogo precisar de correção, `modo_01.png`, `modo_02.png` e os seguintes representam os botões clicáveis da sua sequência de ajuste. Cada imagem deve mostrar o botão que está disponível naquele passo. O macro espera a imagem de confirmação antes de entrar na fila.

Para habilitar saída antecipada por composição do squad, crie `botoes/squad.json` com as três áreas dos companheiros no HUD, em frações de 0 a 1 da janela do jogo. Exemplo de formato, com posições ilustrativas que precisam ser ajustadas:

```json
{"slots": [[0.01, 0.04, 0.16, 0.04], [0.01, 0.08, 0.16, 0.04], [0.01, 0.12, 0.16, 0.04]]}
```

Em `botoes/squad/skins_padrao`, coloque imagens dos retratos de skins padrão visíveis no HUD. Em `botoes/squad/ausentes`, coloque recortes de sinais explícitos de vaga vazia ou eliminação. Duas vagas reconhecidas como ausentes ou dois retratos padrão por 20 segundos acionam a saída. A skin padrão é um critério visual e pode sinalizar pessoas que estão jogando. Um companheiro derrubado só será contado como ausente se você usar um recorte que também corresponda ao estado de derrubado.

## Região de dia

Para automatizar a seleção no lobby, crie uma subpasta em `botoes/regioes` por região que quiser usar. Nomes aceitos: `europa`, `america_do_norte`, `asia`, `oceania` e `oriente_medio`. Use uma imagem por botão na ordem do seu menu, começando com `01.png`. Inclua um passo com o sufixo `-verificar` (por exemplo, `06-verificar.png`) para identificar a região selecionada depois de aplicar. Esse passo só verifica a tela. Inclua os botões seguintes para retornar ao lobby.

O macro usa o horário local de uma cidade representativa de cada região configurada. Escolhe entre 7h e 19h e dá preferência à mais próxima das 14h. Com as sequências ativadas, espera uma região diurna antes de entrar na fila e não escolhe Brasil ou Automático. A cidade é uma aproximação e o pareamento do Fortnite determina o servidor efetivo.

## Opções

`--minutos 8` ajusta a saída entre 4,5 e 8,5 minutos. `--pausar-apos 60` faz uma pausa no lobby depois de 60 minutos de sessão. `--sem-movimento` desliga os movimentos aleatórios. `--skins-padrao 3` ajusta o limite de retratos para sair do squad. `--limiar 0.92` ajusta a exigência de correspondência visual.

Use os campos correspondentes nas páginas do painel. Para executar pelo código-fonte, veja README.md.

O controle exige que o Fortnite esteja em primeiro plano. Os recortes e as sequências dependem da interface atual do seu jogo.

