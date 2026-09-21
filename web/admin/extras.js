// O que a API já fazia e o console não oferecia: webhooks por sede, o log do
// build de camada, registrar uma camada pronta, publicar um arquivo, editar a
// imagem e aprovar um pedido criando a imagem direto.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, toast, el, quando, copiavel } from "/common/ui.js";

const A = { kind: "admin" };
const ROTULOS = () => ({ copy: t("copy"), copied: t("copied") });

function modal(titulo) {
  const dlg = el("dialog", { class: "reauth wide" });
  const corpo = el("div");
  const fechar = el("button", { type: "button" }, t("close"));
  fechar.onclick = () => dlg.close();
  dlg.onclose = () => dlg.remove();
  dlg.append(el("h2", {}, titulo), corpo, el("div", { class: "actions" }, fechar));
  document.body.append(dlg);
  dlg.showModal();
  return { dlg, corpo };
}

// --- webhooks de uma sede ---

let eventos = null;

async function catalogo() {
  if (eventos) return eventos;
  try {
    eventos = (await api.get("/api/v1/events/types", A)).events;
  } catch {
    eventos = [];
  }
  return eventos;
}

function checklist(marcados) {
  const box = el("div", { class: "checks" });
  for (const ev of eventos) {
    box.append(el("label", { class: "inline" },
      el("input", { type: "checkbox", value: ev, checked: marcados.includes(ev) }), " ", el("span", { class: "mono" }, ev)));
  }
  const todos = el("button", { class: "small", type: "button" }, t("select_all_events"));
  todos.onclick = () => box.querySelectorAll("input").forEach((i) => (i.checked = true));
  const nenhum = el("button", { class: "small", type: "button" }, t("select_no_events"));
  nenhum.onclick = () => box.querySelectorAll("input").forEach((i) => (i.checked = false));
  box.append(el("div", {}, todos, " ", nenhum));
  return box;
}

function marcados(box) {
  return [...box.querySelectorAll("input:checked")].map((i) => i.value);
}

export async function abrirWebhooks(imageId) {
  await catalogo();
  const base = `/api/v1/site-images/${encodeURIComponent(imageId)}/webhooks`;
  const { corpo } = modal(`${t("webhooks_title")}: ${imageId}`);

  const pinta = async () => {
    corpo.innerHTML = "";
    let d;
    try {
      d = await api.get(base, A);
    } catch (e) {
      corpo.append(el("p", { class: "warn" }, e.message));
      return;
    }
    corpo.append(el("p", { class: "help muted" }, t("webhooks_help")));
    if (!d.webhooks.length) corpo.append(el("p", { class: "muted" }, t("webhooks_none")));
    for (const w of d.webhooks) {
      const linha = el("div", { class: "whrow" });
      const url = el("input", { type: "text", value: w.url, style: "width:100%" });
      const lista = checklist(w.events || []);
      const salvar = el("button", { class: "small primary", type: "button" }, t("save"));
      salvar.onclick = async () => {
        try {
          await api.put(`${base}/${w.id}`, { url: url.value.trim(), events: marcados(lista) }, A);
          toast(t("webhook_saved"));
          pinta();
        } catch (e) {
          toast(e.message, true);
        }
      };
      const rodar = el("button", { class: "small", type: "button" }, t("webhook_rotate"));
      rodar.onclick = async () => {
        if (!confirm(t("webhook_rotate_confirm"))) return;
        // o servidor não gera segredo: a tela gera um aqui, e o mostra uma vez
        const seg = novoSegredo();
        try {
          await api.put(`${base}/${w.id}`, { secret: seg }, A);
          linha.append(el("div", { class: "card onetime" }, el("b", {}, t("webhook_secret"), ": "), copiavel(seg, ROTULOS()),
            el("p", { class: "help muted" }, t("webhook_secret_once"))));
        } catch (e) {
          toast(e.message, true);
        }
      };
      const testar = el("button", { class: "small", type: "button" }, t("webhook_test"));
      const resultado = el("span", { class: "muted" });
      testar.onclick = async () => {
        resultado.textContent = "…";
        try {
          const r = await api.post(`${base}/${w.id}/test`, undefined, A);
          resultado.textContent = r.ok ? t("webhook_test_ok", { code: r.status_code, ms: r.elapsed_ms }) : t("webhook_test_fail", { erro: r.error || r.status_code });
          resultado.className = r.ok ? "ok" : "warn";
        } catch (e) {
          resultado.textContent = e.message;
        }
      };
      const remover = el("button", { class: "small danger", type: "button" }, t("delete"));
      remover.onclick = async () => {
        if (!confirm(t("webhook_delete_confirm"))) return;
        await api.del(`${base}/${w.id}`, A);
        pinta();
      };
      linha.append(
        el("div", { class: "muted" }, el("span", { class: "mono" }, w.id), ` · ${w.owner} · ${quando(w.created_at)} · `,
          w.secret ? t("webhook_secret_set") : t("webhook_secret_none")),
        url, lista,
        el("div", { class: "actions" }, salvar, rodar, testar, remover, resultado));
      corpo.append(linha);
    }
    // novo
    const nurl = el("input", { type: "text", placeholder: "https://…", style: "width:100%" });
    const nlista = checklist(["alert.raised", "alert.dismissed"]);
    const nseg = el("input", { type: "text", placeholder: t("webhook_secret"), style: "width:60%" });
    const gerar = el("button", { class: "small", type: "button" }, t("webhook_secret_generate"));
    gerar.onclick = () => (nseg.value = novoSegredo());
    const add = el("button", { class: "small primary", type: "button" }, t("webhook_add"));
    add.onclick = async () => {
      const u = nurl.value.trim();
      if (!u.startsWith("http://") && !u.startsWith("https://")) return toast(t("webhook_bad_url"), true);
      try {
        await api.post(base, { url: u, secret: nseg.value.trim(), events: marcados(nlista) }, A);
        toast(t("webhook_saved"));
        pinta();
      } catch (e) {
        toast(e.message, true);
      }
    };
    corpo.append(el("h3", {}, t("webhook_add")), nurl, nlista, el("div", { class: "actions" }, nseg, gerar, add));
    // falhas de entrega
    try {
      const f = await api.get(`${base}/deliveries?n=30`, A);
      corpo.append(el("h3", {}, t("webhook_deliveries")));
      if (!f.deliveries.length) {
        corpo.append(el("p", { class: "muted" }, t("webhook_deliveries_none")));
      } else {
        const tb = el("table");
        for (const x of f.deliveries.slice().reverse()) {
          tb.append(el("tr", {}, el("td", { class: "muted" }, quando(x.at)), el("td", { class: "mono" }, x.event),
            el("td", { class: "mono muted" }, `${x.host || ""}${x.path || ""}`),
            el("td", {}, el("span", { class: "pill bad" }, x.error || String(x.last_status || "")))));
        }
        corpo.append(tb);
      }
    } catch {
      /* rota de antes: sem a lista */
    }
  };
  await pinta();
}

function novoSegredo() {
  // 24 bytes aleatórios do navegador, em hexadecimal
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// --- o log de um build de camada ---

export function verLogDoBuild(jobId) {
  const { dlg, corpo } = modal(`${t("layer_log_title")}: ${jobId}`);
  const cab = el("p", { class: "muted" });
  const pre = el("pre", { style: "max-height:60vh;overflow:auto;white-space:pre-wrap" });
  corpo.append(cab, el("p", { class: "help muted" }, t("layer_log_tail_note")), pre);
  let timer = null;
  const busca = async () => {
    let b;
    try {
      b = await api.get(`/api/v1/layerbuilds/${encodeURIComponent(jobId)}`, A);
    } catch (e) {
      cab.textContent = e.message;
      return;
    }
    cab.textContent = `${b.state} · ${(b.packages || []).join(" ")}${b.error ? " · " + b.error : ""}`;
    pre.textContent = b.log || t("layer_log_empty");
    pre.scrollTop = pre.scrollHeight;
    if (b.state === "queue" || b.state === "running") timer = setTimeout(busca, 3000);
  };
  dlg.addEventListener("close", () => clearTimeout(timer));
  busca();
}

// --- registrar uma camada já construída ---

export function formularioRegistrarCamada(imageId, aoRegistrar) {
  const arquivo = el("input", { type: "text", placeholder: "extra-2026.squash" });
  const md5 = el("input", { type: "text", placeholder: "md5 (32 hex)", pattern: "[0-9a-fA-F]{32}" });
  const cdn = el("input", { type: "text", placeholder: t("layer_cdn_url") });
  const btn = el("button", { class: "small primary", type: "button" }, t("layer_register"));
  btn.onclick = async () => {
    if (!/^[0-9a-fA-F]{32}$/.test(md5.value.trim())) return toast(t("layer_md5_invalid"), true);
    const corpo = { file: arquivo.value.trim(), md5: md5.value.trim().toLowerCase() };
    if (cdn.value.trim()) corpo.cdn_url = cdn.value.trim();
    try {
      await api.post(`/api/v1/site-images/${encodeURIComponent(imageId)}/layers`, corpo, A);
      toast(t("layer_registered"));
      if (aoRegistrar) aoRegistrar();
    } catch (e) {
      toast(e.message, true);
    }
  };
  return el("div", { class: "registrar" },
    el("h3", {}, t("layer_register_title")),
    el("p", { class: "help muted" }, t("layer_register_help")),
    el("div", { class: "actions", style: "flex-wrap:wrap" }, arquivo, md5, cdn, btn));
}

// --- publicar um arquivo ---

export async function publicarArquivo() {
  const nome = $("#pub_file").value.trim();
  const kind = $("#pub_kind").value;
  if (!nome) return;
  try {
    const r = await api.post("/api/v1/publish/file", { file: nome, kind }, A);
    // invariante 15: a resposta diz se publicou; um 200 com `failed` é falha
    if (r.status !== "done") return toast(t("publish_failed_msg", { erro: r.error || r.status }), true);
    toast(t("publish_status_done"));
    document.dispatchEvent(new CustomEvent("nb3:publicacao-mudou"));
  } catch (e) {
    toast(e.status === 404 ? t("publish_not_found") : e.message, true);
  }
}

// --- editar uma imagem ---

export function editarImagem(img, modelos, ehAdmin) {
  const { dlg, corpo } = modal(`${t("image_edit_title")}: ${img.id}`);
  const nome = el("input", { type: "text", value: img.fullname || "", style: "width:100%" });
  const modelo = el("select");
  for (const m of modelos) modelo.append(el("option", { value: m.name, selected: m.name === img.model }, m.name));
  const cota = el("input", { type: "number", min: 0, value: img.build_quota ?? 5, style: "max-width:100px" });
  const salvar = el("button", { class: "primary", type: "button" }, t("save"));
  salvar.onclick = async () => {
    const campos = {};
    if (nome.value.trim() !== (img.fullname || "")) campos.fullname = nome.value.trim();
    if (modelo.value !== img.model) {
      if (!confirm(t("image_edit_model_warn"))) return;
      campos.model = modelo.value;
    }
    if (ehAdmin && Number(cota.value) !== Number(img.build_quota ?? 5)) campos.build_quota = Number(cota.value);
    if (!Object.keys(campos).length) return dlg.close();
    try {
      await api.patch(`/api/v1/site-images/${encodeURIComponent(img.id)}`, campos, A);
      toast(t("image_saved"));
      dlg.close();
      document.dispatchEvent(new CustomEvent("nb3:recarregar"));
    } catch (e) {
      toast(e.message, true);
    }
  };
  corpo.append(
    el("label", { class: "fld" }, el("span", {}, t("image_name")), nome),
    el("label", { class: "fld" }, el("span", {}, t("template")), modelo),
    ehAdmin ? el("label", { class: "fld" }, el("span", {}, t("image_build_quota")), cota) : null,
    el("div", { class: "actions" }, salvar));
}

// --- aprovar um pedido criando a imagem ---

export function aprovarCriando(req, modelos, aoCriar) {
  const { dlg, corpo } = modal(t("request_approve_create"));
  const id = el("input", { type: "text", value: (req.wanted_name || "").toLowerCase().replace(/[^a-z0-9._-]/g, "").slice(0, 32) });
  const modelo = el("select");
  for (const m of modelos) modelo.append(el("option", { value: m.name }, m.name));
  const livre = el("select", {}, el("option", { value: "1" }, t("profile_free")), el("option", { value: "0" }, t("profile_official")));
  const criar = el("button", { class: "primary", type: "button" }, t("create"));
  criar.onclick = async () => {
    try {
      const r = await api.post(`/api/v1/requests/${req.id}/approve`,
        { action: "create", id: id.value.trim(), model: modelo.value, unlocked: livre.value === "1" }, A);
      dlg.close();
      if (aoCriar) aoCriar(r.created);
    } catch (e) {
      toast(e.message, true);
    }
  };
  corpo.append(
    el("label", { class: "fld" }, el("span", {}, t("request_create_id")), id),
    el("label", { class: "fld" }, el("span", {}, t("template")), modelo),
    el("label", { class: "fld" }, el("span", {}, t("profile")), livre),
    el("div", { class: "actions" }, criar));
}
