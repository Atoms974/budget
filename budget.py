import streamlit as st
import pandas as pd
from supabase import create_client, Client
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import re

# ── SUPABASE CONFIGURATION ───────────────────────────────────────────────────
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except Exception as e:
    st.error("⚠️ Clés API manquantes ou incorrectes. Vérifiez vos secrets Streamlit.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def get_regles():
    try:
        res = supabase.table("regles").select("*").order("priorite", desc=True).execute()
        if not res.data:
            return pd.DataFrame(columns=['id', 'mot_cle', 'categorie', 'sous_categorie', 'priorite', 'compte'])
        return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Erreur chargement des règles : {e}")
        return pd.DataFrame(columns=['id', 'mot_cle', 'categorie', 'sous_categorie', 'priorite', 'compte'])

def categoriser(libelle, regles_df, compte=None):
    if regles_df.empty:
        return "À classer", ""
    l = str(libelle).upper()
    for _, row in regles_df.iterrows():
        if str(row['mot_cle']).upper() in l:
            regle_compte = row.get('compte', None)
            if regle_compte and pd.notna(regle_compte) and str(regle_compte).strip() != "":
                if compte != regle_compte:
                    continue
            return row['categorie'], row.get('sous_categorie', '')
    return "À classer", ""

@st.cache_data(ttl=60)
def load_transactions(comptes=None, annees=None, exclure_cat=None):
    try:
        all_data = []
        limit = 1000
        offset = 0
        while True:
            res = supabase.table("transactions").select("*").range(offset, offset + limit - 1).execute()
            if not res.data:
                break
            all_data.extend(res.data)
            if len(res.data) < limit:
                break
            offset += limit

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        df['montant'] = pd.to_numeric(df['montant'], errors='coerce')
        df['date'] = pd.to_datetime(df['date'])
        df['mois_num'] = df['date'].dt.month
        df['annee'] = df['date'].dt.year
        df['mois_label'] = df['date'].dt.strftime('%Y-%m')

        if comptes:
            df = df[df['compte'].isin(comptes)]
        if annees:
            df = df[df['annee'].isin(annees)]
        if exclure_cat:
            df = df[~df['categorie'].isin(exclure_cat)]

        return df
    except Exception as e:
        st.error(f"Erreur chargement transactions : {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_budgets():
    try:
        res = supabase.table("budgets").select("*").execute()
        if not res.data:
            return pd.DataFrame(columns=['id', 'categorie', 'montant_budget', 'mois', 'annee'])
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame(columns=['id', 'categorie', 'montant_budget', 'mois', 'annee'])

@st.cache_data(ttl=60)
def get_alertes():
    try:
        res = supabase.table("alertes").select("*").execute()
        if not res.data:
            return pd.DataFrame(columns=['id', 'categorie', 'seuil', 'actif'])
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame(columns=['id', 'categorie', 'seuil', 'actif'])

def clear_all_cache():
    st.cache_data.clear()

def parse_montant(val):
    """Parse un montant depuis une chaîne, retourne None si invalide."""
    try:
        cleaned = str(val).replace(',', '.').replace(' ', '').replace('\xa0', '').replace('€', '')
        return float(cleaned)
    except Exception:
        return None

def parse_date(val):
    """Parse une date depuis une chaîne, retourne None si invalide."""
    try:
        raw = str(val)
        dfirst = False if "-" in raw else True
        dt = pd.to_datetime(raw, dayfirst=dfirst, errors='coerce')
        if pd.isna(dt):
            return None
        return dt
    except Exception:
        return None

def detecter_recurrents(df, seuil_occurrences=3):
    """Détecte les transactions récurrentes (même libellé normalisé, montant similaire)."""
    if df.empty:
        return pd.DataFrame()
    df_dep = df[df['montant'] < 0].copy()
    df_dep['libelle_norm'] = df_dep['libelle'].str.upper().str.strip()
    df_dep['libelle_norm'] = df_dep['libelle_norm'].apply(lambda x: re.sub(r'\d+', '', x).strip())
    grouped = df_dep.groupby('libelle_norm').agg(
        occurrences=('id', 'count'),
        montant_moyen=('montant', 'mean'),
        derniere_date=('date', 'max'),
        categorie=('categorie', 'first')
    ).reset_index()
    recurrents = grouped[grouped['occurrences'] >= seuil_occurrences].sort_values('occurrences', ascending=False)
    recurrents['montant_moyen'] = recurrents['montant_moyen'].abs()
    return recurrents

# ══════════════════════════════════════════════════════════════════════════════
# VISUALISATIONS
# ══════════════════════════════════════════════════════════════════════════════

def afficher_sankey(df_filtre):
    st.markdown('<div class="section-title">🌊 Flux de trésorerie</div>', unsafe_allow_html=True)
    total_revenus = df_filtre[df_filtre['montant'] > 0]['montant'].sum()
    df_dep = df_filtre[df_filtre['montant'] < 0].groupby('categorie')['montant'].sum().abs().reset_index()

    if total_revenus == 0 or df_dep.empty:
        st.info("Données insuffisantes pour générer le flux.")
        return

    total_depenses = df_dep['montant'].sum()
    df_dep['proportion'] = df_dep['montant'] / total_depenses
    df_principales = df_dep[df_dep['proportion'] >= 0.02].copy()
    df_autres = df_dep[df_dep['proportion'] < 0.02]

    if not df_autres.empty:
        autres_sum = df_autres['montant'].sum()
        df_principales = pd.concat([
            df_principales,
            pd.DataFrame([{'categorie': 'Autres', 'montant': autres_sum, 'proportion': autres_sum / total_depenses}])
        ], ignore_index=True)

    reste = max(0, total_revenus - total_depenses)
    labels = ["Revenus"] + df_principales['categorie'].tolist()
    if reste > 0:
        labels.append("Épargne / Restant")

    sources, targets, values = [], [], []
    for i, (_, row) in enumerate(df_principales.iterrows()):
        sources.append(0)
        targets.append(i + 1)
        values.append(row['montant'])

    if reste > 0:
        sources.append(0)
        targets.append(len(labels) - 1)
        values.append(reste)

    fig = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=labels, color="#4c78a8"),
        link=dict(source=sources, target=targets, value=values, color="rgba(169,172,182,0.4)")
    )])
    fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), font_size=12, height=400)
    st.plotly_chart(fig, use_container_width=True)

def afficher_heatmap(df_filtre):
    st.markdown('<div class="section-title">📅 Intensité par jour</div>', unsafe_allow_html=True)
    df_heat = df_filtre[df_filtre['montant'] < 0].copy()
    if df_heat.empty:
        st.info("Aucune dépense à afficher.")
        return

    jours_ordre = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    day_name_map = {
        'Monday': 'Lundi', 'Tuesday': 'Mardi', 'Wednesday': 'Mercredi',
        'Thursday': 'Jeudi', 'Friday': 'Vendredi', 'Saturday': 'Samedi', 'Sunday': 'Dimanche'
    }
    df_heat['jour_semaine'] = df_heat['date'].dt.day_name().map(day_name_map)
    heatmap_data = df_heat.groupby(['mois_label', 'jour_semaine'])['montant'].sum().abs().reset_index()
    heatmap_pivot = heatmap_data.pivot(index='jour_semaine', columns='mois_label', values='montant').fillna(0)
    heatmap_pivot = heatmap_pivot.reindex(jours_ordre).fillna(0)

    fig = px.imshow(heatmap_pivot, labels=dict(x="Mois", y="Jour", color="Dépenses (€)"),
                    color_continuous_scale='Reds', aspect="auto")
    fig.update_xaxes(side="top")
    fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=400)
    st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# STYLES
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Budget Cloud", layout="wide", page_icon="💳")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.main { padding: 2rem; }
.page-title { font-family: 'DM Serif Display', serif; font-size: 2.4rem; margin-bottom: 0.2rem; }
.page-sub { color: #94a3b8; margin-bottom: 1.5rem; font-size: 0.95rem; }
.section-title { font-family: 'DM Serif Display', serif; font-size: 1.3rem; margin: 1.5rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 1px solid rgba(128,128,128,0.2); }
.kpi-card { background: rgba(255,255,255,0.05); border-radius: 16px; padding: 1.4rem; border: 1px solid rgba(128,128,128,0.2); }
.kpi-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.3rem; }
.kpi-value { font-family: 'DM Serif Display', serif; font-size: 1.8rem; }
.kpi-value.pos { color: #00eb93; }
.kpi-value.neg { color: #ff4b4b; }
.kpi-value.warn { color: #f59e0b; }
.alert-box { background: rgba(245,158,11,0.1); border: 1px solid #f59e0b; border-radius: 8px; padding: 0.75rem 1rem; color: #f59e0b; }
.alert-danger { background: rgba(255,75,75,0.1); border: 1px solid #ff4b4b; border-radius: 8px; padding: 0.75rem 1rem; color: #ff4b4b; margin-bottom: 0.5rem; }
.import-error { background: rgba(255,75,75,0.07); border-left: 3px solid #ff4b4b; padding: 0.4rem 0.8rem; margin: 0.2rem 0; border-radius: 4px; font-size: 0.85rem; }
.import-ok { background: rgba(0,235,147,0.07); border-left: 3px solid #00eb93; padding: 0.4rem 0.8rem; margin: 0.2rem 0; border-radius: 4px; font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("<h2 style='color:white;'>💳 Budget Cloud</h2>", unsafe_allow_html=True)
    page = st.radio("Navigation", [
        "🏠 Tableau de bord",
        "🔍 Journal des données",
        "📥 Importer CSV",
        "📊 Analyse détaillée",
        "📅 Comparaison N/N-1",
        "🔁 Dépenses récurrentes",
        "🎯 Budgets & Alertes",
        "🏷️ Règles de catégories",
        "✏️ Recatégoriser",
    ])

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : TABLEAU DE BORD
# ══════════════════════════════════════════════════════════════════════════════
if page == "🏠 Tableau de bord":
    st.markdown('<div class="page-title">Tableau de bord</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Vue d\'ensemble de vos finances</div>', unsafe_allow_html=True)

    df_all = load_transactions()
    if df_all.empty:
        st.info("Aucune donnée. Commencez par importer un CSV.")
        st.stop()

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        annees_dispo = sorted(df_all['annee'].unique(), reverse=True)
        annee_sel = st.selectbox("Année", annees_dispo)
    with col2:
        comptes_dispo = ["Tous"] + sorted(df_all['compte'].unique().tolist())
        compte_sel = st.selectbox("Compte", comptes_dispo)
    with col3:
        exclure_virements = st.checkbox("Masquer les virements internes", value=True)

    c4, c5 = st.columns(2)
    with c4:
        mois_dispo = sorted(df_all[df_all['annee'] == annee_sel]['mois_label'].unique())
        mois_sel = st.multiselect("Mois (Optionnel)", mois_dispo)
    with c5:
        cats_dispo = sorted(df_all['categorie'].dropna().unique())
        cat_sel = st.multiselect("Catégorie (Optionnel)", cats_dispo)

    df = load_transactions(
        comptes=None if compte_sel == "Tous" else [compte_sel],
        annees=[annee_sel],
        exclure_cat=["Virement interne"] if exclure_virements else None
    )
    if mois_sel:
        df = df[df['mois_label'].isin(mois_sel)]
    if cat_sel:
        df = df[df['categorie'].isin(cat_sel)]

    depenses = df[df['montant'] < 0]['montant'].sum()
    revenus  = df[df['montant'] > 0]['montant'].sum()
    solde    = revenus + depenses
    taux_epargne = (solde / revenus * 100) if revenus != 0 else 0
    nb_a_classer = len(df[(df['categorie'] == "À classer") | (df['categorie'].isna())])

    # Alertes dépassement
    alertes_df = get_alertes()
    if not alertes_df.empty:
        for _, alerte in alertes_df[alertes_df['actif'] == True].iterrows():
            dep_cat = abs(df[(df['categorie'] == alerte['categorie']) & (df['montant'] < 0)]['montant'].sum())
            if dep_cat > alerte['seuil']:
                st.markdown(
                    f'<div class="alert-danger">🚨 Dépassement : <b>{alerte["categorie"]}</b> — '
                    f'{dep_cat:,.0f} € / seuil {alerte["seuil"]:,.0f} €</div>',
                    unsafe_allow_html=True
                )

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Dépenses</div><div class="kpi-value neg">{depenses:,.0f} €</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Revenus</div><div class="kpi-value pos">+{revenus:,.0f} €</div></div>', unsafe_allow_html=True)
    with k3:
        cls = "pos" if solde >= 0 else "neg"
        sign = "+" if solde >= 0 else ""
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Solde net</div><div class="kpi-value {cls}">{sign}{solde:,.0f} €</div></div>', unsafe_allow_html=True)
    with k4:
        cls_e = "pos" if taux_epargne >= 10 else ("warn" if taux_epargne >= 0 else "neg")
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">Taux d\'épargne</div><div class="kpi-value {cls_e}">{taux_epargne:.1f}%</div></div>', unsafe_allow_html=True)
    with k5:
        st.markdown(f'<div class="kpi-card"><div class="kpi-label">À recatégoriser</div><div class="kpi-value warn">{nb_a_classer}</div></div>', unsafe_allow_html=True)

    if nb_a_classer > 0:
        st.markdown(f'<div class="alert-box" style="margin-top:1rem">⚠️ {nb_a_classer} transactions dans "À classer". Allez dans <b>Recatégoriser</b>.</div>', unsafe_allow_html=True)

    # Sunburst avec filtres
    st.markdown('<div class="section-title">Dépenses par catégorie</div>', unsafe_allow_html=True)

    df_dep = df[df['montant'] < 0].copy()
    df_dep['montant_abs'] = df_dep['montant'].abs()
    df_dep['sous_categorie'] = df_dep['sous_categorie'].fillna('Général')
    df_dep.loc[df_dep['sous_categorie'] == '', 'sous_categorie'] = 'Général'

    with st.expander("🎛️ Filtrer le diagramme"):
        fc1, fc2 = st.columns(2)
        with fc1:
            cats_a_masquer = st.multiselect("Masquer catégories", sorted(df_dep['categorie'].dropna().unique()), key="sun_cats")
        with fc2:
            subs_a_masquer = st.multiselect("Masquer sous-catégories", sorted(df_dep['sous_categorie'].dropna().unique()), key="sun_subs")

    df_sun = df_dep.copy()
    if cats_a_masquer:
        df_sun = df_sun[~df_sun['categorie'].isin(cats_a_masquer)]
    if subs_a_masquer:
        df_sun = df_sun[~df_sun['sous_categorie'].isin(subs_a_masquer)]

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        if not df_sun.empty:
            fig_sun = px.sunburst(df_sun, path=['categorie', 'sous_categorie'], values='montant_abs',
                                  color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_sun.update_layout(paper_bgcolor='rgba(0,0,0,0)', margin=dict(t=20, b=20, l=20, r=20))
            fig_sun.update_traces(hovertemplate='<b>%{label}</b><br>%{value:.2f} €<br>%{percentParent:.1%}')
            st.plotly_chart(fig_sun, use_container_width=True, theme="streamlit")
        else:
            st.info("Aucune donnée après filtrage.")

    with col_g2:
        if not df_dep.empty:
            by_cat_sub = df_dep.groupby(['categorie', 'sous_categorie'])['montant_abs'].sum().reset_index()
            top_cats = df_dep.groupby('categorie')['montant_abs'].sum().nlargest(10).index
            by_cat_sub = by_cat_sub[by_cat_sub['categorie'].isin(top_cats)]
            fig_bar = px.bar(by_cat_sub, x='montant_abs', y='categorie', color='sous_categorie',
                             orientation='h', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_bar.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                  yaxis=dict(categoryorder='total ascending'),
                                  legend=dict(orientation="h", yanchor="top", y=-0.2, title_text=''),
                                  margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig_bar, use_container_width=True, theme="streamlit")

    # Top 10 transactions
    st.markdown('<div class="section-title">💸 Top 10 des plus grosses dépenses</div>', unsafe_allow_html=True)
    top10 = df[df['montant'] < 0].nsmallest(10, 'montant')[['date', 'libelle', 'montant', 'categorie', 'compte']]
    if not top10.empty:
        top10['montant'] = top10['montant'].apply(lambda x: f"{x:,.2f} €")
        top10['date'] = top10['date'].dt.strftime('%d/%m/%Y')
        st.dataframe(top10, use_container_width=True, hide_index=True)

    # Solde cumulé
    st.markdown('<div class="section-title">📈 Évolution du solde cumulé</div>', unsafe_allow_html=True)
    df_solde = df.sort_values('date').copy()
    df_solde['solde_cumule'] = df_solde['montant'].cumsum()
    fig_solde = go.Figure()
    fig_solde.add_trace(go.Scatter(
        x=df_solde['date'], y=df_solde['solde_cumule'],
        mode='lines', fill='tozeroy',
        line=dict(color='#4c78a8', width=2),
        fillcolor='rgba(76,120,168,0.15)'
    ))
    fig_solde.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                             margin=dict(t=20, b=20, l=20, r=20), height=250)
    st.plotly_chart(fig_solde, use_container_width=True, theme="streamlit")

    # Évolution mensuelle
    st.markdown('<div class="section-title">Évolution mensuelle</div>', unsafe_allow_html=True)
    monthly = df.groupby('mois_label').agg(
        depenses=('montant', lambda x: x[x < 0].sum()),
        revenus=('montant', lambda x: x[x > 0].sum())
    ).reset_index().sort_values('mois_label')
    monthly['taux_epargne'] = ((monthly['revenus'] + monthly['depenses']) / monthly['revenus'] * 100).fillna(0)

    fig_line = go.Figure()
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['revenus'], name='Revenus', marker_color='#00eb93'))
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['depenses'].abs(), name='Dépenses', marker_color='#ff4b4b'))
    fig_line.add_trace(go.Scatter(x=monthly['mois_label'], y=monthly['taux_epargne'],
                                  name="Taux d'épargne %", mode='lines+markers',
                                  line=dict(color='#f59e0b', width=2), yaxis='y2'))
    fig_line.update_layout(
        barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=30, b=20, l=20, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis2=dict(overlaying='y', side='right', ticksuffix='%', showgrid=False)
    )
    st.plotly_chart(fig_line, use_container_width=True, theme="streamlit")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : JOURNAL DES DONNÉES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Journal des données":
    st.markdown('<div class="page-title">Journal des transactions</div>', unsafe_allow_html=True)

    df = load_transactions()
    if df.empty:
        st.info("La base de données est vide.")
        st.stop()

    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    with c1: search = st.text_input("🔍 Libellé", "")
    with c2: compte_f = st.multiselect("Compte", df['compte'].unique())
    with c3: cat_f = st.multiselect("Catégorie", df['categorie'].unique())
    with c4:
        type_f = st.radio("Type", ["Tout", "Dépenses", "Revenus"], horizontal=True)

    df_filtered = df.copy()
    if search:
        df_filtered = df_filtered[df_filtered['libelle'].str.contains(search, case=False, na=False)]
    if compte_f:
        df_filtered = df_filtered[df_filtered['compte'].isin(compte_f)]
    if cat_f:
        df_filtered = df_filtered[df_filtered['categorie'].isin(cat_f)]
    if type_f == "Dépenses":
        df_filtered = df_filtered[df_filtered['montant'] < 0]
    elif type_f == "Revenus":
        df_filtered = df_filtered[df_filtered['montant'] > 0]

    df_filtered = df_filtered.sort_values('date', ascending=False)

    # Pagination
    PAGE_SIZE = 100
    total = len(df_filtered)
    nb_pages = max(1, (total - 1) // PAGE_SIZE + 1)
    page_num = st.number_input(f"Page (1 à {nb_pages}) — {total} transaction(s)", min_value=1, max_value=nb_pages, value=1, step=1)
    start = (page_num - 1) * PAGE_SIZE
    df_page = df_filtered.iloc[start:start + PAGE_SIZE]

    st.dataframe(df_page[['date', 'compte', 'libelle', 'montant', 'categorie', 'sous_categorie']],
                 use_container_width=True, height=550)

    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        st.download_button("📥 Exporter la sélection (CSV)", df_filtered.to_csv(index=False),
                           "export_budget.csv", "text/csv")
    with col_exp2:
        # Export règles
        regles = get_regles()
        if not regles.empty:
            st.download_button("📥 Exporter les règles (CSV)", regles.to_csv(index=False),
                               "export_regles.csv", "text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : IMPORTER CSV
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📥 Importer CSV":
    st.markdown('<div class="page-title">Importer des transactions</div>', unsafe_allow_html=True)
    compte_nom = st.text_input("Nom du compte (ex: Compte Courant)", "Principal")
    uploaded = st.file_uploader("Choisir un fichier CSV", type="csv")

    if uploaded:
        df_raw = pd.read_csv(uploaded, sep=None, engine='python')
        st.write("Aperçu du fichier :")
        st.dataframe(df_raw.head(5))

        cols = df_raw.columns.tolist()
        c1, c2, c3, c4 = st.columns(4)
        col_d = c1.selectbox("Colonne Date", cols)
        col_l = c2.selectbox("Colonne Libellé", cols)
        col_m = c3.selectbox("Colonne Montant", cols)
        # Solde optionnel
        col_s = c4.selectbox("Colonne Solde (optionnel)", ["— Aucune —"] + cols)

        if st.button("🚀 Lancer l'importation"):
            regles = get_regles()
            to_insert = []
            erreurs = []

            for idx, row in df_raw.iterrows():
                ligne = idx + 2  # numéro ligne lisible
                errs = []

                # Date
                dt = parse_date(row[col_d])
                if dt is None:
                    errs.append(f"date invalide : '{row[col_d]}'")

                # Montant
                mt = parse_montant(row[col_m])
                if mt is None:
                    errs.append(f"montant invalide : '{row[col_m]}'")

                # Solde (optionnel)
                solde_val = None
                if col_s != "— Aucune —":
                    solde_val = parse_montant(row[col_s])
                    if solde_val is None:
                        errs.append(f"solde invalide : '{row[col_s]}'")

                if errs:
                    erreurs.append(f"Ligne {ligne} — {', '.join(errs)}")
                    continue

                cat, sub = categoriser(str(row[col_l]), regles, compte=compte_nom)
                record = {
                    "date": dt.strftime('%Y-%m-%d'),
                    "libelle": str(row[col_l]),
                    "montant": mt,
                    "compte": compte_nom,
                    "categorie": cat,
                    "sous_categorie": sub,
                    "occurrence": 0,
                }
                if solde_val is not None:
                    record["solde"] = solde_val
                to_insert.append(record)

            # Rapport de validation
            if erreurs:
                with st.expander(f"⚠️ {len(erreurs)} ligne(s) ignorée(s) — cliquer pour voir le détail"):
                    for e in erreurs:
                        st.markdown(f'<div class="import-error">❌ {e}</div>', unsafe_allow_html=True)

            if to_insert:
                df_to_upsert = pd.DataFrame(to_insert)
                # Clé de déduplication selon présence du solde
                if 'solde' in df_to_upsert.columns:
                    df_to_upsert['occurrence'] = df_to_upsert.groupby(
                        ['date', 'libelle', 'montant', 'compte', 'solde']
                    ).cumcount()
                    conflict_cols = "date,libelle,montant,compte,solde,occurrence"
                else:
                    df_to_upsert['occurrence'] = df_to_upsert.groupby(
                        ['date', 'libelle', 'montant', 'compte']
                    ).cumcount()
                    conflict_cols = "date,libelle,montant,compte,occurrence"

                final_list = df_to_upsert.to_dict(orient='records')
                try:
                    supabase.table("transactions").upsert(final_list, on_conflict=conflict_cols).execute()
                    st.success(f"✅ {len(final_list)} transactions importées !")
                    if erreurs:
                        st.warning(f"{len(erreurs)} ligne(s) ignorée(s) à cause d'erreurs de format.")
                    clear_all_cache()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur Supabase : {e}")
            else:
                st.error("Aucune transaction valide n'a pu être extraite. Vérifiez le format du fichier.")

    st.divider()
    col_reset1, col_reset2 = st.columns([3, 1])
    with col_reset2:
        if st.button("⚠️ VIDER LA BASE"):
            st.session_state['confirm_reset'] = True

    if st.session_state.get('confirm_reset'):
        st.warning("⚠️ Cette action est irréversible. Toutes les transactions seront supprimées.")
        cc1, cc2 = st.columns(2)
        with cc1:
            if st.button("✅ Confirmer la suppression", type="primary"):
                supabase.table("transactions").delete().neq("id", 0).execute()
                clear_all_cache()
                st.session_state['confirm_reset'] = False
                st.success("Base vidée.")
                st.rerun()
        with cc2:
            if st.button("❌ Annuler"):
                st.session_state['confirm_reset'] = False
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : ANALYSE DÉTAILLÉE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Analyse détaillée":
    st.markdown('<div class="page-title">Analyse détaillée</div>', unsafe_allow_html=True)
    df_all = load_transactions()

    if df_all.empty:
        st.info("Aucune donnée.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        comptes_dispo = sorted(df_all['compte'].dropna().unique().tolist())
        compte_sel = st.multiselect("Comptes", comptes_dispo, default=comptes_dispo)
    with c2:
        annees_dispo = sorted(df_all['annee'].dropna().unique(), reverse=True)
        annee_sel = st.multiselect("Années", annees_dispo, default=[annees_dispo[0]] if annees_dispo else [])
    with c3:
        mois_dispo = sorted(df_all[df_all['annee'].isin(annee_sel)]['mois_label'].dropna().unique()) if annee_sel else []
        mois_sel = st.multiselect("Mois spécifiques", mois_dispo)
    with c4:
        type_sel = st.radio("Type", ["Dépenses", "Revenus", "Tout"], horizontal=True)

    exclure_virements_ana = st.checkbox("Masquer les virements internes", value=True, key="chk_ana")

    df_filtre = df_all.copy()
    if compte_sel: df_filtre = df_filtre[df_filtre['compte'].isin(compte_sel)]
    if annee_sel: df_filtre = df_filtre[df_filtre['annee'].isin(annee_sel)]
    if mois_sel: df_filtre = df_filtre[df_filtre['mois_label'].isin(mois_sel)]
    if exclure_virements_ana:
        df_filtre = df_filtre[df_filtre['categorie'] != "Virement interne"]

    f1, f2 = st.columns(2)
    with f1:
        cats_sel = st.multiselect("Filtrer par catégories", sorted(df_filtre['categorie'].dropna().unique()))
        if cats_sel: df_filtre = df_filtre[df_filtre['categorie'].isin(cats_sel)]
    with f2:
        subs_sel = st.multiselect("Filtrer par sous-catégories", sorted(df_filtre['sous_categorie'].dropna().unique()))
        if subs_sel: df_filtre = df_filtre[df_filtre['sous_categorie'].isin(subs_sel)]

    if type_sel == "Dépenses":
        df_table = df_filtre[df_filtre['montant'] < 0].copy()
    elif type_sel == "Revenus":
        df_table = df_filtre[df_filtre['montant'] > 0].copy()
    else:
        df_table = df_filtre.copy()
    df_table['montant_abs'] = df_table['montant'].abs()

    st.markdown('<div class="section-title">Tableau croisé détaillé</div>', unsafe_allow_html=True)
    if not df_table.empty:
        tcd = df_table.pivot_table(
            index=['categorie', 'sous_categorie'], columns='mois_label',
            values='montant', aggfunc='sum', fill_value=0
        )
        tcd['TOTAL'] = tcd.sum(axis=1)
        color_max = "#2e0101" if type_sel == "Dépenses" else ("#012e01" if type_sel == "Revenus" else "#333333")
        st.dataframe(tcd.style.format("{:.2f} €").highlight_max(axis=0, color=color_max), use_container_width=True)

        st.markdown('### Récapitulatif par catégorie')
        cat_total = df_table.groupby('categorie')['montant'].sum().reset_index()
        cat_total = cat_total.rename(columns={'montant': 'Total (€)'}).sort_values(
            'Total (€)', ascending=type_sel != "Revenus"
        )
        st.dataframe(cat_total.style.format({"Total (€)": "{:.2f} €"}), use_container_width=True)

        st.markdown('<div class="section-title">📊 Évolution mensuelle</div>', unsafe_allow_html=True)
        df_group = df_table.groupby(['annee', 'mois_num', 'mois_label', 'categorie'])['montant_abs'].sum().reset_index()
        df_group = df_group.sort_values(['annee', 'mois_num'])
        totaux_mois = df_group.groupby(['annee', 'mois_num', 'mois_label'])['montant_abs'].sum().reset_index()
        totaux_mois = totaux_mois.rename(columns={'montant_abs': 'total_mois'})
        df_group = pd.merge(df_group, totaux_mois, on=['annee', 'mois_num', 'mois_label'])
        df_group['pourcentage'] = (df_group['montant_abs'] / df_group['total_mois']) * 100

        tab1, tab2, tab3 = st.tabs(["📈 Montants", "📊 Pourcentages", "🔢 Totaux"])
        with tab1:
            fig_m = px.line(df_group, x='mois_label', y='montant_abs', color='categorie', markers=True,
                            labels={'montant_abs': '€', 'mois_label': 'Mois', 'categorie': 'Catégorie'})
            st.plotly_chart(fig_m, use_container_width=True)
        with tab2:
            fig_p = px.area(df_group, x='mois_label', y='pourcentage', color='categorie', markers=True,
                            labels={'pourcentage': '%', 'mois_label': 'Mois', 'categorie': 'Catégorie'})
            fig_p.update_layout(yaxis_ticksuffix="%")
            st.plotly_chart(fig_p, use_container_width=True)
        with tab3:
            nb_cols = min(len(totaux_mois), 4)
            if nb_cols > 0:
                col_totaux = st.columns(nb_cols)
                for i, (_, row) in enumerate(totaux_mois.iterrows()):
                    with col_totaux[i % nb_cols]:
                        st.metric(row['mois_label'], f"{row['total_mois']:,.2f} €")

        col_a, col_b = st.columns(2)
        with col_a:
            afficher_sankey(df_filtre)
        with col_b:
            afficher_heatmap(df_filtre)
    else:
        st.warning("Aucune donnée pour cette sélection.")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : COMPARAISON N / N-1
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📅 Comparaison N/N-1":
    st.markdown('<div class="page-title">Comparaison N / N-1</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Comparez vos dépenses et revenus entre deux années</div>', unsafe_allow_html=True)

    df_all = load_transactions()
    if df_all.empty:
        st.info("Aucune donnée.")
        st.stop()

    annees_dispo = sorted(df_all['annee'].dropna().unique(), reverse=True)
    if len(annees_dispo) < 2:
        st.info("Il faut au moins 2 années de données pour cette comparaison.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    with c1:
        annee_n = st.selectbox("Année N", annees_dispo, index=0)
    with c2:
        annee_n1 = st.selectbox("Année N-1", annees_dispo, index=1)
    with c3:
        type_cmp = st.radio("Type", ["Dépenses", "Revenus"], horizontal=True)

    exclure_vir = st.checkbox("Masquer les virements internes", value=True, key="chk_cmp")

    df_n  = df_all[df_all['annee'] == annee_n].copy()
    df_n1 = df_all[df_all['annee'] == annee_n1].copy()
    if exclure_vir:
        df_n  = df_n[df_n['categorie'] != "Virement interne"]
        df_n1 = df_n1[df_n1['categorie'] != "Virement interne"]

    if type_cmp == "Dépenses":
        df_n  = df_n[df_n['montant'] < 0]
        df_n1 = df_n1[df_n1['montant'] < 0]
    else:
        df_n  = df_n[df_n['montant'] > 0]
        df_n1 = df_n1[df_n1['montant'] > 0]

    # KPIs globaux
    total_n  = df_n['montant'].abs().sum()
    total_n1 = df_n1['montant'].abs().sum()
    delta = total_n - total_n1
    delta_pct = (delta / total_n1 * 100) if total_n1 != 0 else 0

    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric(f"Total {annee_n}", f"{total_n:,.0f} €")
    with k2:
        st.metric(f"Total {annee_n1}", f"{total_n1:,.0f} €")
    with k3:
        st.metric("Variation", f"{delta:+,.0f} €", f"{delta_pct:+.1f}%")

    # Comparaison par catégorie
    st.markdown('<div class="section-title">Par catégorie</div>', unsafe_allow_html=True)

    agg_n  = df_n.groupby('categorie')['montant'].sum().abs().reset_index().rename(columns={'montant': str(annee_n)})
    agg_n1 = df_n1.groupby('categorie')['montant'].sum().abs().reset_index().rename(columns={'montant': str(annee_n1)})
    cmp_df = pd.merge(agg_n, agg_n1, on='categorie', how='outer').fillna(0)
    cmp_df['variation €'] = cmp_df[str(annee_n)] - cmp_df[str(annee_n1)]
    cmp_df['variation %'] = cmp_df.apply(
        lambda r: (r['variation €'] / r[str(annee_n1)] * 100) if r[str(annee_n1)] != 0 else float('inf'), axis=1
    )
    cmp_df = cmp_df.sort_values('variation €', ascending=False)

    st.dataframe(
        cmp_df.style
            .format({str(annee_n): "{:.2f} €", str(annee_n1): "{:.2f} €",
                     'variation €': "{:+.2f} €", 'variation %': "{:+.1f}%"})
            .applymap(lambda v: 'color: #ff4b4b' if isinstance(v, (int, float)) and v > 0 else
                                'color: #00eb93' if isinstance(v, (int, float)) and v < 0 else '',
                      subset=['variation €', 'variation %']),
        use_container_width=True
    )

    # Graphe barres groupées par mois
    st.markdown('<div class="section-title">Évolution mensuelle comparée</div>', unsafe_allow_html=True)

    monthly_n  = df_n.groupby('mois_num')['montant'].sum().abs().reset_index()
    monthly_n['annee'] = str(annee_n)
    monthly_n1 = df_n1.groupby('mois_num')['montant'].sum().abs().reset_index()
    monthly_n1['annee'] = str(annee_n1)
    monthly_cmp = pd.concat([monthly_n, monthly_n1])
    monthly_cmp['mois'] = monthly_cmp['mois_num'].apply(lambda m: datetime(2000, m, 1).strftime('%b'))

    fig_cmp = px.bar(monthly_cmp, x='mois', y='montant', color='annee', barmode='group',
                     color_discrete_map={str(annee_n): '#4c78a8', str(annee_n1): '#94a3b8'},
                     labels={'montant': '€', 'mois': 'Mois'})
    fig_cmp.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                           margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig_cmp, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : DÉPENSES RÉCURRENTES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔁 Dépenses récurrentes":
    st.markdown('<div class="page-title">Dépenses récurrentes</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Détection automatique des abonnements et charges fixes</div>', unsafe_allow_html=True)

    df_all = load_transactions()
    if df_all.empty:
        st.info("Aucune donnée.")
        st.stop()

    c1, c2 = st.columns(2)
    with c1:
        seuil_occ = st.slider("Nombre minimum d'occurrences", 2, 12, 3)
    with c2:
        comptes_r = st.multiselect("Comptes", sorted(df_all['compte'].dropna().unique()), key="rec_comptes")

    df_r = df_all.copy()
    if comptes_r:
        df_r = df_r[df_r['compte'].isin(comptes_r)]

    recurrents = detecter_recurrents(df_r, seuil_occ)

    if recurrents.empty:
        st.info(f"Aucune dépense détectée avec au moins {seuil_occ} occurrences.")
    else:
        total_rec = recurrents['montant_moyen'].sum()
        st.markdown(f"**{len(recurrents)} dépenses récurrentes détectées — coût mensuel estimé : {total_rec:,.2f} €**")

        fig_rec = px.bar(
            recurrents.head(15), x='montant_moyen', y='libelle_norm',
            orientation='h', color='categorie',
            color_discrete_sequence=px.colors.qualitative.Pastel,
            labels={'montant_moyen': 'Montant moyen (€)', 'libelle_norm': 'Libellé'}
        )
        fig_rec.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                               yaxis=dict(categoryorder='total ascending'),
                               margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig_rec, use_container_width=True)

        recurrents_display = recurrents.copy()
        recurrents_display['montant_moyen'] = recurrents_display['montant_moyen'].apply(lambda x: f"{x:,.2f} €")
        recurrents_display['derniere_date'] = recurrents_display['derniere_date'].dt.strftime('%d/%m/%Y')
        recurrents_display.columns = ['Libellé normalisé', 'Occurrences', 'Montant moyen', 'Dernière date', 'Catégorie']
        st.dataframe(recurrents_display, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : BUDGETS & ALERTES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🎯 Budgets & Alertes":
    st.markdown('<div class="page-title">Budgets & Alertes</div>', unsafe_allow_html=True)

    df_all = load_transactions()
    cats_dispo = sorted(df_all['categorie'].dropna().unique().tolist()) if not df_all.empty else []
    mois_actuel = datetime.now().month
    annee_actuelle = datetime.now().year

    tab_budget, tab_alerte = st.tabs(["💰 Budgets", "🚨 Alertes"])

    with tab_budget:
        budgets_df = get_budgets()
        st.caption("Définissez un budget mensuel par catégorie.")

        with st.form("form_budget"):
            bc1, bc2, bc3, bc4 = st.columns([2, 1, 1, 1])
            with bc1: cat_budget = st.selectbox("Catégorie", cats_dispo)
            with bc2: montant_budget = st.number_input("Budget (€)", min_value=0.0, step=10.0)
            with bc3: mois_budget = st.number_input("Mois", 1, 12, mois_actuel)
            with bc4: annee_budget = st.number_input("Année", 2020, 2030, annee_actuelle)

            if st.form_submit_button("💾 Enregistrer", use_container_width=True):
                try:
                    supabase.table("budgets").upsert({
                        "categorie": cat_budget, "montant_budget": montant_budget,
                        "mois": int(mois_budget), "annee": int(annee_budget)
                    }, on_conflict="categorie,mois,annee").execute()
                    st.toast(f"✅ Budget enregistré : {cat_budget} — {montant_budget:.0f} €", icon="✅")
                    clear_all_cache()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")

        if not budgets_df.empty and not df_all.empty:
            st.markdown("#### Comparaison réel / budget")
            bc1, bc2 = st.columns(2)
            with bc1:
                mois_cmp = st.selectbox("Mois", list(range(1, 13)), index=mois_actuel - 1,
                                        format_func=lambda x: datetime(2000, x, 1).strftime('%B'))
            with bc2:
                annee_cmp = st.selectbox("Année", sorted(df_all['annee'].unique(), reverse=True))

            budgets_mois = budgets_df[(budgets_df['mois'] == mois_cmp) & (budgets_df['annee'] == annee_cmp)]
            mois_label = f"{annee_cmp}-{mois_cmp:02d}"
            df_mois = df_all[df_all['mois_label'] == mois_label]

            if budgets_mois.empty:
                st.info("Aucun budget pour cette période.")
            else:
                reels = []
                for _, b in budgets_mois.iterrows():
                    reel = abs(df_mois[(df_mois['categorie'] == b['categorie']) & (df_mois['montant'] < 0)]['montant'].sum())
                    budget = b['montant_budget']
                    pct = (reel / budget * 100) if budget > 0 else 0
                    couleur = "🟢" if pct <= 80 else ("🟡" if pct <= 100 else "🔴")
                    col_b1, col_b2, col_b3 = st.columns([2, 3, 1])
                    with col_b1: st.markdown(f"**{b['categorie']}**")
                    with col_b2: st.progress(min(pct / 100, 1.0))
                    with col_b3: st.markdown(f"{couleur} {reel:.0f} € / {budget:.0f} €")
                    reels.append({'categorie': b['categorie'], 'type': 'Réel', 'montant': reel})
                    reels.append({'categorie': b['categorie'], 'type': 'Budget', 'montant': budget})

                df_cmp = pd.DataFrame(reels)
                fig_cmp = px.bar(df_cmp, x='categorie', y='montant', color='type', barmode='group',
                                 color_discrete_map={'Réel': '#ff4b4b', 'Budget': '#4c78a8'})
                fig_cmp.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                       margin=dict(t=20, b=20, l=20, r=20))
                st.plotly_chart(fig_cmp, use_container_width=True)

            # Export budgets
            st.download_button("📥 Exporter les budgets (CSV)", budgets_df.to_csv(index=False),
                               "export_budgets.csv", "text/csv")

            with st.expander("🗑️ Supprimer un budget"):
                budgets_df['label'] = budgets_df.apply(
                    lambda r: f"{r['categorie']} — {int(r['mois']):02d}/{int(r['annee'])}", axis=1)
                to_del = st.selectbox("Budget à supprimer", budgets_df['label'].tolist())
                if st.button("Supprimer", key="del_budget", type="secondary"):
                    st.session_state['confirm_del_budget'] = to_del

            if st.session_state.get('confirm_del_budget'):
                st.warning(f"Supprimer le budget **{st.session_state['confirm_del_budget']}** ?")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("✅ Confirmer", key="confirm_del_budget_yes"):
                        row_del = budgets_df[budgets_df['label'] == st.session_state['confirm_del_budget']].iloc[0]
                        supabase.table("budgets").delete().eq("id", int(row_del['id'])).execute()
                        st.session_state['confirm_del_budget'] = None
                        clear_all_cache()
                        st.rerun()
                with cc2:
                    if st.button("❌ Annuler", key="cancel_del_budget"):
                        st.session_state['confirm_del_budget'] = None
                        st.rerun()

    with tab_alerte:
        alertes_df = get_alertes()
        st.caption("Une alerte s'affiche sur le tableau de bord si le seuil mensuel est dépassé.")

        with st.form("form_alerte"):
            ac1, ac2 = st.columns(2)
            with ac1: cat_alerte = st.selectbox("Catégorie", cats_dispo)
            with ac2: seuil_alerte = st.number_input("Seuil (€)", min_value=0.0, step=10.0)

            if st.form_submit_button("🚨 Enregistrer l'alerte", use_container_width=True):
                try:
                    supabase.table("alertes").upsert({
                        "categorie": cat_alerte, "seuil": seuil_alerte, "actif": True
                    }, on_conflict="categorie").execute()
                    st.toast(f"✅ Alerte enregistrée : {cat_alerte} — {seuil_alerte:.0f} €", icon="🚨")
                    clear_all_cache()
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {e}")

        if not alertes_df.empty:
            st.dataframe(alertes_df[['categorie', 'seuil', 'actif']], use_container_width=True)
            with st.expander("🗑️ Supprimer une alerte"):
                to_del_a = st.selectbox("Alerte à supprimer", alertes_df['categorie'].tolist())
                if st.button("Supprimer", key="del_alerte", type="secondary"):
                    st.session_state['confirm_del_alerte'] = to_del_a

            if st.session_state.get('confirm_del_alerte'):
                st.warning(f"Supprimer l'alerte **{st.session_state['confirm_del_alerte']}** ?")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("✅ Confirmer", key="confirm_del_alerte_yes"):
                        supabase.table("alertes").delete().eq("categorie", st.session_state['confirm_del_alerte']).execute()
                        st.session_state['confirm_del_alerte'] = None
                        clear_all_cache()
                        st.rerun()
                with cc2:
                    if st.button("❌ Annuler", key="cancel_del_alerte"):
                        st.session_state['confirm_del_alerte'] = None
                        st.rerun()
        else:
            st.info("Aucune alerte configurée.")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : RÈGLES DE CATÉGORIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🏷️ Règles de catégories":
    st.markdown('<div class="page-title">Règles de catégories</div>', unsafe_allow_html=True)

    df_all = load_transactions()
    cats_base = ["Alimentation", "Transport", "Logement", "Santé", "Loisirs", "Revenus", "Virement interne", "Épargne"]
    if not df_all.empty:
        cats_utilisees = [c for c in df_all['categorie'].dropna().unique() if c != "À classer"]
        subs_utilisees = [s for s in df_all['sous_categorie'].dropna().unique() if str(s).strip() != ""]
        comptes_existants = ["Tous les comptes"] + sorted(df_all['compte'].dropna().unique().tolist())
    else:
        cats_utilisees, subs_utilisees, comptes_existants = [], [], ["Tous les comptes"]

    cats_dispo = sorted(set(cats_base + cats_utilisees))
    subs_dispo = sorted(set(subs_utilisees))

    with st.form("add_rule_form"):
        c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 1, 2])
        with c1: mot = st.text_input("Libellé contient", key="rule_keyword")
        with c2:
            cat_sel = st.selectbox("Catégorie", ["Sélectionner..."] + cats_dispo + ["✏️ NOUVELLE"], key="sel_cat")
            cat_new = st.text_input("Nom", placeholder="Nouvelle catégorie...", label_visibility="collapsed", key="input_new_cat")
        with c3:
            sub_sel = st.selectbox("Sous-catégorie", ["(Aucune)"] + subs_dispo + ["✏️ NOUVELLE"], key="sel_sub")
            sub_new = st.text_input("Nom", placeholder="Nouvelle sous-cat...", label_visibility="collapsed", key="input_new_sub")
        with c4:
            prio = st.number_input("Priorité", 0, 100, 10, key="rule_prio")
        with c5:
            compte_regle = st.selectbox("Compte", comptes_existants, key="rule_compte")

        if st.form_submit_button("Enregistrer la règle", use_container_width=True):
            final_cat = cat_new.strip() if cat_sel == "✏️ NOUVELLE" else (cat_sel if cat_sel != "Sélectionner..." else "")
            final_sub = sub_new.strip() if sub_sel == "✏️ NOUVELLE" else (sub_sel if sub_sel != "(Aucune)" else "")
            final_compte = None if compte_regle == "Tous les comptes" else compte_regle

            if mot and final_cat:
                supabase.table("regles").upsert({
                    "mot_cle": mot.upper(), "categorie": final_cat,
                    "sous_categorie": final_sub, "priorite": prio, "compte": final_compte,
                }, on_conflict="mot_cle").execute()
                label_c = f" ({final_compte})" if final_compte else ""
                st.toast(f"✅ {mot.upper()} → {final_cat}{label_c}", icon="✅")
                st.rerun()
            else:
                st.error("⚠️ Mot-clé et catégorie obligatoires.")

    regles = get_regles()
    st.dataframe(regles, use_container_width=True)

    st.divider()
    st.subheader("🔄 Appliquer les règles aux données existantes")

    if st.button("Lancer la mise à jour globale", use_container_width=True):
        regles_df = get_regles()
        df_all = load_transactions()

        if df_all.empty:
            st.warning("Aucune transaction.")
        else:
            updates = {}
            for _, row in df_all.iterrows():
                new_cat, new_sub = categoriser(row['libelle'], regles_df, compte=row.get('compte'))
                if new_cat != "À classer":
                    cat_act = row['categorie'] if pd.notna(row['categorie']) else ""
                    sub_act = row.get('sous_categorie', '') if pd.notna(row.get('sous_categorie', '')) else ""
                    if cat_act != new_cat or sub_act != new_sub:
                        updates[row['id']] = (new_cat, new_sub)

            if updates:
                with st.status(f"Mise à jour de {len(updates)} transactions...", expanded=True) as status:
                    grouped = {}
                    for tid, (cat, sub) in updates.items():
                        grouped.setdefault((cat, sub), []).append(tid)
                    for (cat, sub), ids in grouped.items():
                        for tid in ids:
                            supabase.table("transactions").update(
                                {"categorie": cat, "sous_categorie": sub}
                            ).eq("id", tid).execute()
                    status.update(label=f"✅ {len(updates)} transactions mises à jour.", state="complete")
                clear_all_cache()
                st.rerun()
            else:
                st.info("Toutes les transactions sont déjà à jour.")

    with st.expander("🔀 Fusionner deux catégories"):
        st.caption("Les transactions de la catégorie source seront déplacées vers la cible.")
        if not df_all.empty:
            cats_ex = sorted(df_all['categorie'].dropna().unique().tolist())
            fm1, fm2 = st.columns(2)
            with fm1: cat_src = st.selectbox("Source (à vider)", cats_ex, key="merge_src")
            with fm2: cat_dst = st.selectbox("Cible (à garder)", cats_ex, key="merge_dst")
            if st.button("🔀 Fusionner", type="secondary"):
                if cat_src == cat_dst:
                    st.error("Les deux catégories sont identiques.")
                else:
                    st.session_state['confirm_fusion'] = (cat_src, cat_dst)

            if st.session_state.get('confirm_fusion'):
                src, dst = st.session_state['confirm_fusion']
                st.warning(f"Fusionner **{src}** → **{dst}** ? Cette action est irréversible.")
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("✅ Confirmer la fusion"):
                        df_merge = df_all[df_all['categorie'] == src]
                        for _, r in df_merge.iterrows():
                            supabase.table("transactions").update({"categorie": dst}).eq("id", r['id']).execute()
                        st.session_state['confirm_fusion'] = None
                        st.toast(f"✅ {len(df_merge)} transactions fusionnées.", icon="✅")
                        clear_all_cache()
                        st.rerun()
                with cc2:
                    if st.button("❌ Annuler"):
                        st.session_state['confirm_fusion'] = None
                        st.rerun()

    with st.expander("🗑️ Supprimer une règle"):
        if not regles.empty:
            to_delete = st.selectbox("Règle à supprimer", regles['mot_cle'].tolist())
            if st.button("Supprimer", type="secondary"):
                st.session_state['confirm_del_regle'] = to_delete

        if st.session_state.get('confirm_del_regle'):
            st.warning(f"Supprimer la règle **{st.session_state['confirm_del_regle']}** ?")
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("✅ Confirmer", key="confirm_del_regle_yes"):
                    supabase.table("regles").delete().eq("mot_cle", st.session_state['confirm_del_regle']).execute()
                    st.session_state['confirm_del_regle'] = None
                    st.rerun()
            with cc2:
                if st.button("❌ Annuler", key="cancel_del_regle"):
                    st.session_state['confirm_del_regle'] = None
                    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : RECATÉGORISER
# ══════════════════════════════════════════════════════════════════════════════
elif page == "✏️ Recatégoriser":
    st.markdown('<div class="page-title">Recatégoriser</div>', unsafe_allow_html=True)

    df_all = load_transactions()
    if df_all.empty:
        st.info("Aucune transaction.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    with c1:
        filtre = st.radio("Afficher", ["À classer uniquement", "Toutes"], horizontal=True)
    with c2:
        compte_f = st.selectbox("Compte", ["Tous"] + sorted(df_all['compte'].unique().tolist()))
    with c3:
        search_recat = st.text_input("🔍 Rechercher un libellé", "")

    df_show = df_all.copy()
    if filtre == "À classer uniquement":
        df_show = df_show[(df_show['categorie'] == "À classer") | (df_show['categorie'].isna())]
    if compte_f != "Tous":
        df_show = df_show[df_show['compte'] == compte_f]
    if search_recat:
        df_show = df_show[df_show['libelle'].str.contains(search_recat, case=False, na=False)]

    df_show = df_show.sort_values('date', ascending=False)

    total_show = len(df_show)
    PAGE_SIZE_RECAT = 50
    nb_pages_recat = max(1, (total_show - 1) // PAGE_SIZE_RECAT + 1)
    page_recat = st.number_input(
        f"Page (1 à {nb_pages_recat}) — {total_show} transaction(s)",
        min_value=1, max_value=nb_pages_recat, value=1, step=1
    )
    start_recat = (page_recat - 1) * PAGE_SIZE_RECAT
    df_page_recat = df_show.iloc[start_recat:start_recat + PAGE_SIZE_RECAT]

    if 'extra_cats' not in st.session_state:
        st.session_state.extra_cats = []

    all_cats = sorted(set(
        [c for c in df_all['categorie'].unique() if pd.notna(c)] +
        ["Alimentation", "Transport", "Logement", "Santé", "Loisirs", "Revenus", "Banque", "Épargne"] +
        st.session_state.extra_cats
    ))

    for _, row in df_page_recat.iterrows():
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            with col1:
                st.markdown(f"**{row['date'].strftime('%d/%m/%Y')}** · {row['compte']}")
                st.caption(row['libelle'][:80])
            with col2:
                color = "🔴" if row['montant'] < 0 else "🟢"
                st.markdown(f"{color} **{row['montant']:+,.2f} €**")
                current_cat = row['categorie'] if pd.notna(row['categorie']) else "À classer"
                st.caption(f"Actuel : {current_cat} / {row.get('sous_categorie', '')}")
            with col3:
                cat_options = all_cats + ["✏️ NOUVELLE CATÉGORIE"]
                selected_cat = st.selectbox(
                    "Cat", cat_options,
                    index=all_cats.index(row['categorie']) if row['categorie'] in all_cats else 0,
                    key=f"cat_{row['id']}", label_visibility="collapsed"
                )
                if selected_cat == "✏️ NOUVELLE CATÉGORIE":
                    new_cat = st.text_input(
                        "Nouvelle cat.", placeholder="Nom de la catégorie...",
                        key=f"newcat_{row['id']}", label_visibility="collapsed"
                    )
                else:
                    new_cat = selected_cat
                new_sub = st.text_input(
                    "Sub",
                    value=row.get('sous_categorie', '') if pd.notna(row.get('sous_categorie')) else '',
                    key=f"sub_{row['id']}", label_visibility="collapsed", placeholder="Sous-catégorie"
                )
            with col4:
                if st.button("💾", key=f"save_{row['id']}"):
                    if new_cat and new_cat not in st.session_state.extra_cats:
                        st.session_state.extra_cats.append(new_cat)
                    supabase.table("transactions").update(
                        {"categorie": new_cat, "sous_categorie": new_sub}
                    ).eq("id", row['id']).execute()
                    clear_all_cache()
                    st.toast("✅ Sauvegardé", icon="✅")
                    st.rerun()
            st.divider()
