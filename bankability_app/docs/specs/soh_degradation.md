# `core/soh_degradation.py` — courbe SoH reelle et seuil de repowering force

Spec retrospective.

## Objectif

Fournir la vraie courbe de State of Health (SoH) d'une batterie BESS, par duree (2h/4h), pour
pouvoir forcer un repowering quand le SoH devient trop bas — meme si l'optimisation economique
(Equity IRR) prefererait ne jamais repowerer. Consomme par `core/portfolio.py`
(`max_op_year_without_forced_repowering`, `repowering_candidate_years`,
`find_best_repowering_op_year`, `_effective_repowering_op_year`).

## Pourquoi ce module

Question de l'utilisateur, 2026-10-01, suite au constat (message precedent) que "ne jamais
repowerer" battait systematiquement toutes les annees de repowering candidates sur l'Equity IRR :
*"T'es sur que tu gardes une courbe de degradation correcte sur 30 ans sans repowering, c'est a
dire qu'a la fin la batterie doit etre HS ?"*

Reponse : non. `DegFactor_noRepo` (`AU_Store`, consomme par
`aur_cases.revenue_and_turpe_series`) degrade le **revenu**, pas la sante physique de la batterie
- ce n'est PAS le SoH qu'Aurora cite comme declencheur du repowering ("SoH triggering repowering:
66.00 %/68.67 % pour 2h/4h", PDF Aurora Q2 2026 Q2 26 FRA Flexible Energy Market Forecast, p.11).
Preuve : a l'annee 15 (= `RepowOpYear`, l'annee ou Aurora repowere dans son scenario central),
`DegFactor_noRepo` vaut encore 83.9 % - tres loin de 66 %. Consequence : sans ce module, "pas de
repowering" ne declenchait jamais (le `DegFactor_noRepo` ne descend jamais sous 71.4 %, meme a
l'annee 30, la derniere couverte par la table) - "ne jamais repowerer gagne toujours" etait un
artefact de donnee, pas un insight economique reel.

## Source des donnees

`config/soh_degradation.xlsx` (fourni par l'utilisateur, 2026-10-01, feuille "Hypotheses BESS") :
2 blocs "BESS 2h"/"BESS 4h", chacun avec les colonnes HTA et HTB2 - **verifiees identiques a la
decimale entre les 2 segments** (le SoH ne depend pas du segment reseau, seulement de la duree et
du nombre de cycles/jour : 1.5 cycle/jour pour 2h, 1 cycle/jour pour 4h) - donc une seule courbe
par duree, pas de dimension tension/segment. Parse par recherche de libelle ("Annee"/"System SoH"),
pas par adresse de cellule fixe (meme discipline que le reste de l'app, voir
`docs/specs/bp_parsing.md`).

La table couvre l'annee 0 (BoL, SoH=100%) a 15 (= `RepowOpYear` AU_Store) - Aurora n'a jamais eu
besoin d'aller plus loin, son scenario central repowere toujours a 15 ans.

## Decisions

- **Seuil de declenchement = `SOH_TRIGGER_REPOWERING_PCT = {2: 0.66, 4: 0.6867}`**, cite
  explicitement dans le PDF Aurora Q2 2026 ("Aurora estimates a 12.8% IRR if repowered at a SoH of
  66%", p.11 et p.162) et dans `AU_Store!SoH1 triggering repowering`. Source Aurora uniquement, pas
  verifie independamment - a ajuster si une meilleure donnee devient disponible.
- **Extrapolation lineaire au-dela de l'annee 15** (demande explicite de l'utilisateur, "pour 20
  ans tu peux faire une extrapolation lineaire") : regression sur les 5 dernieres annees connues
  (11-15), pas sur toute la courbe 0-15 - la courbe est legerement concave en debut de vie (fade
  calendaire/cyclage plus rapide au depart, physique Li-ion classique : 2h passe de -6 pt la 1ere
  annee a -1.5 pt/an stabilise des l'annee ~10) ; une regression globale biaiserait l'extrapolation
  vers une pente trop forte. Pentes observees sur la queue : -1.5 pt/an (2h), -1.0 pt/an (4h),
  remarquablement constantes sur 11-15 (verifie a l'oeil : chaque delta consecutif vaut exactement
  la pente retenue).
- **`max_op_year_before_forced_repowering(duree_h)`** : dernier op-year ou le SoH extrapole reste
  >= au seuil. Resultat avec les donnees actuelles : **17 pour 2h** (SoH(17)=0.66 pile, SoH(18)=
  0.645 < seuil), **22 pour 4h** (SoH(22)=0.69 >= 0.6867, SoH(23)=0.68 < seuil). Le 2h decroche plus
  tot malgre un seuil plus bas (66 % vs 68.67 %) - le cyclage plus intensif (1.5 vs 1/jour) domine.
- **Pas de dependance circulaire avec `core/aur_cases.py`/`core/portfolio.py`** : ce module ne
  connait que la courbe SoH et le seuil, jamais les revenus/CAPEX/OPEX - c'est `portfolio.py` qui
  fait le lien (voir docs/specs/portfolio.md, section repowering).

## Questions ouvertes

- **Le fichier source (`config/soh_degradation.xlsx`) n'est pas (encore) un fichier QEF interne
  maintenu/mis a jour comme `copex_icp.xlsx`** - fourni une fois par l'utilisateur le 2026-10-01
  pour debloquer ce fix, statut de mise a jour future (mensuelle ? jamais ?) non precise.
- **Extrapolation lineaire non confirmee comme hypothese physique a long terme** - une batterie
  Li-ion degrade typiquement en S (fade initial rapide, plateau, puis acceleration en fin de vie
  "knee point") plutot que lineairement a l'infini ; l'extrapolation lineaire reste une
  approximation raisonnable sur l'horizon teste (annees 15-25), pas verifiee au-dela.
- **HTA n'a pas de donnees SoH separees dans le fichier source** (seulement HTA et HTB2, verifiees
  identiques) - suppose que HTB1/HTB3 suivraient la meme courbe que HTA/HTB2 (le SoH ne depend que
  de la duree, pas du segment, d'apres les donnees disponibles), jamais verifie pour HTB1/HTB3
  specifiquement faute de colonnes dans le fichier.
