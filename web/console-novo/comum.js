// O que todas as abas do console usam: quem sou eu, rascunhos que sobrevivem
// ao redesenho, e as peças de página (cabeçalho, seção, tabela, carregamento).
// Cada objeto (imagem, modelo, pessoa) tem UMA página, feita destas peças; o
// diálogo fica para confirmar, criar, escolher e mostrar segredo.

import { t } from "/common/i18n.js";
import { el } from "/common/ui.js";
import { mensagemDeErro, mostrarErro } from "/common/acao.js";

export const A = { kind: "admin" };

let euAtual = null;

export const definirEu = (x) => {
  euAtual = x;
};
export const eu = () => euAtual;
export const ehAdmin = () => Boolean(euAtual && euAtual.kind === "admin");

// --- rascunhos ---
//
// Um formulário da página guarda o que foi digitado aqui, e não no DOM: a
// troca de idioma redesenha a página, e antes cada ação redesenhava o painel
// inteiro e jogava fora os cadeados que ninguém tinha salvado.
const rascunhos = new Map();
const sujos = new Set();

export const rascunho = (chave, criar) => {
  if (!rascunhos.has(chave)) rascunhos.set(chave, criar());
  return rascunhos.get(chave);
};
export const esquecerRascunho = (chave) => {
  rascunhos.delete(chave);
  sujos.delete(chave);
};
export const esquecerRascunhos = () => {
  rascunhos.clear();
  sujos.clear();
};
export const marcarSujo = (chave, sujo = true) => {
  if (sujo) sujos.add(chave);
  else sujos.delete(chave);
};
export const temSujo = () => sujos.size > 0;

// --- endereços ---

export const hashDe = (...partes) =>
  "#" + partes.filter((p) => p !== undefined && p !== null && p !== "").map((p) => encodeURIComponent(p)).join("/");
export const linkPara = (texto, ...partes) => el("a", { href: hashDe(...partes) }, texto);
export const irPara = (...partes) => {
  location.hash = hashDe(...partes);
};

// --- peças de página ---

export const cabecalho = ({ trilha = [], titulo = "", pills = [], acoes = [] } = {}) => {
  const topo = el("div", {});
  if (trilha.length) {
    const linha = el("p", { class: "trilha" });
    trilha.forEach((item, i) => {
      if (i) linha.append(" › ");
      linha.append(item);
    });
    topo.append(linha);
  }
  topo.append(
    el("div", { class: "cabecalho" },
      el("h1", { tabindex: "-1" }, titulo),
      ...pills,
      acoes.length ? el("div", { class: "acoes actions" }, ...acoes) : null)
  );
  return topo;
};

// Uma seção da página. O `id` vira âncora: #imagens/<id>/acesso rola até ela.
export const secao = ({ id = "", titulo = "", ajuda = "", acoes = [], perigo = false } = {}) => {
  const corpo = el("div", {});
  const no = el("section", { class: perigo ? "card perigo" : "card", id: id ? `s-${id}` : false },
    el("div", { class: "card-topo" },
      el("h2", {}, titulo),
      acoes.length ? el("div", { class: "acoes actions" }, ...acoes) : null),
    ajuda ? el("p", { class: "help" }, ajuda) : null,
    corpo);
  return { no, corpo };
};

// Carrega e desenha dentro de `corpo`; se falhar, o erro fica ali mesmo, com
// "Tentar de novo". Uma seção que falha não derruba as outras da página.
export const carregarEm = async (corpo, sinal, fn) => {
  corpo.replaceChildren(el("p", { class: "muted" }, t("loading")));
  try {
    await fn();
  } catch (e) {
    if (sinal && sinal.aborted) return;
    if (e && e.status === 401) {
      mostrarErro(e);
      return;
    }
    const repetir = el("button", { type: "button", class: "small" }, t("act_retry"));
    repetir.onclick = () => carregarEm(corpo, sinal, fn);
    corpo.replaceChildren(el("p", { class: "msg bad" }, mensagemDeErro(e), " ", repetir));
  }
};

// Objeto que não existe OU que é de outro dono: a mesma mensagem (o servidor
// já responde 404 aos dois, e a tela não pode ser o oráculo que ele evita).
export const naoEncontrado = (alvo, aba, rotuloDaAba) => {
  alvo.replaceChildren(
    cabecalho({ trilha: [linkPara(rotuloDaAba, aba)], titulo: t("err_not_found_title") }),
    el("p", { class: "msg warn" }, t("err_not_found_help")),
    el("p", {}, linkPara(t("act_back_to_list"), aba))
  );
};

export const campo = (rotulo, controle, ajuda = "") =>
  el("label", { class: "fld" }, el("span", {}, rotulo), controle, ajuda ? el("span", { class: "help" }, ajuda) : null);

export const caixa = (rotulo, controle, ajuda = "") =>
  el("div", { class: "fld" }, el("label", { class: "inline" }, controle, " ", rotulo),
    ajuda ? el("span", { class: "help" }, ajuda) : null);

// linhas: [células] ou {celulas, aoClicar}. A linha clicável leva à página do
// objeto; um clique num link, botão ou campo dentro dela não conta.
export const tabela = (colunas, linhas, { vazio = "" } = {}) => {
  if (!linhas.length && vazio) return el("p", { class: "muted" }, vazio);
  const corpo = el("tbody");
  for (const linha of linhas) {
    const celulas = Array.isArray(linha) ? linha : linha.celulas;
    const tr = el("tr", { class: linha.aoClicar ? "clicavel" : false },
      ...celulas.map((c) => (c && c.tagName === "TD" ? c : el("td", {}, c))));
    if (linha.aoClicar) {
      tr.onclick = (ev) => {
        if (ev.target.closest("a, button, input, select, label, textarea")) return;
        linha.aoClicar();
      };
    }
    corpo.append(tr);
  }
  const cabeca = colunas.length ? el("thead", {}, el("tr", {}, ...colunas.map((c) => el("th", {}, c)))) : null;
  return el("div", { class: "rolagem" }, el("table", {}, cabeca, corpo));
};

// --- rótulos ---

// De quem é: a administração, ou o rótulo do convite de quem criou (nunca o
// código, que é a credencial dele).
export const rotuloDoDono = (x) => {
  if (x.owner_kind !== "subadmin") return t("owner_admin");
  return x.owner_label || x.owner_ref || "";
};

export const pillPerfil = (livre) =>
  el("span", { class: livre ? "pill ok" : "pill", title: livre ? t("profile_free") : t("profile_official") },
    livre ? t("profile_free_short") : t("profile_official_short"));

export const rotuloDoPapel = (papel) => {
  if (papel === "base") return t("role_base");
  if (papel === "telemetry") return t("role_telemetry");
  if (papel === "wifi") return t("role_wifi");
  return t("role_extra");
};

export const rotuloDoEstado = (estado) => {
  if (estado === "done") return t("layer_state_done");
  if (estado === "failed") return t("layer_state_failed");
  if (estado === "running") return t("layer_state_running");
  return t("layer_state_queue");
};

export const tamanho = (bytes) => {
  if (!bytes && bytes !== 0) return "";
  if (bytes >= 1048576) return `${Math.round(bytes / 1048576)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} kB`;
};
