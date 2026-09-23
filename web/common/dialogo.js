// O único lugar que cria <dialog>.
//
// O console tinha quatro construtores de diálogo copiados um do outro, mais
// prompt() e confirm() do navegador, um painel solto no fim da página e cartões
// enfiados no topo: cada ação perguntava de um jeito, e metade aparecia longe
// do botão. Aqui há quatro formas, e só estas:
//   confirmar     — sim/não, com "digite para confirmar" no que é irreversível;
//   formulario    — criar, editar, escolher (Enter confirma; o erro fica dentro);
//   mostrarSegredo — o que aparece uma vez só (chave nova, código de convite);
//   abrirDialogo  — a moldura, para quem monta um escolhedor próprio.

import { t } from "/common/i18n.js";
import { el, copiavel } from "/common/ui.js";
import { mensagemDeErro, mostrarErro } from "/common/acao.js";

export const rotulosDeCopia = () => ({
  copy: t("copy"),
  copied: t("copied"),
  show: t("act_show"),
  hide: t("act_hide"),
});

// A moldura: título, corpo, rodapé com os botões, dentro de um
// <form method="dialog"> (Enter num campo aciona o botão de submit). `fixo`
// ignora o Esc: é o segredo que só aparece uma vez. O foco volta para quem
// abriu, e o diálogo sai do DOM ao fechar.
export const abrirDialogo = ({ titulo = "", largo = false, fixo = false, aoFechar = null } = {}) => {
  const quemAbriu = document.activeElement;
  const dlg = el("dialog", { class: largo ? "dlg largo" : "dlg" });
  const form = el("form", { method: "dialog" });
  const corpo = el("div", { class: "dlg-corpo" });
  const rodape = el("div", { class: "acoes-dlg" });
  form.append(corpo, rodape);
  dlg.append(el("h2", {}, titulo), form);
  // O `cancel` só é cancelável depois de um gesto do usuário (regra do
  // navegador contra janelas que não fecham), e o segredo abre depois de uma
  // chamada assíncrona: o Esc fechava assim mesmo. Barrar o próprio keydown do
  // Esc impede o pedido de fechamento antes de ele existir.
  dlg.addEventListener("keydown", (ev) => {
    if (fixo && ev.key === "Escape") ev.preventDefault();
  });
  dlg.addEventListener("cancel", (ev) => {
    if (fixo) ev.preventDefault();
  });
  dlg.addEventListener("close", () => {
    dlg.remove();
    if (quemAbriu && quemAbriu.isConnected && quemAbriu.focus) quemAbriu.focus();
    if (aoFechar) aoFechar(dlg.returnValue);
  });
  document.body.append(dlg);
  dlg.showModal();
  const fechar = () => {
    if (dlg.open) dlg.close();
  };
  return { dlg, form, corpo, rodape, fechar };
};

// Sim ou não. `perigo` pinta o botão de vermelho e põe o foco no Cancelar;
// `digitar` exige escrever aquele texto (o id da imagem, o nome do modelo)
// antes de liberar o botão — para o que não tem volta.
export const confirmar = ({ titulo = "", texto = "", acao = "", perigo = false, digitar = "" } = {}) =>
  new Promise((resolve) => {
    let aceito = false;
    const { corpo, rodape, fechar } = abrirDialogo({
      titulo: titulo || t("dlg_confirm_title"),
      aoFechar: () => resolve(aceito),
    });
    if (texto) corpo.append(el("p", {}, texto));
    const sim = el("button", { type: "button", class: perigo ? "danger" : "primary" }, acao || t("act_confirm"));
    const nao = el("button", { type: "button" }, t("cancel"));
    sim.onclick = () => {
      aceito = true;
      fechar();
    };
    nao.onclick = () => fechar();
    rodape.append(sim, nao);
    if (digitar) {
      const campo = el("input", { type: "text", autocomplete: "off", spellcheck: "false" });
      corpo.append(el("label", { class: "fld" }, el("span", {}, t("dlg_type_to_confirm", { texto: digitar })), campo));
      sim.disabled = true;
      campo.oninput = () => {
        sim.disabled = campo.value.trim() !== digitar;
      };
      campo.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (!sim.disabled) sim.click();
        }
      };
      campo.focus();
    } else if (perigo) {
      nao.focus();
    } else {
      sim.focus();
    }
  });

const controleDe = (campo) => {
  const tipo = campo.tipo || "text";
  if (tipo === "no") return campo.no;
  if (tipo === "select") {
    const sel = el("select", { name: campo.nome });
    for (const op of campo.opcoes || []) {
      sel.append(el("option", { value: op.valor, selected: String(op.valor) === String(campo.valor ?? "") }, op.rotulo));
    }
    return sel;
  }
  if (tipo === "textarea") {
    const area = el("textarea", { name: campo.nome, placeholder: campo.placeholder || false });
    area.value = campo.valor ?? "";
    return area;
  }
  if (tipo === "checkbox") return el("input", { type: "checkbox", name: campo.nome, checked: Boolean(campo.valor) });
  const entrada = el("input", {
    type: tipo,
    name: campo.nome,
    placeholder: campo.placeholder || false,
    min: campo.min ?? false,
    max: campo.max ?? false,
    accept: campo.accept || false,
    autocomplete: "off",
  });
  if (tipo !== "file") entrada.value = campo.valor ?? "";
  return entrada;
};

const valorDe = (campo, controle) => {
  const tipo = campo.tipo || "text";
  if (tipo === "no") return campo.ler ? campo.ler() : null;
  if (tipo === "checkbox") return controle.checked;
  if (tipo === "file") return controle.files && controle.files.length ? controle.files[0] : null;
  if (tipo === "number") return controle.value === "" ? null : Number(controle.value);
  if (tipo === "select" || tipo === "password") return controle.value;
  return controle.value.trim();
};

// Um formulário curto. `campos`: [{nome, rotulo, tipo, valor, opcoes:[{valor,
// rotulo}], ajuda, obrigatorio, min, max, placeholder, accept, aoMudar}], com
// tipo text | number | password | date | url | select | textarea | checkbox |
// file | no (um nó pronto, com `ler()`). `aoMudar(valor, controles)` deixa um
// campo mexer em outro (Livre desmarca a trava do papel de parede).
//
// Com `enviar(valores)`, o diálogo só fecha quando ele termina bem; o erro
// aparece DENTRO do diálogo, com o que foi digitado intacto. Devolve o que
// `enviar` devolveu (ou os valores), ou null quando cancelado.
export const formulario = ({
  titulo = "",
  texto = "",
  campos = [],
  acao = "",
  perigo = false,
  largo = false,
  enviar = null,
  antes = null,
} = {}) =>
  new Promise((resolve) => {
    let resultado = null;
    const { form, corpo, rodape, fechar } = abrirDialogo({ titulo, largo, aoFechar: () => resolve(resultado) });
    const erro = el("p", { class: "msg bad", hidden: true, role: "alert" });
    corpo.append(erro);
    if (texto) corpo.append(el("p", { class: "help" }, texto));
    if (antes) corpo.append(antes);

    const controles = {};
    for (const campo of campos) {
      const controle = controleDe(campo);
      controles[campo.nome] = controle;
      const ajuda = campo.ajuda ? el("span", { class: "help" }, campo.ajuda) : null;
      if ((campo.tipo || "text") === "checkbox") {
        corpo.append(el("div", { class: "fld" }, el("label", { class: "inline" }, controle, " ", campo.rotulo), ajuda));
      } else if (campo.tipo === "no") {
        // bloco pronto (prévia com botões): dentro de <label>, um clique nele
        // acionaria o primeiro controle
        corpo.append(el("div", { class: "fld" }, el("span", {}, campo.rotulo), controle, ajuda));
      } else {
        corpo.append(el("label", { class: "fld" }, el("span", {}, campo.rotulo), controle, ajuda));
      }
    }
    for (const campo of campos) {
      if (!campo.aoMudar) continue;
      const controle = controles[campo.nome];
      const avisar = () => campo.aoMudar(valorDe(campo, controle), controles);
      controle.addEventListener("change", avisar);
      if ((campo.tipo || "text") !== "checkbox") controle.addEventListener("input", avisar);
    }

    const ok = el("button", { type: "submit", class: perigo ? "danger" : "primary" }, acao || t("save"));
    const cancelar = el("button", { type: "button" }, t("cancel"));
    cancelar.onclick = () => fechar();
    rodape.append(ok, cancelar);

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      erro.hidden = true;
      const valores = {};
      for (const campo of campos) {
        valores[campo.nome] = valorDe(campo, controles[campo.nome]);
        const vazio = valores[campo.nome] === "" || valores[campo.nome] === null;
        if (campo.obrigatorio && vazio) {
          erro.textContent = t("dlg_required", { campo: campo.rotulo });
          erro.hidden = false;
          controles[campo.nome].focus();
          return;
        }
      }
      if (!enviar) {
        resultado = valores;
        fechar();
        return;
      }
      ok.disabled = true;
      ok.setAttribute("aria-busy", "true");
      try {
        const r = await enviar(valores);
        resultado = r === undefined ? valores : r;
        fechar();
      } catch (e) {
        if (e && e.status === 401) {
          // a sessão caiu: o login não pode aparecer atrás de um modal
          fechar();
          mostrarErro(e);
          return;
        }
        erro.textContent = mensagemDeErro(e);
        erro.hidden = !erro.textContent;
      } finally {
        ok.disabled = false;
        ok.removeAttribute("aria-busy");
      }
    });

    const primeiro = campos.length ? controles[campos[0].nome] : ok;
    if (primeiro && primeiro.focus) primeiro.focus();
  });

// O que aparece uma vez só. Com `umaVez`, o Esc não fecha e o único botão é
// "Já copiei": fechar sem querer perdia a chave. `itens`: [{rotulo, valor,
// oculto}]; `extra`: um nó a mais (o bloco do pendrive, os links).
export const mostrarSegredo = ({ titulo = "", itens = [], aviso = "", extra = null, umaVez = true } = {}) =>
  new Promise((resolve) => {
    const { corpo, rodape, fechar } = abrirDialogo({
      titulo,
      largo: true,
      fixo: umaVez,
      aoFechar: () => resolve(),
    });
    if (aviso) corpo.append(el("p", { class: "msg warn" }, aviso));
    const lista = el("dl", { class: "kv" });
    for (const item of itens) {
      if (!item || !item.valor) continue;
      lista.append(
        el("dt", {}, item.rotulo),
        el("dd", {}, copiavel(item.valor, rotulosDeCopia(), { oculto: Boolean(item.oculto) }))
      );
    }
    corpo.append(lista);
    if (extra) corpo.append(extra);
    const ok = el("button", { type: "button", class: "primary" }, umaVez ? t("dlg_copied_close") : t("close"));
    ok.onclick = () => fechar();
    rodape.append(ok);
    ok.focus();
  });
