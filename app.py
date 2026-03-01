import json
from pathlib import Path
from datetime import date, datetime

import streamlit as st

DATA_DIR = Path("data")
TEMPLATE_FILE = DATA_DIR / "budget_template.json"
BUDGETS_FILE = DATA_DIR / "budgets.json"
EXPENSE_FILE = DATA_DIR / "expenses.json"


# ----------------------------
# Utils fichiers / JSON robustes
# ----------------------------
def ensure_files():
    DATA_DIR.mkdir(exist_ok=True)

    if not TEMPLATE_FILE.exists():
        TEMPLATE_FILE.write_text("{}", encoding="utf-8")

    if not BUDGETS_FILE.exists():
        BUDGETS_FILE.write_text("{}", encoding="utf-8")

    if not EXPENSE_FILE.exists():
        EXPENSE_FILE.write_text("[]", encoding="utf-8")


def _safe_read_json(path: Path, default):
    try:
        txt = path.read_text(encoding="utf-8").strip()
        if not txt:
            return default
        return json.loads(txt)
    except Exception:
        return default


def load_template() -> dict:
    # format: { "Courses": 200.0, "Essence": 120.0, ... }
    data = _safe_read_json(TEMPLATE_FILE, {})
    if not isinstance(data, dict):
        return {}
    # force float
    out = {}
    for k, v in data.items():
        try:
            out[str(k)] = float(v)
        except Exception:
            pass
    return out


def save_template(template: dict) -> None:
    TEMPLATE_FILE.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all_budgets() -> dict:
    # nouveau format attendu: { "YYYY-MM": { "Courses": 200.0, ... }, ... }
    data = _safe_read_json(BUDGETS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_all_budgets(all_budgets: dict) -> None:
    BUDGETS_FILE.write_text(json.dumps(all_budgets, ensure_ascii=False, indent=2), encoding="utf-8")


def load_expenses() -> list[dict]:
    data = _safe_read_json(EXPENSE_FILE, [])
    return data if isinstance(data, list) else []


def save_expenses(expenses: list[dict]) -> None:
    EXPENSE_FILE.write_text(json.dumps(expenses, ensure_ascii=False, indent=2), encoding="utf-8")


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def expenses_for_month(expenses: list[dict], key: str) -> list[dict]:
    return [e for e in expenses if e.get("month") == key]


def totals_by_category(expenses: list[dict]) -> dict:
    totals = {}
    for e in expenses:
        cat = e.get("category")
        if not cat:
            continue
        try:
            totals[cat] = totals.get(cat, 0.0) + float(e.get("amount", 0.0))
        except Exception:
            continue
    return totals


def is_month_key(s: str) -> bool:
    # très simple: "YYYY-MM"
    if not isinstance(s, str) or len(s) != 7:
        return False
    if s[4] != "-":
        return False
    y, m = s.split("-", 1)
    if not (y.isdigit() and m.isdigit()):
        return False
    mi = int(m)
    return 1 <= mi <= 12


def migrate_old_budgets_if_needed(all_budgets: dict, current_key: str) -> dict:
    """
    Ancien format: {"Courses": 200, "Essence": 120}
    Nouveau format: {"2026-02": {"Courses": 200, "Essence": 120}}
    """
    if not all_budgets:
        return all_budgets

    # si les clés ne ressemblent pas à des mois et que les valeurs sont numériques, c'est l'ancien format
    keys_are_months = all(is_month_key(k) for k in all_budgets.keys())
    sample_value = next(iter(all_budgets.values()))

    if (not keys_are_months) and isinstance(sample_value, (int, float)):
        migrated = {current_key: {str(k): float(v) for k, v in all_budgets.items()}}
        save_all_budgets(migrated)
        return migrated

    # si structure partiellement incorrecte, on nettoie: chaque mois doit pointer vers un dict
    cleaned = {}
    changed = False
    for k, v in all_budgets.items():
        if not is_month_key(str(k)):
            continue
        if isinstance(v, dict):
            cleaned[str(k)] = {str(cat): float(val) for cat, val in v.items() if _is_number(val)}
        else:
            changed = True
    if changed:
        save_all_budgets(cleaned)
    return cleaned if cleaned else all_budgets


def _is_number(x) -> bool:
    try:
        float(x)
        return True
    except Exception:
        return False


def make_month_from_template(all_budgets: dict, template: dict, key: str, overwrite: bool) -> dict:
    if (key in all_budgets) and (not overwrite):
        return all_budgets
    all_budgets[key] = {k: float(v) for k, v in template.items()}
    save_all_budgets(all_budgets)
    return all_budgets


# ----------------------------
# App
# ----------------------------
ensure_files()

st.set_page_config(page_title="Budget mensuel", page_icon="💶", layout="centered")
st.title("💶 Suivi de budget mensuel")

template = load_template()
all_budgets = load_all_budgets()
expenses = load_expenses()

today = date.today()
current_key = month_key(today)

# migration si ancien format détecté
all_budgets = migrate_old_budgets_if_needed(all_budgets, current_key)

# liste des mois disponibles: mois courant + ceux des budgets + ceux des dépenses (qui ressemblent à un mois)
months_in_expenses = {e.get("month") for e in expenses if is_month_key(str(e.get("month", "")))}
months_in_budgets = {k for k in all_budgets.keys() if is_month_key(str(k))}
all_months = sorted({current_key} | months_in_expenses | months_in_budgets, reverse=True)

selected_month = st.selectbox("Mois affiché", options=all_months, index=0)
st.caption(f"Mois affiché : {selected_month}")

month_budgets = all_budgets.get(selected_month, {})
if not isinstance(month_budgets, dict):
    month_budgets = {}

tab_dashboard, tab_add, tab_budgets, tab_list = st.tabs(
    ["Tableau de bord", "Ajouter dépense", "Budgets", "Dépenses du mois"]
)

# ----------------------------
# TAB: Dashboard
# ----------------------------
with tab_dashboard:
    exp_month = expenses_for_month(expenses, selected_month)
    totals = totals_by_category(exp_month)

    if not month_budgets:
        st.warning(
            "Aucun budget mensuel créé pour ce mois. "
            "Va dans l'onglet Budgets et clique sur 'Créer budget du mois depuis le template'."
        )

    if month_budgets:
        st.subheader("Reste par catégorie")

        for cat, budget in month_budgets.items():
            budget = float(budget)
            spent = float(totals.get(cat, 0.0))
            remaining = budget - spent

            c1, c2, c3 = st.columns([2, 1, 1])
            c1.write(f"**{cat}**")
            c2.write(f"Dépensé : {spent:.2f} €")

            if remaining < 0:
                c3.error(f"Reste : {remaining:.2f} €")
            elif budget > 0 and remaining < budget * 0.2:
                c3.warning(f"Reste : {remaining:.2f} €")
            else:
                c3.success(f"Reste : {remaining:.2f} €")

        st.divider()
        total_budget = sum(float(v) for v in month_budgets.values())
        total_spent = sum(float(v) for v in totals.values())
        st.write(f"**Total budget** : {total_budget:.2f} €")
        st.write(f"**Total dépensé** : {total_spent:.2f} €")
        st.write(f"**Reste** : {(total_budget - total_spent):.2f} €")
    else:
        st.subheader("Dépenses du mois (même sans budget)")
        if not exp_month:
            st.info("Aucune dépense ce mois-ci.")
        else:
            total_spent = sum(float(e.get("amount", 0.0)) for e in exp_month if _is_number(e.get("amount", 0.0)))
            st.write(f"**Total dépensé** : {total_spent:.2f} €")

# ----------------------------
# TAB: Ajouter dépense
# ----------------------------
with tab_add:
    st.subheader("Ajouter une dépense")

    d = st.date_input("Date", value=today)
    expense_month = month_key(d)

    budgets_for_date = all_budgets.get(expense_month, {})
    if not isinstance(budgets_for_date, dict):
        budgets_for_date = {}

    if not budgets_for_date:
        st.warning(
            f"Aucun budget mensuel n'existe pour {expense_month}. "
            "Crée le budget dans l'onglet Budgets avant d'ajouter une dépense."
        )

    categories = list(budgets_for_date.keys())
    if not categories:
        st.info("Aucune catégorie disponible pour ce mois. Crée le budget du mois depuis le template.")
    else:
        with st.form("add_expense", clear_on_submit=True):
            cat = st.selectbox("Catégorie", options=categories)
            amount = st.number_input("Montant (€)", min_value=0.0, step=0.5, format="%.2f")
            note = st.text_input("Note (optionnel)", max_chars=80)

            ok = st.form_submit_button("Ajouter")
            if ok:
                if amount <= 0:
                    st.error("Le montant doit être supérieur à 0.")
                else:
                    expenses.append(
                        {
                            "id": str(int(datetime.utcnow().timestamp() * 1000)),
                            "date": d.isoformat(),
                            "month": expense_month,
                            "category": cat,
                            "amount": float(amount),
                            "note": note.strip(),
                        }
                    )
                    save_expenses(expenses)
                    st.success("Dépense ajoutée.")
                    st.rerun()

# ----------------------------
# TAB: Budgets (template + mois)
# ----------------------------
with tab_budgets:
    st.subheader("Budgets")

    colA, colB = st.columns(2)

    with colA:
        st.markdown("### Template (budget de base)")
        st.caption("Ce template sert à créer le budget d'un mois. Changer le template ne modifie pas les mois déjà créés.")

        with st.form("add_template_category"):
            new_cat = st.text_input("Catégorie (template)", placeholder="Ex: Courses")
            new_budget = st.number_input("Budget mensuel (template) (€)", min_value=0.0, step=10.0, format="%.2f")
            ok = st.form_submit_button("Ajouter / Mettre à jour le template")

            if ok:
                name = new_cat.strip()
                if not name:
                    st.error("Nom de catégorie requis.")
                else:
                    template[name] = float(new_budget)
                    save_template(template)
                    st.success(f"Template mis à jour : {name}")
                    st.rerun()

        if template:
            st.divider()
            st.write("Catégories du template")
            for cat in list(template.keys()):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**{cat}**")
                c2.write(f"{float(template[cat]):.2f} €")
                if c3.button("Supprimer", key=f"del_tpl_{cat}"):
                    template.pop(cat, None)
                    save_template(template)
                    st.rerun()
        else:
            st.info("Template vide. Ajoute au moins une catégorie.")

    with colB:
        st.markdown(f"### Budget du mois : {selected_month}")
        exists = selected_month in all_budgets

        st.caption(
            "Le budget du mois est une copie figée du template. "
            "Tu peux le modifier sans impacter les autres mois."
        )

        overwrite = st.checkbox("Écraser le budget du mois si déjà créé", value=False)
        create_btn = st.button("Créer budget du mois depuis le template", disabled=(not template))

        if create_btn:
            if not template:
                st.error("Le template est vide.")
            else:
                if exists and (not overwrite):
                    st.warning("Ce mois existe déjà. Coche 'Écraser' si tu veux le recréer depuis le template.")
                else:
                    all_budgets = make_month_from_template(all_budgets, template, selected_month, overwrite=overwrite)
                    st.success("Budget mensuel créé depuis le template.")
                    st.rerun()

        st.divider()

        month_budgets = all_budgets.get(selected_month, {})
        if not isinstance(month_budgets, dict):
            month_budgets = {}

        if not month_budgets:
            st.info("Aucun budget mensuel pour ce mois. Clique sur le bouton pour le créer.")
        else:
            st.write("Modifier le budget mensuel (snapshot)")
            with st.form("edit_month_budget"):
                cat = st.selectbox("Catégorie (mois)", options=list(month_budgets.keys()))
                new_val = st.number_input("Nouveau budget (€)", min_value=0.0, step=10.0, format="%.2f")
                ok = st.form_submit_button("Mettre à jour")

                if ok:
                    month_budgets[cat] = float(new_val)
                    all_budgets[selected_month] = month_budgets
                    save_all_budgets(all_budgets)
                    st.success("Budget mensuel mis à jour.")
                    st.rerun()

            st.divider()
            st.write("Catégories du mois")
            for cat in list(month_budgets.keys()):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**{cat}**")
                c2.write(f"{float(month_budgets[cat]):.2f} €")
                if c3.button("Supprimer", key=f"del_month_{selected_month}_{cat}"):
                    month_budgets.pop(cat, None)
                    all_budgets[selected_month] = month_budgets
                    save_all_budgets(all_budgets)

                    # Supprime aussi les dépenses orphelines pour ce mois
                    expenses = [
                        e for e in expenses
                        if not (e.get("month") == selected_month and e.get("category") == cat)
                    ]
                    save_expenses(expenses)

                    st.rerun()

# ----------------------------
# TAB: Liste des dépenses
# ----------------------------
with tab_list:
    st.subheader("Dépenses du mois")

    exp_month = expenses_for_month(expenses, selected_month)
    if not exp_month:
        st.info("Aucune dépense ce mois-ci.")
    else:
        exp_month = sorted(exp_month, key=lambda x: x.get("date", ""), reverse=True)
        for e in exp_month:
            amount = float(e.get("amount", 0.0)) if _is_number(e.get("amount", 0.0)) else 0.0
            line = f"{e.get('date', '')} | **{e.get('category','')}** | {amount:.2f} €"
            if e.get("note"):
                line += f" | {e['note']}"
            st.write(line)