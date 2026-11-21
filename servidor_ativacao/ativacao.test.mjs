import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";
import { criarServico } from "./index.js";

// Executa as consultas do Worker em SQLite, incluindo a transação usada pelo batch do D1.
function bancoDeTeste(t) {
  const sql = new DatabaseSync(":memory:");
  t.after(() => sql.close());
  function preparar(texto, valores = []) {
    const stmt = sql.prepare(texto);
    return {
      bind: (...args) => preparar(texto, args),
      first: async () => stmt.get(...valores),
      executar: () => ({ results: stmt.all(...valores) }),
    };
  }
  return {
    prepare: (texto) => ({
      bind: (...args) => preparar(texto, args),
      first: async () => sql.prepare(texto).get(),
      executar: () => ({ results: sql.prepare(texto).all() }),
    }),
    async batch(declaracoes) {
      sql.exec("BEGIN");
      try {
        const resultado = declaracoes.map(stmt => stmt.executar());
        sql.exec("COMMIT");
        return resultado;
      } catch (erro) {
        sql.exec("ROLLBACK");
        throw erro;
      }
    },
  };
}

const pcA = "0A".repeat(16);
const pcB = "0B".repeat(16);
const origem = "https://teste.invalid";
async function contexto(t) {
  const DB = bancoDeTeste(t);
  const vendedor = await crypto.subtle.generateKey("Ed25519", true, ["verify", "sign"]);
  const publica = Buffer.from(await crypto.subtle.exportKey("raw", vendedor.publicKey)).toString("hex");
  const obterServico = (instante) => criarServico(publica, () => new Date(instante));
  const servico = obterServico("2026-11-22T02:59:00Z"); // 23h59 de 21/11 em Brasília
  async function venda(dias) {
    const prazo = Buffer.alloc(4);
    prazo.writeUInt32BE(dias);
    const carga = Buffer.concat([Buffer.from("AutoFarmToken/Venda/v1\0"),
      crypto.getRandomValues(new Uint8Array(16)), prazo]);
    const sig = await crypto.subtle.sign("Ed25519", vendedor.privateKey, carga);
    return "AFV1." + Buffer.concat([carga, new Uint8Array(sig)]).toString("base64url");
  }
  function ativar(chave, pc, em = servico) {
    return em.fetch(new Request(origem + "/ativar", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chave, pc }) }), { DB });
  }
  async function chavePublica(em = servico) {
    const resposta = await em.fetch(new Request(origem + "/chave-publica"), { DB });
    const dados = await resposta.json();
    assert.deepEqual(Object.keys(dados), ["chave_publica"]);
    return dados.chave_publica;
  }
  return { venda, ativar, chavePublica, obterServico };
}

test("somente um PC vence a corrida e recupera o mesmo recibo após reiniciar o serviço", async (t) => {
  const ctx = await contexto(t);
  const chave = await ctx.venda(30);
  const [a, b] = await Promise.all([ctx.ativar(chave, pcA), ctx.ativar(chave, pcB)]);
  assert.deepEqual([a.status, b.status].sort(), [200, 409]);
  const pc = a.ok ? pcA : pcB;
  const { licenca } = await (a.ok ? a : b).json();
  assert.match(licenca, /^AFA1\./);
  const dados = Buffer.from(licenca.slice(5), "base64url");
  const carga = dados.subarray(0, -64);
  const publica = await ctx.chavePublica();
  const verificador = await crypto.subtle.importKey("raw", Buffer.from(publica, "hex"), "Ed25519", false, ["verify"]);
  assert.ok(await crypto.subtle.verify("Ed25519", verificador, dados.subarray(-64), carga));
  const marca = Buffer.from("AutoFarmToken/Ativacao/v1\0");
  assert.deepEqual(carga.subarray(0, marca.length), marca);
  assert.deepEqual(carga.subarray(marca.length, -20), Buffer.from(await crypto.subtle.digest("SHA-256", Buffer.from(chave))));
  assert.equal(carga.subarray(-20, -4).toString("hex").toUpperCase(), pc);
  const reiniciado = ctx.obterServico("2026-11-26T16:00:00Z");
  assert.equal(await ctx.chavePublica(reiniciado), publica);
  assert.deepEqual(await (await ctx.ativar(chave, pc, reiniciado)).json(), { licenca });
});

test("validade segue o dia de Brasília da primeira ativação e vitalícia permanece válida", async (t) => {
  const ctx = await contexto(t);
  const umDia = await ctx.venda(1);
  const vitalicia = await ctx.venda(0);
  assert.equal((await ctx.ativar(umDia, pcA)).status, 200);
  const proximoDia = ctx.obterServico("2026-11-22T03:00:00Z");
  assert.equal((await ctx.ativar(umDia, pcA, proximoDia)).status, 410);
  const r = await (await ctx.ativar(vitalicia, pcB)).json();
  const carga = Buffer.from(r.licenca.slice(5), "base64url").subarray(0, -64);
  assert.equal(carga.readUInt32BE(carga.length - 4), 0);
  assert.deepEqual(await (await ctx.ativar(vitalicia, pcB, ctx.obterServico("2100-01-01T14:00:00Z"))).json(), r);
});

test("recusa chave sem assinatura do vendedor, formato inválido e corpo grande", async (t) => {
  const a = await contexto(t);
  const b = await contexto(t);
  const venda = await a.venda(1);
  assert.equal((await b.ativar(venda, pcA)).status, 400);
  assert.equal((await a.ativar(venda + "=", pcA)).status, 400);
  assert.equal((await a.ativar(venda, "sem código")).status, 400);
  assert.equal((await a.ativar("x".repeat(3000), pcA)).status, 413);
  assert.equal((await a.ativar(venda, pcB)).status, 200);
});
