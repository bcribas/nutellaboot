// Aba Modelos: a lista e a criação. A página de um modelo mora em modelo.js.
//
// Copiar um modelo tinha dois caminhos (o "Partir de" da criação e um
// "Duplicar" por prompt() que não deixava pôr descrição). Agora é um diálogo
// só: "Duplicar" abre o mesmo "Novo modelo", já partindo daquele.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { A, cabecalho, ehAdmin, irPara, linkPara, rotuloDoDono, tabela } from "./comum.js";
import * as modelo from "./modelo.js";

export const vista = async (alvo, ctx) => {
  if (ctx.id) return modelo.vista(alvo, ctx);
  const admin = ehAdmin();
  const d = await api.get("/api/v1/models", { ...A, signal: ctx.sinal });
  const modelos = d.models;

  const novo = el("button", { type: "button", class: "primary" }, t("model_new"));
  novo.onclick = acao(async () => Boolean(await modelo.dialogoNovoModelo({ modelos })));
  alvo.append(
    cabecalho({ titulo: `${t("nav_models")} (${modelos.length})`, acoes: [novo] }),
    el("p", { class: "help" }, t("models_section_help"))
  );

  const colunas = [t("model_name"), t("model_desc"), t("model_layers"), t("nav_images")];
  if (admin) colunas.push(t("owner_col"));
  colunas.push("");
  alvo.append(
    tabela(colunas, modelos.map((m) => {
      const pills = [];
      if (m.public) pills.push(el("span", { class: "pill ok" }, t("template_public")));
      if (!m.can_manage) pills.push(" ", el("span", { class: "pill", title: t("model_readonly") }, t("model_readonly_short")));
      const celulas = [
        el("span", { class: "mono" }, linkPara(m.name, "modelos", m.name)),
        el("span", { class: "muted" }, m.description || ""),
        String(m.layers),
        String(m.used_by),
      ];
      if (admin) {
        celulas.push(m.owner_kind === "subadmin" ? linkPara(rotuloDoDono(m), "pessoas", m.owner_ref) : el("span", { class: "muted" }, rotuloDoDono(m)));
      }
      celulas.push(el("span", {}, ...pills));
      return { celulas, aoClicar: () => irPara("modelos", m.name) };
    }), { vazio: t("models_none") })
  );
};
