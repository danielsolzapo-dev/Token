// Esta chave verifica vendas emitidas pelo vendedor. A chave que assina os recibos fica no D1.
const PUBLICA_VENDEDOR = "fdd57e5f40516e3016932e0a9e1be3a2f511a1413bd49df6c2f8bf7358b54602";
const utf8 = new TextEncoder();
const VENDA = utf8.encode("AutoFarmToken/Venda/v1\0");
const RECIBO = utf8.encode("AutoFarmToken/Ativacao/v1\0");
const LIMITE_CORPO = 2048;
const dataBrasilia = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit",
});

function emHex(bytes) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}

function deHex(texto) {
  return Uint8Array.from(texto.match(/../g), par => parseInt(par, 16));
}

function emBase64(bytes) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function deBase64(texto) {
  return Uint8Array.from(atob(texto.replace(/-/g, "+").replace(/_/g, "/")), letra => letra.charCodeAt(0));
}

function ordinalBrasilia(instante) {
  const p = Object.fromEntries(dataBrasilia.formatToParts(instante).map(item => [item.type, item.value]));
  return Math.floor(Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day)) / 86400000) + 719163;
}

class ErroPedido extends Error {
  constructor(status, mensagem) {
    super(mensagem);
    this.status = status;
  }
}

function json(dados, status = 200) {
  return Response.json(dados, { status, headers: { "Cache-Control": "no-store" } });
}

async function lerPedido(request) {
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    throw new ErroPedido(415, "Envie o pedido como JSON.");
  }
  if (Number(request.headers.get("content-length")) > LIMITE_CORPO) {
    throw new ErroPedido(413, "Pedido muito grande.");
  }
  if (!request.body) throw new ErroPedido(400, "O pedido está vazio.");
  const leitor = request.body.getReader();
  const corpo = new Uint8Array(LIMITE_CORPO);
  let tamanho = 0;
  try {
    while (true) {
      const { value, done } = await leitor.read();
      if (done) break;
      if (tamanho + value.length > LIMITE_CORPO) {
        await leitor.cancel();
        throw new ErroPedido(413, "Pedido muito grande.");
      }
      corpo.set(value, tamanho);
      tamanho += value.length;
    }
  } finally {
    leitor.releaseLock();
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(corpo.subarray(0, tamanho)));
  } catch {
    throw new ErroPedido(400, "O pedido está incompleto ou inválido.");
  }
}

async function verificarVenda(chave, vendedor) {
  const erro = new ErroPedido(400, "Chave de venda inválida.");
  const tamanho = VENDA.length + 16 + 4 + 64;
  if (typeof chave !== "string" || chave.length !== 5 + Math.ceil(tamanho * 4 / 3)
      || !/^AFV1\.[A-Za-z0-9_-]+$/.test(chave)) throw erro;
  const texto = chave.slice(5);
  const dados = deBase64(texto);
  if (emBase64(dados) !== texto || !VENDA.every((byte, i) => dados[i] === byte)) throw erro;
  const carga = dados.subarray(0, tamanho - 64);
  const dias = new DataView(carga.buffer, carga.byteOffset, carga.length).getUint32(carga.length - 4);
  const publica = await crypto.subtle.importKey("raw", deHex(vendedor), "Ed25519", false, ["verify"]);
  if (dias > 36500 || !await crypto.subtle.verify("Ed25519", publica, dados.subarray(carga.length), carga)) {
    throw erro;
  }
  return { dias, digest: new Uint8Array(await crypto.subtle.digest("SHA-256", utf8.encode(chave))) };
}

const esquemaPronto = new WeakSet();

async function prepararBanco(db) {
  if (esquemaPronto.has(db)) return;
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS assinante (
      id INTEGER PRIMARY KEY CHECK (id = 1), publica TEXT NOT NULL, privada TEXT NOT NULL)`),
    db.prepare(`CREATE TABLE IF NOT EXISTS ativacoes (
      venda TEXT PRIMARY KEY, pc TEXT NOT NULL, dia_inicio INTEGER NOT NULL, vencimento INTEGER NOT NULL)`),
  ]);
  esquemaPronto.add(db);
}

async function obterAssinante(db) {
  const consulta = db.prepare("SELECT publica, privada FROM assinante WHERE id = 1");
  const existente = await consulta.first();
  if (existente) return existente;
  const par = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
  const publica = emHex(new Uint8Array(await crypto.subtle.exportKey("raw", par.publicKey)));
  const privada = emBase64(new Uint8Array(await crypto.subtle.exportKey("pkcs8", par.privateKey)));
  // Releia o par efetivamente gravado mesmo se outra instância inicializou o banco em paralelo.
  const [, leitura] = await db.batch([
    db.prepare("INSERT INTO assinante(id, publica, privada) VALUES (1, ?, ?) ON CONFLICT(id) DO NOTHING")
      .bind(publica, privada), consulta,
  ]);
  return leitura.results[0];
}

async function registrar(db, venda, pc, hoje, dias) {
  const fim = dias ? hoje + dias - 1 : 0;
  const [, leitura] = await db.batch([
    db.prepare(`INSERT INTO ativacoes(venda, pc, dia_inicio, vencimento) VALUES (?, ?, ?, ?)
      ON CONFLICT(venda) DO NOTHING`).bind(venda, pc, hoje, fim),
    db.prepare("SELECT pc, vencimento FROM ativacoes WHERE venda = ?").bind(venda),
  ]);
  const registro = leitura.results[0];
  if (registro.pc !== pc) throw new ErroPedido(409, "Esta chave já foi ativada em outro PC.");
  if (registro.vencimento && registro.vencimento < hoje) throw new ErroPedido(410, "Esta licença venceu.");
  return registro.vencimento;
}

async function emitirRecibo(privada, digest, pc, fim) {
  const carga = new Uint8Array(RECIBO.length + 32 + 16 + 4);
  carga.set(RECIBO);
  carga.set(digest, RECIBO.length);
  carga.set(deHex(pc), RECIBO.length + 32);
  new DataView(carga.buffer).setUint32(carga.length - 4, fim);
  const chave = await crypto.subtle.importKey("pkcs8", deBase64(privada), "Ed25519", false, ["sign"]);
  const assinatura = await crypto.subtle.sign("Ed25519", chave, carga);
  const token = new Uint8Array(carga.length + assinatura.byteLength);
  token.set(carga);
  token.set(new Uint8Array(assinatura), carga.length);
  return "AFA1." + emBase64(token);
}

export function criarServico(vendedor, relogio = () => new Date()) {
  return {
    async fetch(request, env) {
      try {
        const rota = new URL(request.url).pathname;
        if (rota === "/" && request.method === "GET") return json({ servico: "Ativação do Auto Farm" });
        if (rota === "/chave-publica" && request.method === "GET") {
          await prepararBanco(env.DB);
          const assinante = await obterAssinante(env.DB);
          return json({ chave_publica: assinante.publica });
        }
        if (rota !== "/ativar") return json({ erro: "Recurso indisponível." }, 404);
        if (request.method !== "POST") return json({ erro: "Use POST para ativar." }, 405);
        const pedido = await lerPedido(request);
        const pc = pedido?.pc;
        if (typeof pc !== "string" || pc.length !== 32 || !/^[A-F0-9]{32}$/.test(pc)) {
          throw new ErroPedido(400, "Código do PC inválido.");
        }
        const { dias, digest } = await verificarVenda(pedido.chave, vendedor);
        await prepararBanco(env.DB);
        const assinante = await obterAssinante(env.DB);
        const fim = await registrar(env.DB, emHex(digest), pc, ordinalBrasilia(relogio()), dias);
        return json({ licenca: await emitirRecibo(assinante.privada, digest, pc, fim) });
      } catch (erro) {
        if (erro instanceof ErroPedido) return json({ erro: erro.message }, erro.status);
        return json({ erro: "Serviço de ativação indisponível. Tente novamente." }, 503);
      }
    },
  };
}

export default criarServico(PUBLICA_VENDEDOR);
