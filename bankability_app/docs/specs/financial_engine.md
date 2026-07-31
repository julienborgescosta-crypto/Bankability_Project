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
cashflows deduite independamment (pas en rappelant `compute_results`).

## Questions ouvertes

- Le moteur ne modelise pas de DSRA, commitment fees, ni cash sweep — le DSCR calcule est donc
  structurellement different (souvent plus favorable) que celui d'un vrai financement senior
  sculpte. Documente dans l'UI (`ui/overview.py` affiche les deux valeurs), pas cache.
