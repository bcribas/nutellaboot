// Quem entrou por convite: os sub-admins (suspender, cotas, uso) e os convites
// que são a credencial deles (ajustar, revogar sem destruir, apagar).
import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { $, toast, el, quando, copiavel } from "/common/ui.js";

const A = { kind: "admin" };

function inteiro(texto) {
  const n = parseInt(texto, 10);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

// --- sub-admins ---

export async function carregarDonos() {
  const box = $("#ownerlist");
  if (!box) return;
  let d;
  try {
    d = await api.get("/api/v1/owners", A);
  } catch {
    return;
  }
  box.innerHTML = "";
  if (!d.owners.length) {
    box.className = "muted";
    box.textContent = t("owners_none");
    return;
  }
  box.className = "";
  const tabela = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, t("owner_col")), el("th", {}, t("models_section")), el("th", {}, t("images")),
      el("th", {}, t("owner_builds")), el("th", {}, t("owner_last_seen")), el("th", {}))));
  const corpo = el("tbody");
  for (const o of d.owners) {
    const q = o.quotas || {};
    const u = o.usage || {};
    const suspender = el("button", { class: "small" + (o.disabled ? "" : " danger"), type: "button" },
      o.disabled ? t("owner_reactivate") : t("owner_suspend"));
    suspender.onclick = async () => {
      try {
        await api.post(`/api/v1/owners/${encodeURIComponent(o.id)}/disable`, { disabled: !o.disabled }, A);
        carregarDonos();
      } catch (e) {
        toast(e.message, true);
      }
    };
    const cotas = el("button", { class: "small", type: "button" }, t("owner_quotas_edit"));
    cotas.onclick = async () => {
      const resp = prompt(t("owner_quotas_prompt"), `${q.models} ${q.site_images} ${q.builds}`);
      if (!resp) return;
      const [m, i, b] = resp.trim().split(/[\s,]+/).map(inteiro);
      if (m === null || i === null || b === null) return toast(t("owner_quotas_bad"), true);
      try {
        await api.patch(`/api/v1/owners/${encodeURIComponent(o.id)}/quotas`,
          { max_models: m, max_images: i, build_quota: b }, A);
        carregarDonos();
      } catch (e) {
        toast(e.message, true);
      }
    };
    corpo.append(el("tr", {},
      el("td", {}, el("b", {}, o.label || "—"),
        o.disabled ? el("span", { class: "pill warn" }, t("owner_suspended")) : null,
        o.console_ok === false && !o.disabled
          ? el("span", { class: "pill", title: o.console_reason || "" }, t("owner_console_off")) : null),
      el("td", { class: "muted" }, `${u.models ?? 0}/${q.models ?? "∞"}`),
      el("td", { class: "muted" }, `${u.site_images ?? 0}/${q.site_images ?? "∞"}`),
      el("td", { class: "muted" }, String(q.builds ?? "∞")),
      el("td", { class: "muted" }, quando(o.last_seen)),
      el("td", {}, cotas, " ", suspender)));
  }
  tabela.append(corpo);
  box.append(tabela);
}

// --- convites ---

async function apagarConvite(inv) {
  if (!confirm(t("invite_delete_confirm"))) return;
  try {
    await api.del(`/api/v1/invites/${inv.code}`, A);
  } catch (e) {
    // 409: o convite virou console de alguém. O servidor diz o que ficaria
    // órfão; só com a confirmação explícita vai o ?force.
    if (e.status !== 409) return toast(e.message, true);
    if (!confirm(`${e.message}\n\n${t("invite_delete_force")}`)) return;
    try {
      await api.del(`/api/v1/invites/${inv.code}?force=true`, A);
    } catch (e2) {
      return toast(e2.message, true);
    }
  }
  carregarConvites();
  carregarDonos();
}

async function editarConvite(inv) {
  const rotulo = prompt(t("invite_label"), inv.label || inv.note || "");
  if (rotulo === null) return;
  const dias = prompt(t("invite_expires_prompt"), "");
  const corpo = { label: rotulo.trim() };
  if (dias !== null && dias.trim() !== "") {
    const n = inteiro(dias);
    if (n === null) return toast(t("invite_expires_bad"), true);
    corpo.expires_at = n === 0 ? null : Math.floor(Date.now() / 1000) + n * 86400;
  }
  try {
    await api.patch(`/api/v1/invites/${inv.code}`, corpo, A);
    carregarConvites();
    carregarDonos();
    document.dispatchEvent(new CustomEvent("nb3:recarregar"));
  } catch (e) {
    toast(e.message, true);
  }
}

export async function carregarConvites() {
  const box = $("#invlist");
  if (!box) return;
  let data;
  try {
    data = await api.get("/api/v1/invites", A);
  } catch {
    return;
  }
  box.innerHTML = "";
  if (!data.invites.length) {
    box.className = "muted";
    box.textContent = "—";
    return;
  }
  box.className = "";
  const tabela = el("table");
  for (const inv of data.invites) {
    const perfil = inv.unlocked === false ? t("profile_official_short") : t("profile_free_short");
    const partes = [`${inv.remaining} ${t("invite_remaining")}`, perfil];
    if (inv.model) partes.push(inv.model);
    if (inv.expires_at) partes.push(`${t("invite_expires")} ${quando(inv.expires_at)}`);

    const revogar = el("button", { class: "small" + (inv.revoked ? "" : " danger"), type: "button" },
      inv.revoked ? t("invite_restore") : t("invite_revoke"));
    revogar.onclick = async () => {
      try {
        // reversível: fecha o console e a criação, e não deixa nada órfão
        await api.patch(`/api/v1/invites/${inv.code}`, { revoked: !inv.revoked }, A);
        carregarConvites();
        carregarDonos();
      } catch (e) {
        toast(e.message, true);
      }
    };
    const editar = el("button", { class: "small", type: "button" }, t("invite_edit"));
    editar.onclick = () => editarConvite(inv);
    const apagar = el("button", { class: "small danger", type: "button" }, t("invite_delete"));
    apagar.onclick = () => apagarConvite(inv);

    tabela.append(el("tr", {},
      el("td", {}, copiavel(inv.code, { copy: t("copy"), copied: t("copied") })),
      el("td", {}, el("b", {}, inv.label || inv.note || ""),
        inv.revoked ? el("span", { class: "pill warn" }, t("invite_revoked_pill")) : null,
        el("br"), el("span", { class: "muted" }, partes.join(" · "))),
      el("td", {}, editar, " ", revogar, " ", apagar)));
  }
  box.append(tabela);
}

// os campos do formulário que a API já aceitava e a tela não mandava
export function camposExtrasDoConvite() {
  const extra = {};
  const rotulo = $("#inv_label").value.trim();
  if (rotulo) extra.label = rotulo;
  const modelos = inteiro($("#inv_maxmodels").value);
  if (modelos !== null) extra.max_models = modelos;
  const dias = inteiro($("#inv_expires").value);
  if (dias) extra.expires_at = Math.floor(Date.now() / 1000) + dias * 86400;
  if ($("#inv_walllock").checked) extra.wallpaper_locked = true;
  return extra;
}
