// Aba Pessoas (só a administração): quem entra por convite.
//
// O convite É a credencial do console do sub-admin, e as cotas dele moram no
// convite; mas convites e sub-administradores eram duas listas longe uma da
// outra, cada uma com metade das ações (suspender numa, revogar na outra, cotas
// num prompt de "três números"). Agora é uma linha por pessoa, e a página dela
// tem tudo. O endereço da página usa o `owner_ref`: o código é credencial e
// não pode ir para o histórico do navegador.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, quando, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { confirmar, formulario, mostrarSegredo } from "/common/dialogo.js";
import { A, cabecalho, caixa, campo, esquecerRascunho, irPara, linkPara, marcarSujo, naoEncontrado, rascunho, secao, tabela } from "./comum.js";
import { dialogoNovaImagem } from "./imagens.js";

const DIA = 86400;

const situacao = (inv, dono) => {
  if (inv && inv.revoked) return { texto: t("st_revoked"), cor: "warn" };
  if (dono && dono.disabled) return { texto: t("st_suspended"), cor: "warn" };
  if (inv && inv.expires_at && inv.expires_at * 1000 < Date.now()) return { texto: t("st_expired"), cor: "warn" };
  if (!inv) return { texto: t("st_orphan"), cor: "bad" };
  if (dono) return { texto: t("st_in_use"), cor: "ok" };
  return { texto: t("st_unused"), cor: "" };
};
const pillDaSituacao = (s) => el("span", { class: s.cor ? `pill ${s.cor}` : "pill" }, s.texto);

// uma pessoa = um convite e, se já entrou, o registro de sub-admin
const juntar = (convites, donos) => {
  const porRef = new Map();
  for (const inv of convites) porRef.set(inv.owner_ref, { ref: inv.owner_ref, inv, dono: null });
  for (const dono of donos) {
    const item = porRef.get(dono.owner_ref) || { ref: dono.owner_ref, inv: null, dono: null };
    item.dono = dono;
    porRef.set(dono.owner_ref, item);
  }
  return [...porRef.values()];
};

const rotuloDe = (p) => (p.dono && p.dono.label) || (p.inv && (p.inv.label || p.inv.note)) || "—";

const uso = (p, qual) => {
  const u = p.dono ? p.dono.usage || {} : {};
  const q = p.dono ? p.dono.quotas || {} : {};
  if (qual === "models") return `${u.models ?? 0}/${q.models ?? (p.inv ? p.inv.max_models : "∞")}`;
  if (qual === "images") return `${p.dono ? u.site_images ?? 0 : p.inv ? p.inv.used : 0}/${q.site_images ?? (p.inv ? p.inv.max_images : "∞")}`;
  return `${u.builds ?? 0}/${q.builds ?? (p.inv ? p.inv.build_quota : "∞")}`;
};

const linksDeEntrada = () =>
  el("dl", { class: "kv" },
    el("dt", {}, t("invite_console_link")), el("dd", { class: "mono" }, `${location.origin}/admin/`),
    el("dt", {}, t("invite_create_link")), el("dd", { class: "mono" }, `${location.origin}/criar/`));

// O convite novo. Com `pedido`, aprova o pedido emitindo o código (a mesma
// tela, os mesmos campos: a aprovação lia só três e descartava o resto).
export const dialogoNovoConvite = async ({ modelos = [], pedido = null } = {}) => {
  const publicos = modelos.filter((m) => m.public);
  const campos = [
    { nome: "label", rotulo: t("invite_label"), valor: pedido ? pedido.wanted_name || "" : "", obrigatorio: true },
    { nome: "note", rotulo: t("invite_note"), valor: pedido ? pedido.note || "" : "" },
  ];
  if (!pedido) campos.push({ nome: "count", rotulo: t("invite_count"), tipo: "number", valor: 1, min: 1 });
  campos.push(
    { nome: "max_images", rotulo: t("invite_max_images"), tipo: "number", valor: 1, min: 0 },
    { nome: "max_models", rotulo: t("invite_max_models"), tipo: "number", valor: 2, min: 0 },
    { nome: "build_quota", rotulo: t("quota_builds"), tipo: "number", valor: 5, min: 0 },
    {
      nome: "model",
      rotulo: t("invite_model"),
      tipo: "select",
      valor: "",
      ajuda: t("invite_model_help"),
      opcoes: [{ valor: "", rotulo: t("invite_model_any") }, ...publicos.map((m) => ({ valor: m.name, rotulo: m.name }))],
    },
    {
      nome: "perfil",
      rotulo: t("profile"),
      tipo: "select",
      valor: "free",
      ajuda: t("invite_profile_help"),
      opcoes: [
        { valor: "free", rotulo: t("profile_free") },
        { valor: "official", rotulo: t("profile_official") },
      ],
    },
    { nome: "wallpaper_locked", rotulo: t("invite_wallpaper_locked"), tipo: "checkbox" },
    { nome: "dias", rotulo: t("invite_expires_days"), tipo: "number", min: 1, placeholder: "∞", ajuda: t("invite_expires_help") }
  );
  const r = await formulario({
    titulo: pedido ? t("request_issue_invite") : t("invite_new"),
    texto: pedido ? `${pedido.wanted_name} · ${pedido.contact || ""}` : "",
    acao: t("invite_generate"),
    largo: true,
    campos,
    enviar: async (v) => {
      const corpo = {
        label: v.label,
        note: v.note,
        max_images: v.max_images ?? 1,
        max_models: v.max_models ?? 2,
        build_quota: v.build_quota ?? 5,
        unlocked: v.perfil === "free",
        wallpaper_locked: Boolean(v.wallpaper_locked),
      };
      if (v.model) corpo.model = v.model;
      if (v.dias) corpo.expires_at = Math.floor(Date.now() / 1000) + v.dias * DIA;
      if (pedido) {
        const d = await api.post(`/api/v1/requests/${encodeURIComponent(pedido.id)}/approve`, { action: "issue_code", ...corpo }, A);
        return [d.issued];
      }
      const d = await api.post("/api/v1/invites", { ...corpo, count: v.count || 1 }, A);
      return d.invites;
    },
  });
  if (!r) return null;
  await mostrarSegredo({
    titulo: t("invite_codes_title"),
    itens: r.map((c) => ({ rotulo: c.label || t("invite_code"), valor: c.code })),
    aviso: t("invite_codes_help"),
    extra: linksDeEntrada(),
    umaVez: false,
  });
  return r;
};

// --- a lista ---

const vistaLista = async (alvo, ctx) => {
  const [convites, donos, pedidos, modelos] = await Promise.all([
    api.get("/api/v1/invites", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/owners", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/requests", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/models", { ...A, signal: ctx.sinal }),
  ]);
  const redesenhar = () => document.dispatchEvent(new CustomEvent("nb3:redesenhar"));
  const novo = el("button", { type: "button", class: "primary" }, t("invite_new"));
  novo.onclick = acao(async () => {
    const r = await dialogoNovoConvite({ modelos: modelos.models });
    if (r) redesenhar();
    return Boolean(r);
  });
  alvo.append(cabecalho({ titulo: t("nav_people"), acoes: [novo] }), el("p", { class: "help" }, t("people_help")));

  // pedidos de quem não tem código: aprovar é emitir convite ou criar a imagem
  const pendentes = pedidos.requests.filter((r) => r.status === "pending");
  if (pendentes.length) {
    const s = secao({ id: "pedidos", titulo: t("requests_admin"), ajuda: t("requests_help") });
    s.corpo.append(tabela([t("request_who"), t("request_note"), ""], pendentes.map((req) => {
      const emitir = el("button", { type: "button", class: "small primary" }, t("request_issue_invite"));
      emitir.onclick = acao(async () => {
        const r = await dialogoNovoConvite({ modelos: modelos.models, pedido: req });
        if (r) redesenhar();
        return Boolean(r);
      });
      const criar = el("button", { type: "button", class: "small" }, t("request_approve_create"));
      criar.onclick = acao(async () => {
        const criada = await dialogoNovaImagem({ modelos: modelos.models, pedido: req });
        if (!criada) return false;
        toast(t("image_created"));
        irPara("imagens", criada.id, "acesso");
        return true;
      });
      const recusar = el("button", { type: "button", class: "small danger" }, t("request_reject"));
      recusar.onclick = acao(async () => {
        const r = await formulario({
          titulo: t("request_reject"),
          texto: req.wanted_name,
          acao: t("request_reject"),
          perigo: true,
          campos: [{ nome: "reason", rotulo: t("request_reject_reason") }],
          enviar: (v) => api.post(`/api/v1/requests/${encodeURIComponent(req.id)}/reject`, { reason: v.reason }, A),
        });
        if (r) redesenhar();
        return Boolean(r);
      });
      return [
        el("div", {}, el("b", {}, req.wanted_name || ""), el("br"), el("span", { class: "muted mono" }, req.contact || "")),
        el("span", { class: "muted" }, req.note || ""),
        el("div", { class: "actions" }, emitir, criar, recusar),
      ];
    })));
    alvo.append(s.no);
  }

  const pessoas = juntar(convites.invites, donos.owners);
  const lista = secao({ id: "lista", titulo: t("people_list_title") });
  lista.corpo.append(tabela(
    [t("invite_label"), t("status"), t("nav_models"), t("nav_images"), t("quota_builds"), t("owner_last_seen")],
    pessoas.map((p) => ({
      celulas: [
        el("b", {}, linkPara(rotuloDe(p), "pessoas", p.ref)),
        pillDaSituacao(situacao(p.inv, p.dono)),
        uso(p, "models"),
        uso(p, "images"),
        uso(p, "builds"),
        el("span", { class: "muted" }, p.dono && p.dono.last_seen ? quando(p.dono.last_seen) : "—"),
      ],
      aoClicar: () => irPara("pessoas", p.ref),
    })),
    { vazio: t("people_none") }
  ));
  alvo.append(lista.no);
};

// --- a página de uma pessoa ---

const desenharConvite = (corpo, inv, modelos) => {
  const chave = `pessoa:${inv.owner_ref}:convite`;
  const original = {
    label: inv.label || "",
    note: inv.note || "",
    max_images: inv.max_images ?? 1,
    max_models: inv.max_models ?? 2,
    build_quota: inv.build_quota ?? 5,
    model: inv.model || "",
    perfil: inv.unlocked === false ? "official" : "free",
    wallpaper_locked: Boolean(inv.wallpaper_locked),
    dias: "",
    sem_validade: false,
  };
  const r = rascunho(chave, () => ({ ...original }));
  const mudou = () => marcarSujo(chave, JSON.stringify(r) !== JSON.stringify(original));
  const texto = (nome) => {
    const entrada = el("input", { type: "text", value: r[nome] });
    entrada.oninput = () => {
      r[nome] = entrada.value;
      mudou();
    };
    return entrada;
  };
  const numero = (nome, min = 0) => {
    const entrada = el("input", { type: "number", min, value: r[nome] });
    entrada.oninput = () => {
      r[nome] = entrada.value === "" ? "" : Number(entrada.value);
      mudou();
    };
    return entrada;
  };
  const modelo = el("select", {}, el("option", { value: "" }, t("invite_model_any")),
    ...modelos.filter((m) => m.public || m.name === r.model).map((m) => el("option", { value: m.name, selected: m.name === r.model }, m.name)));
  modelo.onchange = () => {
    r.model = modelo.value;
    mudou();
  };
  const perfil = el("select", {},
    el("option", { value: "free", selected: r.perfil === "free" }, t("profile_free")),
    el("option", { value: "official", selected: r.perfil === "official" }, t("profile_official")));
  perfil.onchange = () => {
    r.perfil = perfil.value;
    mudou();
  };
  const trava = el("input", { type: "checkbox", checked: r.wallpaper_locked });
  trava.onchange = () => {
    r.wallpaper_locked = trava.checked;
    mudou();
  };
  const semValidade = el("input", { type: "checkbox", checked: r.sem_validade });
  semValidade.onchange = () => {
    r.sem_validade = semValidade.checked;
    mudou();
  };
  const validadeAtual = inv.expires_at ? t("invite_expires_at", { quando: quando(inv.expires_at) }) : t("invite_never_expires");

  const salvar = el("button", { type: "button", class: "primary" }, t("save"));
  salvar.onclick = acao(async () => {
    const mudancas = {};
    for (const k of ["label", "note"]) if (r[k].trim() !== original[k]) mudancas[k] = r[k].trim();
    for (const k of ["max_images", "max_models", "build_quota"]) {
      if (r[k] !== "" && r[k] !== original[k]) mudancas[k] = r[k];
    }
    if (r.model !== original.model) mudancas.model = r.model || null;
    if (r.perfil !== original.perfil) mudancas.unlocked = r.perfil === "free";
    if (r.wallpaper_locked !== original.wallpaper_locked) mudancas.wallpaper_locked = r.wallpaper_locked;
    if (r.sem_validade) mudancas.expires_at = null;
    else if (r.dias) mudancas.expires_at = Math.floor(Date.now() / 1000) + r.dias * DIA;
    if (!Object.keys(mudancas).length) return false;
    await api.patch(`/api/v1/invites/${encodeURIComponent(inv.code)}`, mudancas, A);
    esquecerRascunho(chave);
    document.dispatchEvent(new CustomEvent("nb3:redesenhar"));
    return true;
  }, { ok: t("saved_ok") });

  corpo.replaceChildren(
    el("div", { class: "grade" },
      campo(t("invite_label"), texto("label")),
      campo(t("invite_note"), texto("note")),
      campo(t("invite_max_images"), numero("max_images")),
      campo(t("invite_max_models"), numero("max_models")),
      campo(t("quota_builds"), numero("build_quota"), t("quota_builds_help")),
      campo(t("invite_model"), modelo, t("invite_model_help")),
      campo(t("profile"), perfil, t("invite_profile_help")),
      caixa(t("invite_wallpaper_locked"), trava),
      campo(t("invite_expires_days"), numero("dias", 1), validadeAtual),
      caixa(t("invite_no_expiry"), semValidade)),
    el("div", { class: "actions" }, salvar)
  );
};

const vistaPessoa = async (alvo, ctx) => {
  const [convites, donos, imagens, modelos] = await Promise.all([
    api.get("/api/v1/invites", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/owners", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/site-images", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/models", { ...A, signal: ctx.sinal }),
  ]);
  const p = juntar(convites.invites, donos.owners).find((x) => x.ref === ctx.id);
  if (!p) return naoEncontrado(alvo, "pessoas", t("nav_people"));
  const redesenhar = () => document.dispatchEvent(new CustomEvent("nb3:redesenhar"));
  alvo.append(cabecalho({
    trilha: [linkPara(t("nav_people"), "pessoas")],
    titulo: rotuloDe(p),
    pills: [pillDaSituacao(situacao(p.inv, p.dono))],
  }));

  if (p.inv) {
    const codigo = secao({ id: "codigo", titulo: t("invite_code"), ajuda: t("invite_codes_help") });
    const ver = el("button", { type: "button", class: "small" }, t("invite_show_code"));
    ver.onclick = () =>
      mostrarSegredo({ titulo: rotuloDe(p), itens: [{ rotulo: t("invite_code"), valor: p.inv.code }], extra: linksDeEntrada(), umaVez: false });
    codigo.corpo.append(el("div", { class: "actions" }, ver));
    alvo.append(codigo.no);

    const convite = secao({ id: "convite", titulo: t("invite_settings_title") });
    desenharConvite(convite.corpo, p.inv, modelos.models);
    alvo.append(convite.no);
  }

  // o que é dela
  const minhasImagens = imagens.images.filter((i) => i.owner_ref === p.ref);
  const meusModelos = modelos.models.filter((m) => m.owner_ref === p.ref);
  const uso_ = secao({ id: "uso", titulo: t("person_usage_title") });
  uso_.corpo.append(
    el("dl", { class: "kv" },
      el("dt", {}, t("nav_models")), el("dd", {}, uso(p, "models"), " ",
        ...meusModelos.flatMap((m, i) => [i ? ", " : "", linkPara(m.name, "modelos", m.name)])),
      el("dt", {}, t("nav_images")), el("dd", {}, uso(p, "images"), " ",
        ...minhasImagens.flatMap((m, i) => [i ? ", " : "", linkPara(m.id, "imagens", m.id)])),
      el("dt", {}, t("quota_builds")), el("dd", {}, uso(p, "builds")),
      el("dt", {}, t("owner_last_seen")), el("dd", {}, p.dono && p.dono.last_seen ? quando(p.dono.last_seen) : "—"))
  );
  alvo.append(uso_.no);

  // acesso: suspender (a pessoa) e revogar (o convite) são coisas diferentes
  const acesso = secao({ id: "acesso", titulo: t("person_access_title"), ajuda: t("person_access_help") });
  const botoes = [];
  if (p.dono) {
    const suspenso = Boolean(p.dono.disabled);
    const b = el("button", { type: "button", class: suspenso ? "small" : "small danger" }, suspenso ? t("owner_reactivate") : t("owner_suspend"));
    b.onclick = acao(async () => {
      if (!suspenso && !(await confirmar({ texto: t("owner_suspend_confirm"), acao: t("owner_suspend"), perigo: true }))) return false;
      await api.post(`/api/v1/owners/${encodeURIComponent(p.dono.id)}/disable`, { disabled: !suspenso }, A);
      redesenhar();
      return true;
    }, { ok: t("saved_ok") });
    botoes.push(b);
  }
  if (p.inv) {
    const revogado = Boolean(p.inv.revoked);
    const b = el("button", { type: "button", class: revogado ? "small" : "small danger" }, revogado ? t("invite_restore") : t("invite_revoke"));
    b.onclick = acao(async () => {
      if (!revogado && !(await confirmar({ texto: t("invite_revoke_confirm"), acao: t("invite_revoke"), perigo: true }))) return false;
      await api.patch(`/api/v1/invites/${encodeURIComponent(p.inv.code)}`, { revoked: !revogado }, A);
      redesenhar();
      return true;
    }, { ok: t("saved_ok") });
    botoes.push(b);
  }
  acesso.corpo.append(el("div", { class: "actions" }, ...botoes));
  alvo.append(acesso.no);

  if (p.inv) {
    const apagar = secao({ id: "apagar", titulo: t("invite_delete_title"), ajuda: t("invite_delete_help"), perigo: true });
    const b = el("button", { type: "button", class: "danger" }, t("invite_delete_title"));
    b.onclick = acao(async () => {
      if (!(await confirmar({ texto: t("invite_delete_confirm"), acao: t("act_delete"), perigo: true }))) return false;
      const base = `/api/v1/invites/${encodeURIComponent(p.inv.code)}`;
      try {
        await api.del(base, A);
      } catch (e) {
        // 409: o convite virou console de alguém; o servidor diz o que ficaria órfão
        if (e.status !== 409) throw e;
        const forcar = await confirmar({ texto: `${e.message}. ${t("invite_delete_force")}`, acao: t("act_delete"), perigo: true });
        if (!forcar) return false;
        await api.del(`${base}?force=true`, A);
      }
      irPara("pessoas");
      return true;
    }, { ok: t("invite_deleted") });
    apagar.corpo.append(b);
    alvo.append(apagar.no);
  }
};

export const vista = async (alvo, ctx) => (ctx.id ? vistaPessoa(alvo, ctx) : vistaLista(alvo, ctx));
