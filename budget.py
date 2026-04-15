import streamlit as st
import pandas as pd
from supabase import create_client, Client
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURATION SUPABASE ---
# Ces valeurs seront lues depuis les Secrets sur Streamlit Cloud
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
except:
    st.error("Clés API manquantes. Configurez les Secrets Streamlit.")
    st.stop()

supabase: Client = create_client(URL, KEY)

# --- LOGIQUE DE DONNÉES ---

def get_regles():
    try:
        res = supabase.table("regles").select("*").order("priorite", desc=True).execute()
        if not res.data:
            return pd.DataFrame(columns=['mot_cle', 'categorie', 'sous_categorie', 'priorite'])
        return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Erreur règles : {e}")
        return pd.DataFrame()

def categoriser(libelle, regles_df):
    l = str(libelle).upper()
    for _, row in regles_df.iterrows():
        if str(row['mot_cle']).upper() in l:
            return row['categorie'], row['sous_categorie']
    return "À classer", ""

def load_transactions(comptes=None, annees=None, exclure_cat=None):
    try:
        res = supabase.table("transactions").select("*").execute()
        if not res.data:
            return pd.DataFrame()
        
        df = pd.DataFrame(res.data)
        
        # --- CORRECTIONS CRITIQUES ---
        # 1. Convertir les montants (Supabase envoie du texte ou decimal)
        df['montant'] = pd.to_numeric(df['montant'], errors='coerce')
        
        # 2. Convertir les dates proprement
        df['date'] = pd.to_datetime(df['date'])
        
        # 3. Créer les colonnes de temps pour les graphiques
        df['annee'] = df['date'].dt.year
        df['mois_num'] = df['date'].dt.month
        df['mois_label'] = df['date'].dt.strftime('%Y-%m')
        
        # Filtres
        if comptes: df = df[df['compte'].isin(comptes)]
        if annees: df = df[df['annee'].isin(annees)]
        if exclure_cat: df = df[~df['categorie'].isin(exclure_cat)]
        
        return df
    except Exception as e:
        st.error(f"Erreur chargement transactions : {e}")
        return pd.DataFrame()

# --- INTERFACE (DESIGN) ---
st.set_page_config(page_title="Mon Budget Cloud", layout="wide", page_icon="☁️")

# (Ici tu peux garder tout le bloc <style> CSS de Claude que tu as envoyé précédemment)

# --- NAVIGATION ---
page = st.sidebar.radio("Navigation", ["🏠 Dashboard", "📥 Import CSV", "🏷️ Règles", "✏️ Recatégoriser"])

if page == "🏠 Dashboard":
    st.title("📊 Dashboard Financier")
    df = load_transactions()
    
    if df.empty:
        st.info("Aucune donnée. Allez dans l'onglet Import.")
    else:
        # Filtres et graphiques (Récupère la logique de Claude ici, elle fonctionne parfaitement avec le DataFrame df)
        st.write("Données chargées depuis Supabase ✅")
        st.dataframe(df.head())

elif page == "📥 Import CSV":
    st.title("📥 Importation")
    compte_nom = st.text_input("Nom du compte", "Boursorama")
    uploaded = st.file_uploader("Fichier CSV", type="csv")
    
    if uploaded:
        df_raw = pd.read_csv(uploaded, sep=None, engine='python')
        st.dataframe(df_raw.head(3))
        
        cols = df_raw.columns.tolist()
        c1, c2, c3 = st.columns(3)
        col_date = c1.selectbox("Date", cols)
        col_lib = c2.selectbox("Libellé", cols)
        col_mt = c3.selectbox("Montant", cols)
        
        if st.button("Lancer l'import vers le Cloud"):
            regles = get_regles()
            
            # Préparation des données
            to_insert = []
            for _, row in df_raw.iterrows():
                lib = str(row[col_lib])
                cat, sub = categoriser(lib, regles)
                
                # Nettoyage montant
                mt = str(row[col_mt]).replace(',', '.').replace(' ', '')
                try:
                    mt_float = float(mt)
                except:
                    continue

                to_insert.append({
                    "date": pd.to_datetime(row[col_date], dayfirst=True).strftime('%Y-%m-%d'),
                    "libelle": lib,
                    "montant": mt_float,
                    "compte": compte_nom,
                    "categorie": cat,
                    "sous_categorie": sub,
                    "type": "Revenu" if mt_float > 0 else "Dépense"
                })
            
            # Envoi par paquets à Supabase
            res = supabase.table("transactions").upsert(to_insert, on_conflict="date,libelle,montant,compte").execute()
            st.success(f"Import terminé ! {len(to_insert)} lignes traitées.")

elif page == "🏷️ Règles":
    st.title("🏷️ Gestion des règles")
    # Formulaire d'ajout
    with st.form("add_regle"):
        mot = st.text_input("Mot clé")
        cat = st.text_input("Catégorie")
        sub = st.text_input("Sous-catégorie")
        prio = st.number_input("Priorité", 0, 100, 10)
        if st.form_submit_button("Ajouter la règle"):
            supabase.table("regles").upsert({"mot_cle": mot.upper(), "categorie": cat, "sous_categorie": sub, "priorite": prio}).execute()
            st.rerun()
    
    st.dataframe(get_regles())
