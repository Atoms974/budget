import streamlit as st
import pandas as pd
from supabase import create_client, Client
import plotly.express as px
import plotly.graph_objects as go

# ── SUPABASE CONFIGURATION ───────────────────────────────────────────────────
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except Exception as e:
    st.error("⚠️ Clés API manquantes ou incorrectes. Vérifiez vos secrets Streamlit.")
    st.stop()

# ── DATA LOGIC ───────────────────────────────────────────────────────────────
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

def load_transactions(comptes=None, annees=None, exclure_cat=None):
    try:
        res = supabase.table("transactions").select("*").execute()
        if not res.data:
            return pd.DataFrame()

        df = pd.DataFrame(res.data)

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

# ── FONCTIONS D'ANALYSE ───────────────────────────────────────────────────────
def afficher_sankey(df_filtre):
    st.markdown('<div class="section-title">🌊 Flux de trésorerie</div>', unsafe_allow_html=True)

    total_revenus = df_filtre[df_filtre['montant'] > 0]['montant'].sum()
    df_dep = df_filtre[df_filtre['montant'] < 0].groupby('categorie')['montant'].sum().abs().reset_index()

    if total_revenus == 0 or df_dep.empty:
        st.info("Données insuffisantes pour générer le flux (nécessite revenus et dépenses).")
        return

    total_depenses = df_dep['montant'].sum()
    df_dep['proportion'] = df_dep['montant'] / total_depenses

    df_principales = df_dep[df_dep['proportion'] >= 0.02].copy()
    df_autres = df_dep[df_dep['proportion'] < 0.02]

    if not df_autres.empty:
        autres_sum = df_autres['montant'].sum()
        df_principales = pd.concat(
            [df_principales, pd.DataFrame([{'categorie': 'Autres Dépenses', 'montant': autres_sum, 'proportion': autres_sum / total_depenses}])],
            ignore_index=True
        )

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
        link=dict(source=sources, target=targets, value=values, color="rgba(169, 172, 182, 0.4)")
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

    fig = px.imshow(
        heatmap_pivot,
        labels=dict(x="Mois", y="Jour", color="Dépenses (€)"),
        color_continuous_scale='Reds',
        aspect="auto"
    )
    fig.update_xaxes(side="top")
    fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=400)
    st.plotly_chart(fig, use_container_width=True)

# ── STYLES ET INTERFACE ──────────────────────────────────────────────────────
st.set_page_config(page_title="Budget Cloud", layout="wide", page_icon="💳")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.main { padding: 2rem; }
.page-title { font-family: 'DM Serif Display', serif; font-size: 2.4rem; margin-bottom: 0.2rem; }
.section-title { font-family: 'DM Serif Display', serif; font-size: 1.3rem; margin: 1.5rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 1px solid rgba(128,128,128,0.2); }
.kpi-card { background: rgba(255, 255, 255, 0.05); border-radius: 16px; padding: 1.4rem; border: 1px solid rgba(128,128,128,0.2); }
.kpi-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #94a3b8; }
.kpi-value { font-family: 'DM Serif Display', serif; font-size: 1.8rem; }
</style>
""", unsafe_allow_html=True)

# ── SIDEBAR NAV ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<h2 style='color:white;'>💳 Budget Cloud</h2>", unsafe_allow_html=True)
    page = st.radio("Navigation", [
        "🏠 Tableau de bord",
        "🔍 Journal des données",
        "📥 Importer CSV",
        "📊 Analyse détaillée",
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
    nb_a_classer = len(df[(df['categorie'] == "À classer") | (df['categorie'].isna())])

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Dépenses filtrées</div>
            <div class="kpi-value neg">{depenses:,.0f} €</div>
        </div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Revenus filtrés</div>
            <div class="kpi-value pos">+{revenus:,.0f} €</div>
        </div>""", unsafe_allow_html=True)
    with k3:
        col = "pos" if solde >= 0 else "neg"
        sign = "+" if solde >= 0 else ""
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Solde net</div>
            <div class="kpi-value {col}">{sign}{solde:,.0f} €</div>
        </div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">À recatégoriser</div>
            <div class="kpi-value" style="color:#f59e0b">{nb_a_classer}</div>
        </div>""", unsafe_allow_html=True)

    if nb_a_classer > 0:
        st.markdown(f'<div class="alert-box" style="margin-top:1rem">⚠️ {nb_a_classer} transactions sont dans "À classer". Allez dans <b>Recatégoriser</b>.</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">Dépenses par catégorie et sous-catégorie</div>', unsafe_allow_html=True)

    df_dep = df[df['montant'] < 0].copy()
    df_dep['montant_abs'] = df_dep['montant'].abs()
    df_dep['sous_categorie'] = df_dep['sous_categorie'].fillna('Général')
    df_dep.loc[df_dep['sous_categorie'] == '', 'sous_categorie'] = 'Général'

    # Filtres d'exclusion pour le sunburst
    with st.expander("🎛️ Filtrer le diagramme"):
        fc1, fc2 = st.columns(2)
        with fc1:
            cats_a_masquer = st.multiselect(
                "Masquer ces catégories",
                sorted(df_dep['categorie'].dropna().unique()),
                key="sun_cats_masquer"
            )
        with fc2:
            subs_a_masquer = st.multiselect(
                "Masquer ces sous-catégories",
                sorted(df_dep['sous_categorie'].dropna().unique()),
                key="sun_subs_masquer"
            )

    df_sun = df_dep.copy()
    if cats_a_masquer:
        df_sun = df_sun[~df_sun['categorie'].isin(cats_a_masquer)]
    if subs_a_masquer:
        df_sun = df_sun[~df_sun['sous_categorie'].isin(subs_a_masquer)]

    col_g1, col_g2 = st.columns([1, 1])
    with col_g1:
        if not df_sun.empty:
            fig_sun = px.sunburst(
                df_sun, path=['categorie', 'sous_categorie'], values='montant_abs',
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_sun.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=20, b=20, l=20, r=20))
            fig_sun.update_traces(hovertemplate='<b>%{label}</b><br>Montant: %{value:.2f} €<br>Part: %{percentParent:.1%}')
            st.plotly_chart(fig_sun, use_container_width=True, theme="streamlit")
        else:
            st.info("Aucune donnée après filtrage.")

    with col_g2:
        if not df_dep.empty:
            by_cat_sub = df_dep.groupby(['categorie', 'sous_categorie'])['montant_abs'].sum().reset_index()
            top_10_cats = df_dep.groupby('categorie')['montant_abs'].sum().nlargest(10).index
            by_cat_sub = by_cat_sub[by_cat_sub['categorie'].isin(top_10_cats)]
            fig_bar = px.bar(
                by_cat_sub, x='montant_abs', y='categorie', color='sous_categorie',
                orientation='h', color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_bar.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                yaxis=dict(categoryorder='total ascending'),
                showlegend=True, legend=dict(orientation="h", yanchor="top", y=-0.2, title_text=''),
                margin=dict(t=20, b=20, l=20, r=20)
            )
            st.plotly_chart(fig_bar, use_container_width=True, theme="streamlit")

    st.markdown('<div class="section-title">Évolution mensuelle globale</div>', unsafe_allow_html=True)

    monthly = df.groupby('mois_label').agg(
        depenses=('montant', lambda x: x[x < 0].sum()),
        revenus=('montant', lambda x: x[x > 0].sum())
    ).reset_index().sort_values('mois_label')

    fig_line = go.Figure()
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['revenus'], name='Revenus', marker_color='#00eb93'))
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['depenses'].abs(), name='Dépenses', marker_color='#ff4b4b'))
    fig_line.update_layout(
        barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(t=30, b=20, l=20, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_line, use_container_width=True, theme="streamlit")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : JOURNAL DES DONNÉES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Journal des données":
    st.markdown('<div class="page-title">Journal des transactions</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Vue brute de la base de données</div>', unsafe_allow_html=True)

    df = load_transactions()

    if df.empty:
        st.info("La base de données est vide.")
    else:
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1: search = st.text_input("🔍 Rechercher un libellé", "")
        with c2: compte_f = st.multiselect("Compte", df['compte'].unique())
        with c3: cat_f = st.multiselect("Catégorie", df['categorie'].unique())

        df_filtered = df.copy()
        if search: df_filtered = df_filtered[df_filtered['libelle'].str.contains(search, case=False, na=False)]
        if compte_f: df_filtered = df_filtered[df_filtered['compte'].isin(compte_f)]
        if cat_f: df_filtered = df_filtered[df_filtered['categorie'].isin(cat_f)]

        st.dataframe(df_filtered[['date', 'compte', 'libelle', 'montant', 'categorie', 'sous_categorie']],
                     use_container_width=True, height=600)
        st.download_button("📥 Exporter en CSV", df_filtered.to_csv(index=False), "export_budget.csv", "text/csv")

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
        st.dataframe(df_raw.head(3))

        cols = df_raw.columns.tolist()
        c1, c2, c3, c4 = st.columns(4)
        col_d = c1.selectbox("Date", cols)
        col_l = c2.selectbox("Libellé", cols)
        col_m = c3.selectbox("Montant", cols)
        col_s = c4.selectbox("Solde", cols)

        if st.button("🚀 Lancer l'importation"):
            regles = get_regles()
            to_insert = []
            for _, row in df_raw.iterrows():
                try:
                    raw_date = str(row[col_d])
                    dfirst = False if "-" in raw_date else True
                    dt = pd.to_datetime(raw_date, dayfirst=dfirst, errors='coerce')
                    if pd.isna(dt):
                        continue

                    m_raw = str(row[col_m]).replace(',', '.').replace(' ', '').replace('\xa0', '')
                    mt = float(m_raw)

                    s_raw = str(row[col_s]).replace(',', '.').replace(' ', '').replace('\xa0', '')
                    solde_val = float(s_raw)

                    # On passe le compte à categoriser() pour filtrage par compte
                    cat, sub = categoriser(row[col_l], regles, compte=compte_nom)

                    to_insert.append({
                        "date": dt.strftime('%Y-%m-%d'),
                        "libelle": str(row[col_l]),
                        "montant": mt,
                        "solde": solde_val,
                        "compte": compte_nom,
                        "categorie": cat,
                        "sous_categorie": sub,
                        "occurrence": 0,
                    })
                except Exception:
                    continue

            if to_insert:
                df_to_upsert = pd.DataFrame(to_insert)
                df_to_upsert['occurrence'] = df_to_upsert.groupby(
                    ['date', 'libelle', 'montant', 'compte', 'solde']
                ).cumcount()

                final_list = df_to_upsert.to_dict(orient='records')
                try:
                    supabase.table("transactions").upsert(
                        final_list,
                        on_conflict="date,libelle,montant,compte,solde,occurrence"
                    ).execute()
                    st.success(f"Données envoyées ! ({len(final_list)} transactions)")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur Supabase : {e}")
            else:
                st.warning("Aucune transaction valide n'a pu être extraite du fichier.")

    st.divider()
    if st.button("⚠️ VIDER TOUTE LA BASE (RESET)"):
        supabase.table("transactions").delete().neq("id", 0).execute()
        st.warning("Base vidée.")
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
        cats_dispo = sorted(df_filtre['categorie'].dropna().unique())
        cats_sel = st.multiselect("Filtrer par catégories", cats_dispo)
        if cats_sel: df_filtre = df_filtre[df_filtre['categorie'].isin(cats_sel)]
    with f2:
        subs_dispo = sorted(df_filtre['sous_categorie'].dropna().unique())
        subs_sel = st.multiselect("Filtrer par sous-catégories", subs_dispo)
        if subs_sel: df_filtre = df_filtre[df_filtre['sous_categorie'].isin(subs_sel)]

    if type_sel == "Dépenses":
        df_table = df_filtre[df_filtre['montant'] < 0].copy()
        df_table['montant_abs'] = df_table['montant'].abs()
    elif type_sel == "Revenus":
        df_table = df_filtre[df_filtre['montant'] > 0].copy()
        df_table['montant_abs'] = df_table['montant'].abs()
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

        st.markdown('### Récapitulatif global par catégorie')
        cat_total = df_table.groupby('categorie')['montant'].sum().reset_index()
        cat_total = cat_total.rename(columns={'montant': 'Total (€)'}).sort_values(
            'Total (€)', ascending=False if type_sel == "Revenus" else True
        )
        st.dataframe(cat_total.style.format({"Total (€)": "{:.2f} €"}), use_container_width=True)

        st.markdown('<div class="section-title">📊 Évolution mensuelle croisée</div>', unsafe_allow_html=True)

        df_group = df_table.groupby(['annee', 'mois_num', 'mois_label', 'categorie'])['montant_abs'].sum().reset_index()
        df_group = df_group.sort_values(by=['annee', 'mois_num'])

        totaux_mois = df_group.groupby(['annee', 'mois_num', 'mois_label'])['montant_abs'].sum().reset_index()
        totaux_mois = totaux_mois.rename(columns={'montant_abs': 'total_mois'})

        df_group = pd.merge(df_group, totaux_mois, on=['annee', 'mois_num', 'mois_label'])
        df_group['pourcentage'] = (df_group['montant_abs'] / df_group['total_mois']) * 100

        tab1, tab2, tab3 = st.tabs(["📈 Évolution des Montants", "📊 Évolution des Pourcentages", "🔢 Totaux Mensuels"])

        with tab1:
            fig_montants = px.line(
                df_group, x='mois_label', y='montant_abs', color='categorie', markers=True,
                title=f"Évolution des {type_sel.lower()} par mois",
                labels={'montant_abs': 'Montant (€)', 'mois_label': 'Mois', 'categorie': 'Catégorie'}
            )
            st.plotly_chart(fig_montants, use_container_width=True)

        with tab2:
            fig_pct = px.area(
                df_group, x='mois_label', y='pourcentage', color='categorie', markers=True,
                title="Évolution de la proportion de chaque catégorie (%)",
                labels={'pourcentage': 'Part du total (%)', 'mois_label': 'Mois', 'categorie': 'Catégorie'}
            )
            fig_pct.update_layout(yaxis_ticksuffix="%")
            st.plotly_chart(fig_pct, use_container_width=True)

        with tab3:
            nb_cols = min(len(totaux_mois), 4)
            if nb_cols > 0:
                col_totaux = st.columns(nb_cols)
                for i, (_, row) in enumerate(totaux_mois.iterrows()):
                    with col_totaux[i % nb_cols]:
                        st.metric(label=f"{row['mois_label']}", value=f"{row['total_mois']:,.2f} €")

        col_a, col_b = st.columns(2)
        with col_a:
            afficher_sankey(df_filtre)
        with col_b:
            afficher_heatmap(df_filtre)

    else:
        st.warning("Aucune donnée pour cette sélection.")

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
        cats_utilisees = []
        subs_utilisees = []
        comptes_existants = ["Tous les comptes"]

    cats_dispo = sorted(set(cats_base + cats_utilisees))
    subs_dispo = sorted(set(subs_utilisees))

    with st.form("add_rule_form"):
        c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 1, 2])
        with c1:
            mot = st.text_input("Si le libellé contient", key="rule_keyword")
        with c2:
            cat_sel = st.selectbox("Catégorie", ["Sélectionner..."] + cats_dispo + ["✏️ NOUVELLE CATÉGORIE"], key="sel_cat")
            cat_new = st.text_input("Nom cat.", placeholder="Nouvelle catégorie...", label_visibility="collapsed", key="input_new_cat")
        with c3:
            sub_sel = st.selectbox("Sous-catégorie", ["(Aucune)"] + subs_dispo + ["✏️ NOUVELLE SOUS-CAT."], key="sel_sub")
            sub_new = st.text_input("Nom sous-cat.", placeholder="Nouvelle sous-cat...", label_visibility="collapsed", key="input_new_sub")
        with c4:
            prio = st.number_input("Priorité", 0, 100, 10, key="rule_prio")
        with c5:
            compte_regle = st.selectbox("Compte", comptes_existants, key="rule_compte",
                                        help="Restreindre cette règle à un compte spécifique, ou laisser 'Tous les comptes'")

        submit_button = st.form_submit_button("Enregistrer la règle", use_container_width=True)

        if submit_button:
            final_cat = cat_new.strip() if cat_sel == "✏️ NOUVELLE CATÉGORIE" else (cat_sel if cat_sel != "Sélectionner..." else "")
            final_sub = sub_new.strip() if sub_sel == "✏️ NOUVELLE SOUS-CAT." else (sub_sel if sub_sel != "(Aucune)" else "")
            final_compte = None if compte_regle == "Tous les comptes" else compte_regle

            if mot and final_cat:
                supabase.table("regles").upsert({
                    "mot_cle": mot.upper(),
                    "categorie": final_cat,
                    "sous_categorie": final_sub,
                    "priorite": prio,
                    "compte": final_compte,
                }, on_conflict="mot_cle").execute()
                label_compte = f" (compte : {final_compte})" if final_compte else " (tous les comptes)"
                st.success(f"✅ Règle enregistrée : {mot.upper()} -> {final_cat}{label_compte}")
                st.rerun()
            else:
                st.error("⚠️ Il manque le mot-clé ou la catégorie.")

    regles = get_regles()
    st.dataframe(regles, use_container_width=True)

    st.divider()
    st.subheader("🔄 Appliquer les règles aux données existantes")
    st.info("Ce bouton va scanner TOUTES les transactions et appliquer vos règles.")

    if st.button("Lancer la mise à jour globale", use_container_width=True):
        regles_df = get_regles()
        df_all = load_transactions()

        if df_all.empty:
            st.warning("Aucune transaction à analyser.")
        else:
            count = 0
            with st.status("Analyse en cours...", expanded=True) as status:
                for _, row in df_all.iterrows():
                    # On passe le compte de la transaction pour respecter les règles par compte
                    new_cat, new_sub = categoriser(row['libelle'], regles_df, compte=row.get('compte'))
                    if new_cat != "À classer":
                        cat_actuelle = row['categorie'] if pd.notna(row['categorie']) else ""
                        sub_actuelle = row.get('sous_categorie', '') if pd.notna(row.get('sous_categorie', '')) else ""
                        if cat_actuelle != new_cat or sub_actuelle != new_sub:
                            supabase.table("transactions").update({
                                "categorie": new_cat, "sous_categorie": new_sub
                            }).eq("id", row['id']).execute()
                            count += 1
                status.update(label=f"Terminé ! {count} transactions mises à jour.", state="complete")
            st.rerun()

    with st.expander("🗑️ Supprimer une règle"):
        if not regles.empty:
            to_delete = st.selectbox("Règle à supprimer", regles['mot_cle'].tolist())
            if st.button("Supprimer", type="secondary"):
                supabase.table("regles").delete().eq("mot_cle", to_delete).execute()
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

    c1, c2 = st.columns(2)
    with c1:
        filtre = st.radio("Afficher", ["À classer uniquement", "Toutes"], horizontal=True)
    with c2:
        compte_f = st.selectbox("Compte", ["Tous"] + sorted(df_all['compte'].unique().tolist()))

    df_show = df_all.copy()
    if filtre == "À classer uniquement":
        df_show = df_show[(df_show['categorie'] == "À classer") | (df_show['categorie'].isna())]
    if compte_f != "Tous":
        df_show = df_show[df_show['compte'] == compte_f]

    df_show = df_show.sort_values('date', ascending=False)
    st.markdown(f"**{len(df_show)} transaction(s)**", unsafe_allow_html=True)

    if 'extra_cats' not in st.session_state:
        st.session_state.extra_cats = []

    all_cats = sorted(set(
        [c for c in df_all['categorie'].unique() if pd.notna(c)] +
        ["Alimentation", "Transport", "Logement", "Santé", "Loisirs", "Revenus", "Banque", "Épargne"] +
        st.session_state.extra_cats
    ))

    for _, row in df_show.head(50).iterrows():
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
                    st.rerun()
            st.divider()
