// O seletor da visão da frota: o que aparece no dashboard e nos laboratórios.
// A visão mora no SERVIDOR (por dono): vale em qualquer navegador, no telão e
// no link compartilhado que a segue. Usado pelo /admin/ e pelo /laboratorios/.
// O /dashboard/ NÃO importa isto: é tela de leitura, não grava nada.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { toast, el } from "/common/ui.js";

const A = { kind: "admin" };

export async function lerVisao() {
  return api.get("/api/v1/labs/view", A);
}

export async function gravarVisao(visao) {
  return api.put("/api/v1/labs/view", visao, A);
}

function resumo(meta) {
  const partes = [t("fview_shown", { n: meta.shown, total: meta.total })];
  if (meta.new_outside && meta.new_outside.length) {
    partes.push(t("fview_new_outside", { n: meta.new_outside.length }));
  }
  return partes.join(" · ");
}

// Monta o seletor dentro de `caixa`. `aoMudar(meta)` roda depois de gravar.
// `escolhidas()` (opcional) devolve os ids marcados na tela, para o modo
// "escolhidas à mão".
export async function montarSeletor(caixa, { aoMudar, escolhidas } = {}) {
  let d;
  try {
    d = await lerVisao();
  } catch {
    caixa.innerHTML = "";
    return null;
  }
  const admin = Array.isArray(d.owners);
  caixa.innerHTML = "";

  const modo = el("select", { class: "fview-mode" });
  const opcoes = [["mine", t("fview_mine")], ["all", t("fview_all")]];
  if (admin) opcoes.push(["owners", t("fview_owners")]);
  opcoes.push(["custom", t("fview_custom")]);
  for (const [valor, rotulo] of opcoes) modo.append(el("option", { value: valor }, rotulo));
  modo.value = d.view.mode;

  const donos = el("div", { class: "checks" });
  for (const o of d.owners || []) {
    const marcado = (d.view.owners || []).includes(o.owner_ref);
    donos.append(el("label", { class: "inline" },
      el("input", { type: "checkbox", value: o.owner_ref, checked: marcado }), " ",
      o.owner_kind === "admin" ? t("owner_admin") : (o.owner_label || o.owner_ref),
      el("span", { class: "muted" }, ` (${o.images})`)));
  }
  const dica = el("span", { class: "muted fview-hint" }, resumo(d.meta));
  const salvar = el("button", { class: "small primary", type: "button" }, t("fview_save"));

  const mostra = () => {
    donos.classList.toggle("hidden", modo.value !== "owners");
    salvar.classList.toggle("hidden", modo.value !== "owners" && modo.value !== "custom");
  };
  const grava = async () => {
    const visao = { mode: modo.value };
    if (modo.value === "owners") {
      visao.owners = [...donos.querySelectorAll("input:checked")].map((i) => i.value);
    }
    if (modo.value === "custom") {
      visao.images = escolhidas ? escolhidas() : (d.view.images || []);
      if (!visao.images.length) return toast(t("fview_pick_first"), true);
    }
    try {
      const r = await gravarVisao(visao);
      d.view = r.view;
      dica.textContent = resumo(r.meta);
      toast(t("fview_saved"));
      if (aoMudar) aoMudar(r.meta);
    } catch (e) {
      toast(e.message, true);
    }
  };
  modo.onchange = () => {
    mostra();
    // "minhas" e "todas" não têm o que escolher: gravam na hora
    if (modo.value === "mine" || modo.value === "all") grava();
  };
  salvar.onclick = grava;
  mostra();

  caixa.append(el("label", { class: "inline" }, el("b", {}, t("fview_mode")), " ", modo), " ", salvar, " ", dica, donos);
  return d;
}
