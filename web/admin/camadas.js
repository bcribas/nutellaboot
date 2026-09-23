// Aba Camadas: as construções (pacotes instalados por cima de um modelo) e onde
// cada camada está. E as peças que as páginas de imagem e de modelo usam:
// escolher uma camada, construir uma, ver o log, anexar uma construção.
//
// Era aqui que o dono de uma imagem se perdia: a construção era anexada à
// IMAGEM, a tela do modelo não a mostrava, o md5 não aparecia em lugar nenhum e
// o "Anexar" só sabia de imagens. Agora cada construção diz onde está, mostra
// o md5 e anexa também ao modelo em que foi construída.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, copiavel, quando, toast } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { abrirDialogo, formulario, rotulosDeCopia } from "/common/dialogo.js";
import {
  A, cabecalho, carregarEm, linkPara, rotuloDoEstado, rotuloDoPapel, secao, tabela, tamanho,
} from "./comum.js";

const MOSTRAR = 50;
let mostrarTodas = false;

export const pacotesDe = (texto) =>
  String(texto || "").split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);

const pillDoEstado = (b) => {
  const cor = { done: "ok", failed: "bad", running: "warn" }[b.state] || "";
  return el("span", { class: cor ? `pill ${cor}` : "pill" }, rotuloDoEstado(b.state));
};

// md5 inteiro com copiar: é o que se digita num "Anexar camada" à mão
export const md5Copiavel = (md5) => (md5 ? copiavel(md5, rotulosDeCopia()) : "");

// --- o log de uma construção ---

export const verLog = (jobId) => {
  let timer = null;
  const { corpo } = abrirDialogo({
    titulo: `${t("layer_log_title")}: ${jobId}`,
    largo: true,
    aoFechar: () => clearTimeout(timer),
  });
  const cab = el("p", { class: "muted" });
  const pre = el("pre", { class: "log" });
  corpo.append(cab, el("p", { class: "help" }, t("layer_log_tail_note")), pre);
  const busca = async () => {
    let b;
    try {
      b = await api.get(`/api/v1/layerbuilds/${encodeURIComponent(jobId)}`, A);
    } catch (e) {
      cab.textContent = e.message;
      return;
    }
    cab.textContent = `${rotuloDoEstado(b.state)} · ${(b.packages || []).join(" ")}${b.error ? ` · ${b.error}` : ""}`;
    pre.textContent = b.log || t("layer_log_empty");
    pre.scrollTop = pre.scrollHeight;
    if (b.state === "queue" || b.state === "running") timer = setTimeout(busca, 3000);
  };
  busca();
};

// --- construir ---

// Uma lista de caixas de marcar (imagens), para um campo `no` do formulário.
const listaDeMarcar = (itens, { marcados = [], travados = [] } = {}) => {
  const caixas = el("div", { class: "checks" });
  const entradas = [];
  for (const item of itens) {
    const ja = travados.includes(item.valor);
    const entrada = el("input", {
      type: "checkbox",
      value: item.valor,
      checked: ja || marcados.includes(item.valor),
      disabled: ja,
    });
    entradas.push(entrada);
    caixas.append(el("label", { class: "inline" }, entrada, " ", el("span", { class: "mono" }, item.rotulo),
      item.nota ? el("span", { class: "muted" }, ` ${item.nota}`) : null));
  }
  return {
    no: caixas,
    ler: () => entradas.filter((e) => e.checked && !e.disabled).map((e) => e.value),
  };
};

// Sobre um modelo (e, se quiser, já anexada a imagens dele quando ficar pronta)
// ou para uma imagem só (anexada a ela sozinha). O modelo inteiro fica para o
// "Anexar" da construção pronta.
export const dialogoConstruir = async ({ modelo = "", imagem = "", modelos = [], imagens = [] } = {}) => {
  if (imagem) {
    return formulario({
      titulo: `${t("layer_build")}: ${imagem}`,
      texto: t("layer_build_image_help"),
      acao: t("act_build"),
      campos: [
        { nome: "name", rotulo: t("layer_name"), obrigatorio: true, placeholder: "spim" },
        { nome: "packages", rotulo: t("layer_packages"), obrigatorio: true, placeholder: "htop tmux" },
      ],
      enviar: (v) =>
        api.post(`/api/v1/site-images/${encodeURIComponent(imagem)}/layerbuilds`,
          { name: v.name, packages: pacotesDe(v.packages) }, A),
    });
  }
  const geridos = modelos.filter((m) => m.can_manage);
  if (!geridos.length) {
    toast(t("layer_build_no_model"), true);
    return null;
  }
  const inicial = geridos.some((m) => m.name === modelo) ? modelo : geridos[0].name;
  const destino = el("div", {});
  let lista = listaDeMarcar([]);
  const montarLista = (nomeDoModelo) => {
    lista = listaDeMarcar(
      imagens.filter((i) => i.model === nomeDoModelo).map((i) => ({ valor: i.id, rotulo: i.id, nota: i.fullname || "" }))
    );
    destino.replaceChildren(lista.no.children.length ? lista.no : el("p", { class: "muted" }, t("layer_build_no_images")));
  };
  montarLista(inicial);
  return formulario({
    titulo: t("layer_build"),
    texto: t("layer_build_model_help"),
    acao: t("act_build"),
    largo: true,
    campos: [
      { nome: "name", rotulo: t("layer_name"), obrigatorio: true, placeholder: "extras" },
      {
        nome: "model",
        rotulo: t("template"),
        tipo: "select",
        valor: inicial,
        opcoes: geridos.map((m) => ({ valor: m.name, rotulo: m.name })),
        aoMudar: (valor) => montarLista(valor),
      },
      { nome: "packages", rotulo: t("layer_packages"), obrigatorio: true, placeholder: "htop tmux" },
      { nome: "attach_to", rotulo: t("layer_attach_when_ready"), tipo: "no", no: destino, ler: () => lista.ler() },
    ],
    enviar: (v) =>
      api.post("/api/v1/layerbuilds",
        { name: v.name, model: v.model, packages: pacotesDe(v.packages), attach_to: v.attach_to }, A),
  });
};

// --- anexar uma construção pronta ---

// Ao modelo em que foi construída (todas as imagens dele, inclusive as
// futuras) e/ou a imagens. Outro modelo, não: a camada leva o estado do apt
// daquela base.
export const anexarBuild = async (b, { modelos = [], imagens = [] } = {}) => {
  const saida = b.output || {};
  const ja = b.attached || { images: [], model: false };
  const gere = modelos.some((m) => m.name === b.model && m.can_manage);
  const livres = imagens.filter((i) => !(ja.images || []).includes(i.id));
  if ((ja.model || !gere) && !livres.length) {
    toast(t("layer_attach_nothing_left"));
    return null;
  }
  const modeloCaixa = el("input", { type: "checkbox", checked: ja.model, disabled: ja.model || !gere });
  const doModelo = imagens.filter((i) => i.model === b.model);
  const outras = imagens.filter((i) => i.model !== b.model);
  const lista = listaDeMarcar(
    [
      ...doModelo.map((i) => ({ valor: i.id, rotulo: i.id, nota: i.fullname || "" })),
      ...outras.map((i) => ({ valor: i.id, rotulo: i.id, nota: t("layer_attach_other_model", { modelo: i.model }) })),
    ],
    { travados: ja.images || [] }
  );
  const info = el("dl", { class: "kv" },
    el("dt", {}, t("layer_file")), el("dd", { class: "mono" }, `${saida.file || ""} · ${tamanho(saida.size)}`),
    el("dt", {}, "md5"), el("dd", {}, md5Copiavel(saida.md5)));
  const blocoModelo = el("div", { class: "fld" },
    el("label", { class: "inline" }, modeloCaixa, " ", t("layer_attach_model", { modelo: b.model })),
    el("span", { class: "help" }, gere ? t("layer_attach_model_help") : t("layer_attach_model_not_yours")));
  const r = await formulario({
    titulo: `${t("act_attach")}: ${b.name}`,
    acao: t("act_attach"),
    largo: true,
    antes: info,
    campos: [
      { nome: "modelo", rotulo: t("template"), tipo: "no", no: blocoModelo, ler: () => modeloCaixa.checked && !modeloCaixa.disabled },
      { nome: "imagens", rotulo: t("layer_attach_images"), tipo: "no", no: lista.no, ler: () => lista.ler() },
    ],
    enviar: (v) => {
      if (!v.modelo && !v.imagens.length) throw new Error(t("layer_attach_pick"));
      return api.post(`/api/v1/layerbuilds/${encodeURIComponent(b.id)}/attach`,
        { image_ids: v.imagens, model: v.modelo }, A);
    },
  });
  if (r) toast(t("layer_attached"));
  return r;
};

// --- escolher uma camada (catálogo, construções prontas ou à mão) ---

const rotuloDoCatalogo = (c) => {
  if (c.build) return `${c.file} — ${t("layer_from_build", { nome: c.build.name, modelo: c.build.model })}`;
  return `${c.file} — ${(c.used_by || []).join(", ")}`;
};

// Devolve {file, md5, cdn_url, size, role, build} ou null. Com `comPapel`, o
// papel entra no formulário (camadas de modelo têm papel; as de imagem são
// sempre extra).
export const escolherCamada = async ({ titulo = "", comPapel = false } = {}) => {
  let catalogo = [];
  try {
    catalogo = (await api.get("/api/v1/layers/catalog", A)).layers || [];
  } catch {
    /* sem catálogo, sobra o à mão */
  }
  const usaveis = catalogo.filter((c) => c.available !== false);
  const campos = [
    {
      nome: "escolha",
      rotulo: t("layer_pick_from_list"),
      tipo: "select",
      valor: "",
      opcoes: [{ valor: "", rotulo: t("layer_pick_manual") }, ...usaveis.map((c, i) => ({ valor: String(i), rotulo: rotuloDoCatalogo(c) }))],
      aoMudar: (valor, controles) => {
        const c = valor === "" ? null : usaveis[Number(valor)];
        for (const nome of ["file", "md5", "cdn_url"]) {
          controles[nome].disabled = Boolean(c);
          controles[nome].value = c ? c[nome] || "" : "";
        }
        if (comPapel && c) controles.role.value = c.role || "extra";
      },
    },
    { nome: "file", rotulo: t("layer_file"), placeholder: "extra-2026.squash" },
    { nome: "md5", rotulo: "md5", placeholder: "32 hex" },
    { nome: "cdn_url", rotulo: t("layer_cdn_url"), placeholder: "https://…" },
  ];
  if (comPapel) {
    campos.push({
      nome: "role",
      rotulo: t("layer_role"),
      tipo: "select",
      valor: "extra",
      opcoes: ["extra", "telemetry", "wifi", "base"].map((p) => ({ valor: p, rotulo: rotuloDoPapel(p) })),
    });
  }
  return formulario({
    titulo: titulo || t("layer_attach_title"),
    acao: t("act_attach"),
    largo: true,
    campos,
    enviar: (v) => {
      const c = v.escolha === "" ? null : usaveis[Number(v.escolha)];
      const escolhida = c
        ? { file: c.file, md5: c.md5, cdn_url: c.cdn_url || "", size: c.size, build: c.build || null }
        : { file: v.file, md5: v.md5.toLowerCase(), cdn_url: v.cdn_url, build: null };
      if (!escolhida.file) throw new Error(t("layer_file_required"));
      // o servidor recusaria igual; aqui a mensagem diz de onde tirar o md5
      if (!/^[0-9a-f]{32}$/.test(escolhida.md5 || "")) throw new Error(t("layer_md5_invalid_pick"));
      return { ...escolhida, role: comPapel ? v.role : "extra" };
    },
  });
};

// --- a aba ---

const ondeEsta = (b) => {
  const a = b.attached;
  if (!a) return "";
  const partes = [];
  if (a.model) partes.push(el("span", { class: "pill ok" }, t("layer_on_model", { modelo: b.model })));
  for (const img of a.images || []) partes.push(" ", el("span", { class: "pill" }, linkPara(img, "imagens", img, "camadas")));
  return partes.length ? el("span", {}, ...partes) : el("span", { class: "muted" }, t("layer_nowhere"));
};

const linhaDaConstrucao = (b, aoMudar, contexto) => {
  const saida = b.output || {};
  const log = el("button", { type: "button", class: "small" }, t("act_log"));
  log.onclick = () => verLog(b.id);
  const acoes = [log];
  if (b.state === "done" && saida.file) {
    const anexar = el("button", { type: "button", class: "small", disabled: b.available === false }, t("act_attach"));
    if (b.available === false) anexar.title = t("layer_unavailable");
    anexar.onclick = acao(async () => {
      const r = await anexarBuild(b, contexto);
      if (r) aoMudar();
    });
    acoes.push(" ", anexar);
  }
  return [
    el("div", {}, el("b", {}, b.name), el("br"), el("span", { class: "muted" }, linkPara(b.model, "modelos", b.model))),
    el("span", { class: "muted mono" }, (b.packages || []).join(" ")),
    el("div", {}, pillDoEstado(b), b.error ? el("div", { class: "muted small" }, String(b.error).slice(0, 120)) : null),
    saida.file
      ? el("div", {}, el("span", { class: "mono" }, saida.file), el("span", { class: "muted" }, ` · ${tamanho(saida.size)}`),
        el("div", {}, md5Copiavel(saida.md5)))
      : el("span", { class: "muted" }, quando(b.created_at)),
    b.state === "done" ? ondeEsta(b) : "",
    el("div", { class: "actions" }, ...acoes),
  ];
};

export const vista = async (alvo, ctx) => {
  const construir = el("button", { type: "button", class: "primary" }, t("layer_build"));
  alvo.append(cabecalho({ titulo: t("nav_layers"), acoes: [construir] }));
  alvo.append(el("p", { class: "help" }, t("layers_section_help")));

  const construcoes = secao({ id: "construcoes", titulo: t("layer_builds_title") });
  const catalogo = secao({ id: "catalogo", titulo: t("layer_catalog_title"), ajuda: t("layer_catalog_help") });
  alvo.append(construcoes.no, catalogo.no);

  let contexto = { modelos: [], imagens: [] };
  let timer = null;
  ctx.sinal.addEventListener("abort", () => clearTimeout(timer));

  const desenharCatalogo = () =>
    carregarEm(catalogo.corpo, ctx.sinal, async () => {
      const d = await api.get("/api/v1/layers/catalog", { ...A, signal: ctx.sinal });
      const emUso = (d.layers || []).filter((c) => (c.used_by || []).length);
      catalogo.corpo.replaceChildren(
        tabela(
          [t("layer_file"), t("layer_role"), "md5", t("layer_used_by")],
          emUso.map((c) => [
            el("span", { class: "mono" }, c.file),
            rotuloDoPapel(c.role),
            md5Copiavel(c.md5),
            el("span", {}, ...(c.used_by || []).flatMap((m, i) => [i ? ", " : "", linkPara(m, "modelos", m)])),
          ]),
          { vazio: t("layer_none") }
        )
      );
    });

  // anexar muda as duas seções: onde a construção está e quem usa a camada
  const aposAnexar = () => {
    desenhar();
    desenharCatalogo();
  };

  const desenhar = () =>
    carregarEm(construcoes.corpo, ctx.sinal, async () => {
      const [d, mods, imgs] = await Promise.all([
        api.get("/api/v1/layerbuilds", { ...A, signal: ctx.sinal }),
        api.get("/api/v1/models", { ...A, signal: ctx.sinal }),
        api.get("/api/v1/site-images", { ...A, signal: ctx.sinal }),
      ]);
      contexto = { modelos: mods.models, imagens: imgs.images };
      const lista = mostrarTodas ? d.builds : d.builds.slice(0, MOSTRAR);
      construcoes.corpo.replaceChildren(
        tabela(
          [t("layer_name"), t("packages"), t("status"), t("layer_file"), t("layer_where"), ""],
          lista.map((b) => linhaDaConstrucao(b, aposAnexar, contexto)),
          { vazio: t("layer_none") }
        )
      );
      if (!mostrarTodas && d.builds.length > MOSTRAR) {
        const mais = el("button", { type: "button", class: "small" }, t("act_show_all", { n: d.builds.length }));
        mais.onclick = () => {
          mostrarTodas = true;
          desenhar();
        };
        construcoes.corpo.append(mais);
      }
      // enquanto houver construção andando, atualiza sozinho
      clearTimeout(timer);
      if (!ctx.sinal.aborted && d.builds.some((b) => b.state === "queue" || b.state === "running")) {
        timer = setTimeout(desenhar, 4000);
      }
    });

  construir.onclick = acao(async () => {
    const r = await dialogoConstruir(contexto);
    if (!r) return false;
    toast(t("build_queued"));
    document.dispatchEvent(new CustomEvent("nb3:eu-mudou"));
    desenhar();
    return r;
  });

  await desenhar();
  desenharCatalogo();
};
