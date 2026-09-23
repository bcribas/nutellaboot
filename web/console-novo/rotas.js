// As abas do console e o endereço de cada página: #aba[/id[/seção]].
//
// Uma aba por vez, cada uma com link próprio (dá para mandar #imagens/26brbr
// para alguém), e o voltar do navegador funciona. Aba desconhecida, ou só da
// administração para um sub-admin, cai na aba padrão do mesmo jeito: a tela
// não diz o que existe para quem não pode ver.

import { t } from "/common/i18n.js";
import { $ } from "/common/ui.js";
import { confirmar } from "/common/dialogo.js";
import { mostrarErro } from "/common/acao.js";
import { ehAdmin, esquecerRascunhos, temSujo } from "./comum.js";
import * as imagens from "./imagens.js";
import * as modelos from "./modelos.js";
import * as camadas from "./camadas.js";
import * as pessoas from "./pessoas.js";
import * as chaves from "./chaves.js";
import * as sistema from "./sistema.js";

export const PADRAO = "imagens";

export const ROTAS = {
  imagens: { admin: false, vista: imagens.vista, titulo: "nav_images" },
  modelos: { admin: false, vista: modelos.vista, titulo: "nav_models" },
  camadas: { admin: false, vista: camadas.vista, titulo: "nav_layers" },
  pessoas: { admin: true, vista: pessoas.vista, titulo: "nav_people" },
  chaves: { admin: true, vista: chaves.vista, titulo: "nav_keys" },
  sistema: { admin: true, vista: sistema.vista, titulo: "nav_system" },
};

const decodificar = (p) => {
  try {
    return decodeURIComponent(p);
  } catch {
    return p;
  }
};

export const lerHash = (hash) => {
  const partes = String(hash || "").replace(/^#/, "").split("/").map(decodificar);
  return { aba: partes[0] || "", id: partes[1] || "", secao: partes[2] || "" };
};

const permitida = (aba) => Boolean(ROTAS[aba]) && (!ROTAS[aba].admin || ehAdmin());

let atual = null;
let hashAtual = "";

const rolarPara = (secao) => {
  const alvo = document.getElementById(`s-${secao}`);
  if (alvo) alvo.scrollIntoView({ behavior: "smooth", block: "start" });
};

const marcarAba = (aba) => {
  for (const a of document.querySelectorAll("#abas a")) {
    const ativa = a.dataset.aba === aba;
    a.classList.toggle("on", ativa);
    if (ativa) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
};

// Desenha a página do endereço atual. Com `forcar`, redesenha a mesma página
// (troca de idioma, sessão que voltou): os rascunhos continuam.
export const renderizar = async ({ forcar = false } = {}) => {
  let rota = lerHash(location.hash);
  if (!permitida(rota.aba)) {
    history.replaceState(null, "", `#${PADRAO}`);
    rota = { aba: PADRAO, id: "", secao: "" };
  }
  const vista = $("#vista");
  const mesmaPagina = atual && atual.aba === rota.aba && atual.id === rota.id;
  if (mesmaPagina && !forcar && vista.dataset.pronto === "1") {
    // só a seção mudou: rola até ela, sem redesenhar
    hashAtual = location.hash;
    if (rota.secao) rolarPara(rota.secao);
    return;
  }
  if (atual && atual.controle) atual.controle.abort();
  const controle = new AbortController();
  atual = { ...rota, controle };
  hashAtual = location.hash;
  marcarAba(rota.aba);
  vista.dataset.pronto = "0";
  vista.dataset.rota = rota.id ? `${rota.aba}/${rota.id}` : rota.aba;
  vista.replaceChildren();
  try {
    await ROTAS[rota.aba].vista(vista, { ...rota, sinal: controle.signal });
  } catch (e) {
    if (!controle.signal.aborted) mostrarErro(e);
  }
  if (controle.signal.aborted) return;
  document.title = `${t(ROTAS[rota.aba].titulo)} · NutellaBoot 3`;
  vista.dataset.pronto = "1";
  if (rota.secao) {
    rolarPara(rota.secao);
  } else {
    const titulo = vista.querySelector("h1");
    if (titulo) titulo.focus({ preventScroll: true });
  }
};

// Sair de uma página com edição não salva pergunta antes. O hashchange já
// aconteceu quando isto roda: o endereço volta enquanto a pergunta está aberta.
const aoMudarHash = async () => {
  if (location.hash === hashAtual) return;
  const destino = location.hash;
  const rota = lerHash(destino);
  const mesmaPagina = atual && rota.aba === atual.aba && rota.id === atual.id;
  if (!mesmaPagina && temSujo()) {
    history.replaceState(null, "", hashAtual);
    const sair = await confirmar({ texto: t("unsaved_leave_confirm"), acao: t("act_leave"), perigo: true });
    if (!sair) return;
    history.pushState(null, "", destino);
  }
  if (!mesmaPagina) esquecerRascunhos();
  renderizar();
};

export const iniciar = () => {
  window.addEventListener("hashchange", aoMudarHash);
  // recarregar ou fechar a aba com edição pendente: o navegador pergunta
  window.addEventListener("beforeunload", (ev) => {
    if (!temSujo()) return;
    ev.preventDefault();
    ev.returnValue = "";
  });
  renderizar();
};
