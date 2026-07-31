# Moteur financier (IRR / NPV / dette / DSCR)

Spec retrospective.

## Objectif

Calculer, a partir d'un `ProjectInputs` et d'hypotheses de financement (gearing, taux, tenor),
les metriques de bancabilite standard : Project IRR, Equity IRR, NPV, DSCR annuel (min/moyen).
Sert de socle a `scenarios.py`, `sensitivity.py`, `stress_test.py` (tous appellent
`compute_results` avec des multiplicateurs differents plutot que de dupliquer la logique).

## Fichiers impactes

- `core/financial_engine.py` — `annuity_payment`, `compute_results`
- `core/models.py` — `YearlyResult`, `ProjectResults`

## Logique metier

**Dette a gearing fixe (decision produit)** : pas de dette sculptee iterative (contrairement au
vrai modele du classeur complet, qui a une dette senior avec DSRA/commitment fees/cash sweep).
`Debt = gearing_pct x CAPEX total`, `Equity = CAPEX total - Debt`, service de la dette en
**annuite constante** sur `debt_tenor_years` au taux `interest_rate`. Ecart assume avec le
"DSCR reel" du BP source pour les classeurs complets — affiche cote a cote dans l'UI
(`ProjectInputs.reported_dscr_avg/min`) plutot que masque.

**Dette de repowering = 2e tranche independante.** Le classeur complet montre (`I-Project`
section 6 "Financing") que la dette de repowering est une facility a part entiere — sa propre
date de closing, son propre gearing, son propre taux, sa propre maturite — distincte de la
dette senior initiale. `compute_results` reproduit ce decoupage :
- Detection : la 2e annee avec une sortie de CAPEX non nulle dans `capex_keur` (s'il y en a
  une) marque le debut de la tranche repowering ; tout CAPEX a partir de cette annee (y compris
  une eventuelle 3e sortie, cas non observe mais gere par simplification) est rattache a cette
  tranche plutot qu'a l'initiale.
- Chaque tranche a son propre `capex_total_*`, `debt_amount_*`, `equity_amount_*`,
  `debt_service_*` (annuite independante, propre gearing/taux/tenor -
  `repowering_gearing_pct`/`repowering_interest_rate`/`repowering_debt_tenor_years`).
- Le service de la dette total d'une annee d'exploitation = service initial (s'il reste dans sa
  fenetre de `debt_tenor_years` depuis la 1ere annee d'exploitation) + service repowering (s'il
  reste dans sa fenetre de `repowering_debt_tenor_years` depuis la 1ere annee d'exploitation
  *apres* le repowering) — les deux compteurs (`op_year_counter` / `op_year_counter_repowering`)
  sont independants et peuvent se chevaucher.
- Retro-compatible : sans 2e sortie de CAPEX dans la serie, `capex_total_repowering_keur` et
  tous les champs `*_repowering_keur` de `ProjectResults` restent a 0 — comportement identique
  a avant l'introduction de cette logique (voir `test_no_repowering_tranche_when_single_capex_year`).

**CFADS = simple somme des composantes deja signees** : `revenue + opex + turpe + end_of_life`.
`opex`/`turpe` sont deja negatifs dans les donnees source (voir `bp_parsing.md`). Aucune
soustraction dans la formule — un `-opex` aurait *ajoute* le cout au lieu de le retrancher.

**Le service de la dette ne demarre qu'a la premiere annee avec revenu non nul.** Une annee
sans CAPEX mais aussi sans revenu (ramp-up/construction differee, COD posterieure au dernier
decaissement CAPEX) n'est pas une annee d'exploitation : `first_op_index` (premiere annee ou
`revenue != 0`) sert de frontiere. Les annees avant cette frontiere n'ont ni DSCR ni service de
dette ; leur CFADS (potentiellement negatif) est absorbe integralement par l'equity.

**Part CAPEX financee par l'equity, au prorata de l'annee.** Pour une annee avec CAPEX non nul,
`equity_share = equity_amount * (capex_out / capex_total)` — `capex_out` etant negatif, le
resultat est negatif (une sortie de cash pour l'actionnaire), pas positif.

**NPV via `numpy_financial.npv(wacc, net_cashflow_series)`**, ou `net_cashflow_series[0]`
(l'annee de construction) n'est pas actualisee (`(1+wacc)^0`) — coherent avec la convention
"CAPEX paye a la date 0" du secteur.

## Bugs corriges pendant l'implementation (a ne pas reintroduire)

1. **Signe CFADS inverse** : premiere version faisait `revenue - opex - turpe`, correct
   seulement si `opex`/`turpe` etaient des magnitudes positives — faux, ils sont deja negatifs
   dans les donnees source. Corrige en simple somme. Detecte via la validation croisee IRR
   (voir `bp_parsing.md`).
2. **Signe de la part CAPEX equity inverse** : `capex_out / -capex_total` au lieu de
   `capex_out / capex_total` — produisait un flux equity **positif** pendant la construction
   (au lieu d'une sortie de cash), donc un IRR equity absurdement optimiste.
3. **DSCR negatif sur annee de ramp-up** : avant l'introduction de `first_op_index`, toute
   annee avec `capex_out == 0` etait traitee comme une annee d'exploitation, y compris une
   annee de construction tardive sans CAPEX ni revenu — le service de la dette s'appliquait
   alors a un CFADS negatif, donnant un DSCR negatif absurde. Regression coverte par
   `tests/test_financial_engine.py::test_ramp_up_year_without_capex_or_revenue_has_no_debt_service`.

## Tests

`tests/test_financial_engine.py` — fixture `simple_inputs` (3 annees, chiffres ronds
verifiables a la main) pour les breakdowns annuels et agregats ; fixture `ramp_up_inputs`
(regression bug #3) ; comparaison IRR/NPV contre `numpy_financial` applique a une liste de
cashflows deduite independamment (pas en rappelant `compute_results`). Fixture
`repowering_inputs` (11 annees, 2 sorties de CAPEX a termes de financement distincts) pour la
dette a 2 tranches : `test_repowering_tranche_uses_its_own_financing_terms`,
`test_debt_service_windows_dont_overlap_after_initial_tenor_expires` (verifie que chaque
fenetre de tenor s'applique independamment, y compris les annees ou aucune des deux dettes ne
sert), `test_no_repowering_tranche_when_single_capex_year` (non-regression sans repowering).

## Questions ouvertes

- Le moteur ne modelise pas de DSRA, commitment fees, ni cash sweep — le DSCR calcule est donc
  structurellement different (souvent plus favorable) que celui d'un vrai financement senior
  sculpte. Documente dans l'UI (`ui/overview.py` affiche les deux valeurs), pas cache.
- La detection de la tranche repowering (2e sortie de CAPEX dans la serie) suppose une seule
  operation de repowering. Un projet avec 2+ repowering successifs verrait tous les CAPEX a
  partir du 2e regroupes dans une seule et meme tranche "repowering" (simplification, cas non
  observe dans les fichiers reels a ce jour).
