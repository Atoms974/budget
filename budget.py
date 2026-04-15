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

# ── STYLES ET INTERFACE ──────────────────────────────────────────────────────
st.set_page_config(page_title="Budget Cloud", layout="wide", page_icon="💳")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* Sidebar */
[data-testid="stSidebar"] { background: #0f172a; border-right: 1px solid #1e293b; }
[data-testid="stSidebar"] * { color: #94a3b8 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 { color: #f1f5f9 !important; }
[data-testid="stSidebarNav"] { display: none; }

/* Main bg */
.main { background: #f8fafc; }

/* Titles */
.page-title { font-family: 'DM Serif Display', serif; font-size: 2.4rem; color: #0f172a; margin-bottom: 0.2rem; letter-spacing: -0.5px; }
.page-sub { color: #64748b; font-size: 0.95rem; margin-bottom: 2rem; font-weight: 300; }
.section-title { font-family: 'DM Serif Display', serif; font-size: 1.3rem; color: #0f172a; margin: 1.5rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 2px solid #f1f5f9; }

/* KPI Cards */
.kpi-card { background: white; border-radius: 16px; padding: 1.4rem 1.6rem; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.kpi-label { font-size: 0.78rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8; margin-bottom: 0.5rem; }
.kpi-value { font-family: 'DM Serif Display', serif; font-size: 2rem; color: #0f172a; }
.kpi-value.neg { color: #ef4444; }
.kpi-value.pos { color: #10b981; }

.alert-box { background: #fef3c7; border: 1px solid #fbbf24; border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.88rem; color: #92400e; }
</style>
""", unsafe_allow_html=True)

# ── SIDEBAR NAV ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding: 1rem 0 1.5rem 0;">
        <div style="font-family:'DM Serif Display',serif; font-size:1.4rem; color:#f1f5f9; margin-bottom:0.2rem;">💳 Budget Cloud</div>
        <div style="font-size:0.78rem; color:#475569; font-weight:300;">Synchronisé via Supabase</div>
    </div>
    """, unsafe_allow_html=True)

    page = st.radio("Navigation", [
        "🏠 Tableau de bord",
        "📥 Importer CSV",
        "📊 Analyse détaillée",
        "🏷️ Règles de catégories",
        "✏️ Recatégoriser",
    ], label_visibility="collapsed")

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

    # Filters
    col1, col2, col3 = st.columns([2,2,3])
    with col1:
        annees_dispo = sorted(df_all['annee'].unique(), reverse=True)
        annee_sel = st.selectbox("Année", annees_dispo)
    with col2:
        comptes_dispo = ["Tous"] + sorted(df_all['compte'].unique().tolist())
        compte_sel = st.selectbox("Compte", comptes_dispo)
    with col3:
        exclure_virements = st.checkbox("Masquer les virements internes", value=True)

    df = load_transactions(
        comptes=None if compte_sel == "Tous" else [compte_sel],
        annees=[annee_sel],
        exclure_cat=["Banque"] if exclure_virements else None
    )

    depenses = df[df['montant'] < 0]['montant'].sum()
    revenus  = df[df['montant'] > 0]['montant'].sum()
    solde    = revenus + depenses
    # Fix : On compte aussi les valeurs nulles
    nb_a_classer = len(df[(df['categorie'] == "À classer") | (df['categorie'].isna())])

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Dépenses {annee_sel}</div>
            <div class="kpi-value neg">{depenses:,.0f} €</div>
        </div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""<div class="kpi-card">
            <div class="kpi-label">Revenus {annee_sel}</div>
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

    st.markdown('<div class="section-title">Dépenses par catégorie</div>', unsafe_allow_html=True)

    df_dep = df[df['montant'] < 0].copy()
    df_dep['montant_abs'] = df_dep['montant'].abs()

    col_g1, col_g2 = st.columns([1, 1])
    
    # -- La couleur de texte forcée pour qu'on puisse lire --
    text_color = '#0f172a' 

    with col_g1:
        if not df_dep.empty:
            by_cat = df_dep.groupby('categorie')['montant_abs'].sum().sort_values(ascending=False).reset_index()
            fig_pie = px.pie(by_cat, values='montant_abs', names='categorie', hole=0.5, color_discrete_sequence=px.colors.qualitative.Set3)
            fig_pie.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)', 
                margin=dict(t=10,b=10,l=10,r=10),
                font=dict(color=text_color) # <-- Fix de la couleur
            )
            # theme=None bloque le thème par défaut de Streamlit
            st.plotly_chart(fig_pie, use_container_width=True, theme=None) 

    with col_g2:
        if not df_dep.empty:
            # J'ai remplacé 'Blues' par 'Teal' pour le dégradé, ça évite l'overdose de bleu
            fig_bar = px.bar(by_cat.head(10), x='montant_abs', y='categorie', orientation='h', color='montant_abs', color_continuous_scale='Teal')
            fig_bar.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)', 
                yaxis=dict(autorange='reversed'), 
                showlegend=False, 
                coloraxis_showscale=False, 
                margin=dict(t=10,b=10,l=10,r=10),
                font=dict(color=text_color) # <-- Fix de la couleur
            )
            st.plotly_chart(fig_bar, use_container_width=True, theme=None)

    st.markdown('<div class="section-title">Évolution mensuelle</div>', unsafe_allow_html=True)

    monthly = df.groupby('mois_label').agg(
        depenses=('montant', lambda x: x[x<0].sum()),
        revenus=('montant', lambda x: x[x>0].sum())
    ).reset_index().sort_values('mois_label')

    fig_line = go.Figure()
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['revenus'], name='Revenus', marker_color='#10b981', opacity=0.8))
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['depenses'].abs(), name='Dépenses', marker_color='#ef4444', opacity=0.8))
    fig_line.update_layout(
        barmode='group', 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(t=30,b=10,l=10,r=10),
        font=dict(color=text_color) # <-- Fix de la couleur
    )
    st.plotly_chart(fig_line, use_container_width=True, theme=None)
# ══════════════════════════════════════════════════════════════════════════════
# PAGE : IMPORTER CSV
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📥 Importer CSV":
    st.markdown('<div class="page-title">Importer un CSV</div>', unsafe_allow_html=True)

    compte_nom = st.selectbox("Compte source", ["Compte Courant Principal", "Compte Courant Secondaire", "Compte Épargne / Joint", "Autre..."])
    if compte_nom == "Autre...": compte_nom = st.text_input("Nom du compte")

    uploaded = st.file_uploader("Fichier CSV", type=["csv", "txt"])

    if uploaded:
        for sep in [';', ',', '\t', '|']:
            try:
                df_raw = pd.read_csv(uploaded, sep=sep, engine='python', encoding='utf-8-sig')
                if len(df_raw.columns) >= 2: break
            except: continue
        
        st.dataframe(df_raw.head(3), use_container_width=True)
        cols = df_raw.columns.tolist()
        
        c1, c2, c3 = st.columns(3)
        col_date  = c1.selectbox("📅 Colonne Date", cols, index=0)
        col_lib   = c2.selectbox("📝 Colonne Libellé", cols, index=min(1,len(cols)-1))
        col_mt    = c3.selectbox("💶 Colonne Montant", cols, index=min(2,len(cols)-1))

        if st.button("✅ Valider et envoyer vers Supabase"):
            regles = get_regles()
            to_insert = []
            
            for _, row in df_raw.iterrows():
                lib = str(row[col_lib])
                cat, sub = categoriser(lib, regles)
                
                mt = str(row[col_mt]).replace(r'\s', '').replace(' ', '').replace(',', '.')
                try: mt_float = float(mt)
                except: continue

                to_insert.append({
                    "date": pd.to_datetime(row[col_date], dayfirst=True).strftime('%Y-%m-%d'),
                    "libelle": lib,
                    "montant": mt_float,
                    "compte": compte_nom,
                    "categorie": cat,
                    "sous_categorie": sub,
                    "type": "Revenu" if mt_float > 0 else "Dépense"
                })
            
            if to_insert:
                try:
                    res = supabase.table("transactions").upsert(to_insert, on_conflict="date,libelle,montant,compte").execute()
                    st.success(f"✅ Import terminé ! Lignes traitées vers le Cloud.")
                except Exception as e:
                    st.error(f"Erreur d'insertion : {e}")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : ANALYSE DÉTAILLÉE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Analyse détaillée":
    st.markdown('<div class="page-title">Analyse détaillée</div>', unsafe_allow_html=True)
    df = load_transactions()
    
    if df.empty:
        st.info("Aucune donnée.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        annees_dispo = sorted(df['annee'].unique(), reverse=True)
        annee_sel = st.multiselect("Années", annees_dispo, default=[annees_dispo[0]])
    with c2:
        comptes_dispo = sorted(df['compte'].unique().tolist())
        comptes_sel = st.multiselect("Comptes", comptes_dispo, default=comptes_dispo)
    with c3:
        cats_dispo = [c for c in df['categorie'].unique().tolist() if pd.notna(c)]
        cats_sel = st.multiselect("Catégories", cats_dispo, default=cats_dispo)
    with c4:
        type_sel = st.radio("Type", ["Dépenses", "Revenus", "Tout"], horizontal=True)

    df = df[df['annee'].isin(annee_sel)] if annee_sel else df
    df = df[df['compte'].isin(comptes_sel)] if comptes_sel else df
    df = df[df['categorie'].isin(cats_sel)] if cats_sel else df
    
    if type_sel == "Dépenses":
        df = df[df['montant'] < 0].copy()
        df['montant'] = df['montant'].abs()
    elif type_sel == "Revenus":
        df = df[df['montant'] > 0]

    pivot_view = st.radio("Vue", ["Catégorie", "Catégorie + Sous-catégorie"], horizontal=True)

    if not df.empty:
        idx = ['categorie'] if pivot_view == "Catégorie" else ['categorie', 'sous_categorie']
        tcd = df.pivot_table(index=idx, columns='mois_label', values='montant', aggfunc='sum', fill_value=0, margins=True, margins_name='TOTAL')
        tcd = tcd.round(2)
        st.dataframe(tcd, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE : RÈGLES DE CATÉGORIES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🏷️ Règles de catégories":
    st.markdown('<div class="page-title">Règles de catégories</div>', unsafe_allow_html=True)
    
    with st.form("add_rule"):
        c1, c2, c3, c4 = st.columns([3,2,2,1])
        with c1: mot = st.text_input("Si le libellé contient")
        with c2: cat = st.text_input("Catégorie")
        with c3: sub = st.text_input("Sous-catégorie")
        with c4: prio = st.number_input("Priorité", 0, 100, 10)
        
        if st.form_submit_button("Enregistrer", use_container_width=True) and mot and cat:
            supabase.table("regles").upsert({
                "mot_cle": mot.upper(), "categorie": cat, "sous_categorie": sub, "priorite": prio
            }, on_conflict="mot_cle").execute()
            
            st.success("✅ Règle enregistrée !")
            st.rerun()

    regles = get_regles()
    st.dataframe(regles, use_container_width=True)

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
        # Le fameux correctif est ici
        df_show = df_show[(df_show['categorie'] == "À classer") | (df_show['categorie'].isna())]
    if compte_f != "Tous":
        df_show = df_show[df_show['compte'] == compte_f]

    df_show = df_show.sort_values('date', ascending=False)
    st.markdown(f"**{len(df_show)} transaction(s)**", unsafe_allow_html=True)

    all_cats = sorted(set([c for c in df_all['categorie'].unique() if pd.notna(c)] + ["Alimentation","Transport","Logement","Santé","Loisirs","Revenus","Banque","Épargne"]))

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
                st.caption(f"Actuel : {current_cat} / {row.get('sous_categorie','')}")
            with col3:
                new_cat = st.selectbox("Cat", all_cats, index=all_cats.index(row['categorie']) if row['categorie'] in all_cats else 0, key=f"cat_{row['id']}", label_visibility="collapsed")
                new_sub = st.text_input("Sub", value=row.get('sous_categorie','') if pd.notna(row.get('sous_categorie')) else '', key=f"sub_{row['id']}", label_visibility="collapsed", placeholder="Sous-catégorie")
            with col4:
                if st.button("💾", key=f"save_{row['id']}"):
                    supabase.table("transactions").update({"categorie": new_cat, "sous_categorie": new_sub}).eq("id", row['id']).execute()
                    st.rerun()
            st.divider()
