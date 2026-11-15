# Auto Farm do Token Pirata

[Baixar o executável para Windows x64](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

Painel portátil para Windows x64. Abra `AutoFarmTokenPirata.exe` e deixe o Fortnite em primeiro plano. Use **Testar leitura** para conferir as detecções em **Atividade**. Use **Iniciar cliques** para agir no jogo.

- **Fila e saída** controla o clique no lobby, o cronômetro por partida e a pausa programada.
- **Movimento** oferece controles para o movimento aleatório, o inventário e o ônibus.
- **Tesouro e Discord** configura o resgate, o webhook e as imagens de recompensa.
- **Esquadrão** configura a conferência do modo e o critério de saída pela composição da equipe.
- **Região de dia** importa as sequências de seleção e verificação do pareamento.
- **Leitura de tela** controla o OCR em português e inglês e permite recortes opcionais.
- **Atualizações** consulta as releases do GitHub e instala novas versões quando não há sessão em execução.

Na página **Atividade**, **Testar fila do Fortnite** executa só o teste de entrada na fila. O app confirma a fila pela tela ou por eventos novos do log local do jogo. **Copiar atividade** copia o resultado para diagnóstico.

O Fortnite precisa estar no primeiro plano. **F8** pausa ou retoma. **F9** encerra a sessão. A leitura de regiões e a composição visual do esquadrão têm configuração própria. Veja [as etapas opcionais de configuração](Configuracao.md).

Para usar em outro computador, copie o executável. Se personalizou as detecções, leve a pasta de recortes também. Os ajustes são gravados ao lado do executável. O arquivo `webhook_discord.txt` contém a credencial do canal e deve ficar privado.

## Desenvolvimento

No Windows com Python 3.14, execute `py -3.14 -m pip install -r requirements.txt`, `py -3.14 preparar_ocr.py` e `py -3.14 app.py`.

Para gerar o executável, use:

```powershell
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --collect-data tzdata --collect-all rapidocr --copy-metadata rapidocr --add-data "modelos;modelos" app.py
```

O workflow compila e testa o executável no Windows. A publicação usa a versão em `versao.py`.

A leitura de tela usa [RapidOCR](https://github.com/RapidAI/RapidOCR) e os modelos PP-OCR. O executável inclui os avisos de licença do pacote RapidOCR.
