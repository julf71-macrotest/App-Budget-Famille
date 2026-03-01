import time
from datetime import date, datetime

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


# =========================
# Google Sheets connection
# =========================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


@st.cache_resource
def gs_client():
    if "google" not in st.secrets or "service_account" not in st.secrets["google"]:
        raise RuntimeError("Secrets Google manquants. Configure [google.service_account] dans Streamlit Secrets.")
    creds_dict = dict(st.secrets["google"]["service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def open_sheet():
    sheet_id = st.secrets["google"]["sheet_id"]
    return gs_client().open_by_key(sheet_id)


def ws(name: str):
    return open_sheet().worksheet(name)


# =========================
# Helpers
# =========================
def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _to_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, str):
            x = x.replace(",", ".").strip()
        return float(x)
    except Exception:
        return default


def _now_id() -> str:
    return str(int(datetime.utcnow().timestamp() * 1000))


def _cache_bust():
    # Invalidate cached reads after write operations
    st.cache_data.clear()


# =========================
# Sheet data access
# =========================
@st.cache_data(ttl=120)
def load_template() -> dict:
    rows = ws("template").get_all_records()
    out = {}
    for r in rows:
        cat = str(r.get("category", "")).strip()
        if not cat:
            continue
        out[cat] = _to_float(r.get("budget"), 0.0)
    return out


def upsert_template(cat: str, budget: float) -> None:
    w = ws("template")
    values = w.get_all_values()
    # values[0] is header row
    target_row = None
    for i in range(1, len(values)):
        if len(values[i]) > 0 and values[i][0].strip() == cat:
            target_row = i + 1  # 1-indexed
            break
    if target_row:
        w.update_cell(target_row, 2, float(budget))
    else:
        w.append_row([cat, float(budget)], value_input_option="USER_ENTERED")
    _cache_bust()


def delete_template(cat: str) -> None:
    w = ws("template")
    values = w.get_all_values()
    for i in range(1, len(values)):
        if len(values[i]) > 0 and values[i][0].strip() == cat:
            w.delete_rows(i + 1)
            break
    _cache_bust()


@st.cache_data(ttl=120)
def load_budgets_all() -> dict:
    rows = ws("budgets").get_all_records()
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        m = str(r.get("month", "")).strip()
        cat = str(r.get("category", "")).strip()
        if not m or not cat:
            continue
        out.setdefault(m, {})
        out[m][cat] = _to_float(r.get("budget"), 0.0)
    return out


def upsert_budget(month: str, cat: str, budget: float) -> None:
    w = ws("budgets")
    values = w.get_all_values()
    # header: month, category, budget
    target_row = None
    for i in range(1, len(values)):
        row = values[i]
        if len(row) >= 2 and row[0].strip() == month and row[1].strip() == cat:
            target_row = i + 1
            break

    if target_row:
        w.update_cell(target_row, 3, float(budget))
    else:
        w.append_row([month, cat, float(budget)], value_input_option="USER_ENTERED")
    _cache_bust()


def delete_budget(month: str, cat: str) -> None:
    w = ws("budgets")
    values = w.get_all_values()
    for i in range(1, len(values)):
        row = values[i]
        if len(row) >= 2 and row[0].strip() == month and row[1].strip() == cat:
            w.delete_rows(i + 1)
            break
    _cache_bust()


def delete_month_budgets(month: str) -> None:
    w = ws("budgets")
    values = w.get_all_values()
    # delete from bottom to top to keep indexes valid
    to_delete = []
    for i in range(1, len(values)):
        row = values[i]
        if len(row) >= 1 and row[0].strip() == month:
            to_delete.append(i + 1)
    for r in reversed(to_delete):
        w.delete_rows(r)
    _cache_bust()


@st.cache_data(ttl=120)
def load_expenses_all() -> list[dict]:
    rows = ws("expenses").get_all_records()
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r.get("id", "")).strip(),
                "date": str(r.get("date", "")).strip(),
                "month": str(r.get("month", "")).strip(),
                "category": str(r.get("category", "")).strip(),
                "amount": _to_float(r.get("amount"), 0.0),
                "note": str(r.get("note", "")).strip(),
            }
        )
    return out


def append_expense(d: date, cat: str, amount: float, note: str) -> None:
    w = ws("expenses")
    m = month_key(d)
    w.append_row(
        [_now_id(), d.isoformat(), m, cat, float(amount), note.strip()],
        value_input_option="USER_ENTERED",
    )
    _cache_bust()


def delete_expenses_for_month_category(month: str, cat: str) -> None:
    w = ws("expenses")
    values = w.get_all_values()
    # header: id,date,month,category,amount,note
    to_delete = []
    for i in range(1, len(values)):
        row = values[i]
        if len(row) >= 4 and row[2].strip() == month and row[3].strip() == cat:
            to_delete.append(i + 1)
    for r in reversed(to_delete):
        w.delete_rows(r)
    _cache_bust()


def expenses_for_month(expenses: list[dict], month: str) -> list[dict]:
    return [e for e in expenses if e.get("month") == month]


def totals_by_category(expenses: list[dict]) -> dict:
    totals = {}
    for e in expenses:
        cat = e.get("category")
        if not cat:
            continue
        totals[cat] = totals.get(cat, 0.0) + _to_float(e.get("amount"), 0.0)
    return totals


# =========================
# UI
# =========================
st.set_page_config(page_title="Budget mensuel", page_icon="💶", layout="centered")
st.title("💶 Suivi de budget mensuel")

try:
    template = load_template()
    all_budgets = load_budgets_all()
    expenses = load_expenses_all()
except Exception as e:
    st.error("Connexion Google Sheets impossible. Vérifie les Secrets et le partage du Google Sheet avec le service account.")
    st.exception(e)
    st.stop()

today = date.today()
current_month = month_key(today)

months = set(all_budgets.keys())
for e in expenses:
    if e.get("month"):
        months.add(e["month"])
months.add(current_month)

months_list = sorted(months, reverse=True)
selected_month = st.selectbox("Mois affiché", options=months_list, index=0)
st.caption(f"Mois affiché : {selected_month}")

month_budgets = all_budgets.get(selected_month, {})

tab_dashboard, tab_add, tab_budgets, tab_list = st.tabs(
    ["Tableau de bord", "Ajouter dépense", "Budgets", "Dépenses du mois"]
)

# -------- Dashboard
with tab_dashboard:
    exp_month = expenses_for_month(expenses, selected_month)
    totals = totals_by_category(exp_month)

    if not month_budgets:
        st.warning(
            "Aucun budget mensuel pour ce mois. "
            "Va dans l'onglet Budgets et clique sur 'Créer budget du mois depuis le template'."
        )

    if month_budgets:
        st.subheader("Reste par catégorie")

        for cat, budget in month_budgets.items():
            budget = _to_float(budget, 0.0)
            spent = _to_float(totals.get(cat), 0.0)
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
        total_budget = sum(_to_float(v) for v in month_budgets.values())
        total_spent = sum(_to_float(v) for v in totals.values())
        st.write(f"**Total budget** : {total_budget:.2f} €")
        st.write(f"**Total dépensé** : {total_spent:.2f} €")
        st.write(f"**Reste** : {(total_budget - total_spent):.2f} €")

# -------- Add expense
with tab_add:
    st.subheader("Ajouter une dépense")

    d = st.date_input("Date", value=today)
    exp_month_key = month_key(d)

    month_b = all_budgets.get(exp_month_key, {})
    if not month_b:
        st.warning(
            f"Aucun budget mensuel n'existe pour {exp_month_key}. "
            "Va dans l'onglet Budgets et clique sur 'Créer budget du mois depuis le template' avant d'ajouter une dépense."
        )
    else:
        categories = list(month_b.keys())
        if not categories:
            st.info("Aucune catégorie dans le budget de ce mois.")
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
                        append_expense(d, cat, float(amount), note)
                        st.success("Dépense ajoutée.")
                        st.rerun()

# -------- Budgets
with tab_budgets:
    st.subheader("Budgets")

    colA, colB = st.columns(2)

    with colA:
        st.markdown("### Template (budget de base)")
        st.caption("Changer le template ne modifie pas les mois déjà créés.")

        with st.form("add_template_category"):
            new_cat = st.text_input("Catégorie (template)", placeholder="Ex: Courses")
            new_budget = st.number_input("Budget mensuel (template) (€)", min_value=0.0, step=10.0, format="%.2f")
            ok = st.form_submit_button("Ajouter / Mettre à jour le template")
            if ok:
                name = new_cat.strip()
                if not name:
                    st.error("Nom de catégorie requis.")
                else:
                    upsert_template(name, float(new_budget))
                    st.success(f"Template mis à jour : {name}")
                    st.rerun()

        template = load_template()
        if template:
            st.divider()
            st.write("Catégories du template")
            for cat in list(template.keys()):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**{cat}**")
                c2.write(f"{_to_float(template[cat]):.2f} €")
                if c3.button("Supprimer", key=f"del_tpl_{cat}"):
                    delete_template(cat)
                    st.rerun()
        else:
            st.info("Template vide. Ajoute au moins une catégorie.")

    with colB:
        st.markdown(f"### Budget du mois : {selected_month}")
        st.caption("Le budget mensuel est une copie figée du template. Tu peux ensuite le modifier.")

        template = load_template()
        all_budgets = load_budgets_all()
        exists = selected_month in all_budgets

        overwrite = st.checkbox("Écraser le budget du mois si déjà créé", value=False)
        create_btn = st.button("Créer budget du mois depuis le template", disabled=(not template))

        if create_btn:
            if not template:
                st.error("Template vide.")
            else:
                if exists and not overwrite:
                    st.warning("Ce mois existe déjà. Coche Écraser si tu veux le recréer depuis le template.")
                else:
                    if overwrite and exists:
                        delete_month_budgets(selected_month)
                    for cat, bud in template.items():
                        upsert_budget(selected_month, cat, _to_float(bud))
                    st.success("Budget mensuel créé depuis le template.")
                    st.rerun()

        st.divider()
        all_budgets = load_budgets_all()
        month_budgets = all_budgets.get(selected_month, {})

        if not month_budgets:
            st.info("Aucun budget mensuel pour ce mois. Clique sur le bouton pour le créer.")
        else:
            st.write("Modifier le budget mensuel (snapshot)")
            with st.form("edit_month_budget"):
                cat = st.selectbox("Catégorie (mois)", options=list(month_budgets.keys()))

                current_val = float(month_budgets.get(cat, 0.0))

                new_val = st.number_input(
                    "Nouveau budget (€)",
                    value=current_val,
                    min_value=0.0,
                    step=10.0,
                    format="%.2f"
                )

                ok = st.form_submit_button("Mettre à jour")

                if ok:
                    upsert_budget(selected_month, cat, float(new_val))
                    st.success("Budget mensuel mis à jour.")
                    st.rerun()

            st.divider()
            st.write("Catégories du mois")
            for cat in list(month_budgets.keys()):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**{cat}**")
                c2.write(f"{_to_float(month_budgets[cat]):.2f} €")

                if c3.button("Supprimer", key=f"del_month_{selected_month}_{cat}"):
                    delete_budget(selected_month, cat)
                    delete_expenses_for_month_category(selected_month, cat)
                    st.rerun()

# -------- Expense list
with tab_list:
    st.subheader("Dépenses du mois")
    exp_month = expenses_for_month(expenses, selected_month)

    if not exp_month:
        st.info("Aucune dépense ce mois-ci.")
    else:
        exp_month = sorted(exp_month, key=lambda x: x.get("date", ""), reverse=True)
        for e in exp_month:
            amount = _to_float(e.get("amount"), 0.0)
            line = f"{e.get('date','')} | **{e.get('category','')}** | {amount:.2f} €"
            if e.get("note"):
                line += f" | {e['note']}"
            st.write(line)




