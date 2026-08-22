## Que hace

El PR #537 monto el panel de agentes en MonitoringTab.tsx, pero ese componente es CODIGO MUERTO: page.tsx:6421 renderiza MonitoringPanel directamente, asi que el panel nunca aparecia. Este PR lo monta donde de verdad se renderiza la pestana Monitoring, en page.tsx: layout de dos columnas (monitoring a la izquierda, AgentActivityPanel a la derecha, sticky, ancho xl:w-96).

## Verificacion

page.tsx parseado con @babel/parser (jsx+typescript): PAGE-PARSE-OK. Sintaxis, no tipos (la imagen de produccion no trae tsc).

## Nota

MonitoringTab.tsx queda como estaba en #537 (con el panel); si algun dia page.tsx delega en el, no habra doble montaje porque solo uno de los dos se renderiza. Limpiar el componente muerto es tarea aparte.
