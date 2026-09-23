// Aba Chaves (só a administração): as chaves de administração, as de serviço
// (o MOJ, o telão) e o link do dashboard, que é uma chave de serviço com
// labs:read. Eram duas listas das mesmas chaves (a do cartão da frota revogava
// sem perguntar), e cada chave nova aparecia de um jeito diferente.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, el, quando, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { confirmar, formulario, mostrarSegredo } from "/common/dialogo.js";
import { A, cabecalho, carregarEm, secao, tabela } from "./comum.js";

// --- reautenticação ---
//
// Criar ou revogar chave de admin pede a PRÓPRIA chave de novo: o cookie prova
// que alguém entrou neste navegador, não que é essa pessoa clicando agora. O
// diálogo é estático no HTML para o gerenciador de senhas encontrá-lo.
function pedirChave(errou) {
  const dlg = $("#reauth");
  const campo_ = $("#reauth_key");
  campo_.value = "";
  $("#reauth_err").classList.toggle("hidden", !errou);
  return new Promise((resolve) => {
    const fim = (valor) => {
      dlg.close();
      $("#reauth_form").onsubmit = null;
      $("#reauth_cancel").onclick = null;
      dlg.oncancel = null;
      campo_.value = "";
      resolve(valor);
    };
    $("#reauth_form").onsubmit = (ev) => {
      ev.preventDefault();
      fim(campo_.value.trim());
    };
    $("#reauth_cancel").onclick = () => fim(null);
    dlg.oncancel = () => fim(null);
    dlg.showModal();
    campo_.focus();
  });
}

// Roda `pedido(current_key)`; se o servidor recusar a chave, pergunta de novo,
// agora com o aviso dentro do diálogo (antes era um toast atrás dele).
async function comReauth(pedido) {
  let errou = false;
  for (;;) {
    const chave = await pedirChave(errou);
    if (chave === null) return null;
    try {
      return await pedido(chave);
    } catch (e) {
      if (e.code !== "reauth_required") throw e;
      errou = true;
    }
  }
}

// --- chaves de administração ---

const desenharAdmin = (corpo, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const d = await api.get("/api/v1/admin-keys", { ...A, signal: sinal });
    const refazer = () => desenharAdmin(corpo, sinal);
    const nova = el("button", { type: "button", class: "small primary" }, t("adminkey_new"));
    nova.onclick = acao(async () => {
      const v = await formulario({
        titulo: t("adminkey_new"),
        texto: t("adminkey_new_help"),
        acao: t("create"),
        campos: [{ nome: "id", rotulo: t("adminkey_id"), obrigatorio: true, placeholder: "camila" }],
      });
      if (!v) return false;
      const r = await comReauth((chave) => api.post("/api/v1/admin-keys", { id: v.id, current_key: chave }, A));
      if (!r) return false;
      await mostrarSegredo({ titulo: `${t("adminkey_created")} ${r.id}`, itens: [{ rotulo: r.id, valor: r.key }], aviso: t("key_shown_once") });
      refazer();
      return true;
    });
    const linhas = d.keys.map((k) => {
      const revogar = el("button", { type: "button", class: "small danger" }, t("act_revoke"));
      revogar.onclick = acao(async () => {
        if (d.keys.length <= 1) throw new Error(t("adminkey_last_one"));
        const ok = await confirmar({
          texto: k.current ? t("adminkey_revoke_self_confirm", { id: k.id }) : t("adminkey_revoke_confirm", { id: k.id }),
          acao: t("act_revoke"),
          perigo: true,
          // a chave desta sessão: o servidor também exige o id por extenso
          digitar: k.current ? k.id : "",
        });
        if (!ok) return false;
        const r = await comReauth((chave) =>
          api.post(`/api/v1/admin-keys/${encodeURIComponent(k.id)}/revoke`,
            { current_key: chave, fp: k.fp, confirm: k.current ? k.id : undefined }, A));
        if (!r) return false;
        toast(t("adminkey_revoked", { n: r.sessions_ended }));
        if (k.current) location.reload();
        else refazer();
        return true;
      });
      return [
        el("span", { class: "mono" }, k.id, " ", el("span", { class: "muted" }, k.fp),
          k.current ? el("span", { class: "pill ok", title: t("adminkey_current_help") }, t("adminkey_current")) : null),
        el("span", { class: "muted" }, quando(k.created_at), k.created_by ? ` · ${k.created_by}` : ""),
        el("span", { class: "muted" }, k.last_used ? quando(k.last_used) : t("keys_never")),
        String(k.sessions),
        revogar,
      ];
    });
    corpo.replaceChildren(
      el("div", { class: "actions" }, nova),
      tabela([t("adminkey_id"), t("keys_created_at"), t("keys_last_used"), t("keys_sessions"), ""], linhas)
    );
  });

// --- chaves de serviço (e o link do dashboard) ---

let escopos = null;

const listaDeEscopos = async () => {
  if (escopos) return escopos;
  try {
    escopos = (await api.get("/api/v1/events/types", A)).scopes;
  } catch {
    escopos = [];
  }
  return escopos;
};

const caixasDeEscopo = (marcados) => {
  const caixas = el("div", { class: "checks" }, ...escopos.map((s) =>
    el("label", { class: "inline" }, el("input", { type: "checkbox", value: s, checked: marcados.includes(s) }), " ",
      el("span", { class: "mono" }, s))));
  return { no: caixas, ler: () => [...caixas.querySelectorAll("input:checked")].map((i) => i.value) };
};

const lista = (texto) => String(texto || "").split(/[\s,]+/).filter(Boolean);

const ehDoDashboard = (k) => (k.scopes || []).length === 1 && k.scopes[0] === "labs:read";

const urlDoDashboard = (chave) => `${location.origin}/dashboard/?tk=${chave}`;

const desenharServico = (corpo, sinal) =>
  carregarEm(corpo, sinal, async () => {
    await listaDeEscopos();
    const d = await api.get("/api/v1/service-keys", { ...A, signal: sinal });
    const refazer = () => desenharServico(corpo, sinal);

    const nova = el("button", { type: "button", class: "small primary" }, t("svckey_new"));
    nova.onclick = acao(async () => {
      const esc = caixasDeEscopo([]);
      const r = await formulario({
        titulo: t("svckey_new"),
        texto: t("svckey_new_help"),
        acao: t("create"),
        largo: true,
        campos: [
          { nome: "name", rotulo: t("svckey_name"), obrigatorio: true, placeholder: "moj-2026" },
          { nome: "scopes", rotulo: t("svckey_scopes"), tipo: "no", no: esc.no, ler: esc.ler },
          { nome: "images", rotulo: t("svckey_images"), placeholder: "26brbr* 26brsp*", ajuda: t("svckey_images_help") },
        ],
        enviar: (v) => {
          if (!v.scopes.length) throw new Error(t("svckey_need_name_scope"));
          return api.post("/api/v1/service-keys", { name: v.name, scopes: v.scopes, images: lista(v.images) }, A);
        },
      });
      if (!r) return false;
      await mostrarSegredo({ titulo: `${t("svckey_created")} ${r.name}`, itens: [{ rotulo: r.name, valor: r.key }], aviso: t("key_shown_once") });
      refazer();
      return true;
    });

    const dashboard = el("button", { type: "button", class: "small" }, t("dash_share_make"));
    dashboard.onclick = acao(async () => {
      const r = await formulario({
        titulo: t("dash_share_make"),
        texto: t("dash_share_help"),
        acao: t("create"),
        campos: [
          {
            nome: "modo",
            rotulo: t("dash_share_mode"),
            tipo: "select",
            valor: "segue",
            opcoes: [
              { valor: "segue", rotulo: t("dash_share_follow") },
              { valor: "globs", rotulo: t("dash_share_globs") },
            ],
          },
          { nome: "images", rotulo: t("svckey_images"), placeholder: "26br*", ajuda: t("dash_share_images_help") },
        ],
        enviar: (v) => {
          // "seguir": o link mostra o que a administração escolheu na visão da
          // frota, e muda junto com ela. "globs": o recorte fixo de sempre.
          const segue = v.modo === "segue";
          const nome = `dashboard-${new Date().toISOString().slice(0, 10)}-${Math.random().toString(36).slice(2, 6)}`;
          return api.post("/api/v1/service-keys",
            { name: nome, scopes: ["labs:read"], images: segue ? [] : lista(v.images), follow: segue ? "admin" : "" }, A);
        },
      });
      if (!r) return false;
      await mostrarSegredo({ titulo: t("dash_share_make"), itens: [{ rotulo: t("dash_share_url"), valor: urlDoDashboard(r.key) }], aviso: t("dash_share_once") });
      refazer();
      return true;
    });

    const linhas = d.service_keys.map((k) => {
      const editar = el("button", { type: "button", class: "small" }, t("act_edit"));
      editar.onclick = acao(async () => {
        const esc = caixasDeEscopo(k.scopes || []);
        const r = await formulario({
          titulo: `${t("act_edit")}: ${k.name}`,
          largo: true,
          campos: [
            { nome: "scopes", rotulo: t("svckey_scopes"), tipo: "no", no: esc.no, ler: esc.ler },
            { nome: "images", rotulo: t("svckey_images"), valor: (k.images || []).join(" "), ajuda: t("svckey_images_help") },
          ],
          enviar: (v) => {
            if (!v.scopes.length) throw new Error(t("svckey_need_name_scope"));
            return api.patch(`/api/v1/service-keys/${encodeURIComponent(k.name)}`, { scopes: v.scopes, images: lista(v.images) }, A);
          },
        });
        if (!r) return false;
        refazer();
        return true;
      }, { ok: t("saved_ok") });
      const trocar = el("button", { type: "button", class: "small danger" }, t("act_replace"));
      trocar.onclick = acao(async () => {
        if (!(await confirmar({ texto: t("svckey_rotate_confirm", { name: k.name }), acao: t("act_replace"), perigo: true }))) return false;
        const r = await api.post(`/api/v1/service-keys/${encodeURIComponent(k.name)}/rotate`, undefined, A);
        await mostrarSegredo({
          titulo: k.name,
          itens: [ehDoDashboard(k) ? { rotulo: t("dash_share_url"), valor: urlDoDashboard(r.key) } : { rotulo: k.name, valor: r.key }],
          aviso: t("key_shown_once"),
        });
        refazer();
        return true;
      });
      const revogar = el("button", { type: "button", class: "small danger" }, t("act_revoke"));
      revogar.onclick = acao(async () => {
        if (!(await confirmar({ texto: t("svckey_revoke_confirm", { name: k.name }), acao: t("act_revoke"), perigo: true }))) return false;
        await api.del(`/api/v1/service-keys/${encodeURIComponent(k.name)}`, A);
        refazer();
        return true;
      });
      const pills = [];
      if (ehDoDashboard(k)) pills.push(" ", el("span", { class: "pill" }, t("svckey_dashboard")));
      if (k.follow) pills.push(" ", el("span", { class: "pill", title: t("svckey_follow_help") }, t("svckey_follow")));
      return [
        el("span", { class: "mono" }, k.name, ...pills),
        el("span", { class: "muted mono" }, (k.scopes || []).join(" ")),
        el("span", { class: "muted mono" }, (k.images || []).join(" ") || t("svckey_all_images")),
        el("span", { class: "muted" }, quando(k.created_at), k.created_by ? ` · ${k.created_by}` : ""),
        el("span", { class: "muted" }, k.last_used ? quando(k.last_used) : t("keys_never")),
        el("span", { class: "actions" }, editar, trocar, revogar),
      ];
    });
    corpo.replaceChildren(
      el("div", { class: "actions" }, nova, dashboard),
      tabela([t("svckey_name"), t("svckey_scopes"), t("svckey_images"), t("keys_created_at"), t("keys_last_used"), ""], linhas,
        { vazio: t("svckey_none") })
    );
  });

export const vista = async (alvo, ctx) => {
  alvo.append(cabecalho({ titulo: t("nav_keys") }), el("p", { class: "help" }, t("keys_section_help")));
  const admin = secao({ id: "admin", titulo: t("adminkey_title") });
  const servico = secao({ id: "servico", titulo: t("svckey_title"), ajuda: t("svckey_help") });
  alvo.append(admin.no, servico.no);
  desenharAdmin(admin.corpo, ctx.sinal);
  desenharServico(servico.corpo, ctx.sinal);
};
