// Webhooks de uma imagem (só a administração): quem recebe os eventos dela.
// Era um diálogo aberto por um botão na linha da lista; é uma seção da página
// da imagem.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, quando, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { confirmar, formulario, mostrarSegredo } from "/common/dialogo.js";
import { A, carregarEm, tabela } from "./comum.js";

let eventos = null;

const catalogo = async () => {
  if (eventos) return eventos;
  try {
    eventos = (await api.get("/api/v1/events/types", A)).events;
  } catch {
    eventos = [];
  }
  return eventos;
};

const checklist = (marcados) => {
  const caixas = el("div", { class: "checks" });
  for (const ev of eventos) {
    caixas.append(el("label", { class: "inline" },
      el("input", { type: "checkbox", value: ev, checked: marcados.includes(ev) }), " ", el("span", { class: "mono" }, ev)));
  }
  const todos = el("button", { class: "small", type: "button" }, t("select_all_events"));
  todos.onclick = () => caixas.querySelectorAll("input").forEach((i) => (i.checked = true));
  const nenhum = el("button", { class: "small", type: "button" }, t("select_no_events"));
  nenhum.onclick = () => caixas.querySelectorAll("input").forEach((i) => (i.checked = false));
  return { no: el("div", {}, caixas, el("div", { class: "actions" }, todos, nenhum)), caixas };
};

const marcados = (caixas) => [...caixas.querySelectorAll("input:checked")].map((i) => i.value);

// o servidor não gera segredo: a tela gera, e mostra uma vez
const novoSegredo = () => {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
};

const bloco = (w, base, refazer) => {
  const url = el("input", { type: "url", value: w.url });
  const lista = checklist(w.events || []);
  const salvar = el("button", { class: "small primary", type: "button" }, t("save"));
  salvar.onclick = acao(async () => {
    await api.put(`${base}/${w.id}`, { url: url.value.trim(), events: marcados(lista.caixas) }, A);
    refazer();
  }, { ok: t("webhook_saved") });

  const trocar = el("button", { class: "small", type: "button" }, t("webhook_rotate"));
  trocar.onclick = acao(async () => {
    if (!(await confirmar({ texto: t("webhook_rotate_confirm"), acao: t("webhook_rotate"), perigo: true }))) return false;
    const seg = novoSegredo();
    await api.put(`${base}/${w.id}`, { secret: seg }, A);
    await mostrarSegredo({
      titulo: t("webhook_secret_title"),
      itens: [{ rotulo: w.url, valor: seg }],
      aviso: t("webhook_secret_once"),
    });
    return true;
  });

  const resultado = el("span", { class: "muted" });
  const testar = el("button", { class: "small", type: "button" }, t("webhook_test"));
  testar.onclick = acao(async () => {
    resultado.textContent = "…";
    const r = await api.post(`${base}/${w.id}/test`, undefined, A);
    resultado.textContent = r.ok
      ? t("webhook_test_ok", { code: r.status_code, ms: r.elapsed_ms })
      : t("webhook_test_fail", { erro: r.error || r.status_code });
    resultado.className = r.ok ? "msg ok" : "msg bad";
  });

  const apagar = el("button", { class: "small danger", type: "button" }, t("act_delete"));
  apagar.onclick = acao(async () => {
    if (!(await confirmar({ texto: t("webhook_delete_confirm"), acao: t("act_delete"), perigo: true }))) return false;
    await api.del(`${base}/${w.id}`, A);
    refazer();
    return true;
  });

  return el("div", { class: "card" },
    el("p", { class: "muted small" }, el("span", { class: "mono" }, w.id), ` · ${w.owner} · ${quando(w.created_at)} · `,
      w.secret ? t("webhook_secret_set") : t("webhook_secret_none")),
    url, lista.no,
    el("div", { class: "actions" }, salvar, trocar, testar, apagar, resultado));
};

export const desenharWebhooks = (corpo, imageId, sinal) =>
  carregarEm(corpo, sinal, async () => {
    await catalogo();
    const base = `/api/v1/site-images/${encodeURIComponent(imageId)}/webhooks`;
    const d = await api.get(base, { ...A, signal: sinal });
    const refazer = () => desenharWebhooks(corpo, imageId, sinal);

    const acrescentar = el("button", { class: "small primary", type: "button" }, t("webhook_add"));
    acrescentar.onclick = acao(async () => {
      const lista = checklist(["alert.raised", "alert.dismissed"]);
      const segredo = el("input", { type: "text", autocomplete: "off" });
      const gerar = el("button", { class: "small", type: "button" }, t("webhook_secret_generate"));
      gerar.onclick = () => (segredo.value = novoSegredo());
      const r = await formulario({
        titulo: t("webhook_add"),
        acao: t("webhook_add"),
        largo: true,
        campos: [
          { nome: "url", rotulo: "URL", tipo: "url", obrigatorio: true, placeholder: "https://…" },
          { nome: "events", rotulo: t("webhook_events"), tipo: "no", no: lista.no, ler: () => marcados(lista.caixas) },
          {
            nome: "secret",
            rotulo: t("webhook_secret"),
            tipo: "no",
            no: el("div", { class: "actions" }, segredo, gerar),
            ler: () => segredo.value.trim(),
          },
        ],
        enviar: (v) => {
          if (!/^https?:[/][/]/.test(v.url)) throw new Error(t("webhook_bad_url"));
          return api.post(base, { url: v.url, secret: v.secret, events: v.events }, A);
        },
      });
      if (!r) return false;
      toast(t("webhook_saved"));
      refazer();
      return r;
    });

    const partes = [el("div", { class: "actions" }, acrescentar)];
    if (!d.webhooks.length) partes.push(el("p", { class: "muted" }, t("webhooks_none")));
    for (const w of d.webhooks) partes.push(bloco(w, base, refazer));

    // entregas que falharam: o que o destinatário não recebeu
    try {
      const f = await api.get(`${base}/deliveries?n=30`, { ...A, signal: sinal });
      partes.push(el("h3", {}, t("webhook_deliveries")));
      partes.push(
        tabela([], f.deliveries.slice().reverse().map((x) => [
          el("span", { class: "muted" }, quando(x.at)),
          el("span", { class: "mono" }, x.event),
          el("span", { class: "mono muted" }, `${x.host || ""}${x.path || ""}`),
          el("span", { class: "pill bad" }, x.error || String(x.last_status || "")),
        ]), { vazio: t("webhook_deliveries_none") })
      );
    } catch {
      /* rota de antes: sem a lista */
    }
    corpo.replaceChildren(...partes);
  });
