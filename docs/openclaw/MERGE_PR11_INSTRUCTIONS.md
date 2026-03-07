# Cómo mergear el PR #11 (path-guard en main)

**Objetivo:** Integrar en `main` el workflow Path Guard para que el check obligatorio se ejecute en todos los PRs a `main`.

**PR:** [ci: add path-guard workflow (no label bypass, minimal permissions) #11](https://github.com/ccruz0/crypto-2.0/pull/11)

---

## Opción A — Con 1 aprobación (recomendado)

1. Abre **https://github.com/ccruz0/crypto-2.0/pull/11**
2. Si tienes **otra cuenta** con permisos de escritura en el repo:
   - Inicia sesión con esa cuenta, ve al PR #11, pestaña **"Files changed"**
   - Arriba a la derecha: desplegable **"Review changes"** → **"Approve"** → **"Submit review"**
3. Si tienes un **colaborador** con write:
   - En el PR #11, sidebar derecha → **"Reviewers"** → añade a esa persona
   - Esa persona abre el PR, hace **Approve** y envía el review
4. Cuando **todos los checks estén en verde** (o solo fallen los que no sean obligatorios en tu ruleset) y haya **1 approval**:
   - Pulsa **"Merge pull request"** (elige Merge / Squash / Rebase según tu preferencia)
   - Confirma con **"Confirm merge"**
5. Opcional: borra la rama `chore/path-guard-and-permissions` tras el merge.

---

## Opción B — Sin aprobación (relajar ruleset solo para este merge)

1. **Relajar la regla de review (solo un momento):**
   - Repo → **Settings** → **Rules** → **Rulesets**
   - Abre **protect-main-production** → **Edit**
   - Busca **"Require a pull request before merging"** / **"Require approval of the most recent reviewable push"** o **"Require X approving review(s)"**
   - **Desactívalo** (o pon **0** aprobaciones) → **Save**

2. **Mergear el PR #11:**
   - Abre **https://github.com/ccruz0/crypto-2.0/pull/11**
   - Pulsa **"Merge pull request"** → **"Confirm merge"**

3. **Volver a dejar la protección como antes:**
   - **Settings** → **Rules** → **Rulesets** → **protect-main-production** → **Edit**
   - **Activa de nuevo** "Require 1 approving review" (o el valor que tuvieras) → **Save**

4. Opcional: borra la rama `chore/path-guard-and-permissions`.

---

## Después del merge

- En **main** existirá `.github/workflows/path-guard.yml`.
- Los **nuevos PRs a main** ejecutarán el check **Path Guard**.
- Si un PR toca un path protegido (p. ej. `backend/app/api/routes_control.py`), el check **Path Guard** fallará y el merge estará bloqueado hasta que se quiten esos cambios o se resuelva según tu política.

**Comprobar:** Abre cualquier PR a `main` que modifique un path protegido y verifica que el check "Path Guard" aparece en la pestaña **Checks** y falla (rojo).
