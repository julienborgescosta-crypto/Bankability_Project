# Moteur financier (IRR / NPV / dette / DSCR)

Spec retrospective.

## Objectif

Calculer, a partir d'un `ProjectInputs` et d'hypotheses de financement (gearing, taux, tenor),
les metriques de bancabilite standard : Project IRR, Equity IRR, NPV, DSCR annuel (min/moyen).
Sert de socle a `scenarios.py`, `sensitivity.py`, `stress_test.py` (tous appellent
`compute_results` avec des multiplicateurs differents plutot que de dupliquer la logique).

## Fichiers impactes

- `core/financial_engine.py` — `annuity_payment`, `debt_amount_from_annuity`, `present_value`,
  `sculpt_debt_service`, `capitalized_construction_interest`, `compute_results`
- `core/models.py` — `YearlyResult`, `ProjectResults`, `ProjectInputs.senior_debt_upfront_fee_pct`
- `config/bp_mapping_full.yaml` — `i_project_fields.senior_debt_upfront_fee_pct` ("Senior Debt
  Upfront fee" d'`I-Project`, offset 2)

## Logique metier

**Deux modes de dimensionnement de la dette**, choisis via `debt_sizing_mode` ("gearing" par
defaut, ou "dscr"). Le mode `"gearing"` est **totalement insensible** a tout ce qui suit (frais,
IDC, sculpting) — zero risque de regression sur son comportement existant, verifie en test
(`test_gearing_mode_ignores_upfront_fee_and_idc`).

1. **`"gearing"`** : `Debt = gearing_pct x CAPEX total`, `Equity = CAPEX total - Debt`, service
   de la dette en **annuite constante** sur `debt_tenor_years` au taux `interest_rate`. Le DSCR
   est un pur *output*.
2. **`"dscr"`** : la dette est **sculptee** (`sculpt_debt_service`). L'utilisateur nous a
   communique le code VBA reel de son BP (`Sub Debt_Sizing()`, onglet `C-SPV`) : il resout le
   meme probleme par **iteration circulaire** (copier-coller en valeurs jusqu'a ce qu'une
   tolerance de convergence soit atteinte), et prend en compte des frais (Upfront Fee,
   Commitment Fee, DSRF Upfront/Commitment Fee) et des interets pendant la construction
   distincts des interets de la periode de remboursement. Notre version resout la partie
   "sculpting pur" en **forme fermee** (pas d'iteration necessaire, voir ci-dessous), et
   approxime une partie du reste (frais upfront, interets intercalaires capitalises) — sans
   reproduire la circularite complete de la macro (DSRA en tant que facility separee,
   commitment fee, cash sweep : non modelises, voir "Questions ouvertes"). Necessite
   `target_dscr` (parametre, ou `ProjectInputs.target_dscr` extrait d'`I-Project`) — leve
   `ValueError` si absent des deux.

   **Sculpting reel, pas une annuite plafonnee par la pire annee.** `sculpt_debt_service` fixe
   `service_annee = CFADS_annee / target_dscr` pour **chaque** annee de la fenetre de tenor (pas
   seulement la pire) — le DSCR resultant est exactement egal a la cible **toutes les annees**
   de la fenetre, pas seulement dans la pire. `present_value(service, rate)` donne alors le
   principal : c'est l'identite financiere standard obligation/pret (la somme des service
   actualises au taux du pret reconstruit exactement le principal qui, amorti selon ce meme
   service, s'eteint a zero en fin de tenor) — **aucune iteration necessaire**, malgre le fait
   que ceci reproduit ce que la macro resout par iteration. Verifie en test avec un CFADS
   variable d'une annee sur l'autre (`test_dscr_sculpting_tracks_varying_cfads`) — avec
   `simple_inputs`/`repowering_inputs` (CFADS constant sur toute la periode), un sculpting reel
   et une simple annuite plafonnee sont indiscernables, d'ou ce fixture dedie.

   **Plafond de gearing, gonfle par les frais et les interets intercalaires.**
   `_size_tranche_by_dscr` plafonne le principal sculpte par
   `gearing_pct x (CAPEX + IDC + frais upfront)` plutot que juste `gearing_pct x CAPEX` :
   - `capitalized_construction_interest` : interets courus sur le tirage pendant la
     construction, **capitalises** (ajoutes au principal, pas payes cash — pas de CFADS
     disponible avant la mise en service). Convention mi-annee (le tirage d'une annee de
     construction accumule un demi-an d'interets sur sa propre annee, puis un an complet par
     annee de construction supplementaire jusqu'a la mise en service) — seule granularite
     disponible, le BP ne donne pas de date de tirage precise (annuelle, pas mensuelle).
   - Frais upfront (`ProjectInputs.senior_debt_upfront_fee_pct`, `I-Project` "Senior Debt
     Upfront fee") : % du montant tire, paye une fois a la cloture financiere.
   - **Approximation en une seule passe** : IDC et frais sont calcules a partir du tirage
     "CAPEX x gearing" brut, pas resolus comme un systeme circulaire complet avec le plafond
     qu'ils gonflent eux-memes en retour (contrairement a la vraie macro, qui, elle, itere) —
     assume car frais/IDC representent typiquement quelques % du CAPEX (effet de 2nd ordre
     negligeable). Aucun champ equivalent n'est extrait pour la tranche repowering (absent
     d'`I-Project`) — IDC seul s'applique a cette tranche, pas de frais upfront.
   - **Frais/IDC n'affectent que le plafond de dette, pas les cashflows.** Ils ne sont pas
     ajoutes comme cout cash au CFADS, au CAPEX total ou a l'equity ailleurs dans le modele —
     simplification assumee.

   Si le principal sculpte non-plafonne depasse ce plafond, le **service** (pas seulement le
   principal) est mis a l'echelle uniformement (`scale = plafond / principal_non_plafonne`) — le
   DSCR resultant devient alors superieur a la cible chaque annee, de facon uniforme.

   **Sequencement chronologique pour la 2e tranche.** La tranche initiale est fermee avant que
   le repowering n'existe : elle est donc dimensionnee **en isolation**, sans se soucier d'un
   futur repowering. La tranche repowering, elle, est dimensionnee ensuite contre le CFADS
   **net** du service de la dette initiale encore actif pendant les annees de chevauchement —
   pas de dependance circulaire, et ca correspond a l'ordre reel des evenements (le repowering
   n'existe pas encore quand la dette initiale est structuree).

Quel que soit le mode, le service de la dette resultant (constant en mode gearing, variable par
annee en mode dscr) est ensuite applique par `_tranche_service_schedule` sur sa fenetre de
tenor — generalisee pour accepter soit une annuite constante (float), soit une liste sculptee.
`ProjectResults.debt_service_initial_keur`/`debt_service_repowering_keur` (des scalaires, pour
affichage synthetique dans l'UI) rapportent la **moyenne** des annees actives de chaque
tranche (`_mean_active`) — egale a l'annuite constante en mode gearing, une vraie moyenne en
mode dscr.

Ecart assume avec le "DSCR reel" du BP source — affiche cote a cote dans l'UI
(`ProjectInputs.reported_dscr_avg/min`) plutot que masque, meme en mode `"dscr"` (voir
"Questions ouvertes" ci-dessous : le mode `"dscr"` rapproche les chiffres du BP reel, il ne les
reproduit pas exactement).

**Dette de repowering = 2e tranche independante.** Le classeur complet montre (`I-Project`
section 6 "Financing") que la dette de repowering est une facility a part entiere — sa propre
date de closing, son propre gearing, son propre taux, sa propre maturite — distincte de la
dette senior initiale. `compute_results` reproduit ce decoupage :
- Detection : la 2e annee avec une sortie de CAPEX non nulle dans `capex_keur` (s'il y en a
  une) marque le debut de la tranche repowering ; tout CAPEX a partir de cette annee (y compris
  une eventuelle 3e sortie, cas non observe mais gere par simplification) est rattache a cette
  tranche plutot qu'a l'initiale.
- Chaque tranche a son propre `capex_total_*`, `debt_amount_*`, `equity_amount_*`,
  `debt_service_*`, propre gearing/taux/tenor
  (`repowering_gearing_pct`/`repowering_interest_rate`/`repowering_debt_tenor_years`), et en
  mode `"dscr"` le meme `target_dscr` pour les deux tranches.
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

Dimensionnement par DSCR :
- `test_dscr_sizing_requires_target_dscr` (leve sans target), `test_unknown_debt_sizing_mode_raises`
- `test_dscr_sizing_hits_target_exactly_when_not_gearing_capped`,
  `test_dscr_sizing_matches_gearing_mode_debt_amount_at_equivalent_target` (sanity check
  inter-modes : meme dette -> meme DSCR, quel que soit le mode qui l'a produite)
- `test_dscr_sizing_capped_by_gearing_when_target_is_lax` (plafond recalcule
  `gearing x (CAPEX + IDC)`, pas juste `gearing x CAPEX`)
- `test_dscr_sizing_two_tranches_sequential` (sur `repowering_inputs`, sequencement
  chronologique initiale-puis-repowering)
- Fixture dediee `varying_cfads_inputs` (CFADS different chaque annee, contrairement aux autres
  fixtures ou le CFADS est constant) + `test_dscr_sculpting_tracks_varying_cfads` : preuve que
  le service de la dette **varie** annee par annee en suivant le CFADS (vrai sculpting), avec un
  DSCR exactement egal a la cible **chaque** annee malgre cette variation
- `present_value`/`sculpt_debt_service`/`capitalized_construction_interest` : tests unitaires
  directs (formule, cas limites : taux nul, cible nulle/negative, aucun tirage)
- `test_upfront_fee_increases_the_gearing_cap`, `test_gearing_mode_ignores_upfront_fee_and_idc`
  (isolation confirmee : le mode gearing reste identique avec ou sans frais renseignes)

## Questions ouvertes

- **Le mode `"dscr"` se rapproche de la vraie macro sans la reproduire.** Non modelises : DSRA
  comme facility de reserve separee (avec ses propres frais upfront/commitment), Commitment Fee
  sur la dette senior (convention "% of LT margin" observee dans `I-Project`, necessiterait un
  echeancier de tirage qu'on n'a pas), cash sweep. La macro reelle resout tout ca simultanement
  par iteration circulaire ; nous resolvons uniquement le sculpting pur en forme fermee et
  approximons IDC + frais upfront en une seule passe (voir "Logique metier" ci-dessus).
- **Meme corrige, le mode `"dscr"` ne reproduit pas exactement le DSCR reel du BP.** Valide sur
  Belle Epine (`target_dscr` = 1.5x, upfront fee 1.3%) : le sculpting fait remonter la dette de
  8,0 M€ (ancienne version, annuite plafonnee par la pire annee) a 11,3 M€ (sculpting reel, DSCR
  min = DSCR moyen = 1.5x exactement) — mais toujours tres different du DSCR min reellement
  rapporte dans le BP (0.10x). Hypothese la plus probable : la dette reelle du BP a ete
  dimensionnee **une seule fois, a la cloture financiere**, sur un cas de revenus different
  (probablement plus favorable) de celui que reflete aujourd'hui la serie `O-Financials` — les
  covenants DSCR sont testes contre les previsions **live/actualisees**, qui peuvent avoir
  diverge du cas de sizing initial. Notre moteur, lui, dimensionne toujours contre la serie de
  revenus **courante** (celle du fichier charge), donc les deux ne peuvent structurellement pas
  coincider sauf si le cas de sizing d'origine est identique au cas actuel. Pas un bug ; une
  limite methodologique documentee.
- La detection de la tranche repowering (2e sortie de CAPEX dans la serie) suppose une seule
  operation de repowering. Un projet avec 2+ repowering successifs verrait tous les CAPEX a
  partir du 2e regroupes dans une seule et meme tranche "repowering" (simplification, cas non
  observe dans les fichiers reels a ce jour).
- La fenetre de dimensionnement DSCR (`cfads_list[first_op_index : first_op_index + tenor]`)
  suppose qu'aucune sortie de CAPEX n'interrompt la fenetre de la tranche initiale — vrai pour
  tous les fichiers reels vus a ce jour (CAPEX initial isole, repowering eventuel bien plus
  tard), mais non verifie explicitement si ce n'etait pas le cas.
