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
            return pd.DataFrame(columns=['id', 'mot_cle', 'categorie', 'sous_categorie', 'priorite'])
        return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Erreur chargement des règles : {e}")
        return pd.DataFrame(columns=['id', 'mot_cle', 'categorie', 'sous_categorie', 'priorite'])

def categoriser(libelle, regles_df):
    if regles_df.empty:
        return "À classer", ""
    l = str(libelle).upper()
    for _, row in regles_df.iterrows():
        if str(row['mot_cle']).upper() in l:
            return row['categorie'], row.get('sous_categorie', '')
    return "À classer", ""

def load_transactions(comptes=None, annees=None, exclure_cat=None):
    try:
        res = supabase.table("transactions").select("*").execute()
        if not res.data:
            return pd.DataFrame()
        
        df = pd.DataFrame(res.data)
        
        # Corrections critiques pour Streamlit / Pandas
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

# ── NOUVELLES FONCTIONS D'ANALYSE (Sankey & Heatmap) ─────────────────────────
def afficher_sankey(df_filtre):
    st.markdown('<div class="section-title">🌊 Flux de trésorerie</div>', unsafe_allow_html=True)
    
    total_revenus = df_filtre[df_filtre['montant'] > 0]['montant'].sum()
    df_dep = df_filtre[df_filtre['montant'] < 0].groupby('categorie')['montant'].sum().abs().reset_index()
    
    if total_revenus == 0 or df_dep.empty:
        st.info("Données insuffisantes pour générer le flux (nécessite revenus et dépenses).")
        return

    # On groupe les petites catégories (< 2% du total) pour la lisibilité
    total_depenses = df_dep['montant'].sum()
    df_dep['proportion'] = df_dep['montant'] / total_depenses
    
    df_principales = df_dep[df_dep['proportion'] >= 0.02]
    df_autres = df_dep[df_dep['proportion'] < 0.02]
    
    if not df_autres.empty:
        autres_sum = df_autres['montant'].sum()
        df_principales = pd.concat([df_principales, pd.DataFrame([{'categorie': 'Autres Dépenses', 'montant': autres_sum}])], ignore_index=True)

    reste = max(0, total_revenus - total_depenses)

    labels = ["Revenus"] + df_principales['categorie'].tolist()
    if reste > 0:
        labels.append("Épargne / Restant")
    
    sources = []
    targets = []
    values = []
    
    for i, row in df_principales.iterrows():
        sources.append(0)
        targets.append(i + 1)
        values.append(row['montant'])
        
    if reste > 0:
        sources.append(0)
        targets.append(len(labels) - 1)
        values.append(reste)

    fig = go.Figure(data=[go.Sankey(
        node = dict(
          pad = 15, thickness = 20,
          line = dict(color = "black", width = 0.5),
          label = labels,
          color = "#4c78a8"
        ),
        link = dict(
          source = sources, target = targets, value = values,
          color = "rgba(169, 172, 182, 0.4)"
      ))])
    fig.update_layout(margin=dict(t=20,b=20,l=20,r=20), font_size=12, height=400)
    st.plotly_chart(fig, use_container_width=True)

def afficher_heatmap(df_filtre):
    st.markdown('<div class="section-title">📅 Intensité par jour</div>', unsafe_allow_html=True)
    
    df_heat = df_filtre[df_filtre['montant'] < 0].copy()
    if df_heat.empty:
        st.info("Aucune dépense à afficher.")
        return

    jours_ordre = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    df_heat['jour_semaine'] = df_heat['date'].dt.day_name().replace({
        'Monday': 'Lundi', 'Tuesday': 'Mardi', 'Wednesday': 'Mercredi', 
        'Thursday': 'Jeudi', 'Friday': 'Vendredi', 'Saturday': 'Samedi', 'Sunday': 'Dimanche'
    })
    
    heatmap_data = df_heat.groupby(['mois_label', 'jour_semaine'])['montant'].sum().abs().reset_index()
    heatmap_pivot = heatmap_data.pivot(index='jour_semaine', columns='mois_label', values='montant').fillna(0)
    
    # S'assurer que tous les jours de la semaine sont présents dans le bon ordre
    heatmap_pivot = heatmap_pivot.reindex(jours_ordre).fillna(0)

    fig = px.imshow(
        heatmap_pivot,
        labels=dict(x="Mois", y="Jour", color="Dépenses (€)"),
        color_continuous_scale='Reds',
        aspect="auto"
    )
    fig.update_xaxes(side="top")
    fig.update_layout(margin=dict(t=20,b=20,l=20,r=20), height=400)
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

    # Nouveaux filtres inclus (Mois + Catégories optionnelles)
    col1, col2, col3 = st.columns([1,1,2])
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
    
    # Application des filtres optionnels sur les données affichées
    if mois_sel:
        df = df[df['mois_label'].isin(mois_sel)]
    if cat_sel:
        df = df[df['categorie'].isin(cat_sel)]

    depenses = df[df['montant'] < 0]['montant'].sum()
    revenus  = df[df['montant'] > 0]['montant'].sum()
    solde    = revenus + depenses
    nb_a_classer = len(df[(df['categorie'] == "À classer") | (df['categorie'].isna())])

    # KPIs
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
        </div>""", unsafe_allow_html=
