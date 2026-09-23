// A página de um modelo: camadas, papel de parede, o formulário da sede e as
// imagens que derivam dele. E o diálogo de modelo novo, que o "Duplicar" daqui
// reaproveita (a lista importa daqui, para os dois módulos não se importarem).
//
// A página mostra também as camadas que só algumas imagens do modelo têm: a
// tela antiga dizia "2 camadas" enquanto uma imagem bootava com 3, e o dono não
// sabia em qual informação confiar.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { confirmar, formulario } from "/common/dialogo.js";
import {
  A, cabecalho, caixa, campo, carregarEm, ehAdmin, esquecerRascunho, irPara, linkPara, marcarSujo,
  naoEncontrado, pillPerfil, rascunho, rotuloDoDono, rotuloDoPapel, secao, tabela,
} from "./comum.js";
import { dialogoConstruir, escolherCamada, md5Copiavel } from "./camadas.js";
import { desenharFormulario } from "./formulario.js";

const redesenhar = () => document.dispatchEvent(new CustomEvent("nb3:redesenhar"));

export const dialogoNovoModelo = async ({ modelos = [], partirDe = "" } = {}) => {
  const r = await formulario({
    titulo: partirDe ? t("model_duplicate_title", { n: partirDe }) : t("model_new"),
    texto: t("model_from_help"),
    acao: t("create"),
    campos: [
      { nome: "name", rotulo: t("model_name"), obrigatorio: true, placeholder: "meulab2026" },
      { nome: "description", rotulo: t("model_desc") },
      {
        nome: "from",
        rotulo: t("model_from"),
        tipo: "select",
        valor: partirDe,
        opcoes: [{ valor: "", rotulo: t("model_from_blank") }, ...modelos.map((m) => ({ valor: m.name, rotulo: m.name }))],
      },
    ],
    enviar: (v) => api.post("/api/v1/models", { name: v.name, description: v.description, from: v.from || undefined }, A),
  });
  if (!r) return null;
  // modelo sem camadas não faz imagem que boote: o aviso vem do servidor
  toast(r.warning ? `${t("model_created")}. ${t("model_empty_warning")}` : t("model_created"), Boolean(r.warning));
  document.dispatchEvent(new CustomEvent("nb3:eu-mudou"));
  irPara("modelos", r.name);
  return r;
};

// --- Geral: descrição, publicação e a trava do papel de parede ---

const desenharGeral = (corpo, m) => {
  const admin = ehAdmin();
  const chave = `modelo:${m.name}:geral`;
  const original = { description: m.description || "", public: Boolean(m.public), wallpaper_locked: Boolean(m.wallpaper_locked) };
  const r = rascunho(chave, () => ({ ...original }));
  const mudou = () => marcarSujo(chave, JSON.stringify(r) !== JSON.stringify(original));
  const desc = el("input", { type: "text", value: r.description });
  desc.oninput = () => {
    r.description = desc.value;
    mudou();
  };
  const publico = el("input", { type: "checkbox", checked: r.public });
  publico.onchange = () => {
    r.public = publico.checked;
    mudou();
  };
  const trava = el("input", { type: "checkbox", checked: r.wallpaper_locked });
  trava.onchange = () => {
    r.wallpaper_locked = trava.checked;
    mudou();
  };
  const campos = [campo(t("model_desc"), desc)];
  if (admin) campos.push(caixa(t("model_public_label"), publico, t("model_public_help")));
  campos.push(caixa(t("model_wallpaper_lock_label"), trava, t("model_wallpaper_lock_help")));
  const salvar = el("button", { type: "button", class: "primary" }, t("save"));
  salvar.onclick = acao(async () => {
    const mudancas = {};
    if (r.description.trim() !== original.description) mudancas.description = r.description.trim();
    if (admin && r.public !== original.public) mudancas.public = r.public;
    if (r.wallpaper_locked !== original.wallpaper_locked) mudancas.wallpaper_locked = r.wallpaper_locked;
    if (!Object.keys(mudancas).length) return false;
    await api.patch(`/api/v1/models/${encodeURIComponent(m.name)}`, mudancas, A);
    esquecerRascunho(chave);
    redesenhar();
    return true;
  }, { ok: t("saved_ok") });
  corpo.replaceChildren(el("div", { class: "grade" }, ...campos), el("div", { class: "actions" }, salvar));
};

// --- camadas do modelo, e as que só algumas imagens dele têm ---

const desenharCamadas = (corpo, nome, gere, contexto, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const base = `/api/v1/models/${encodeURIComponent(nome)}`;
    const m = await api.get(base, { ...A, signal: sinal });
    const camadas = m.layers || [];
    const refazer = () => desenharCamadas(corpo, nome, gere, contexto, sinal);
    const reordenar = async (ordem) => {
      await api.put(`${base}/layers/order`, { files: ordem }, A);
      refazer();
    };

    const linhas = camadas.map((c, i) => {
      const acoes = [];
      if (gere) {
        const sobe = el("button", { type: "button", class: "small", title: t("act_move_up"), disabled: i === 0 || c.role === "base" }, "↑");
        sobe.onclick = acao(async () => {
          const ordem = camadas.map((x) => x.file);
          [ordem[i - 1], ordem[i]] = [ordem[i], ordem[i - 1]];
          await reordenar(ordem);
        });
        // a base fica por último (invariante 13): nada desce para baixo dela
        const desce = el("button", {
          type: "button",
          class: "small",
          title: t("act_move_down"),
          disabled: i >= camadas.length - 1 || (camadas[i + 1].role || "") === "base",
        }, "↓");
        desce.onclick = acao(async () => {
          const ordem = camadas.map((x) => x.file);
          [ordem[i + 1], ordem[i]] = [ordem[i], ordem[i + 1]];
          await reordenar(ordem);
        });
        const tira = el("button", { type: "button", class: "small danger" }, t("act_remove"));
        tira.onclick = acao(async () => {
          const texto = c.role === "base" ? t("model_layer_remove_base_confirm", { arquivo: c.file }) : t("model_layer_remove_confirm", { arquivo: c.file });
          if (!(await confirmar({ texto, acao: t("act_remove"), perigo: true }))) return false;
          await api.del(`${base}/layers/${encodeURIComponent(c.file)}`, A);
          refazer();
          return true;
        });
        acoes.push(sobe, " ", desce, " ", tira);
      }
      return [
        el("span", { class: "muted" }, String(i + 1)),
        el("span", { class: "mono" }, c.file),
        el("span", { class: c.role === "base" ? "pill warn" : "pill" }, rotuloDoPapel(c.role)),
        md5Copiavel(c.md5),
        el("span", { class: "actions" }, ...acoes),
      ];
    });

    const partes = [
      el("p", { class: "help" }, t("model_layers_help")),
      tabela(["#", t("layer_file"), t("layer_role"), "md5", ""], linhas, { vazio: t("model_empty_warning") }),
    ];
    if (gere) {
      const anexar = el("button", { type: "button", class: "small primary" }, t("layer_attach_title"));
      anexar.onclick = acao(async () => {
        const c = await escolherCamada({ titulo: `${t("layer_attach_title")}: ${nome}`, comPapel: true });
        if (!c) return false;
        if (c.role === "base") {
          // trocar a base substitui a que está lá: duas bases no mesmo modelo
          // fazem a máquina baixar duas raízes e montá-las sobrepostas
          if (!(await confirmar({ texto: t("model_base_replace_confirm"), acao: t("act_replace"), perigo: true }))) return false;
        }
        if (c.build && c.build.model === nome && c.role === "extra") {
          // a construção deste modelo: pela rota da construção, que guarda de onde veio
          await api.post(`/api/v1/layerbuilds/${encodeURIComponent(c.build.id)}/attach`, { model: true }, A);
        } else {
          if (c.build && c.build.model !== nome) {
            const ok = await confirmar({ texto: t("layer_other_model_warn", { modelo: c.build.model }), acao: t("act_attach"), perigo: true });
            if (!ok) return false;
          }
          const corpoPost = { file: c.file, md5: c.md5, role: c.role, size: c.size };
          if (c.cdn_url) corpoPost.cdn_url = c.cdn_url;
          if (c.role === "base") corpoPost.replace_role = "base";
          await api.post(`${base}/layers`, corpoPost, A);
        }
        refazer();
        return true;
      }, { ok: t("layer_attached") });
      const construir = el("button", { type: "button", class: "small" }, t("layer_build"));
      construir.onclick = acao(async () => {
        const r = await dialogoConstruir({ modelo: nome, ...contexto });
        if (!r) return false;
        document.dispatchEvent(new CustomEvent("nb3:eu-mudou"));
        return true;
      }, { ok: t("build_queued") });
      partes.push(el("div", { class: "actions" }, anexar, construir));
    }

    // as camadas que só algumas imagens do modelo têm
    const soDelas = (m.image_extras || []).filter((i) => (i.layers || []).length);
    if (soDelas.length) {
      partes.push(
        el("h3", {}, t("model_image_layers_title")),
        el("p", { class: "help" }, t("model_image_layers_help")),
        tabela([t("image_id"), t("layer_file")], soDelas.map((i) => [
          el("span", { class: "mono" }, linkPara(i.id, "imagens", i.id, "camadas")),
          el("span", { class: "mono" }, (i.layers || []).map((c) => c.file).join(", ")),
        ]))
      );
    }
    corpo.replaceChildren(...partes);
  });

// --- papel de parede do modelo: vale para toda imagem que não tenha o seu ---

const desenharPapel = (corpo, nome, gere, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const base = `/api/v1/models/${encodeURIComponent(nome)}`;
    const m = await api.get(base, { ...A, signal: sinal });
    const refazer = () => desenharPapel(corpo, nome, gere, sinal);
    const w = m.wallpaper;
    const partes = [];
    if (w) {
      // a rota aceita o cookie sem o cabeçalho do console, como a da imagem
      partes.push(el("img", { src: `${base}/wallpaper?v=${encodeURIComponent(w.md5 || "")}`, alt: "", style: "max-width:320px;border-radius:6px" }));
    } else {
      partes.push(el("p", { class: "muted" }, t("wallpaper_none")));
    }
    if (gere) {
      const arquivo = el("input", { type: "file", accept: "image/png,image/jpeg", hidden: true });
      const trocar = el("button", { type: "button", class: "small" }, t("wallpaper_choose"));
      trocar.onclick = () => arquivo.click();
      arquivo.onchange = acao(async () => {
        if (!arquivo.files[0]) return false;
        const fd = new FormData();
        fd.append("file", arquivo.files[0]);
        await api.request("PUT", `${base}/wallpaper`, { raw: fd, kind: "admin" });
        refazer();
        return true;
      }, { ok: t("saved_ok") });
      const acoes = [arquivo, trocar];
      if (w) {
        const remover = el("button", { type: "button", class: "small danger" }, t("act_remove"));
        remover.onclick = acao(async () => {
          if (!(await confirmar({ texto: t("model_wallpaper_remove_confirm"), acao: t("act_remove"), perigo: true }))) return false;
          await api.del(`${base}/wallpaper`, A);
          refazer();
          return true;
        });
        acoes.push(remover);
      }
      partes.push(el("div", { class: "actions" }, ...acoes));
    }
    corpo.replaceChildren(...partes);
  });

// --- a página ---

export const vista = async (alvo, ctx) => {
  const nome = ctx.id;
  let m;
  let lista;
  let imagens;
  try {
    [m, lista, imagens] = await Promise.all([
      api.get(`/api/v1/models/${encodeURIComponent(nome)}`, { ...A, signal: ctx.sinal }),
      api.get("/api/v1/models", { ...A, signal: ctx.sinal }),
      api.get("/api/v1/site-images", { ...A, signal: ctx.sinal }),
    ]);
  } catch (e) {
    if (e.status === 404) return naoEncontrado(alvo, "modelos", t("nav_models"));
    throw e;
  }
  const gere = Boolean(m.can_manage);
  const admin = ehAdmin();
  const contexto = { modelos: lista.models, imagens: imagens.images };
  const pills = [];
  if (m.public) pills.push(el("span", { class: "pill ok" }, t("template_public")));
  if (!gere) pills.push(el("span", { class: "pill" }, t("model_readonly_short")));
  const duplicar = el("button", { type: "button", class: "small" }, t("model_duplicate"));
  duplicar.onclick = acao(async () => Boolean(await dialogoNovoModelo({ modelos: lista.models, partirDe: nome })));
  alvo.append(cabecalho({
    trilha: [linkPara(t("nav_models"), "modelos")],
    titulo: nome,
    pills,
    acoes: [duplicar],
  }));
  const linha = [m.description || ""];
  if (admin) linha.push(" · ", m.owner_kind === "subadmin" ? linkPara(rotuloDoDono(m), "pessoas", m.owner_ref) : rotuloDoDono(m));
  alvo.append(el("p", { class: "muted" }, ...linha));
  if (!gere) alvo.append(el("p", { class: "msg warn" }, t("model_readonly")));

  const secoes = [];
  if (gere) {
    const geral = secao({ id: "geral", titulo: t("section_general") });
    desenharGeral(geral.corpo, m);
    secoes.push(geral.no);
  }
  const camadas = secao({ id: "camadas", titulo: t("model_layers") });
  const papel = secao({ id: "papel", titulo: t("section_wallpaper"), ajuda: t("model_wallpaper_help") });
  const form = secao({ id: "formulario", titulo: t("section_form") });
  const imgs = secao({ id: "imagens", titulo: t("model_images_title") });
  secoes.push(camadas.no, papel.no, form.no, imgs.no);
  alvo.append(...secoes);
  desenharCamadas(camadas.corpo, nome, gere, contexto, ctx.sinal);
  desenharPapel(papel.corpo, nome, gere, ctx.sinal);
  desenharFormulario(form.corpo, nome, gere, ctx.sinal);
  imgs.corpo.append(
    tabela([t("image_id"), t("image_name"), ""], (m.image_extras || []).map((i) => ({
      celulas: [el("span", { class: "mono" }, linkPara(i.id, "imagens", i.id)), i.fullname || "", pillPerfil(i.unlocked)],
      aoClicar: () => irPara("imagens", i.id),
    })), { vazio: t("model_images_none") })
  );

  if (gere) {
    const apagar = secao({ id: "apagar", titulo: t("model_delete_title"), ajuda: t("model_delete_help"), perigo: true });
    const botao = el("button", { type: "button", class: "danger" }, t("model_delete_title"));
    botao.onclick = acao(async () => {
      const ok = await confirmar({
        titulo: t("model_delete_title"),
        texto: t("model_delete_confirm", { n: nome }),
        acao: t("act_delete"),
        perigo: true,
        digitar: nome,
      });
      if (!ok) return false;
      // 409: ainda há imagem derivando dele; a mensagem do servidor diz quais
      await api.del(`/api/v1/models/${encodeURIComponent(nome)}`, A);
      document.dispatchEvent(new CustomEvent("nb3:eu-mudou"));
      irPara("modelos");
      return true;
    }, { ok: t("model_deleted") });
    apagar.corpo.append(botao);
    alvo.append(apagar.no);
  }
};
