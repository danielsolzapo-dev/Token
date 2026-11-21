// SPDX-License-Identifier: GPL-3.0-or-later
using System.Text.Json;
using FortniteReplayReader.Analysis;
using FortniteReplayReader.Editing;

namespace LeitorBaus;

internal static class Program
{
    private static readonly StringComparer Id = StringComparer.OrdinalIgnoreCase;
    private static readonly string[] OutrosRecipientes = ["Ammo", "Cannon", "FoodBox", "Food_Box", "Cooler"];

    private static bool AberturaDeBau(ReplayChestOpening abertura)
    {
        if (abertura.IsDestruction) return false;
        var tipo = abertura.ChestClass;
        return !OutrosRecipientes.Any(palavra => tipo.Contains(palavra, StringComparison.OrdinalIgnoreCase));
    }

    private static object Analisar(string caminho)
    {
        using var arquivo = ReplayContainer.LoadForAnalysis(caminho);
        var leitura = new ReplayChestAnalysisReader(arquivo).Scan();
        if (leitura.SearchFieldsDecoded == 0)
            return new { erro = "Este replay não contém campos de abertura de baú reconhecidos." };

        var jogadores = leitura.Replay.PlayerData.Where(j => !j.IsBot).ToArray();
        var donos = jogadores.Where(j => j.IsReplayOwner).ToArray();
        if (donos.Length != 1 || string.IsNullOrWhiteSpace(donos[0].PlayerId))
            return new { erro = "O replay não identificou quem gravou a partida." };

        var dono = donos[0];
        var colegas = jogadores.Where(j => j.TeamIndex == dono.TeamIndex).ToArray();
        var idsEquipe = colegas.Where(j => !string.IsNullOrWhiteSpace(j.PlayerId))
            .Select(j => j.PlayerId!).ToHashSet(Id);
        // O leitor entrega uma abertura por ator e ciclo de reabastecimento.
        var abertos = leitura.Openings.Where(AberturaDeBau).ToArray();
        int pessoal = abertos.Count(a => Id.Equals(a.PlayerId, dono.PlayerId));
        int totalEquipe = abertos.Count(a => a.PlayerId is not null && idsEquipe.Contains(a.PlayerId));
        int semAutor = abertos.Count(a => string.IsNullOrWhiteSpace(a.PlayerId));
        bool autoriaDisponivel = abertos.Length == 0 ? !leitura.HasDecodeErrors : semAutor < abertos.Length;
        bool equipeSemId = colegas.Any(j => string.IsNullOrWhiteSpace(j.PlayerId));
        int? voce = autoriaDisponivel ? pessoal : null;
        int? esquadrao = autoriaDisponivel && dono.TeamIndex is > 0 ? totalEquipe : null;
        var notas = new List<string> { "Aberturas confirmadas no replay. Ações de colegas distantes podem ficar fora da gravação." };
        if (semAutor > 0) notas.Add($"Aberturas sem autor identificado: {semAutor}.");
        if (leitura.HasDecodeErrors) notas.Add("Parte dos dados de baús ficou ilegível.");
        if (dono.TeamIndex is null or <= 0) notas.Add("O replay não identificou o seu esquadrão.");
        else if (equipeSemId) notas.Add("Há integrantes sem identificação na gravação.");
        return new { protocolo = 1, voce, esquadrao, detalhe = string.Join(" ", notas) };
    }

    public static int Main(string[] args)
    {
        object resposta;
        if (args is ["--verificar-build"])
            resposta = new { protocolo = 1 };
        else if (args.Length != 1)
            resposta = new { erro = "Selecione um arquivo .replay." };
        else
        {
            try
            {
                resposta = Analisar(args[0]);
            }
            catch (NotSupportedException)
            {
                resposta = new { erro = "Esta versão ou formato de replay ainda não é compatível." };
            }
            catch (Exception)
            {
                resposta = new { erro = "Não foi possível ler a partida. O replay pode estar incompleto ou ser de uma versão incompatível." };
            }
        }
        Console.WriteLine(JsonSerializer.Serialize(resposta));
        return 0;
    }
}
