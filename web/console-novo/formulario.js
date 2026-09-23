// O formulário que a sede preenche, como o modelo o define: o valor padrão de
// cada campo, quem pode mudá-lo (o cadeado) e os textos nos três idiomas.
//
// Um Salvar só para a seção inteira, e o que foi digitado vive num rascunho.
// Antes, qualquer ação no painel do modelo (anexar uma camada, trocar o papel de
// parede) redesenhava tudo e jogava fora os cadeados e padrões não salvos; o
// botão dizia "Salvar cadeados" e salvava também os padrões.

import * as api from "/common/api.js";
import { t, tr } from "/common/i18n.js";
import { el } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { A, carregarEm, esquecerRascunho, marcarSujo, rascunho, tabela } from "./comum.js";

const LINGUAS = ["pt", "en", "es"];

// O controle do valor padrão, do tipo do campo. Uma caixa de texto para tudo
// deixaria alguém digitar "sim" num campo booleano e só descobrir na sala.
export function editorDePadrao(f, aoMudar) {
  if (f.type === "bool") {
    const s = el("select", {},
      el("option", { value: "true", selected: Boolean(f.default) }, t("yes")),
      el("option", { value: "false", selected: !f.default }, t("no")));
    s.onchange = () => aoMudar(s.value === "true");
    return s;
  }
  if (f.type === "select") {
    const s = el("select", {});
    for (const op of f.options || []) {
      const valor = typeof op === "string" ? op : op.value;
      const rotulo = tr(typeof op === "string" ? op : op.label) || valor;
      s.append(el("option", { value: valor, selected: String(valor) === String(f.default ?? "") }, rotulo));
    }
    s.onchange = () => aoMudar(s.value);
    return s;
  }
  if (f.type === "list" && (f.options || []).length) {
    // Lista com opções (INPUT_SOURCES): o mesmo controle do configureitor,
    // ordenado, com ↑ × e +. Era uma caixa de texto partida na vírgula, e os
    // valores TÊM vírgula dentro ("('xkb','br')"): "('xkb','latam'),('xkb','br')"
    // virava "('xkb'", "'latam')"… e o servidor recusava, com razão.
    return editorDeLista(f, aoMudar);
  }
  const i = el("input", { type: f.type === "int" ? "number" : "text", class: "mono" });
  // lista livre (sem opções) vira texto separado por vírgula ou espaço
  i.value = Array.isArray(f.default) ? f.default.join(", ") : (f.default ?? "");
  i.oninput = () => {
    if (f.type === "list") aoMudar(i.value.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean));
    else if (f.type === "int") aoMudar(i.value === "" ? null : Number(i.value));
    else aoMudar(i.value);
  };
  return i;
}

export function editorDeLista(f, aoMudar) {
  const caixa = el("div", { class: "list-editor" });
  const opcoes = (f.options || []).map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  const atual = Array.isArray(f.default) ? [...f.default] : [];
  const rotulo = (v) => {
    const o = opcoes.find((x) => x.value === v);
    return o ? tr(o.label) || o.value : v;
  };
  const redesenhar = () => {
    const linhas = atual.map((item, i) => {
      const sobe = el("button", { type: "button", class: "small", disabled: i === 0, title: t("act_move_up") }, "↑");
      sobe.onclick = () => {
        [atual[i - 1], atual[i]] = [atual[i], atual[i - 1]];
        aoMudar([...atual]);
        redesenhar();
      };
      const tira = el("button", { type: "button", class: "small danger", title: t("act_remove") }, "×");
      tira.onclick = () => {
        atual.splice(i, 1);
        aoMudar([...atual]);
        redesenhar();
      };
      return el("div", { class: "list-item" }, el("span", { class: "grow mono" }, rotulo(item)), sobe, tira);
    });
    const sobra = opcoes.filter((o) => !atual.includes(o.value));
    if (sobra.length) {
      const sel = el("select", { class: "grow" }, ...sobra.map((o) => el("option", { value: o.value }, tr(o.label) || o.value)));
      const mais = el("button", { type: "button", class: "small", title: t("act_add") }, "+");
      mais.onclick = () => {
        atual.push(sel.value);
        aoMudar([...atual]);
        redesenhar();
      };
      linhas.push(el("div", { class: "list-item" }, sel, mais));
    }
    caixa.replaceChildren(...linhas);
  };
  redesenhar();
  return caixa;
}

// {pt, en, es} a partir do que o schema tiver (texto solto vale para os três)
const trilingue = (x) => {
  if (x && typeof x === "object") return { pt: x.pt || "", en: x.en || "", es: x.es || "" };
  return { pt: x || "", en: x || "", es: x || "" };
};

const desligar = (no) => {
  if ("disabled" in no) no.disabled = true;
  no.querySelectorAll("button, select, input, textarea").forEach((x) => (x.disabled = true));
};

// A linha que se abre para editar rótulo e ajuda nos três idiomas.
const linhaDeTextos = (campo, aoMudar) => {
  const grade = el("div", { class: "grade" });
  for (const [chave, rotuloDaChave] of [["label", "field_label_lang"], ["help", "field_help_lang"]]) {
    for (const lingua of LINGUAS) {
      const entrada = el(chave === "help" ? "textarea" : "input", { type: chave === "help" ? false : "text" });
      entrada.value = campo[chave][lingua];
      if (chave === "help") entrada.style.minHeight = "60px";
      entrada.oninput = () => {
        campo[chave][lingua] = entrada.value;
        aoMudar();
      };
      grade.append(el("label", { class: "fld" }, el("span", {}, t(rotuloDaChave, { lang: lingua })), entrada));
    }
  }
  return grade;
};

export const desenharFormulario = (corpo, nome, gere, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const d = await api.get(`/api/v1/models/${encodeURIComponent(nome)}/schema`, { ...A, signal: sinal });
    const chave = `modelo:${nome}:formulario`;
    const original = {};
    for (const f of d.fields) {
      original[f.key] = { default: f.default ?? null, locked: Boolean(f.locked), label: trilingue(f.label), help: trilingue(f.help) };
    }
    const r = rascunho(chave, () => structuredClone(original));
    const mudou = () => marcarSujo(chave, JSON.stringify(r) !== JSON.stringify(original));
    const refazer = () => desenharFormulario(corpo, nome, gere, sinal);

    const linhas = [];
    for (const f of d.fields) {
      const campo = r[f.key];
      if (!campo) continue;
      const editor = editorDePadrao({ ...f, default: campo.default }, (v) => {
        campo.default = v;
        mudou();
      });
      const cadeado = el("input", { type: "checkbox", checked: campo.locked });
      cadeado.onchange = () => {
        campo.locked = cadeado.checked;
        mudou();
      };
      const nomeDoCampo = el("div", {}, el("span", { class: "mono" }, f.key), el("br"),
        el("span", { class: "muted" }, tr(campo.label) || ""));
      if (!gere) {
        desligar(editor);
        cadeado.disabled = true;
      } else {
        const textos = el("button", { type: "button", class: "small" }, t("field_texts_edit"));
        const aberta = el("div", { hidden: true });
        textos.onclick = () => {
          if (!aberta.children.length) aberta.append(linhaDeTextos(campo, mudou));
          aberta.hidden = !aberta.hidden;
        };
        nomeDoCampo.append(" ", textos, aberta);
      }
      linhas.push([nomeDoCampo, editor, el("label", { class: "inline" }, cadeado, " ", t("field_locked"))]);
    }

    const partes = [
      el("p", { class: "help" }, t("locks_help")),
      tabela([t("form_field"), t("form_default"), t("form_lock")], linhas),
    ];
    if (gere) {
      const salvar = el("button", { type: "button", class: "primary" }, t("save"));
      const erro = el("p", { class: "msg bad", hidden: true });
      salvar.onclick = acao(async () => {
        const base = `/api/v1/models/${encodeURIComponent(nome)}/schema`;
        // textos: os três idiomas, ou nenhum (o servidor exige os três)
        for (const [k, campo] of Object.entries(r)) {
          for (const qual of ["label", "help"]) {
            const valores = LINGUAS.map((l) => campo[qual][l].trim());
            if (valores.some(Boolean) && valores.some((v) => !v)) {
              throw new Error(`${k}: ${t("field_texts_need_all")}`);
            }
          }
        }
        // Um PATCH por campo ALTERADO: o servidor valida o padrão pelo mesmo
        // caminho que valida o que a sede digita, e mandar todos faria a recusa
        // de um campo parecer recusa de tudo.
        for (const [k, campo] of Object.entries(r)) {
          const antes = original[k];
          const mudancas = {};
          if (JSON.stringify(campo.default) !== JSON.stringify(antes.default)) mudancas.default = campo.default;
          for (const qual of ["label", "help"]) {
            if (JSON.stringify(campo[qual]) !== JSON.stringify(antes[qual]) && LINGUAS.every((l) => campo[qual][l].trim())) {
              mudancas[qual] = campo[qual];
            }
          }
          if (Object.keys(mudancas).length) {
            await api.patch(`${base}/fields/${encodeURIComponent(k)}`, mudancas, A);
            // gravado: se um campo seguinte falhar, o próximo Salvar não reenvia este
            antes.default = campo.default;
            antes.label = structuredClone(campo.label);
            antes.help = structuredClone(campo.help);
          }
        }
        const cadeados = {};
        for (const [k, campo] of Object.entries(r)) {
          if (campo.locked !== original[k].locked) cadeados[k] = campo.locked;
        }
        if (Object.keys(cadeados).length) await api.put(`${base}/locks`, { locks: cadeados }, A);
        esquecerRascunho(chave);
        refazer();
        return true;
      }, { ok: t("saved_ok"), alvoErro: erro });
      partes.push(erro, el("div", { class: "actions" }, salvar));
    }
    corpo.replaceChildren(...partes);
  });
