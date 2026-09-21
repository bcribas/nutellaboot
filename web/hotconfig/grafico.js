// Os gráficos do hotconfig: o de tempo (detalhe da máquina) e a miniatura
// (a visão Sala, muitas máquinas na mesma escala).
import { t } from "/common/i18n.js";

// O traçado de uma série: levanta a caneta num buraco de mais de 5 min, para
// uma máquina desligada não virar uma reta.
function tracar(pontos, campo, x, y) {
  let d = "";
  let caneta = false;
  let tAnt = 0;
  for (const p of pontos) {
    const v = p[campo];
    if (v == null) {
      caneta = false;
      continue;
    }
    const cmd = caneta && p.t - tAnt < 300 ? "L" : "M";
    d += `${cmd}${x(p.t).toFixed(1)} ${y(v).toFixed(1)} `;
    caneta = true;
    tAnt = p.t;
  }
  return d;
}

export function graficoTempo(pontos, series, maxY, refY, extra) {
  if (pontos.length < 2) return `<p class="muted">${t("samples_none")}</p>`;
  const W = 580;
  const H = 130;
  const PAD = 6;
  const HX = 18; // a faixa dos rótulos de hora, abaixo do traçado
  const t0 = pontos[0].t;
  const t1 = pontos[pontos.length - 1].t;
  const dur = Math.max(1, t1 - t0);
  const x = (tt) => PAD + ((tt - t0) * (W - 2 * PAD)) / dur;
  const y = (v) => H - PAD - (Math.min(v, maxY) * (H - 2 * PAD)) / maxY;
  let corpo = "";
  for (const frac of [0.25, 0.5, 0.75]) {
    const yy = H - PAD - frac * (H - 2 * PAD);
    corpo += `<line x1="${PAD}" y1="${yy}" x2="${W - PAD}" y2="${yy}"
      stroke="var(--line)" stroke-width="1"/>`;
  }
  // 5 marcas de tempo; janela maior que um dia ganha o dia junto da hora
  const comDia = dur > 86400;
  for (let i = 0; i <= 4; i++) {
    const tt = t0 + (dur * i) / 4;
    const xx = PAD + ((W - 2 * PAD) * i) / 4;
    corpo += `<line x1="${xx}" y1="${PAD}" x2="${xx}" y2="${H - PAD}"
      stroke="var(--line)" stroke-width="1" stroke-dasharray="2 4"/>`;
    const dt = new Date(tt * 1000);
    const hh = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const rot = comDia ? `${dt.getDate()}/${dt.getMonth() + 1} ${hh}` : hh;
    const anchor = i === 0 ? "start" : i === 4 ? "end" : "middle";
    corpo += `<text x="${xx}" y="${H + HX - 6}" text-anchor="${anchor}" class="gtick">${rot}</text>`;
  }
  if (refY != null && refY > 0 && refY <= maxY) {
    corpo += `<line x1="${PAD}" y1="${y(refY)}" x2="${W - PAD}" y2="${y(refY)}"
      stroke="var(--warn)" stroke-width="1" stroke-dasharray="6 4"/>`;
  }
  for (const s of series) {
    corpo += `<path d="${tracar(pontos, s.campo, x, y)}" fill="none" stroke="${s.cor}"
      stroke-width="2" stroke-linejoin="round"/>`;
  }
  const ult = pontos[pontos.length - 1];
  const agora = series
    .filter((s) => ult[s.campo] != null)
    .map((s) => `<b style="color:${s.cor}">${ult[s.campo]}${s.suf || ""}</b>`)
    .join(" ");
  const leg = series.map((s) => `<span style="color:${s.cor}">● ${s.rot}</span>`).join(" ");
  return `<div class="gtempo"><div class="gcab"><span class="gleg">${leg}${
    extra ? ` <span class="muted">${extra}</span>` : ""}</span><span class="gval">${agora}</span></div>
    <svg viewBox="0 0 ${W} ${H + HX}">${corpo}</svg></div>`;
}

// Miniatura sem eixos: `pontos` na mesma janela e `maxY` comum, para as
// máquinas da sala serem comparáveis lado a lado.
export function miniGrafico(pontos, campo, maxY, { W = 200, H = 56, cor = "var(--accent)" } = {}) {
  if (pontos.length < 2) return `<svg viewBox="0 0 ${W} ${H}" class="mini"></svg>`;
  const t0 = pontos[0].t;
  const dur = Math.max(1, pontos[pontos.length - 1].t - t0);
  const x = (tt) => 1 + ((tt - t0) * (W - 2)) / dur;
  const y = (v) => H - 1 - (Math.min(v, maxY) * (H - 2)) / maxY;
  return `<svg viewBox="0 0 ${W} ${H}" class="mini"><path d="${tracar(pontos, campo, x, y)}" fill="none" stroke="${cor}" stroke-width="1.5"/></svg>`;
}
