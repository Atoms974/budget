import streamlit as st
import pandas as pd
from supabase import create_client, Client
import plotly.express as px
import plotly.graph_objects as go

# ── CONFIGURATION SUPABASE ───────────────────────────────────────────────────
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except Exception as e:
    st.error("⚠️ Clés API manquantes ou incorrectes.")
    st.stop()

# ── LOGIQUE DES DONNÉES ──────────────────────────────────────────────────────
def get_regles():
    try:
        res = supabase.table("regles").select("*").order("priorite", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=['id', 'mot_cle', 'categorie', 'sous_categorie', 'sous_sous_categorie', 'priorite'])
    except:
        return pd.DataFrame(columns=['id', 'mot_cle', 'categorie', 'sous_categorie', 'sous_sous_categorie', 'priorite'])

def categoriser(libelle, regles_df):
    if regles_df.empty:
        return "À classer", "", ""
    l = str(libelle).upper()
    for _, row in regles_df.iterrows():
        if str(row['mot_cle']).upper() in l:
            return row['categorie'], row.get('sous_categorie', ''), row.get('sous_sous_categorie', '')
    return "À classer", "", ""

def load_transactions(comptes=None, annees=None, mois=None):
    try:
        res = supabase.table("transactions").select("*").execute()
        if not res.data: return pd.DataFrame()
        
        df = pd.DataFrame(res.data)
        df['montant'] = pd.to_numeric(df['montant'], errors='coerce')
        # On ne met PAS dayfirst=True ici car Supabase stocke en ISO (AAAA-MM-JJ)
        df['date'] = pd.to_datetime(df['date'])
        
        df = df.sort_values('date', ascending=False)
        df['annee'] = df['date'].dt.year
        df['mois_label'] = df['date'].dt.strftime('%Y-%m')
        
        if comptes: df = df[df['compte'].isin(comptes)]
        if annees: df = df[df['annee'].isin(annees)]
        if mois: df = df[df['mois_label'].isin(mois)]
            
        return df
    except Exception as e:
        st.error(f"Erreur chargement : {e}")
        return pd.DataFrame()

# ── INTERFACE ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Budget Pro", layout="wide")

st.markdown("""
<style>
    .page-title { font-size: 2rem; font-weight: 700; margin-bottom: 1rem; }
    .section-title { font-size: 1.1rem; font-weight: 600; margin-top: 1.5rem; border-bottom: 1px solid rgba(128,128,128,0.2); }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("💳 Budget App")
    page = st.radio("Menu", ["🏠 Dashboard", "🔍 Journal", "📥 Import CSV", "📊 Analyse", "🏷️ Règles", "✏️ Recatégoriser"])

# ── DASHBOARD ────────────────────────────────────────────────────────────────
if page == "🏠 Dashboard":
    st.markdown('<div class="page-title">Dashboard</div>', unsafe_allow_html=True)
    df_all = load_transactions()
    
    if df_all.empty:
        st.info("Importez des données pour commencer.")
    else:
        c1, c2 = st.columns(2)
        with c1: ann = st.selectbox("Année", sorted(df_all['annee'].unique(), reverse=True))
        with c2: cpt = st.selectbox("Compte", ["Tous"] + sorted(df_all['compte'].unique().tolist()))
        
        df = load_transactions(comptes=None if cpt=="Tous" else [cpt], annees=[ann])
        
        df_dep = df[df['montant'] < 0].copy()
        df_dep['montant_abs'] = df_dep['montant'].abs()
        # On remplit les vides pour le Sunburst
        for col in ['sous_categorie', 'sous_sous_categorie']:
            df_dep[col] = df_dep[col].fillna('Général').replace('', 'Général')

        st.markdown('<div class="section-title">Analyse profonde (3 niveaux)</div>', unsafe_allow_html=True)
        # Graphique Sunburst avec 3 niveaux
        fig = px.sunburst(df_dep, path=['categorie', 'sous_categorie', 'sous_sous_categorie'], 
                          values='montant_abs', color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_layout(margin=dict(t=10, l=10, r=10, b=10))
        st.plotly_chart(fig, use_container_width=True, theme="streamlit")

# ── JOURNAL ──────────────────────────────────────────────────────────────────
elif page == "🔍 Journal":
    st.markdown('<div class="page-title">Journal</div>', unsafe_allow_html=True)
    df = load_transactions()
    if not df.empty:
        st.dataframe(df[['date', 'compte', 'libelle', 'montant', 'categorie', 'sous_categorie', 'sous_sous_categorie']], use_container_width=True)

# ── IMPORT CSV ───────────────────────────────────────────────────────────────
elif page == "📥 Import CSV":
    st.markdown('<div class="page-title">Importation</div>', unsafe_allow_html=True)
    compte_nom = st.text_input("Compte", "Principal")
    uploaded = st.file_uploader("Fichier CSV", type="csv")
    
    if uploaded:
        df_raw = pd.read_csv(uploaded, sep=None, engine='python')
        cols = df_raw.columns.tolist()
        c1, c2, c3 = st.columns(3)
        col_d, col_l, col_m = c1.selectbox("Date", cols), c2.selectbox("Libellé", cols), c3.selectbox("Montant", cols)
        
        if st.button("🚀 Importer"):
            regles = get_regles()
            to_insert = []
            for _, row in df_raw.iterrows():
                try:
                    # FIX DATE : On utilise format='mixed' ou on gère l'ambiguïté intelligemment
                    raw_date = str(row[col_d])
                    # Si la date contient des tirets, c'est probablement ISO, sinon c'est FR
                    day_first = False if '-' in raw_date else True
                    dt = pd.to_datetime(raw_date, dayfirst=day_first, errors='coerce')
                    
                    mt = float(str(row[col_m]).replace(',','.').replace(' ',''))
                    cat, sub, subsub = categoriser(row[col_l], regles)
                    
                    if pd.notna(dt):
                        to_insert.append({
                            "date": dt.strftime('%Y-%m-%d'), "libelle": row[col_l],
                            "montant": mt, "compte": compte_nom, 
                            "categorie": cat, "sous_categorie": sub, "sous_sous_categorie": subsub
                        })
                except: continue
            
            if to_insert:
                supabase.table("transactions").upsert(to_insert, on_conflict="date,libelle,montant,compte").execute()
                st.success("Import réussi !")
                st.rerun()

    st.divider()
    if st.button("🗑️ RESET BASE DE DONNÉES"):
        supabase.table("transactions").delete().neq("id", 0).execute()
        st.rerun()

# ── ANALYSE ──────────────────────────────────────────────────────────────────
elif page == "📊 Analyse":
    st.markdown('<div class="page-title">Analyse Croisée</div>', unsafe_allow_html=True)
    df_all = load_transactions()
    if not df_all.empty:
        mois_dispo = sorted(df_all['mois_label'].unique(), reverse=True)
        mois_sel = st.multiselect("Mois", mois_dispo, default=mois_dispo[:3])
        df = df_all[df_all['mois_label'].isin(mois_sel) & (df_all['montant'] < 0)]
        df['montant'] = df['montant'].abs()
        
        tcd = df.pivot_table(index=['categorie', 'sous_categorie', 'sous_sous_categorie'], 
                             columns='mois_label', values='montant', aggfunc='sum', fill_value=0)
        st.dataframe(tcd, use_container_width=True)

# ── RÈGLES ───────────────────────────────────────────────────────────────────
elif page == "🏷️ Règles":
    st.markdown('<div class="page-title">Règles</div>', unsafe_allow_html=True)
    with st.form("new_rule"):
        c1, c2, c3, c4 = st.columns(4)
        m = c1.text_input("Mot-clé")
        cat = c2.text_input("Catégorie")
        sub = c3.text_input("Sous-cat")
        subsub = c4.text_input("Sous-sous-cat")
        if st.form_submit_button("Ajouter"):
            supabase.table("regles").upsert({"mot_cle": m.upper(), "categorie": cat, "sous_categorie": sub, "sous_sous_categorie": subsub}).execute()
            st.rerun()
    st.dataframe(get_regles(), use_container_width=True)

# ── RECATÉGORISER ─────────────────────────────────────────────────────────────
elif page == "✏️ Recatégoriser":
    st.markdown('<div class="page-title">Recatégoriser</div>', unsafe_allow_html=True)
    df = load_transactions()
    df_ac = df[df['categorie'] == "À classer"].head(10)
    for _, r in df_ac.iterrows():
        with st.container():
            col1, col2, col3, col4 = st.columns([2,1,1,1])
            col1.write(f"**{r['libelle']}** ({r['montant']}€)")
            nc = col2.text_input("Cat", key=f"c_{r['id']}")
            ns = col3.text_input("Sub", key=f"s_{r['id']}")
            nss = col4.text_input("SubSub", key=f"ss_{r['id']}")
            if st.button("Sauver", key=f"b_{r['id']}"):
                supabase.table("transactions").update({"categorie": nc, "sous_categorie": ns, "sous_sous_categorie": nss}).eq("id", r['id']).execute()
                st.rerun()
