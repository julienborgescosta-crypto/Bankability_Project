# Moteur financier (IRR / NPV / dette / DSCR)

Spec retrospective.

## Objectif

Calculer, a partir d'un `ProjectInputs` et d'hypotheses de financement (gearing, taux, tenor),
les metriques de bancabilite standard : Project IRR, Equity IRR, NPV, DSCR annuel (min/moyen).
Sert de socle a `scenarios.py`, `sensitivity.py`, `stress_test.py` (tous appellent
`compute_results` avec des multiplicateurs differents plutot que de dupliquer la logique).

## Fichiers impactes

- `core/financial_engine.py` — `annuity_payment`, `debt_amount_from_annuity`, `compute_results`
- `core/models.py` — `YearlyResult`, `ProjectResults`

## Logique metier

**Deux modes de dimensionnement de la dette**, choisis via `debt_sizing_mode` ("gearing" par
defaut, ou "dscr") :

1. **`"gearing"`** : `Debt = gearing_pct x CAPEX total`, `Equity = CAPEX total - Debt`, service
   de la dette en **annuite constante** sur `debt_tenor_years` au taux `interest_rate`. Le DSCR
   est un pur *output*.
2. **`"dscr"`** : la dette est **sculptee** pour que `CFADS / service >= target_dscr` sur toute
   la fenetre de tenor, plafonnee par `gearing_pct x CAPEX` — reproduit la logique reelle du BP
   (`I-Project` : "Target DSCR" + "Gearing max"), ou c'est l'utilisateur qui dimensionne deja sa
   dette en fonction du DSCR plutot que l'inverse. Le DSCR devient (en partie) un *input*.
   Necessite `target_dscr` (parametre, ou `ProjectInputs.target_dscr` extrait d'`I-Project`) —
   leve `ValueError` si absent des deux.

   Calcul : `debt_amount_from_annuity` est l'inverse exact de `annuity_payment` (memes
   parametres rate/n_periods, resout le principal a partir du paiement au lieu de l'inverse).
   Le paiement maximal soutenable = `min(CFADS de la fenetre de tenor) / target_dscr` — le
   **pire** CFADS observe dans la fenetre determine la dette maximale, pas la moyenne. Quand ce
   pire CFADS est constant sur toute la fenetre (cas de test), le DSCR resultant est **exactement**
   egal a `target_dscr` chaque annee de la fenetre — proprete verifiee en test
   (`test_dscr_sizing_hits_target_exactly_when_not_gearing_capped`).

   **Sequencement chronologique pour la 2e tranche.** La tranche initiale est fermee avant que
   le repowering n'existe : elle est donc dimensionnee **en isolation**, sans se soucier d'un
   futur repowering. La tranche repowering, elle, est dimensionnee ensuite contre le CFADS **net**
   du service de la dette initiale encore actif pendant les annees de chevauchement — pas de
   dependance circulaire, et ca correspond a l'ordre reel des evenements (le repowering
   n'existe pas encore quand la dette initiale est structuree).

Quel que soit le mode, le service de la dette resultant (constant par tranche) est ensuite
applique par `_tranche_service_schedule` sur sa fenetre de tenor, exactement comme avant.
Ecart assume avec le "DSCR reel" du BP source (DSRA, commitment fees, cash sweep, non
modelises) — affiche cote a cote dans l'UI (`ProjectInputs.reported_dscr_avg/min`) plutot que
masque, meme en mode `"dscr"` (voir "Questions ouvertes" ci-dessous : le mode `"dscr"` rapproche
les chiffres du BP reel, il ne les reproduit pas exactement).

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
  `repowering_gearing_pct`/`repowering_interest_rate`/`repowering_debt_tenor_years`, et en mode
  `"dscr"` le meme `target_dscr` pour les deux tranches).
- Le service de la dette total d'une annee d'exploitation = service initial (s'il reste dans sa
  fenetre de `debt_tenor_years` depuis la 1ere annee d'exploitation) + service repowering (s'il
  reste dans sa fenetre de `repowering_debt_tenor_years` depuis la 1ere annee d'exploitation
  *apres* le repowering) — les deux fenetres (`_tranche_service_schedule`, une par tranche) sont
  independantes et peuvent se chevaucher.
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

Dimensionnement par DSCR : `test_dscr_sizing_requires_target_dscr` (leve sans target),
`test_unknown_debt_sizing_mode_raises`, `test_dscr_sizing_hits_target_exactly_when_not_gearing_capped`
(CFADS constant -> DSCR resultant exactement egal a la cible), `test_dscr_sizing_capped_by_gearing_when_target_is_lax`
(la dette DSCR-sizee reste plafonnee par le gearing max), `test_dscr_sizing_matches_gearing_mode_debt_amount_at_equivalent_target`
(sanity check inter-modes : meme dette -> meme DSCR, quel que soit le mode qui l'a produite),
`test_dscr_sizing_two_tranches_sequential` (sur `repowering_inputs`, verifie le sequencement
chronologique initiale-puis-repowering).

## Questions ouvertes

- Le moteur ne modelise pas de DSRA, commitment fees, ni cash sweep — le DSCR calcule est donc
  structurellement different (souvent plus favorable) que celui d'un vrai financement senior
  sculpte, **meme en mode `"dscr"`**. Documente dans l'UI (`ui/overview.py` affiche les deux
  valeurs), pas cache.
- **Le mode `"dscr"` rapproche les chiffres du BP reel sans les reproduire exactement.** Valide
  sur Belle Epine (`target_dscr` = 1.5x) : le DSCR min resultant vaut exactement 1.5x (par
  construction), tres different du DSCR min reellement rapporte dans le BP (0.10x). Hypothese
  la plus probable : la dette reelle du BP a ete dimensionnee **une seule fois, a la cloture
  financiere**, sur un cas de revenus different (probablement plus favorable) de celui que
  reflete aujourd'hui la serie `O-Financials` — les covenants DSCR sont testes contre les
  previsions **live/actualisees**, qui peuvent avoir diverge du cas de sizing initial. Notre
  moteur, lui, dimensionne toujours contre la serie de revenus **courante** (celle du fichier
  charge), donc les deux ne peuvent structurellement pas coincider sauf si le cas de sizing
  d'origine est identique au cas actuel. Pas un bug ; une limite methodologique documentee.
- La detection de la tranche repowering (2e sortie de CAPEX dans la serie) suppose une seule
  operation de repowering. Un projet avec 2+ repowering successifs verrait tous les CAPEX a
  partir du 2e regroupes dans une seule et meme tranche "repowering" (simplification, cas non
  observe dans les fichiers reels a ce jour).
- La fenetre de dimensionnement DSCR (`cfads_list[first_op_index : first_op_index + tenor]`)
  suppose qu'aucune sortie de CAPEX n'interrompt la fenetre de la tranche initiale — vrai pour
  tous les fichiers reels vus a ce jour (CAPEX initial isole, repowering eventuel bien plus
  tard), mais non verifie explicitement si ce n'etait pas le cas.
