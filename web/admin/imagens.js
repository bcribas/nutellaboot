// Aba Imagens: a lista e a criação. A página de uma imagem mora em imagem.js.
//
// Criar imagem tinha quatro caminhos com padrões diferentes (a nova vinha
// Oficial, a em massa sempre Oficial e sem papel de parede, a do pedido vinha
// Livre). Agora é um diálogo para uma imagem e outro para várias, os dois com
// Oficial marcado; o pedido de auto-atendimento usa o mesmo diálogo.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { abrirDialogo, formulario } from "/common/dialogo.js";
import {
  A, cabecalho, ehAdmin, eu, irPara, linkPara, pillPerfil, rotuloDoDono, tabela,
} from "./comum.js";
import * as imagem from "./imagem.js";

// o filtro sobrevive a entrar numa imagem e voltar
const filtro = { texto: "", dono: "", perfil: "" };

// o modelo de um sub-admin diz de quem é: a administração enxerga todos
const opcoesDeModelo = (modelos) =>
  modelos.map((m) => {
    const partes = [m.name];
    if (m.description) partes.push(m.description);
    if (m.owner_kind === "subadmin" && m.owner_label) partes.push(`(${m.owner_label})`);
    return { valor: m.name, rotulo: partes.join(" · ") };
  });

// o padrão é um modelo da casa: o primeiro público, senão o primeiro
const modeloPadrao = (modelos) => (modelos.find((m) => m.public) || modelos[0]).name;

// id sugerido a partir do nome pedido (o formato que o servidor aceita)
const sugestaoDeId = (nome) =>
  String(nome || "").toLowerCase().replace(/[^a-z0-9._-]/g, "").slice(0, 32);

const avisarEu = () => document.dispatchEvent(new CustomEvent("nb3:eu-mudou"));

// Uma imagem. Com `pedido`, aprova o pedido de auto-atendimento criando a
// imagem (a rota do pedido, que o marca como aprovado).
export const dialogoNovaImagem = async ({ modelos, pedido = null } = {}) => {
  const admin = ehAdmin();
  const comCamadas = modelos.filter((m) => m.layers > 0);
  if (!comCamadas.length) {
    toast(t("model_none_with_layers"), true);
    return null;
  }
  // o sub-admin só escolhe Livre quando o convite dele é Livre (o servidor
  // recusa o resto); Oficial vem marcado para todo mundo
  const podeLivre = admin || Boolean(eu() && eu().invite_profile && eu().invite_profile.unlocked);
  const campos = [
    { nome: "id", rotulo: t("image_id"), obrigatorio: true, ajuda: t("image_id_help"), valor: pedido ? sugestaoDeId(pedido.wanted_name) : "" },
    { nome: "fullname", rotulo: t("image_name"), valor: pedido ? pedido.wanted_name || "" : "" },
    { nome: "model", rotulo: t("template"), tipo: "select", opcoes: opcoesDeModelo(comCamadas), valor: modeloPadrao(comCamadas) },
  ];
  if (podeLivre) {
    campos.push({
      nome: "perfil",
      rotulo: t("profile"),
      tipo: "select",
      valor: "official",
      ajuda: t("profile_help"),
      opcoes: [
        { valor: "official", rotulo: t("profile_official") },
        { valor: "free", rotulo: t("profile_free") },
      ],
      aoMudar: (valor, controles) => {
        // Livre é liberar tudo, inclusive o papel de parede
        if (valor === "free" && controles.wallpaper_locked) controles.wallpaper_locked.checked = false;
      },
    });
  }
  if (admin && !pedido) {
    campos.push(
      { nome: "wallpaper_locked", rotulo: t("wallpaper_lock_label"), tipo: "checkbox" },
      { nome: "dashboard_hidden", rotulo: t("dashboard_hidden_label"), tipo: "checkbox", ajuda: t("dashboard_hidden_help") }
    );
  }
  if (!pedido) campos.push({ nome: "papel", rotulo: t("wallpaper_optional"), tipo: "file", accept: "image/png,image/jpeg" });

  return formulario({
    titulo: pedido ? t("request_approve_create") : t("new_image"),
    texto: pedido ? `${pedido.wanted_name} · ${pedido.contact || ""}` : "",
    acao: t("create"),
    campos,
    enviar: async (v) => {
      const { id, fullname, model } = v;
      const unlocked = v.perfil === "free";
      if (pedido) {
        const r = await api.post(`/api/v1/requests/${encodeURIComponent(pedido.id)}/approve`,
          { action: "create", id, fullname, model, unlocked }, A);
        return r.created;
      }
      let info;
      if (admin) {
        const wallpaper_locked = Boolean(v.wallpaper_locked) && !unlocked;
        const dashboard_hidden = Boolean(v.dashboard_hidden);
        info = await api.post("/api/v1/site-images", { id, fullname, model, unlocked, wallpaper_locked, dashboard_hidden }, A);
      } else {
        // o convite decide a trava do papel de parede e a cota; aqui vai só o
        // que é escolha do sub-admin
        info = await api.post("/api/v1/site-images", unlocked ? { id, fullname, model, unlocked } : { id, fullname, model }, A);
      }
      // Daqui para baixo a imagem JÁ EXISTE. O papel de parede falhando (não
      // é PNG, passa de 12 MB) não pode fazer parecer que nada foi criado.
      if (v.papel) {
        const fd = new FormData();
        fd.append("file", v.papel);
        try {
          await api.request("PUT", `/api/v1/site-images/${encodeURIComponent(id)}/wallpaper`, { raw: fd, kind: "admin" });
        } catch (e) {
          toast(`${t("wallpaper_upload_failed")}: ${e.message}`, true);
        }
      }
      return info;
    },
  });
};

// Várias de uma vez (só a administração): uma por linha, id<TAB>nome[<TAB>modelo].
const dialogoVarias = async (modelos) => {
  const comCamadas = modelos.filter((m) => m.layers > 0);
  if (!comCamadas.length) {
    toast(t("model_none_with_layers"), true);
    return null;
  }
  let csv = "";
  const r = await formulario({
    titulo: t("bulk"),
    texto: t("bulk_help"),
    acao: t("bulk_create"),
    largo: true,
    campos: [
      { nome: "linhas", rotulo: t("bulk_lines"), tipo: "textarea", obrigatorio: true, placeholder: "26brbr\tBrazilian Finals\tmaratona2026" },
      { nome: "model", rotulo: t("bulk_default_model"), tipo: "select", opcoes: opcoesDeModelo(comCamadas), valor: modeloPadrao(comCamadas) },
      {
        nome: "perfil",
        rotulo: t("profile"),
        tipo: "select",
        valor: "official",
        opcoes: [
          { valor: "official", rotulo: t("profile_official") },
          { valor: "free", rotulo: t("profile_free") },
        ],
      },
      { nome: "wallpaper_locked", rotulo: t("wallpaper_lock_label"), tipo: "checkbox" },
    ],
    enviar: async (v) => {
      const unlocked = v.perfil === "free";
      const rows = v.linhas.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("#")).map((l) => {
        const partes = l.split("\t");
        return {
          id: (partes[0] || "").trim(),
          fullname: (partes[1] || "").trim(),
          model: (partes[2] || "").trim() || v.model,
          unlocked,
          wallpaper_locked: Boolean(v.wallpaper_locked) && !unlocked,
        };
      });
      if (!rows.length) throw new Error(t("bulk_empty"));
      csv = await api.request("POST", "/api/v1/site-images/bulk?format=csv", { kind: "admin", body: { rows } });
      return rows.length;
    },
  });
  if (!r) return null;
  const linhas = String(csv).trim().split("\n").slice(1);
  const ok = linhas.filter((l) => l.split(",")[1] === "True").length;
  const baixar = el("button", { type: "button", class: "primary" }, t("download_csv"));
  baixar.onclick = () => {
    const blob = new Blob([csv], { type: "text/csv" });
    const a = el("a", { href: URL.createObjectURL(blob), download: "nutellaboot3-credenciais.csv" });
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const { corpo, rodape, fechar } = abrirDialogo({ titulo: t("bulk") });
  const fecharBotao = el("button", { type: "button" }, t("close"));
  fecharBotao.onclick = () => fechar();
  corpo.append(el("p", {}, t("bulk_result", { ok, fail: linhas.length - ok })), el("p", { class: "help" }, t("bulk_csv_help")));
  rodape.append(baixar, fecharBotao);
  return r;
};

const combina = (img) => {
  const q = filtro.texto.trim().toLowerCase();
  if (q && !img.id.includes(q) && !(img.fullname || "").toLowerCase().includes(q)) return false;
  if (filtro.dono && img.owner_ref !== filtro.dono) return false;
  if (filtro.perfil === "free" && !img.unlocked) return false;
  if (filtro.perfil === "official" && img.unlocked) return false;
  return true;
};

export const vista = async (alvo, ctx) => {
  if (ctx.id) return imagem.vista(alvo, ctx);
  const admin = ehAdmin();
  const [imgs, mods] = await Promise.all([
    api.get("/api/v1/site-images", { ...A, signal: ctx.sinal }),
    api.get("/api/v1/models", { ...A, signal: ctx.sinal }),
  ]);
  const imagens = imgs.images;
  const modelos = mods.models;

  const nova = el("button", { type: "button", class: "primary" }, t("new_image"));
  nova.onclick = acao(async () => {
    const criada = await dialogoNovaImagem({ modelos });
    if (!criada) return false;
    avisarEu();
    irPara("imagens", criada.id, "acesso");
    return true;
  }, { ok: t("image_created") });
  const acoes = [nova];
  if (admin) {
    const varias = el("button", { type: "button" }, t("bulk"));
    varias.onclick = acao(async () => {
      const r = await dialogoVarias(modelos);
      if (!r) return false;
      document.dispatchEvent(new CustomEvent("nb3:redesenhar"));
      return true;
    });
    acoes.push(varias);
  }
  const titulo = el("span", {}, t("images"));
  alvo.append(cabecalho({ titulo, acoes }));

  // filtros
  const busca = el("input", { type: "search", placeholder: t("filter"), value: filtro.texto, style: "max-width:260px" });
  const perfil = el("select", { class: "small" },
    el("option", { value: "" }, t("profile_all")),
    el("option", { value: "official", selected: filtro.perfil === "official" }, t("profile_official_short")),
    el("option", { value: "free", selected: filtro.perfil === "free" }, t("profile_free_short")));
  const filtros = [busca, perfil];
  if (admin) {
    const donos = new Map();
    for (const i of imagens) if (!donos.has(i.owner_ref)) donos.set(i.owner_ref, rotuloDoDono(i));
    const dono = el("select", { class: "small" }, el("option", { value: "" }, t("owner_filter_all")),
      ...[...donos].map(([ref, rotulo]) => el("option", { value: ref, selected: filtro.dono === ref }, rotulo)));
    dono.onchange = () => {
      filtro.dono = dono.value;
      desenhar();
    };
    filtros.push(dono);
  }
  const lista = el("div", {});
  alvo.append(el("div", { class: "actions" }, ...filtros), lista);

  const desenhar = () => {
    const visiveis = imagens.filter(combina);
    titulo.textContent = `${t("images")} (${visiveis.length})`;
    const colunas = [t("image_id"), t("image_name"), t("template")];
    if (admin) colunas.push(t("owner_col"));
    colunas.push("");
    lista.replaceChildren(
      tabela(colunas, visiveis.map((img) => {
        const pills = [pillPerfil(img.unlocked)];
        if (img.dashboard_hidden) pills.push(" ", el("span", { class: "pill", title: t("dashboard_hidden_help") }, t("dashboard_hidden_short")));
        if (img.namespace === "contest") pills.push(" ", el("span", { class: "pill warn" }, t("reserved_namespace")));
        const celulas = [
          el("span", { class: "mono" }, linkPara(img.id, "imagens", img.id)),
          img.fullname || "",
          el("span", { class: "muted" }, img.model),
        ];
        if (admin) {
          celulas.push(img.owner_kind === "subadmin" ? linkPara(rotuloDoDono(img), "pessoas", img.owner_ref) : el("span", { class: "muted" }, rotuloDoDono(img)));
        }
        celulas.push(el("span", {}, ...pills));
        return { celulas, aoClicar: () => irPara("imagens", img.id) };
      }), { vazio: t("images_none") })
    );
  };
  busca.oninput = () => {
    filtro.texto = busca.value;
    desenhar();
  };
  perfil.onchange = () => {
    filtro.perfil = perfil.value;
    desenhar();
  };
  desenhar();
};
