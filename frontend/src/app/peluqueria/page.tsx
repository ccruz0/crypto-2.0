"use client";
// app/peluqueria/page.tsx
// Dashboard de Peluquería Cruz — dashboard.hilovivo.com/peluqueria
// Next.js (App Router, Client Component). Autocontenido: estilos en línea, sin dependencias.
//
// FUENTES DE DATOS:
//  - "2026-05" ventas y snapshots de redes = REALES (informe mensual + datos públicos).
//  - Crecimiento mes a mes, sentiment y meses anteriores = DATOS DE EJEMPLO (sustituir por reales).
//  - Tráfico web y embudo = pendientes del pipeline de GA (metricas_web_AAAAMM.json).

import { useState } from "react";

const ORO = "#b8893b";
const TINTA = "#1a1a1a";
const GRIS = "#6b6b6b";
const VERDE = "#2e7d32";
const ROJO = "#c62828";
const BORDE = "#e6e6e6";
const FONDO = "#faf9f7";

type Mes = {
  label: string;
  real: boolean;
  ventas: { ingresos: string; ingresosDelta: number; servicios: string; serviciosDelta: number;
            ticket: string; ticketDelta: number; ocupacion: string; ocupacionDelta: number;
            habituales: string; habitualesPct: string; nuevos: string; nuevosPct: string; nuevosDelta: number };
  web: { sesiones: number | null; usuarios: number | null; vistas: number | null };
  redes: {
    instagram: { seguidores: number; nuevos: number; publicaciones: number; alcance: number; interaccion: number };
    facebook: { seguidores: number; nuevos: number };
    google: { rating: number; resenas: number; nuevasResenas: number };
  };
  sentiment: { positivo: number; neutro: number; negativo: number; muestra: number };
  publicaciones: { red: "Instagram" | "Facebook"; fecha: string; texto: string; likes: number; comentarios: number }[];
  embudo: { etq: string; val: number | null }[];
};

// Claves ordenadas de más reciente a más antiguo
const DATA: Record<string, Mes> = {
  "2026-05": {
    label: "Mayo 2026", real: true,
    ventas: { ingresos: "13.001 €", ingresosDelta: 2.2, servicios: "793", serviciosDelta: -0.8,
      ticket: "16,40 €", ticketDelta: 2.95, ocupacion: "52,1%", ocupacionDelta: -3.0,
      habituales: "662", habitualesPct: "89,5%", nuevos: "78", nuevosPct: "10,5%", nuevosDelta: -11.4 },
    web: { sesiones: null, usuarios: null, vistas: null },
    redes: {
      instagram: { seguidores: 1659, nuevos: 39, publicaciones: 301, alcance: 7800, interaccion: 4.1 },
      facebook: { seguidores: 462, nuevos: 7 },
      google: { rating: 4.7, resenas: 430, nuevasResenas: 7 },
    },
    sentiment: { positivo: 88, neutro: 8, negativo: 4, muestra: 41 },
    publicaciones: [
      { red: "Instagram", fecha: "28 may", texto: "Ritual de afeitado con toalla caliente 💈 reserva tu cita", likes: 142, comentarios: 11 },
      { red: "Instagram", fecha: "20 may", texto: "Corte + barba: el combo del mes", likes: 98, comentarios: 6 },
      { red: "Facebook", fecha: "14 may", texto: "Nuevos horarios de tarde para vosotros", likes: 34, comentarios: 4 },
      { red: "Instagram", fecha: "6 may", texto: "Antes y después · degradado clásico", likes: 167, comentarios: 14 },
    ],
    embudo: [
      { etq: "Impresiones en Google", val: null },
      { etq: "Clics orgánicos", val: null },
      { etq: "Sesiones orgánicas", val: null },
      { etq: "Reservas iniciadas", val: null },
    ],
  },
  "2026-04": {
    label: "Abril 2026", real: false,
    ventas: { ingresos: "12.450 €", ingresosDelta: 1.4, servicios: "767", serviciosDelta: 0.5,
      ticket: "16,23 €", ticketDelta: 1.1, ocupacion: "50,4%", ocupacionDelta: -1.2,
      habituales: "640", habitualesPct: "88,1%", nuevos: "92", nuevosPct: "11,9%", nuevosDelta: 4.5 },
    web: { sesiones: null, usuarios: null, vistas: null },
    redes: {
      instagram: { seguidores: 1620, nuevos: 31, publicaciones: 295, alcance: 7200, interaccion: 3.8 },
      facebook: { seguidores: 455, nuevos: 5 },
      google: { rating: 4.7, resenas: 423, nuevasResenas: 6 },
    },
    sentiment: { positivo: 85, neutro: 10, negativo: 5, muestra: 38 },
    publicaciones: [
      { red: "Instagram", fecha: "24 abr", texto: "Cuidado de barba en primavera: 3 consejos", likes: 121, comentarios: 9 },
      { red: "Facebook", fecha: "16 abr", texto: "Sorteo: corte gratis entre quienes nos sigan", likes: 58, comentarios: 22 },
      { red: "Instagram", fecha: "8 abr", texto: "Corte infantil sin lágrimas 👦", likes: 89, comentarios: 5 },
    ],
    embudo: [
      { etq: "Impresiones en Google", val: null },
      { etq: "Clics orgánicos", val: null },
      { etq: "Sesiones orgánicas", val: null },
      { etq: "Reservas iniciadas", val: null },
    ],
  },
  "2026-03": {
    label: "Marzo 2026", real: false,
    ventas: { ingresos: "12.980 €", ingresosDelta: 3.0, servicios: "812", serviciosDelta: 2.1,
      ticket: "15,99 €", ticketDelta: 0.9, ocupacion: "53,0%", ocupacionDelta: 0.4,
      habituales: "655", habitualesPct: "88,7%", nuevos: "84", nuevosPct: "11,3%", nuevosDelta: -2.0 },
    web: { sesiones: null, usuarios: null, vistas: null },
    redes: {
      instagram: { seguidores: 1589, nuevos: 28, publicaciones: 288, alcance: 6900, interaccion: 3.6 },
      facebook: { seguidores: 450, nuevos: 4 },
      google: { rating: 4.7, resenas: 417, nuevasResenas: 5 },
    },
    sentiment: { positivo: 86, neutro: 9, negativo: 5, muestra: 35 },
    publicaciones: [
      { red: "Instagram", fecha: "26 mar", texto: "Tendencias de corte para esta primavera", likes: 134, comentarios: 8 },
      { red: "Instagram", fecha: "18 mar", texto: "Producto propio CRUZ: cera mate", likes: 76, comentarios: 3 },
      { red: "Facebook", fecha: "10 mar", texto: "Gracias por las 400+ reseñas en Google ⭐", likes: 47, comentarios: 6 },
    ],
    embudo: [
      { etq: "Impresiones en Google", val: null },
      { etq: "Clics orgánicos", val: null },
      { etq: "Sesiones orgánicas", val: null },
      { etq: "Reservas iniciadas", val: null },
    ],
  },
};

const ORDEN = Object.keys(DATA); // ["2026-05","2026-04","2026-03"]

function fmt(n: number) { return n.toLocaleString("es-ES"); }
function signo(n: number, sufijo = "%") {
  const s = n > 0 ? "+" : "";
  return `${s}${n.toLocaleString("es-ES")}${sufijo}`;
}
function colorDelta(n: number, invertir = false) {
  if (n === 0) return GRIS;
  const bueno = invertir ? n < 0 : n > 0;
  return bueno ? VERDE : ROJO;
}

function KPI({ label, value, delta, deltaTxt, hint, invertir }: {
  label: string; value: string; delta?: number; deltaTxt?: string; hint?: string; invertir?: boolean }) {
  return (
    <div style={{ background: "#fff", border: `1px solid ${BORDE}`, borderRadius: 14, padding: "16px 18px", flex: "1 1 160px", minWidth: 160 }}>
      <div style={{ fontSize: 13, color: GRIS, marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: TINTA, lineHeight: 1.1 }}>{value}</div>
      {delta !== undefined && (
        <div style={{ fontSize: 13, color: colorDelta(delta, invertir), marginTop: 6, fontWeight: 600 }}>
          {deltaTxt ?? signo(delta)}
        </div>
      )}
      {hint && <div style={{ fontSize: 11, color: GRIS, marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

function Header2({ title, sub, ejemplo }: { title: string; sub?: string; ejemplo?: boolean }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h2 style={{ fontSize: 16, color: TINTA, margin: 0, fontWeight: 700 }}>{title}</h2>
        {ejemplo && <span style={{ fontSize: 10, color: "#8a6a1f", background: "#f6ecd4", border: "1px solid #e7d4a6", borderRadius: 20, padding: "2px 8px", fontWeight: 600 }}>datos de ejemplo</span>}
      </div>
      {sub && <div style={{ fontSize: 13, color: GRIS, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function PeluqueriaDashboard() {
  const [periodo, setPeriodo] = useState(ORDEN[0]);
  const d = DATA[periodo];
  const maxEmbudo = Math.max(...d.embudo.map((p) => p.val ?? 0), 1);

  return (
    <main style={{ fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", background: FONDO, minHeight: "100vh", color: TINTA }}>
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "32px 24px 60px" }}>
        {/* Cabecera + filtro de fechas */}
        <div style={{ borderBottom: `3px solid ${ORO}`, paddingBottom: 14, marginBottom: 26, display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 800, margin: 0 }}>Peluquería Cruz</h1>
            <div style={{ color: GRIS, fontSize: 14, marginTop: 4 }}>Panel mensual · Alameda de Osuna, Madrid</div>
          </div>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: GRIS }}>
            Periodo
            <select value={periodo} onChange={(e) => setPeriodo(e.target.value)}
              style={{ fontSize: 15, padding: "8px 12px", borderRadius: 10, border: `1px solid ${BORDE}`, background: "#fff", color: TINTA, minWidth: 160 }}>
              {ORDEN.map((k) => <option key={k} value={k}>{DATA[k].label}</option>)}
            </select>
          </label>
        </div>

        {/* 1. Ventas y visitas */}
        <section style={{ marginBottom: 30 }}>
          <Header2 title="Ventas y visitas" sub="Comparativa interanual (vs. mismo mes del año anterior)" ejemplo={!d.real} />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <KPI label="Ingresos" value={d.ventas.ingresos} delta={d.ventas.ingresosDelta} deltaTxt={`${signo(d.ventas.ingresosDelta)} vs año ant.`} />
            <KPI label="Servicios (visitas)" value={d.ventas.servicios} delta={d.ventas.serviciosDelta} deltaTxt={`${signo(d.ventas.serviciosDelta)} vs año ant.`} />
            <KPI label="Ticket medio" value={d.ventas.ticket} delta={d.ventas.ticketDelta} deltaTxt={`${signo(d.ventas.ticketDelta)} vs año ant.`} />
            <KPI label="Ocupación" value={d.ventas.ocupacion} delta={d.ventas.ocupacionDelta} deltaTxt={`${signo(d.ventas.ocupacionDelta, " pp")} vs año ant.`} invertir />
            <KPI label="Clientes habituales" value={d.ventas.habituales} hint={`${d.ventas.habitualesPct} del total`} />
            <KPI label="Clientes nuevos" value={d.ventas.nuevos} delta={d.ventas.nuevosDelta} deltaTxt={`${signo(d.ventas.nuevosDelta)} vs año ant.`} hint={`${d.ventas.nuevosPct} del total`} />
          </div>
        </section>

        {/* 2. Tráfico web */}
        <section style={{ marginBottom: 30 }}>
          <Header2 title="Tráfico web" sub="Google Analytics 4 — se rellena con el pipeline mensual" />
          {d.web.sesiones == null ? (
            <div style={{ background: "#fff", border: `1px dashed #d8d2c6`, borderRadius: 14, padding: "18px 20px", color: GRIS, fontSize: 13 }}>
              Pendiente: sesiones, usuarios y páginas vistas se cargarán automáticamente desde Google Analytics cuando el workflow mensual vuelque los datos.
            </div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              <KPI label="Sesiones" value={fmt(d.web.sesiones!)} />
              <KPI label="Usuarios" value={fmt(d.web.usuarios!)} />
              <KPI label="Páginas vistas" value={fmt(d.web.vistas!)} />
            </div>
          )}
        </section>

        {/* 3. Redes sociales (ampliado, con crecimiento) */}
        <section style={{ marginBottom: 30 }}>
          <Header2 title="Redes sociales" sub="Seguidores, crecimiento e interacción del periodo" ejemplo />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <KPI label="Instagram · seguidores" value={fmt(d.redes.instagram.seguidores)} delta={d.redes.instagram.nuevos} deltaTxt={`+${d.redes.instagram.nuevos} este mes`} hint="@cruz.peluqueria" />
            <KPI label="Instagram · alcance" value={fmt(d.redes.instagram.alcance)} hint="cuentas alcanzadas" />
            <KPI label="Instagram · interacción" value={`${d.redes.instagram.interaccion.toLocaleString("es-ES")}%`} hint="tasa de engagement" />
            <KPI label="Publicaciones" value={fmt(d.redes.instagram.publicaciones)} delta={0} deltaTxt={`${d.publicaciones.length} publicadas este mes`} hint="total en el perfil" />
            <KPI label="Facebook · seguidores" value={fmt(d.redes.facebook.seguidores)} delta={d.redes.facebook.nuevos} deltaTxt={`+${d.redes.facebook.nuevos} este mes`} hint="/cruzpelu" />
            <KPI label="Google · valoración" value={`${d.redes.google.rating.toLocaleString("es-ES")} / 5`} hint={`${fmt(d.redes.google.resenas)} reseñas · +${d.redes.google.nuevasResenas} nuevas`} />
          </div>
        </section>

        {/* 3b. Publicaciones del periodo */}
        <section style={{ marginBottom: 30 }}>
          <Header2 title="Publicaciones del periodo" sub={`Contenido publicado en ${d.label}`} ejemplo />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {d.publicaciones.map((post, i) => (
              <div key={i} style={{ background: "#fff", border: `1px solid ${BORDE}`, borderRadius: 12, padding: "12px 16px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: post.red === "Instagram" ? "#c13584" : "#1877f2", borderRadius: 6, padding: "3px 8px" }}>{post.red}</span>
                <span style={{ fontSize: 12, color: GRIS, minWidth: 52 }}>{post.fecha}</span>
                <span style={{ fontSize: 14, color: TINTA, flex: 1, minWidth: 160 }}>{post.texto}</span>
                <span style={{ fontSize: 13, color: GRIS }}>❤ {fmt(post.likes)} · 💬 {fmt(post.comentarios)}</span>
              </div>
            ))}
          </div>
        </section>

        {/* 4. Sentiment */}
        <section style={{ marginBottom: 30 }}>
          <Header2 title="Sentiment de reseñas y comentarios" sub={`Análisis de reseñas de Google e Instagram (muestra: ${d.sentiment.muestra})`} ejemplo />
          <div style={{ background: "#fff", border: `1px solid ${BORDE}`, borderRadius: 14, padding: 20 }}>
            <div style={{ display: "flex", height: 30, borderRadius: 8, overflow: "hidden", marginBottom: 14 }}>
              <div style={{ width: `${d.sentiment.positivo}%`, background: "#3f9a52" }} />
              <div style={{ width: `${d.sentiment.neutro}%`, background: "#c9c2b4" }} />
              <div style={{ width: `${d.sentiment.negativo}%`, background: "#cf6b5e" }} />
            </div>
            <div style={{ display: "flex", gap: 24, fontSize: 13, flexWrap: "wrap" }}>
              <span style={{ color: TINTA }}><b style={{ color: "#3f9a52" }}>●</b> Positivo <b>{d.sentiment.positivo}%</b></span>
              <span style={{ color: TINTA }}><b style={{ color: "#a99f8c" }}>●</b> Neutro <b>{d.sentiment.neutro}%</b></span>
              <span style={{ color: TINTA }}><b style={{ color: "#cf6b5e" }}>●</b> Negativo <b>{d.sentiment.negativo}%</b></span>
            </div>
          </div>
        </section>

        {/* 5. Reservas / embudo */}
        <section style={{ marginBottom: 24 }}>
          <Header2 title="Reservas y embudo de conversión" sub="Impresiones → clics → sesiones → reservas (pendiente de GA)" />
          <div style={{ background: "#fff", border: `1px solid ${BORDE}`, borderRadius: 14, padding: 20 }}>
            {d.embudo.map((p, i) => {
              const w = p.val == null ? [100, 70, 45, 25][i] : Math.max(18, (p.val / maxEmbudo) * 100);
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: i < d.embudo.length - 1 ? 10 : 0 }}>
                  <div style={{ width: 190, fontSize: 13 }}>{p.etq}</div>
                  <div style={{ flex: 1, background: "#f0ece4", borderRadius: 6, height: 24 }}>
                    <div style={{ width: `${w}%`, background: ORO, height: "100%", borderRadius: 6, opacity: p.val == null ? 0.35 : 1 }} />
                  </div>
                  <div style={{ width: 90, textAlign: "right", fontSize: 13, fontWeight: 600, color: p.val == null ? GRIS : TINTA }}>
                    {p.val == null ? "pendiente" : fmt(p.val)}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <div style={{ fontSize: 12, color: GRIS, borderTop: `1px solid ${BORDE}`, paddingTop: 14 }}>
          Fuente: informe interno mensual (Booksy) + Google Analytics + redes públicas. Las secciones marcadas
          «datos de ejemplo» y el tráfico web/embudo se activan al conectar el pipeline de datos.
        </div>
      </div>
    </main>
  );
}
