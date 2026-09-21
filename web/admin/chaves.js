// As credenciais que a administração emite: chaves de admin, chaves de
// serviço (o MOJ, o telão) e a auditoria do que foi feito com elas.
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, toast, el, quando, copiavel } from "/common/ui.js";

const A = { kind: "admin" };
const ROTULOS = () => ({ copy: t("copy"), copied: t("copied") });

// --- reautenticação ---
//
// Cunhar ou revogar chave de admin pede a PRÓPRIA chave de novo: o cookie
// prova que alguém entrou neste navegador, não que é essa pessoa clicando
// agora. A chave vive numa variável local durante um pedido e some.
function pedirChave() {
  const dlg = $("#reauth");
  const campo = $("#reauth_key");
  campo.value = "";
  $("#reauth_err").classList.add("hidden");
  return new Promise((resolve) => {
    const fim = (valor) => {
      dlg.close();
      $("#reauth_form").onsubmit = null;
      $("#reauth_cancel").onclick = null;
      dlg.oncancel = null;
      campo.value = "";
      resolve(valor);
    };
    $("#reauth_form").onsubmit = (ev) => {
      ev.preventDefault();
      fim(campo.value.trim());
    };
    $("#reauth_cancel").onclick = () => fim(null);
    dlg.oncancel = () => fim(null);
    dlg.showModal();
    campo.focus();
  });
}

// Roda `pedido(current_key)`; se o servidor recusar a chave, pergunta de novo.
async function comReauth(pedido) {
  for (;;) {
    const chave = await pedirChave();
    if (chave === null) return null;
    try {
      return await pedido(chave);
    } catch (e) {
      if (e.code !== "reauth_required") throw e;
      toast(t("reauth_bad"), true);
    }
  }
}

function mostrarUmaVez(caixa, titulo, valor) {
  caixa.innerHTML = "";
  caixa.append(
    el("div", { class: "card onetime" },
      el("b", {}, titulo), " ", copiavel(valor, ROTULOS()),
      el("p", { class: "help muted" }, t("key_shown_once")))
  );
}

// --- chaves de administração ---

async function carregarChavesAdmin() {
  const box = $("#adminkeylist");
  let d;
  try {
    d = await api.get("/api/v1/admin-keys", A);
  } catch {
    return;
  }
  box.className = "";
  box.innerHTML = "";
  const tabela = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, t("adminkey_id")), el("th", {}, t("keys_created_at")),
      el("th", {}, t("keys_last_used")), el("th", {}, t("keys_sessions")), el("th", {}))));
  const corpo = el("tbody");
  for (const k of d.keys) {
    const revogar = el("button", { class: "small danger", type: "button" }, t("adminkey_revoke"));
    revogar.onclick = () => revogarChaveAdmin(k, d.keys.length);
    corpo.append(el("tr", {},
      el("td", { class: "mono" }, k.id, " ", el("span", { class: "muted" }, k.fp),
        k.current ? el("span", { class: "pill ok", title: t("adminkey_current_help") }, t("adminkey_current")) : null),
      el("td", { class: "muted" }, quando(k.created_at), k.created_by ? ` · ${k.created_by}` : ""),
      el("td", { class: "muted" }, k.last_used ? quando(k.last_used) : t("keys_never")),
      el("td", { class: "muted" }, String(k.sessions)),
      el("td", {}, revogar)));
  }
  tabela.append(corpo);
  box.append(tabela);
}

async function criarChaveAdmin() {
  const id = $("#adminkey_id").value.trim();
  if (!id) return;
  try {
    const nova = await comReauth((chave) => api.post("/api/v1/admin-keys", { id, current_key: chave }, A));
    if (!nova) return;
    $("#adminkey_id").value = "";
    mostrarUmaVez($("#adminkey_out"), `${t("adminkey_created")} ${nova.id}:`, nova.key);
    await carregarChavesAdmin();
    carregarAuditoria();
  } catch (e) {
    toast(e.message, true);
  }
}

async function revogarChaveAdmin(k, quantas) {
  if (quantas <= 1) return toast(t("adminkey_last_one"), true);
  if (k.current) {
    // a chave desta sessão: o servidor também exige o id por extenso
    if (prompt(t("adminkey_revoke_self_confirm", { id: k.id })) !== k.id) return;
  } else if (!confirm(t("adminkey_revoke_confirm", { id: k.id }))) return;
  try {
    const r = await comReauth((chave) =>
      api.post(`/api/v1/admin-keys/${encodeURIComponent(k.id)}/revoke`,
        { current_key: chave, fp: k.fp, confirm: k.current ? k.id : undefined }, A));
    if (!r) return;
    toast(t("adminkey_revoked", { n: r.sessions_ended }));
    if (k.current) return location.reload();
    await carregarChavesAdmin();
    carregarAuditoria();
  } catch (e) {
    toast(e.message, true);
  }
}

// --- chaves de serviço ---

let escopos = null;

async function montarEscopos() {
  if (escopos) return;
  try {
    escopos = (await api.get("/api/v1/events/types", A)).scopes;
  } catch {
    escopos = [];
  }
  const box = $("#svc_scopes");
  box.innerHTML = "";
  for (const s of escopos) {
    box.append(el("label", { class: "inline" },
      el("input", { type: "checkbox", value: s }), " ", el("span", { class: "mono" }, s)));
  }
}

function lista(texto) {
  return texto.split(/[\s,]+/).filter(Boolean);
}

async function carregarChavesServico() {
  const box = $("#svclist");
  let d;
  try {
    d = await api.get("/api/v1/service-keys", A);
  } catch {
    return;
  }
  box.innerHTML = "";
  if (!d.service_keys.length) {
    box.className = "muted";
    box.textContent = t("svckey_none");
    return;
  }
  box.className = "";
  const tabela = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, t("svckey_name")), el("th", {}, t("svckey_scopes")), el("th", {}, t("svckey_images")),
      el("th", {}, t("keys_created_at")), el("th", {}, t("keys_last_used")), el("th", {}))));
  const corpo = el("tbody");
  for (const k of d.service_keys) {
    const rot = el("button", { class: "small", type: "button" }, t("svckey_rotate"));
    rot.onclick = async () => {
      if (!confirm(t("svckey_rotate_confirm", { name: k.name }))) return;
      try {
        const r = await api.post(`/api/v1/service-keys/${encodeURIComponent(k.name)}/rotate`, undefined, A);
        mostrarUmaVez($("#svc_out"), `${k.name}:`, r.key);
        carregarChavesServico();
      } catch (e) {
        toast(e.message, true);
      }
    };
    const rev = el("button", { class: "small danger", type: "button" }, t("svckey_revoke"));
    rev.onclick = async () => {
      if (!confirm(t("svckey_revoke_confirm", { name: k.name }))) return;
      try {
        await api.del(`/api/v1/service-keys/${encodeURIComponent(k.name)}`, A);
        carregarChavesServico();
        document.dispatchEvent(new CustomEvent("nb3:chaves-mudaram"));
      } catch (e) {
        toast(e.message, true);
      }
    };
    corpo.append(el("tr", {},
      el("td", { class: "mono" }, k.name,
        k.follow ? el("span", { class: "pill", title: t("svckey_follow_help") }, t("svckey_follow")) : null),
      el("td", { class: "muted mono" }, (k.scopes || []).join(" ")),
      el("td", { class: "muted mono" }, (k.images || []).join(" ") || t("svckey_all_images")),
      el("td", { class: "muted" }, quando(k.created_at), k.created_by ? ` · ${k.created_by}` : ""),
      el("td", { class: "muted" }, k.last_used ? quando(k.last_used) : t("keys_never")),
      el("td", {}, rot, " ", rev)));
  }
  tabela.append(corpo);
  box.append(tabela);
}

async function criarChaveServico() {
  const name = $("#svc_name").value.trim();
  const scopes = [...document.querySelectorAll("#svc_scopes input:checked")].map((i) => i.value);
  if (!name || !scopes.length) return toast(t("svckey_need_name_scope"), true);
  try {
    const r = await api.post("/api/v1/service-keys", { name, scopes, images: lista($("#svc_images").value) }, A);
    $("#svc_name").value = "";
    mostrarUmaVez($("#svc_out"), `${r.name}:`, r.key);
    carregarChavesServico();
    carregarAuditoria();
  } catch (e) {
    toast(e.code === "key_exists" ? t("svckey_exists") : e.message, true);
  }
}

// --- as chaves de UMA imagem ---
//
// A chave de boot só aparecia uma vez, no cartão de credenciais; depois disso,
// relê-la ou trocá-la era só por API, embora a tela já avisasse "pendrive
// desatualizado: chave de boot". E a chave de máquina não tinha rotação.
export async function abrirChavesDaImagem(imageId) {
  const dlg = el("dialog", { class: "reauth" });
  const corpo = el("div");
  const fechar = el("button", { type: "button" }, t("close"));
  fechar.onclick = () => dlg.close();
  dlg.onclose = () => dlg.remove();
  dlg.append(el("h2", {}, `${t("image_keys_title")}: `, el("span", { class: "mono" }, imageId)), corpo,
    el("div", { class: "actions" }, fechar));
  document.body.append(dlg);

  const pinta = async () => {
    corpo.innerHTML = "";
    let boot;
    try {
      boot = await api.get(`/api/v1/site-images/${encodeURIComponent(imageId)}/boot-key`, A);
    } catch (e) {
      corpo.append(el("p", { class: "warn" }, e.message));
      return;
    }
    const rotBoot = el("button", { class: "small danger", type: "button" }, t("bkey_rotate"));
    rotBoot.onclick = async () => {
      if (!confirm(t("bkey_rotate_confirm"))) return;
      try {
        await api.post(`/api/v1/site-images/${encodeURIComponent(imageId)}/boot-key/rotate`, undefined, A);
        toast(t("bkey_rotated"));
        pinta();
        document.dispatchEvent(new CustomEvent("nb3:recarregar"));
      } catch (e) {
        toast(e.message, true);
      }
    };
    corpo.append(
      el("h3", {}, t("boot_key")),
      el("p", {}, copiavel(boot.boot_key, ROTULOS())),
      el("p", { class: "help muted" }, t("bkey_help")), rotBoot);

    const carencia = el("select", {},
      el("option", { value: "12" }, t("mkey_grace", { h: 12 })),
      el("option", { value: "48" }, t("mkey_grace", { h: 48 })),
      el("option", { value: "0" }, t("mkey_grace_none")));
    const saida = el("div");
    const rotMaq = el("button", { class: "small danger", type: "button" }, t("mkey_rotate"));
    rotMaq.onclick = async () => {
      const horas = parseInt(carencia.value, 10);
      if (!confirm(horas ? t("mkey_rotate_confirm", { h: horas }) : t("mkey_rotate_confirm_none"))) return;
      const tenta = (force) =>
        api.post(`/api/v1/site-images/${encodeURIComponent(imageId)}/machine-key/rotate`,
          { grace_hours: horas, force }, A);
      try {
        let r;
        try {
          r = await tenta(false);
        } catch (e) {
          // 409: há máquina travada e a rotação seca a deixaria sem o destravar
          if (e.status !== 409 || !confirm(`${e.message}\n\n${t("mkey_locked_force")}`)) throw e;
          r = await tenta(true);
        }
        saida.innerHTML = "";
        saida.append(el("p", {}, copiavel(r.machine_key, ROTULOS())),
          el("p", { class: "help muted" }, t("mkey_rotated", { online: r.online })));
      } catch (e) {
        toast(e.message, true);
      }
    };
    corpo.append(
      el("h3", {}, t("machine_key")),
      el("p", { class: "help muted" }, t("mkey_rotate_help")),
      el("div", { class: "actions" }, carencia, rotMaq), saida);
  };
  await pinta();
  dlg.showModal();
}

// --- auditoria ---

export async function carregarAuditoria() {
  const box = $("#auditlist");
  if (!box) return;
  let d;
  try {
    d = await api.get("/api/v1/audit?limit=100", A);
  } catch {
    return;
  }
  box.innerHTML = "";
  if (!d.entries.length) {
    box.className = "muted";
    box.textContent = t("audit_none");
    return;
  }
  box.className = "";
  const tabela = el("table");
  for (const e of d.entries) {
    tabela.append(el("tr", {},
      el("td", { class: "muted" }, quando(e.at)),
      el("td", { class: "mono" }, e.action),
      el("td", { class: "mono" }, e.target || ""),
      el("td", { class: "muted" }, `${e.actor || e.actor_kind} · ${e.ip || ""}`),
      el("td", { class: "muted mono" }, Object.keys(e.detail || {}).length ? JSON.stringify(e.detail) : "")));
  }
  box.append(tabela);
}

export async function carregarChaves() {
  await montarEscopos();
  await Promise.all([carregarChavesAdmin(), carregarChavesServico(), carregarAuditoria()]);
}

export function iniciarChaves() {
  $("#adminkey_create").onclick = criarChaveAdmin;
  $("#svc_create").onclick = criarChaveServico;
  $("#audit_reload").onclick = carregarAuditoria;
}
