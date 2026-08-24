# Acquisition (M&A) — prime d'acquisition maximale

Spec retrospective.

## Objectif

Repondre a une question differente de la bancabilite pour developpement interne : *"si on
n'est pas en train de developper ce projet nous-memes, combien peut-on payer pour l'acquerir
(SPV) et quand meme tenir un rendement equity cible ?"*. Reprend la methode fournie par
l'utilisateur (source : slides "Solving for the Maximum Acquisition Premium" — voir capture
dans l'historique de conversation, pas de lien externe) : on ne suppose jamais la prime
d'acquisition en entree, on la resout comme une valeur residuelle.

## Fichiers impactes

- `core/acquisition.py` — `AcquisitionValuation`, `compute_acquisition_valuation`,
  `run_acquisition_sensitivity`, `STAGE_BENCHMARKS`
- `core/sensitivity.py` — `shocked_compute_kwargs` extrait de `run_sensitivity` pour etre
  reutilise par `run_acquisition_sensitivity` (meme logique de choc, deux metriques de sortie
  differentes)
- `ui/acquisition_tab.py` — onglet "Acquisition (M&A)", derriere une case a cocher
- `app.py` — 7e onglet, recoit `inputs`, `base_result`, `debt_kwargs` (memes hypotheses de
  financement que le reste de l'app, y compris la dette de repowering si presente)

## Logique metier

**Formule centrale** (identique a celle montree par l'utilisateur) :

```
Purchase Price + Base Equity Investment  <=  PV(flux equity futurs @ rendement cible)
```

`Base Equity Investment` = `ProjectResults.equity_amount_keur` (deja calcule par
`financial_engine.compute_results`, tient compte du gearing courant et, le cas echeant, de la
dette de repowering — voir `financial_engine.md`).

**La prime maximale = NPV de la serie de cashflows equity au taux cible, pas un calcul separe.**
`equity_cashflow_keur` porte deja son propre signe (negatif pendant les annees de CAPEX — y
compris un futur repowering — positif/negatif en exploitation). Actualiser cette serie complete
au rendement cible avec `numpy_financial.npv` donne directement le "headroom" :

```
headroom = NPV(target_irr, equity_cashflow_series)
VA des flux futurs = headroom + Base Equity Investment
```

Si `headroom > 0` : le projet, a son cout de base, degage plus de valeur que le rendement
cible n'en exige — on peut payer une prime au-dessus de l'equity de base. Si `headroom < 0` :
le projet ne couvre meme pas le rendement cible au prix de base — il faudrait une **decote**,
pas une prime (l'UI l'affiche explicitement, pas de nombre negatif silencieux presente comme
une "prime").

**Sensibilite de la prime** (`run_acquisition_sensitivity`) : reutilise exactement les memes
5 variables et chocs que `sensitivity.run_sensitivity` (Revenue, CAPEX, OPEX, Interest Rate,
Debt Ratio), mais rapporte le headroom au lieu de l'Equity IRR/DSCR pour chaque choc — repond a
"qu'est-ce qui bouge le plus ma marge de negociation ?". Le "grid cost" de l'exemple source n'a
pas d'equivalent direct dans ce modele ; OPEX en est le proxy le plus proche (mentionne dans
l'UI).

**Reperes de marche** (`STAGE_BENCHMARKS`) : purement informatifs, **jamais utilises dans un
calcul** — trois exemples reels par stade de developpement (droits de developpement, RTB,
actifs en exploitation) donnes par l'utilisateur comme contexte marche. Affiches separement de
la prime calculee pour ne pas laisser croire qu'ils la determinent.

## Tests

`tests/test_acquisition.py` :
- `test_headroom_matches_npv_of_equity_series` — validation croisee directe contre
  `numpy_financial.npv` applique independamment
- `test_headroom_is_near_zero_when_target_equals_actual_irr` — propriete mathematique de la
  NPV au taux egal a l'IRR (~0), verification robuste sans dependre de chiffres arbitraires
- monotonicite : rendement cible plus bas -> headroom positif ; plus haut -> headroom negatif ;
  choc Revenue positif -> headroom croissant ; choc CAPEX positif -> headroom decroissant
- `run_acquisition_sensitivity` a choc nul retombe exactement sur la valorisation de base

## Questions ouvertes

- Le proxy OPEX pour "grid cost" est une approximation — si le besoin d'un choc isole sur les
  couts reseau se confirme, il faudrait d'abord resoudre l'extraction du detail TURPE/reseau
  par flux (meme limitation que `bp_parsing.md`, "Detail des revenus par flux").
- Les reperes de marche sont figes en dur dans le code (donnees ponctuelles fournies par
  l'utilisateur) — pas de mecanisme de mise a jour ; a REVOIR si des comparables plus recents
  doivent remplacer ceux-ci.
