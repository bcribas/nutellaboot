// A página de uma imagem: tudo o que se faz com ela, num lugar só.
//
// Eram nove botões na linha da lista (três deles para credenciais, cada um de
// um jeito, e o que trocava o token sem perguntar nada), um cartão enfiado no
// topo da página, um diálogo para as chaves, um painel solto no fim da página
// para as camadas e o papel de parede só na criação.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, copiavel, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { confirmar, rotulosDeCopia } from "/common/dialogo.js";
import { usbBlock } from "/common/usb.js";
import {
  A, cabecalho, caixa, campo, carregarEm, ehAdmin, esquecerRascunho, irPara, linkPara, marcarSujo,
  naoEncontrado, pillPerfil, rascunho, rotuloDoDono, rotuloDoPapel, rotuloDoEstado, secao, tabela,
} from "./comum.js";
import { dialogoConstruir, escolherCamada, md5Copiavel, verLog } from "./camadas.js";
import { desenharWebhooks } from "./webhooks.js";

const redesenhar = () => document.dispatchEvent(new CustomEvent("nb3:redesenhar"));
const eu_mudou = () => document.dispatchEvent(new CustomEvent("nb3:eu-mudou"));

// --- Geral: nome, modelo e, para a administração, perfil, placar e cota ---

const desenharGeral = (corpo, img, modelos) => {
  const admin = ehAdmin();
  const chave = `imagem:${img.id}:geral`;
  const original = {
    fullname: img.fullname || "",
    model: img.model || "",
    perfil: img.unlocked ? "free" : "official",
    dashboard_hidden: Boolean(img.dashboard_hidden),
    build_quota: img.build_quota ?? 5,
    wallpaper_locked: Boolean(img.wallpaper_locked),
  };
  const r = rascunho(chave, () => ({ ...original }));
  const mudou = () => marcarSujo(chave, JSON.stringify(r) !== JSON.stringify(original));

  const nome = el("input", { type: "text", value: r.fullname });
  nome.oninput = () => {
    r.fullname = nome.value;
    mudou();
  };
  const modelo = el("select", {});
  const opcoes = modelos.filter((m) => m.layers > 0 || m.name === img.model);
  for (const m of opcoes) modelo.append(el("option", { value: m.name, selected: m.name === r.model }, m.name));
  modelo.onchange = () => {
    r.model = modelo.value;
    mudou();
  };
  const campos = [campo(t("image_name"), nome), campo(t("template"), modelo, t("image_model_help"))];

  // os controles da administração ficam declarados mesmo sem uso, para o
  // perfil poder mexer na trava
  const perfil = el("select", {},
    el("option", { value: "official", selected: r.perfil === "official" }, t("profile_official")),
    el("option", { value: "free", selected: r.perfil === "free" }, t("profile_free")));
  const trava = el("input", { type: "checkbox", checked: r.wallpaper_locked });
  const oculta = el("input", { type: "checkbox", checked: r.dashboard_hidden });
  const cota = el("input", { type: "number", min: 0, value: r.build_quota });
  perfil.onchange = () => {
    r.perfil = perfil.value;
    // Livre é liberar tudo: a trava do papel de parede sai junto. A trava da
    // imagem vence o `unlocked` (é a do convite, de propósito), e sem isto
    // "liberei a sede" deixava o papel de parede preso sem explicação.
    if (perfil.value === "free") {
      r.wallpaper_locked = false;
      trava.checked = false;
    }
    mudou();
  };
  trava.onchange = () => {
    r.wallpaper_locked = trava.checked;
    mudou();
  };
  oculta.onchange = () => {
    r.dashboard_hidden = oculta.checked;
    mudou();
  };
  cota.oninput = () => {
    r.build_quota = cota.value === "" ? null : Number(cota.value);
    mudou();
  };
  if (admin) {
    campos.push(
      campo(t("profile"), perfil, t("profile_help")),
      caixa(t("wallpaper_lock_label"), trava),
      caixa(t("dashboard_hidden_label"), oculta, t("dashboard_hidden_help")),
      campo(t("quota_builds"), cota, t("image_quota_help"))
    );
  }

  const salvar = el("button", { type: "button", class: "primary" }, t("save"));
  salvar.onclick = acao(async () => {
    const mudancas = {};
    if (r.fullname.trim() !== original.fullname) mudancas.fullname = r.fullname.trim();
    if (r.model !== original.model) {
      if (!(await confirmar({ texto: t("image_edit_model_warn"), acao: t("save"), perigo: true }))) return false;
      mudancas.model = r.model;
    }
    if (admin) {
      if (r.perfil !== original.perfil) mudancas.unlocked = r.perfil === "free";
      if (r.wallpaper_locked !== original.wallpaper_locked) mudancas.wallpaper_locked = r.wallpaper_locked;
      if (r.dashboard_hidden !== original.dashboard_hidden) mudancas.dashboard_hidden = r.dashboard_hidden;
      if (r.build_quota !== original.build_quota && r.build_quota !== null) mudancas.build_quota = r.build_quota;
    }
    if (!Object.keys(mudancas).length) return false;
    await api.patch(`/api/v1/site-images/${encodeURIComponent(img.id)}`, mudancas, A);
    esquecerRascunho(chave);
    redesenhar();
    return true;
  }, { ok: t("saved_ok") });

  corpo.replaceChildren(el("div", { class: "grade" }, ...campos), el("div", { class: "actions" }, salvar));
};

// --- papel de parede: o da imagem ou o herdado do modelo ---

const desenharPapel = (corpo, img, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const base = `/api/v1/site-images/${encodeURIComponent(img.id)}`;
    const c = await api.get(`${base}/config`, { ...A, signal: sinal });
    const w = c.wallpaper;
    const refazer = () => desenharPapel(corpo, img, sinal);
    const origem = !w
      ? t("wallpaper_none")
      : w.origin === "image"
        ? t("wallpaper_origin_image")
        : t("wallpaper_origin_model", { modelo: img.model });
    const partes = [el("p", { class: "muted" }, origem)];
    if (w) partes.push(el("img", { src: api.wallpaperUrl(img.id, w.md5), alt: "", style: "max-width:320px;border-radius:6px" }));

    const arquivo = el("input", { type: "file", accept: "image/png,image/jpeg", hidden: true });
    const trocar = el("button", { type: "button", class: "small", disabled: !c.can_edit_wallpaper }, t("wallpaper_choose"));
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
    if (w && w.origin === "image") {
      const remover = el("button", { type: "button", class: "small danger", disabled: !c.can_edit_wallpaper }, t("act_remove"));
      remover.onclick = acao(async () => {
        if (!(await confirmar({ texto: t("wallpaper_remove_confirm"), acao: t("act_remove"), perigo: true }))) return false;
        await api.del(`${base}/wallpaper`, A);
        refazer();
        return true;
      });
      acoes.push(remover);
    }
    if (!c.can_edit_wallpaper) partes.push(el("p", { class: "msg warn" }, t("wallpaper_locked_msg")));
    partes.push(el("div", { class: "actions" }, ...acoes));
    corpo.replaceChildren(...partes);
  });

// --- acesso: os links para a sede e as três credenciais ---

const desenharAcesso = (corpo, img, sinal, aoTrocarBoot) =>
  carregarEm(corpo, sinal, async () => {
    const id = img.id;
    const base = `/api/v1/site-images/${encodeURIComponent(id)}`;
    const c = await api.get(`${base}/credentials`, { ...A, signal: sinal });
    const rot = rotulosDeCopia();
    const refazer = () => desenharAcesso(corpo, img, sinal, aoTrocarBoot);

    const trocarToken = el("button", { type: "button", class: "small danger" }, t("act_replace"));
    trocarToken.onclick = acao(async () => {
      const ok = await confirmar({ titulo: t("token_rotate_title"), texto: t("token_rotate_confirm"), acao: t("act_replace"), perigo: true });
      if (!ok) return false;
      await api.post(`${base}/token/rotate`, undefined, A);
      refazer();
      return true;
    }, { ok: t("token_rotated") });

    const trocarBoot = el("button", { type: "button", class: "small danger" }, t("act_replace"));
    trocarBoot.onclick = acao(async () => {
      const ok = await confirmar({ titulo: t("bkey_rotate"), texto: t("bkey_rotate_confirm"), acao: t("act_replace"), perigo: true, digitar: id });
      if (!ok) return false;
      await api.post(`${base}/boot-key/rotate`, undefined, A);
      refazer();
      aoTrocarBoot();
      return true;
    }, { ok: t("bkey_rotated") });

    const carencia = el("select", { class: "small" },
      el("option", { value: "12" }, t("mkey_grace", { h: 12 })),
      el("option", { value: "48" }, t("mkey_grace", { h: 48 })),
      el("option", { value: "0" }, t("mkey_grace_none")));
    const trocarMaquina = el("button", { type: "button", class: "small danger" }, t("act_replace"));
    trocarMaquina.onclick = acao(async () => {
      const horas = parseInt(carencia.value, 10);
      const ok = await confirmar({
        titulo: t("mkey_rotate"),
        texto: horas ? t("mkey_rotate_confirm", { h: horas }) : t("mkey_rotate_confirm_none"),
        acao: t("act_replace"),
        perigo: true,
      });
      if (!ok) return false;
      const tenta = (force) => api.post(`${base}/machine-key/rotate`, { grace_hours: horas, force }, A);
      let r;
      try {
        r = await tenta(false);
      } catch (e) {
        // 409: há máquina travada, e a troca sem carência a deixaria sem o destravar
        if (e.status !== 409) throw e;
        const forcar = await confirmar({ titulo: t("mkey_rotate"), texto: `${e.message}. ${t("mkey_locked_force")}`, acao: t("act_replace"), perigo: true });
        if (!forcar) return false;
        r = await tenta(true);
      }
      toast(t("mkey_rotated", { online: r.online }));
      refazer();
      return true;
    });

    corpo.replaceChildren(
      el("h3", {}, t("access_links_title")),
      el("p", { class: "help" }, t("access_links_help")),
      el("dl", { class: "kv" },
        el("dt", {}, t("config_link")), el("dd", {}, copiavel(c.configureitor_url, rot, { oculto: true })),
        el("dt", {}, t("manage_link")), el("dd", {}, copiavel(c.hotconfig_url, rot, { oculto: true }))),
      el("h3", {}, t("access_keys_title")),
      el("dl", { class: "kv" },
        el("dt", {}, t("token")),
        el("dd", {}, copiavel(c.token, rot, { oculto: true }), " ", trocarToken, el("div", { class: "help" }, t("token_help"))),
        el("dt", {}, t("boot_key")),
        el("dd", {}, copiavel(c.boot_key, rot, { oculto: true }), " ", trocarBoot, el("div", { class: "help" }, t("bkey_help"))),
        el("dt", {}, t("machine_key")),
        el("dd", {}, copiavel(c.machine_key, rot, { oculto: true }), " ", carencia, " ", trocarMaquina,
          el("div", { class: "help" }, t("mkey_rotate_help"))))
    );
  });

// --- camadas: o que a máquina desta imagem baixa, na ordem ---

const desenharCamadas = (corpo, img, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const base = `/api/v1/site-images/${encodeURIComponent(img.id)}`;
    const [camadas, construcoes] = await Promise.all([
      api.get(`${base}/layers`, { ...A, signal: sinal }),
      api.get(`${base}/layerbuilds`, { ...A, signal: sinal }),
    ]);
    const refazer = () => desenharCamadas(corpo, img, sinal);
    const daImagem = new Set((camadas.extra || []).map((c) => c.file));

    const linhas = (camadas.all || []).map((c, i) => {
      const propria = daImagem.has(c.file);
      let remover = "";
      if (propria) {
        remover = el("button", { type: "button", class: "small danger" }, t("act_remove"));
        remover.onclick = acao(async () => {
          const ok = await confirmar({ texto: t("layer_remove_image_confirm", { arquivo: c.file }), acao: t("act_remove"), perigo: true });
          if (!ok) return false;
          await api.del(`${base}/layers/${encodeURIComponent(c.file)}`, A);
          refazer();
          return true;
        });
      }
      return [
        el("span", { class: "muted" }, String(i + 1)),
        el("span", { class: "mono" }, c.file),
        propria ? el("span", { class: "pill ok" }, t("layer_origin_image"))
          : el("span", { class: "pill" }, t("layer_origin_model", { modelo: img.model })),
        rotuloDoPapel(c.role),
        md5Copiavel(c.md5),
        remover,
      ];
    });

    const anexar = el("button", { type: "button", class: "small primary" }, t("layer_attach_title"));
    anexar.onclick = acao(async () => {
      const c = await escolherCamada({ titulo: `${t("layer_attach_title")}: ${img.id}` });
      if (!c) return false;
      if (c.build) {
        await api.post(`/api/v1/layerbuilds/${encodeURIComponent(c.build.id)}/attach`, { image_ids: [img.id] }, A);
      } else {
        await api.post(`${base}/layers`, { file: c.file, md5: c.md5, cdn_url: c.cdn_url || undefined, size: c.size }, A);
      }
      refazer();
      return true;
    }, { ok: t("layer_attached") });

    const construir = el("button", { type: "button", class: "small" }, t("layer_build"));
    construir.onclick = acao(async () => {
      const r = await dialogoConstruir({ imagem: img.id });
      if (!r) return false;
      eu_mudou();
      refazer();
      return true;
    }, { ok: t("build_queued") });

    const doLog = (b) => {
      const botao = el("button", { type: "button", class: "small" }, t("act_log"));
      botao.onclick = () => verLog(b.id);
      return botao;
    };
    const cota = construcoes.quota === null || construcoes.quota === undefined ? "" : `/${construcoes.quota}`;
    corpo.replaceChildren(
      el("p", { class: "help" }, t("layer_effective_help")),
      tabela(["#", t("layer_file"), t("layer_origin"), t("layer_role"), "md5", ""], linhas, { vazio: t("layer_none") }),
      el("div", { class: "actions" }, anexar, construir),
      el("h3", {}, `${t("layer_builds_title")} (${construcoes.used}${cota})`),
      tabela([], (construcoes.builds || []).map((b) => [
        el("b", {}, b.name),
        el("span", { class: "pill" }, rotuloDoEstado(b.state)),
        el("span", { class: "mono" }, (b.output && b.output.file) || ""),
        md5Copiavel(b.output && b.output.md5),
        doLog(b),
      ]), { vazio: t("layer_none") })
    );
  });

// --- a página ---

export const vista = async (alvo, ctx) => {
  const id = ctx.id;
  let img;
  let modelos;
  try {
    [img, modelos] = await Promise.all([
      api.get(`/api/v1/site-images/${encodeURIComponent(id)}`, { ...A, signal: ctx.sinal }),
      api.get("/api/v1/models", { ...A, signal: ctx.sinal }),
    ]);
  } catch (e) {
    if (e.status === 404) return naoEncontrado(alvo, "imagens", t("nav_images"));
    throw e;
  }
  const admin = ehAdmin();
  const pills = [pillPerfil(img.unlocked)];
  if (img.dashboard_hidden) pills.push(el("span", { class: "pill", title: t("dashboard_hidden_help") }, t("dashboard_hidden_short")));
  if (img.namespace === "contest") pills.push(el("span", { class: "pill warn" }, t("reserved_namespace")));
  const abrir = (rotulo, tela) =>
    el("a", { class: "btn small", href: `/${tela}/?id=${encodeURIComponent(id)}`, target: "_blank", rel: "noopener" }, rotulo);
  alvo.append(
    cabecalho({
      trilha: [linkPara(t("nav_images"), "imagens")],
      titulo: id,
      pills,
      acoes: [abrir(t("open_lab"), "hotconfig"), abrir(t("open_config"), "configureitor")],
    }),
    el("p", { class: "muted" },
      img.fullname || "", " · ", linkPara(img.model, "modelos", img.model),
      admin ? " · " : "", admin ? (img.owner_kind === "subadmin" ? linkPara(rotuloDoDono(img), "pessoas", img.owner_ref) : rotuloDoDono(img)) : "")
  );

  const geral = secao({ id: "geral", titulo: t("section_general") });
  const papel = secao({ id: "papel", titulo: t("section_wallpaper"), ajuda: t("image_wallpaper_help") });
  const acesso = secao({ id: "acesso", titulo: t("section_access") });
  const pendrive = secao({ id: "pendrive", titulo: t("section_usb") });
  const camadas = secao({ id: "camadas", titulo: t("nav_layers") });
  alvo.append(geral.no, papel.no, acesso.no, pendrive.no, camadas.no);

  const desenharPendrive = () => pendrive.corpo.replaceChildren(usbBlock(id, "", { sinal: ctx.sinal, semTitulo: true }));
  desenharGeral(geral.corpo, img, modelos.models);
  desenharPapel(papel.corpo, img, ctx.sinal);
  desenharAcesso(acesso.corpo, img, ctx.sinal, desenharPendrive);
  desenharPendrive();
  desenharCamadas(camadas.corpo, img, ctx.sinal);

  if (admin) {
    const webhooks = secao({ id: "webhooks", titulo: t("webhooks_title"), ajuda: t("webhooks_help") });
    alvo.append(webhooks.no);
    desenharWebhooks(webhooks.corpo, id, ctx.sinal);
  }

  const apagar = secao({ id: "apagar", titulo: t("image_delete_title"), ajuda: t("image_delete_help"), perigo: true });
  const botao = el("button", { type: "button", class: "danger" }, t("image_delete_title"));
  botao.onclick = acao(async () => {
    const ok = await confirmar({
      titulo: t("image_delete_title"),
      texto: t("confirm_delete", { id }),
      acao: t("act_delete"),
      perigo: true,
      digitar: id,
    });
    if (!ok) return false;
    await api.del(`/api/v1/site-images/${encodeURIComponent(id)}`, A);
    eu_mudou();
    irPara("imagens");
    return true;
  }, { ok: t("image_deleted") });
  apagar.corpo.append(botao);
  alvo.append(apagar.no);
};
