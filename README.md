# Auto Farm do Token Pirata

[Baixar o executável para Windows x64](https://github.com/danielsolzapo-dev/Token/releases/latest/download/AutoFarmTokenPirata.exe)

Painel portátil para Windows x64. Abra `AutoFarmTokenPirata.exe`, importe os recortes nas páginas correspondentes e clique em **Iniciar**. A primeira sessão começa em **Modo prévia**. A tela **Atividade** mostra os resultados.

- **Fila e saída** controla o clique no lobby, o cronômetro por partida e a pausa programada.
- **Movimento** oferece controles para o movimento aleatório, o inventário e o ônibus.
- **Tesouro e Discord** configura o resgate, o webhook e as imagens de recompensa.
- **Esquadrão** configura a conferência do modo e o critério de saída pela composição da equipe.
- **Região de dia** importa as sequências de seleção e verificação do pareamento.
- **Recortes** permite importar os PNGs, escolher a pasta e ajustar a similaridade.

O Fortnite precisa estar no primeiro plano. **F8** pausa ou retoma. **F9** encerra a sessão. Veja [os nomes dos recortes e as etapas de configuração](Configuracao.md).

Para usar em outro computador, copie o executável e a pasta de recortes. Os ajustes são gravados ao lado do executável. O arquivo `webhook_discord.txt` contém a credencial do canal e deve ficar privado.

## Desenvolvimento

No Windows com Python 3.14, execute `py -3.14 -m pip install -r requirements.txt` e depois `py -3.14 app.py`.

Para gerar o executável, use:

```powershell
py -3.14 -m PyInstaller --noconfirm --onefile --windowed --name AutoFarmTokenPirata --collect-data tzdata app.py
```

O workflow compila no Windows e publica o executável na primeira release de `main` e nas novas tags `v*`.
