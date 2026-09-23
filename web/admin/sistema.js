// Aba Sistema (só a administração): o pendrive de boot (o par kernel+initrd e a
// imagem genérica, iguais para todas as sedes), a publicação no servidor de
// arquivos e a auditoria das credenciais.
//
// As ações do pendrive de UMA imagem (baixar, gerar de novo) moram na página
// dela; aqui fica a visão geral, com o link para cada uma.

import * as api from "/common/api.js";
import { t } from "/common/i18n.js";
import { el, quando } from "/common/ui.js";
import { acao } from "/common/acao.js";
import { formulario } from "/common/dialogo.js";
import { A, cabecalho, carregarEm, linkPara, secao, tabela, tamanho } from "./comum.js";

const estadoDoPendrive = (e) => {
  if (e.status === "building") return el("span", { class: "pill warn" }, t("usb_building"));
  if (e.status === "failed") return el("span", { class: "pill bad" }, t("usb_failed"));
  if (e.status === "done") return el("span", { class: "pill ok" }, t("usb_ready"));
  return el("span", { class: "pill" }, t("usb_not_generated"));
};

// o motivo de verdade (a tela antiga dizia "chave de boot" para qualquer um)
const motivoDesatualizado = (razoes) => {
  if (razoes.includes("boot_key")) return t("usb_stale_boot_key");
  if (razoes.includes("kernel")) return t("usb_stale_kernel");
  return t("usb_stale_server");
};

const desenharPendrive = (corpo, sinal) => {
  let timer = null;
  sinal.addEventListener("abort", () => clearTimeout(timer));
  const desenhar = () =>
    carregarEm(corpo, sinal, async () => {
      const d = await api.get("/api/v1/usb", { ...A, signal: sinal });
      const partes = [];
      if (d.kernel.ok) {
        const v = d.kernel.files["vmlinuz"];
        const i = d.kernel.files["initrd.img"];
        partes.push(el("p", { class: "muted" },
          `${t("usb_kernel")}: vmlinuz ${tamanho(v.size)} · initrd.img ${tamanho(i.size)} · ${quando(i.mtime)}`));
      } else {
        partes.push(el("p", { class: "msg warn" }, t("usb_no_kernel"), el("br"), el("code", {}, d.kernel.hint || "")));
      }

      const g = d.generic;
      const gerar = el("button", { type: "button", class: "small", disabled: g.status === "building" }, t("usb_regenerate"));
      gerar.onclick = acao(async () => {
        await api.post("/api/v1/usb/generic", {}, A);
        desenhar();
      });
      const baixar = g.status === "done"
        ? el("a", { class: "btn small", href: api.usbGenericUrl(), download: "" }, t("usb_download"))
        : null;
      partes.push(
        el("h3", {}, t("usb_generic_image")),
        el("p", {}, estadoDoPendrive(g), " ",
          g.file ? el("span", { class: "mono" }, `${g.file} · ${tamanho(g.size)}`) : "",
          g.published ? el("span", { class: "muted" }, ` · ${t("usb_published")}`) : ""),
        g.error ? el("p", { class: "msg bad" }, String(g.error).slice(0, 200)) : "",
        el("div", { class: "actions" }, baixar, gerar)
      );
      if (!d.auto_generate) partes.push(el("p", { class: "help" }, t("usb_auto_off")));

      partes.push(
        el("h3", {}, t("usb_per_site")),
        tabela([t("image_id"), t("status"), ""], d.images.map((i) => [
          el("span", { class: "mono" }, linkPara(i.id, "imagens", i.id, "pendrive")),
          estadoDoPendrive(i),
          i.stale ? el("span", { class: "muted small" }, motivoDesatualizado(i.stale_reason || [])) : "",
        ]), { vazio: t("usb_none") })
      );
      corpo.replaceChildren(...partes);
      // enquanto algo está sendo gerado, volta a perguntar; parado, não bate
      clearTimeout(timer);
      if (!sinal.aborted && (g.status === "building" || d.images.some((i) => i.status === "building"))) {
        timer = setTimeout(desenhar, 4000);
      }
    });
  desenhar();
};

const desenharPublicacao = (corpo, sinal) =>
  carregarEm(corpo, sinal, async () => {
    const d = await api.get("/api/v1/publish", { ...A, signal: sinal });
    const refazer = () => desenharPublicacao(corpo, sinal);
    const reenviar = el("button", { type: "button", class: "small" }, t("publish_retry"));
    reenviar.onclick = acao(async () => {
      const r = await api.post("/api/v1/publish/retry", {}, A);
      refazer();
      return r;
    }, { ok: t("publish_retried") });
    const publicar = el("button", { type: "button", class: "small" }, t("publish_one"));
    publicar.onclick = acao(async () => {
      const r = await formulario({
        titulo: t("publish_one"),
        texto: t("publish_one_help"),
        acao: t("publish_go"),
        campos: [
          { nome: "file", rotulo: t("layer_file"), obrigatorio: true },
          {
            nome: "kind",
            rotulo: t("publish_kind"),
            tipo: "select",
            valor: "layers",
            opcoes: [
              { valor: "layers", rotulo: t("publish_kind_layer") },
              { valor: "usb", rotulo: t("publish_kind_usb") },
            ],
          },
        ],
        enviar: async (v) => {
          const e = await api.post("/api/v1/publish/file", { file: v.file, kind: v.kind }, A);
          // invariante 15: a resposta diz se publicou; um 200 com `failed` é falha
          if (e.status !== "done") throw new Error(t("publish_failed_msg", { erro: e.error || e.status }));
          return e;
        },
      });
      if (!r) return false;
      refazer();
      return true;
    }, { ok: t("publish_status_done") });

    const linhas = d.files.map((f) => [
      el("span", { class: "mono" }, f.file),
      f.status === "done"
        ? el("span", { class: "pill ok" }, t("publish_status_done"))
        : f.status === "failed"
          ? el("span", { class: "pill bad" }, t("publish_status_failed"))
          : el("span", { class: "pill" }, t("publish_status_disabled")),
      el("span", { class: "muted mono" }, String(f.url || f.error || "").slice(0, 80)),
    ]);
    corpo.replaceChildren(
      el("p", { class: d.enabled ? "muted" : "msg warn" }, d.enabled ? `${t("publish_host")}: ${d.host}` : t("publish_disabled_warn")),
      el("div", { class: "actions" }, reenviar, publicar),
      tabela([t("layer_file"), t("status"), "URL"], linhas, { vazio: t("publish_none") })
    );
  });

const desenharAuditoria = (corpo, sinal, limite = 50) =>
  carregarEm(corpo, sinal, async () => {
    const d = await api.get(`/api/v1/audit?limit=${limite}`, { ...A, signal: sinal });
    const linhas = d.entries.map((e) => [
      el("span", { class: "muted" }, quando(e.at)),
      el("span", { class: "mono" }, e.action),
      el("span", { class: "mono" }, e.target || ""),
      el("span", { class: "muted" }, `${e.actor || e.actor_kind} · ${e.ip || ""}`),
      el("span", { class: "muted mono" }, Object.keys(e.detail || {}).length ? JSON.stringify(e.detail) : ""),
    ]);
    const partes = [tabela([], linhas, { vazio: t("audit_none") })];
    if (d.entries.length >= limite) {
      const mais = el("button", { type: "button", class: "small" }, t("act_show_more"));
      mais.onclick = () => desenharAuditoria(corpo, sinal, limite * 10);
      partes.push(mais);
    }
    corpo.replaceChildren(...partes);
  });

export const vista = async (alvo, ctx) => {
  alvo.append(cabecalho({ titulo: t("nav_system") }));
  const pendrive = secao({ id: "pendrive", titulo: t("section_usb"), ajuda: t("usb_section_help") });
  const publicacao = secao({ id: "publicacao", titulo: t("publish_section"), ajuda: t("publish_help") });
  const auditoria = secao({ id: "auditoria", titulo: t("audit_section"), ajuda: t("audit_help") });
  alvo.append(pendrive.no, publicacao.no, auditoria.no);
  desenharPendrive(pendrive.corpo, ctx.sinal);
  desenharPublicacao(publicacao.corpo, ctx.sinal);
  desenharAuditoria(auditoria.corpo, ctx.sinal);
};
