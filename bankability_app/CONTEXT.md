# Bankability_Project — Aurora multi-projets (v2)

Extension multi-projets de l'outil de bancabilité BESS, pilotée par les Business Cases Aurora
(fichier échantillon `sample_data/160926_BP_Stockage_Standalone__.xlsx`). Ce contexte couvre le
vocabulaire propre à cette extension — pour le vocabulaire du moteur financier existant (couches
1-6, cas de développement), voir `README.md` et `docs/specs/`.

## Language

**AU_Store**:
La feuille source des 18 configurations Aurora standalone (Q2 2026) : courbes RAW (revenu net
des charges réseau, brut de TURPE, non dégradé, €/kW, calendaire 2027-2060) et courbes TURPE par
config, plus une table de dégradation par op-year commune à toutes les configs (reset à
l'op-year 15 pour repowering) et une table de métadonnées par config (Duree, Tension, TURPE,
Gabarit, ValideCOD).
_Avoid_: "Aurora sheet", "courbe Aurora" (trop vague — préciser RAW vs TURPE vs métadonnées)

**AUStoreKey**:
La clé technique d'une configuration dans `AU_Store`, ex. `"4h HTB2 injection gabarit"` — sert
d'en-tête de colonne pour les courbes RAW/TURPE. Se construit comme
`"{durée} {config native}"`, où la partie native reprend `I-Project!G39` (tension + `" injection"`
ou `" soutirage"` optionnel + `" gabarit"` optionnel).
_Avoid_: "config key", "clé de config" (utiliser DropKey pour le libellé humain, AUStoreKey pour
la clé technique — ce sont deux choses différentes dans le fichier)

**DropKey**:
Le libellé humain d'une configuration Aurora dans la liste déroulante de `Source BP!B3`, ex.
`"2h HTA Classique g0"` ou `"4h HTB2 Injection g1 (COD2030)"`. Distinct de l'AUStoreKey — une
table de correspondance DropKey → AUStoreKey (+ Duree/Tension/TURPE/Gabarit/ValideCOD) vit dans
`AU_Store!AP:AV`.
_Avoid_: confondre avec AUStoreKey

**Config COD2030-only**:
Une configuration Aurora dont `ValideCOD` (dans `AU_Store!AP:AV`) vaut `2030` au lieu de `"toute"`
— seulement 2 des 18 configs (`4h HTB2 injection gabarit`, `4h HTB2 soutirage gabarit`) sont dans
ce cas. Doit rester derrière un garde-fou : sélectionnable seulement si le projet a COD=2030.

**Source de prix (Source BP)**:
Le sélecteur `Source BP!B1` dans le BP, qui choisit entre `BP Aurora` (prix issus d'`AU_Store`) et
`CH` (feuille `CF CH`, non modélisée dans cette v2 — hors-scope explicite, doit lever un
avertissement si sélectionné plutôt que de retomber silencieusement sur Aurora).
_Avoid_: confondre avec `CF Aurora` / `dev_case.py` — chemin de donnée totalement différent, non
concerné par cette extension (30 configs détaillées par flux de marché, usage : cas de
développement en amont, pas le portefeuille multi-projets)

**Frais d'agrégateur (Aggregator fees)**:
Le mécanisme de frais de trading/optimisation défini dans `I-Project!42-46` : un taux "avant
seuil" et un taux "après seuil" (% du revenu), un seuil annuel (€/MW/an), et deux bascules
indépendantes ("net des coûts d'énergie ?", "net du TURPE énergie ?") qui déterminent l'assiette
du calcul. Sur le projet exemple : avant seuil 0%, après seuil -7,5%, seuil à 0 (donc tout le
revenu est "après seuil"), les deux bascules activées. Le mécanisme complet (pas une
simplification à taux plat) est repris tel quel dans le moteur v2.
_Avoid_: "frais de trading ≈7,5%" comme si c'était un taux plat fixe — c'est un cas particulier
du mécanisme complet, pas la règle générale

**Tiering DSCR sécurisé/merchant (Aurora)**:
Les deux cibles DSCR de `I-Project!247-248` : `Target DSCR - secured revenues (tolling / floor)`
(1,20x sur le projet exemple) et `Target DSCR - merchant revenues` (1,40x) — distinct du tiering
DSCR déjà existant dans `risk_thresholds.yaml` (`dscr_min_amber_contracted`/`_merchant`, 1,30/1,50)
qui sert au Risk Dashboard (couche 5) pour flagger, pas à dimensionner la dette. Ce nouveau
tiering, lui, dimensionne réellement la dette (mode DSCR-sculpté étendu).

**Maturité PPA+3**:
La règle de maturité de dette de `I-Project!249-250` : `10 ans` en full merchant, ou
`durée du PPA + 3 ans` si le projet a un floor/tolling actif (`PPA end date` + 3 ans sur le
projet exemple). Remplace la maturité fixe actuelle du moteur pour les projets sous overlay
contractuel.

**DEVEX**:
Le coût de développement réel dépensé par QEF (études de raccordement, permitting, foncier) —
forfaitaire par projet (150 k€ HTA, 300 k€ HTB1/HTB2/HTB3 confondus), pas un taux par MW. Distinct
du **DSA** (ce que l'acheteur paie à QEF) : `net_margin_keur = TSP - DEVEX` est le profit réel de
QEF, jamais confondu avec TSP (le revenu brut/prix perçu).
_Avoid_: "coût de dev" seul pour DEVEX (voir la mise en garde sous DSA — même ambiguïté)

**DSA (Development Service Agreement)**:
Le coût négocié que l'acheteur RtB paie à QEF pour acquérir le projet — une valeur **fixe**
(défaut = marge de dev cible confirmée par durée BESS — 50 k€/MW en 2h, 80 k€/MW en 4h — + DEVEX,
overridable par projet), pas une sortie de calcul. Construit ainsi, `DSA - DEVEX = marge cible`
exactement quand SPA = 0 (le projet atteint pile le TRI cible de l'acheteur, ni plus ni moins —
voir SPA ci-dessous). Reconnu par les banques
comme financable par dette : rejoint l'assiette « Total Uses » gearée, au même titre que les
ajouts DSRA/frais de financement déjà gérés pour le CAPEX.
_Avoid_: "coût de dev" seul (ambigu avec le coût de dev réel de QEF, différent) — DSA est ce que
l'**acheteur** paie, pas ce que QEF a dépensé pour développer.

**SPA (Share Purchase Agreement)**:
Le complément de prix, au-dessus du DSA, qui ramène le TRI equity réel de l'acheteur (calculé
avec DSA + CAPEX + OPEX + Revenue + financement) **exactement** à son TRI cible. Se calcule en un
seul solve NPV/TRI-cible — mathématiquement le même calcul que `acquisition.py`
(`NPV(TRI cible, cashflows equity) - investissement equity requis`), appliqué à des cashflows qui
incluent déjà le DSA comme sortie financée. Peut être négatif (si le DSA est trop élevé pour le
niveau de rentabilité du projet) sans que TSP le soit forcément.
_Avoid_: "prime d'acquisition" seul (c'est le même calcul qu'`acquisition.py`, mais nommé
différemment ici car c'est un complément à un DSA déjà fixé, pas un prix total)

**TSP (Total Sell Proceeds)**:
`TSP = DSA + SPA` — le revenu total de QEF pour la stratégie 1 (développer & vendre au RtB).
Distinct d'un calcul NPV unique : TSP est une somme de deux composantes de nature différente (une
fixe/négociée, une résolue par TRI-cible), pas une seule formule de valorisation.

**BP Aurora (onglet)**:
L'onglet calculé `BP Aurora` du classeur — **masqué** dans le fichier réel, à ne pas utiliser
comme référence de validation (calcul possiblement obsolète). La vraie référence de validation
est la Summary table externe d'Aurora (transmise hors classeur), jamais copiée telle quelle dans
le moteur — chaque TRI/NPV doit être recalculé par notre propre moteur, la Summary table ne sert
qu'à la comparaison recalculé-vs-reporté en test de non-régression.
