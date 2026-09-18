# Méthodologie v2 — outil multi-projets piloté par les Business Cases Aurora

**Statut : spec de conception, pré-implémentation.** Ce document consolide ce qui a été établi
pendant la session de cadrage (méthode "grilling", voir `CONTEXT.md` pour le vocabulaire et
`docs/adr/0001` à `0004` pour les décisions), avant d'écrire le code des phases 2 à 6 du
`BRIEF_Claude_Code_Bankability_v2`. Chaque module, une fois implémenté, aura sa propre spec
rétrospective dans `docs/specs/` (même convention que le reste du projet) qui fera foi sur les
détails d'implémentation — ce document reste la référence sur l'**intention** et les **formules
de principe**.

Fichier source des faits ci-dessous : `sample_data/160926_BP_Stockage_Standalone__.xlsx`
(données fictives, format complet + onglets Aurora).

---

## 1. Moteur de revenu Aurora (`aur_cases.py`, `config_space.py`)

### 1.1 Source : `AU_Store`

18 configurations Aurora standalone (Q2 2026), une config = `{durée 2h/4h} x {tension
HTA/HTB1/HTB2/HTB3} x {TURPE Classique/Injection/Soutirage} x {gabarit 0/1}` — pas toutes les
combinaisons existent, seulement celles qu'Aurora a modélisées (voir la liste exacte dans
`AU_Store!AP2:AV19`).

Par config, deux courbes calendaires 2027-2060 (`AU_Store!B:S` pour RAW, `V:AM` pour TURPE) plus
une table de dégradation par op-year commune à toutes les configs (`AU_Store!AX:AZ`, reset à
l'op-year 15 pour repowering, `DegFactor_noRepo` sans reset) et deux constantes globales
(`RepowOpYear=15`, `EoL_perkW=118.44`, `AU_Store!BB1:BC2`).

**Clé de config** : deux clés distinctes coexistent, à ne pas confondre (voir `CONTEXT.md`) —
`AUStoreKey` (clé technique, en-tête des courbes, ex. `"4h HTB2 injection gabarit"`) et `DropKey`
(libellé humain de la liste déroulante `Source BP!B3`, ex. `"4h HTB2 Injection g1 (COD2030)"`).
La table `AU_Store!AP:AV` fait la correspondance entre les deux, plus les attributs
Duree/Tension/TURPE/Gabarit/ValideCOD.

**Calcul du revenu pour un COD donné** : lire la courbe RAW calendaire à partir de l'année de
COD, x `DegFactor(op-year)`, x puissance. **Courbe COD-indépendante x dégradation par op-year** —
ne jamais ré-indexer la courbe RAW elle-même par COD.

**Garde-fou COD2030** : 2 configs (`4h HTB2 injection gabarit`, `4h HTB2 soutirage gabarit`) ont
`ValideCOD=2030` — sélectionnables seulement si le projet a COD=2030. Toute autre config a
`ValideCOD="toute"`.

**Hors-scope explicite** (limite de fait, pas une décision) : le sélecteur `Source BP!B1` propose
aussi une source `CH` (feuille `CF CH`) — non modélisée en v2, doit lever un avertissement
explicite si choisie, jamais un repli silencieux sur Aurora. La feuille `CF Aurora` (30 configs,
détail par flux de marché, consommée par `dev_case_parser.py` pour le cas de développement en
amont) est un chemin de donnée **totalement différent**, non concerné par cette extension —
`dev_case.py` reste inchangé. L'onglet calculé `BP Aurora` du classeur est **masqué** et n'est pas
une source de validation fiable.

### 1.2 CAPEX/OPEX : `COPEX_library`

Table "CAPEX assumptions - AURORA" / "OPEX assumptions - AURORA" (`COPEX_library!26-46`), par
durée x tension, base année 2028, avec facteurs d'escalade par année de COD. `aur_cases.py`
réutilise **telle quelle** la logique d'escalade déjà validée et testée dans
`dev_case_parser.py`/`docs/specs/dev_case.md` — ne pas re-dériver une nouvelle logique
d'escalade. (Les chiffres cités dans le brief initial, 463 €/kW et 34,82 €/kW/an pour "2h HTA",
sont une approximation de mémoire — la table réelle donne 466,76 €/kW et 35,06 €/kW/an en base
2028 ; c'est la table qui fait foi, pas le souvenir.)

### 1.3 Validation (Phase 2)

Cible de non-régression : la Summary table Aurora externe (transmise hors classeur, jamais lue
par le moteur) — ex. Case 33 = 2027 / 2h / HTA standard / Central / no curtailment → TRI 9,9 %,
NPV -23,9 €/kW, payback 7,1 ans, PV of revenues 989,2 €/kW. **Toujours recalculer, jamais copier**
une valeur de cette table dans le moteur — elle sert uniquement de point de comparaison
recalculé-vs-reporté, au même titre que `ProjectInputs.reported_*` ailleurs dans l'app. L'écart
attendu (COD, CAPEX -10 %, OPEX -45 % entre le cas Aurora "discret" et le cas BP réel) doit rester
entièrement décomposable, pas un résidu inexpliqué.

Note : la Summary table externe couvre un espace bien plus large qu'`AU_Store` (scénarios
Low/Overbuild, curtailment ORO, configs co-localisées PV/éolien, tarif BT) — ces cas-là sont hors
de portée par construction puisqu'`AU_Store` ne couvre que standalone/Central/no-curtailment
(+2 configs gabarit). Utiliser uniquement les lignes standalone/Central/no-curtailment de la
Summary table comme jeux de test.

---

## 2. Extension dette et frais (`financial_engine.py`)

### 2.1 Constantes de financement des projets synthétiques — voir `docs/adr/0001`

Les projets du Configurateur n'ont pas de classeur `I-Project` réel. Défauts dans
`config/aur_financing_terms.yaml` (calibrés sur le fichier validé), overridables par projet :

| Paramètre | Défaut | Source |
|---|---|---|
| Marge dette senior | 150 bps | `I-Project!226` |
| Marge swap | +10 bps | `I-Project!229` |
| Frais upfront dette senior | 130 bps | `I-Project!224` |
| DSCR cible, revenu sécurisé (tolling/floor) | 1,20x | `I-Project!247` |
| DSCR cible, revenu merchant | 1,40x | `I-Project!248` |
| Maturité, full merchant | 10 ans | `I-Project!249` |
| Maturité, avec overlay contractuel | durée PPA + 3 ans | `I-Project!250` |
| Frais agrégateur, avant seuil | 0 % | `I-Project!44` |
| Frais agrégateur, après seuil | -7,5 % | `I-Project!45` |
| Seuil annuel de revenu | 0 €/MW/an | `I-Project!46` |
| Bascules net-énergie / net-TURPE | activées | `I-Project!42-43` |

Le mécanisme de frais d'agrégateur est repris **complet** (paliers avant/après seuil, deux
bascules d'assiette indépendantes) — pas simplifié en taux plat, malgré le "≈7,5 %" du brief
initial qui n'est qu'un cas particulier (seuil à 0 → tout le revenu est "après seuil").

### 2.2 Tiering DSCR sécurisé/merchant + maturité PPA+3

Le floor et le tolling créent du revenu sécurisé, qui pondère la cible DSCR vers 1,20x (au lieu
de 1,40x en full merchant) et allonge la maturité à durée du PPA + 3 ans (au lieu de 10 ans). Ce
tiering est **distinct** de celui déjà en place dans `risk_thresholds.yaml`
(`dscr_min_amber_contracted`/`_merchant`) qui sert au Risk Dashboard pour flagger — celui-ci
dimensionne réellement la dette (mode DSCR-sculpté déjà existant, étendu).

Deux régimes de dimensionnement à conserver : le plafond de gearing 70 % qui borde avant le DSCR
sur beaucoup de configs (DSCR alors un résultat ~2, pas une contrainte), et les configs à faible
revenu où le DSCR (1,20/1,40) devient mordant. Le moteur doit gérer les deux, comme aujourd'hui.

DSCR strictement **annuel** (piège Excel du trimestriel à ne jamais reproduire — voir brief
section 2), Average DSCR excluant l'année stub post-dette (années où dette EoP = 0).

Implémenté dans `core/contract_overlay.py` (`apply_contract_overlay`, `blended_target_dscr`,
`debt_maturity_years`) — voir `docs/specs/contract_overlay.md`. N'étend pas `financial_engine.py`
lui-même : ce module calcule les valeurs (`target_dscr`, `debt_tenor_years`) à passer telles
quelles à `compute_results(..., debt_sizing_mode="dscr")`.

---

## 3. Les trois stratégies (`strategy.py`)

Trois lectures du même moteur, jamais trois moteurs différents.

### 3.1 Développer & vendre au RtB

Méthodologie reprise de l'outil Optimus (PV) de QEnergy — voir `docs/adr/0004` et `CONTEXT.md`
(termes DSA/SPA/TSP).

- **DSA** (Development Service Agreement) : coût **fixe négocié** que l'acheteur paie à QEF
  (défaut = **marge de dev cible (50 k€/MW en 2h, 80 k€/MW en 4h, confirmé) + DEVEX** — construit
  ainsi, `DSA - DEVEX = marge cible` exactement quand SPA = 0, overridable par projet). Financable
  par dette : rejoint l'assiette
  "Total Uses" gearée, comme les ajouts DSRA/frais de financement déjà gérés pour le CAPEX
  (`docs/specs/financial_engine.md`, mode "Gearing fixe").
- Le moteur calcule Project IRR puis Equity IRR de l'acheteur sur Revenue/CAPEX/OPEX/DSA +
  structure de financement.
- **SPA** (Share Purchase Agreement) : le complément de prix, au-dessus du DSA, qui ramène le TRI
  equity réel de l'acheteur **exactement** à son TRI cible. Solve unique — mathématiquement
  identique à `acquisition.py`
  (`NPV(TRI cible acheteur, cashflows equity) - investissement equity requis`), appliqué à des
  cashflows qui incluent déjà le DSA. Peut être négatif si le DSA est trop élevé pour la
  rentabilité du projet.
- **TSP = DSA + SPA** = revenu total de QEF pour cette stratégie. Toujours afficher DSA et SPA
  séparément, jamais seulement leur somme (TSP positif avec SPA négatif reste possible et doit
  être visible).
- KPI : TSP en €, TSP en €/MW (repère marché 50-100 k€/MW), DSA, SPA, TRI equity réel de
  l'acheteur (pour vérifier qu'il retombe bien sur le TRI cible par construction).

### 3.2 Garder & exploiter

Le moteur actuel, sans changement : TRI projet, TRI equity, NPV sur la durée d'exploitation.

### 3.3 Racheter RtB & vendre au COD

Voir `docs/adr/0002`. QEF paie le prix RtB (calculé comme en 3.1, côté acheteur = QEF cette
fois), construit, puis revend au COD.

- **Valeur de revente au COD** (`docs/adr/0002`, amendé avant implémentation) : PV des cashflows
  non-levérisés post-COD (revenue+opex+turpe+eol des seules années d'exploitation) actualisés au
  TRI cible de l'acheteur à la revente — **pas** de dette re-dimensionnée : le mode "dscr" de
  `financial_engine` plafonne le principal par une assiette liée au CAPEX, nulle une fois l'actif
  construit, ce qui aurait annulé toute dette. Sous-estime donc la valeur réelle (pas de surcroît
  par effet de levier) — limite documentée, pas masquée.
- Rendement build-and-flip = valeur de revente au COD − prix d'achat RtB (calculé en 3.1) − coût
  de construction (CAPEX) − coût de portage (intérêts composés sur prix RtB + CAPEX, sur la durée
  de portage, taux forfaitaire — pas un tirage de dette de construction échelonné).
- KPI : rendement build-and-flip (€ et %), valeur au COD.
- Implémenté dans `core/strategy.py` (`compute_dev_and_sell`, `compute_hold_and_operate`,
  `compute_cod_resale_value_keur`, `compute_build_and_flip`) — voir `docs/specs/strategy.md`.

### 3.4 Nouveaux inputs business (non extraits du fichier)

Hypothèses ne venant d'aucune donnée du classeur — `config/aur_financing_terms.yaml` (défauts,
overridables par projet, même pattern que `docs/adr/0001`) :

| Paramètre | Valeur | Statut |
|---|---|---|
| Durée de portage/construction (stratégie 3, achat RtB → COD) | **18 mois** | Confirmé (2026-09-17) |
| DEVEX QEF, forfaitaire par projet — HTA | **150 k€** | Confirmé (2026-09-17) |
| DEVEX QEF, forfaitaire par projet — HTB1/HTB2/HTB3 | **300 k€** | Confirmé (2026-09-17), pas de distinction fournie entre les 3 classes HTB |
| DSA, marge de dev cible par MW — 2h (+ DEVEX, stratégie 1) | **50 k€/MW** | Confirmé (2026-09-18) |
| DSA, marge de dev cible par MW — 4h (+ DEVEX, stratégie 1) | **80 k€/MW** | Confirmé (2026-09-18) |
| TRI equity cible acheteur RtB — full merchant | **11 %** | Confirmé (2026-09-17), "cible Aurora" standalone merchant |
| TRI equity cible acheteur RtB — revenu sécurisé (floor/tolling) | **9 %** | **Provisoire** — à confirmer |
| Coût de portage, taux (stratégie 3) | **8 %** | **Provisoire** — à confirmer |

Le TRI cible pour un floor **partiel** (ni 100 % merchant ni 100 % sécurisé) interpole entre les
deux ancres ci-dessus au prorata de la part de revenu sécurisé sur la fenêtre considérée — même
principe que le tiering DSCR (section 2.2), voir `contract_overlay.blended_buyer_target_equity_irr`.

Le DEVEX est **forfaitaire**, pas un taux par MW (confirmé explicitement) : ce sont des coûts
largement fixes (études de raccordement, permitting, foncier), pas proportionnels à la puissance.
`net_margin_keur = TSP - DEVEX` est le profit réel de QEF pour la stratégie 1 — toujours affiché
à côté de TSP, jamais à sa place (voir `CONTEXT.md` "DEVEX"/"TSP").

Le TRI cible "revenu sécurisé" (9 %) reste marqué **provisoire** dans l'UI (Configurateur) tant
que l'équipe n'a pas confirmé — pas de silence sur son caractère non-validé. Implémenté dans
`core/aur_cases.py` (`devex_keur_for_tension`) et `core/contract_overlay.py`
(`blended_buyer_target_equity_irr`).

---

## 4. Portefeuille multi-projets (`portfolio.py`) + Configurateur

Chaque projet du Configurateur : nom, tension/segment, COD, gabarit, TURPE, puissance, durée
(2h/4h), durée d'exploitation, structure contractuelle (full merchant/floor/tolling) + prix et
durée floor/tolling, source des coûts (Aurora vs QEnergy — toujours les deux affichés, jamais un
remplacement silencieux), overrides gearing/taux/tenor/DSA/TRI-cible-acheteur.

Vue portefeuille : tableau tous projets x KPI (triable), graphiques de comparaison, tableaux
récap par stratégie.

Implémenté (`core/portfolio.py`, voir `docs/specs/portfolio.md`) : `ProjectConfig` + `run_portfolio`
exécutent les 3 stratégies par projet. **Pas encore fait** : comparaison Aurora vs QEnergy (pas de
bibliothèque de coûts QEnergy réutilisable identifiée à ce stade — voir "Questions ouvertes" de
`docs/specs/portfolio.md`) et l'UI Configurateur/Vue portefeuille (reste une couche `core/` pure,
comme les Phases 2-3).

---

## 5. Analyse globale (`global_sensitivity.py`) — voir `docs/adr/0003`

Espace des configs fini et petit (18 configs `AU_Store` x années de COD valides x
{full merchant, floor, tolling}) — énumération complète et mise en cache, pas un balayage
classique variable-par-variable. Exposé comme table triable/filtrable + heatmaps + coupes 1-2
variables à la volée depuis le même cache. Distinct de la sensibilité par projet (couche 4,
`sensitivity.py`) qui perturbe les inputs d'un seul projet autour de son cas de base.

Implémenté (`core/global_sensitivity.py`, `ui/global_sensitivity_tab.py` — onglet "Analyse
globale Aurora" dans `app.py`) : ~636 cas calculables sur 726 énumérés en ~1-2 secondes (90 cas
HTB3 exclus, `COPEX_library` ne couvre que HTA/HTB1/HTB2 — voir `docs/specs/aur_cases.md`), jamais
silencieusement absents (motif explicite retourné). Prix/durée floor-tolling du balayage global
**non confirmés** (80 k€/MW/an, 10 ans, partage 40 % — représentatifs, pas une donnée Aurora).
Voir `docs/specs/global_sensitivity.md`.

---

## 6. Garde-fous (rappel, cf. brief section 7)

Recalculé vs reporté partout, zéro zéro silencieux (config Aurora sans courbe ou clé manquante →
avertissement explicite, jamais 0), conventions de signe du README, spec rétrospective + tests
pour chaque nouveau module, configs COD-2030-only gardées, tous les toggles (frais de trading,
dégradation avec/sans repo, source des coûts) explicites et les deux valeurs affichées.
