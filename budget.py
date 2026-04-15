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
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* On enlève les couleurs de fond forcées pour laisser le mode sombre de Streamlit agir */
.main { padding: 2rem; }

/* Titres qui s'adaptent au thème */
.page-title { font-family: 'DM Serif Display', serif; font-size: 2.4rem; margin-bottom: 0.2rem; }
.section-title { font-family: 'DM Serif Display', serif; font-size: 1.3rem; margin: 1.5rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 1px solid rgba(128,128,128,0.2); }

/* Cartes KPI transparentes avec bordure légère pour le mode sombre */
.kpi-card { 
    background: rgba(255, 255, 255, 0.05); 
    border-radius: 16px; 
    padding: 1.4rem; 
    border: 1px solid rgba(128,128,128,0.2); 
}
.kpi-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #94a3b8; }
.kpi-value { font-family: 'DM Serif Display', serif; font-size: 1.8rem; }
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

    st.markdown('<div class="section-title">Dépenses par catégorie et sous-catégorie</div>', unsafe_allow_html=True)

    df_dep = df[df['montant'] < 0].copy()
    df_dep['montant_abs'] = df_dep['montant'].abs()
    
    # ⚠️ Important : On remplace les sous-catégories vides par "Général" pour éviter que Plotly ne plante
    df_dep['sous_categorie'] = df_dep['sous_categorie'].fillna('Général')
    df_dep.loc[df_dep['sous_categorie'] == '', 'sous_categorie'] = 'Général'

    col_g1, col_g2 = st.columns([1, 1])

    with col_g1:
        if not df_dep.empty:
            # Graphique Sunburst (Le remplaçant du camembert)
            fig_sun = px.sunburst(
                df_dep, 
                path=['categorie', 'sous_categorie'], 
                values='montant_abs',
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_sun.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)', 
                margin=dict(t=20,b=20,l=20,r=20)
            )
            # Ajout d'une petite astuce pour formater les nombres au survol
            fig_sun.update_traces(hovertemplate='<b>%{label}</b><br>Montant: %{value:.2f} €<br>Part: %{percentParent:.1%}')
            st.plotly_chart(fig_sun, use_container_width=True, theme="streamlit") 

    with col_g2:
        if not df_dep.empty:
            # On groupe par catégorie ET sous-catégorie
            by_cat_sub = df_dep.groupby(['categorie', 'sous_categorie'])['montant_abs'].sum().reset_index()
            
            # On garde seulement les 10 plus grosses catégories pour que la lecture reste agréable
            top_10_cats = df_dep.groupby('categorie')['montant_abs'].sum().nlargest(10).index
            by_cat_sub = by_cat_sub[by_cat_sub['categorie'].isin(top_10_cats)]

            # Graphique en barres empilées
            fig_bar = px.bar(
                by_cat_sub, 
                x='montant_abs', 
                y='categorie', 
                color='sous_categorie', # Découpe la barre selon les sous-catégories
                orientation='h', 
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_bar.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)', 
                yaxis=dict(categoryorder='total ascending'), # Trie par la barre totale la plus grande
                showlegend=True, 
                legend=dict(
                    orientation="h", 
                    yanchor="top", 
                    y=-0.2, 
                    title_text='' # Enlève le titre "sous_categorie" de la légende
                ),
                margin=dict(t=20,b=20,l=20,r=20)
            )
            st.plotly_chart(fig_bar, use_container_width=True, theme="streamlit")

    st.markdown('<div class="section-title">Évolution mensuelle</div>', unsafe_allow_html=True)

    # ... (Garde le code de ton graphique d'évolution mensuelle 'fig_line' exactement comme il était) ...
            
    st.markdown('<div class="section-title">Évolution mensuelle</div>', unsafe_allow_html=True)

    monthly = df.groupby('mois_label').agg(
        depenses=('montant', lambda x: x[x<0].sum()),
        revenus=('montant', lambda x: x[x>0].sum())
    ).reset_index().sort_values('mois_label')

    fig_line = go.Figure()
    # Couleurs vives pour bien ressortir sur le bleu foncé
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['revenus'], name='Revenus', marker_color='#00eb93'))
    fig_line.add_trace(go.Bar(x=monthly['mois_label'], y=monthly['depenses'].abs(), name='Dépenses', marker_color='#ff4b4b'))
    fig_line.update_layout(
        barmode='group', 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(t=30,b=20,l=20,r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_line, on_select="ignore", theme="streamlit")
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
        
        st.dataframe(df_raw.head(3), width='stretch')
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
        st.dataframe(tcd, width='stretch')

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
        
        if st.form_submit_button("Enregistrer", width='stretch') and mot and cat:
            supabase.table("regles").upsert({
                "mot_cle": mot.upper(), "categorie": cat, "sous_categorie": sub, "priorite": prio
            }, on_conflict="mot_cle").execute()
            
            st.success("✅ Règle enregistrée !")
            st.rerun()

    regles = get_regles()
    st.dataframe(regles, width='stretch')

    st.divider()
    st.subheader("🔄 Appliquer les règles aux données existantes")
    st.info("Ce bouton va scanner toutes les transactions 'À classer' et appliquer vos règles enregistrées.")

    if st.button("Lancer la mise à jour globale", width='stretch'):
        regles_df = get_regles()
        df_all = load_transactions()
        
        # On filtre uniquement celles qui n'ont pas encore de catégorie
        a_classer = df_all[(df_all['categorie'] == "À classer") | (df_all['categorie'].isna())]
        
        if a_classer.empty:
            st.success("Toutes les transactions sont déjà catégorisées !")
        else:
            count = 0
            with st.status("Catégorisation en cours...", expanded=True) as status:
                for _, row in a_classer.iterrows():
                    new_cat, new_sub = categoriser(row['libelle'], regles_df)
                    
                    if new_cat != "À classer":
                        # Mise à jour dans Supabase
                        supabase.table("transactions").update({
                            "categorie": new_cat, 
                            "sous_categorie": new_sub
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
