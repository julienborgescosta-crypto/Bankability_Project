# `core/config_extrapolation.py` — extrapolation des combinaisons non modélisées par Aurora

## Objectif

`AU_Store` ne modélise que 22 combinaisons (durée × tension × type TURPE × gabarit × ORO) sur
l'espace théorique complet — ex. HTB1/HTB3 n'ont que la variante Classique, la limitation ORO n'a
été chiffrée que pour HTB2 injection/soutirage. Demande de l'utilisateur, 2026-09-24 : pouvoir
explorer les combinaisons manquantes plutôt que de se heurter à une erreur bloquante ou (pire) un
repli silencieux — mais **toujours indiquer clairement quand un chiffre est une estimation**, pas
une donnée Aurora.

`resolve_config()` est le point d'entrée unique : il retourne une `AuStoreConfig` (réelle si
Aurora l'a modélisée, sinon synthétique) directement utilisable par
`aur_cases.build_project_inputs`, sans que le reste du pipeline (`portfolio.py`, `strategy.py`,
les 3 stratégies, l'UI) n'ait besoin de savoir si elle regarde une donnée réelle ou estimée — la
seule différence visible est `AuStoreConfig.extrapolated` (bool) et les `notes` explicatives
retournées à côté.

## Décisions

- **Config synthétique injectée dans une copie de la bibliothèque**, pas un chemin de calcul
  parallèle : `resolve_config()` retourne un `ResolvedConfig(library, config, notes)` où `library`
  est soit l'`AuStoreLibrary` d'origine inchangée (cas réel), soit une copie (`dataclasses.replace`)
  avec une `AuStoreConfig` de plus et ses courbes RAW/TURPE ajoutées aux dicts existants. Tout le
  reste du pipeline (`aur_cases.revenue_and_turpe_series`, `build_project_inputs`,
  `financial_engine.compute_results`) fonctionne sans modification — c'est la même astuce que pour
  n'importe quelle config réelle, juste une entrée de plus dans le dict.
- **Modèle à facteurs indépendants, calibré sur HTB2** (seule tension où Aurora a modélisé
  Classique/Injection/Soutirage × gabarit 0/1 en intégralité) :
  - Effet type TURPE : `RAW_cible = RAW_cible(Classique) × [RAW_HTB2(type) / RAW_HTB2(Classique)]`
    (multiplicatif) ; `TURPE_cible = TURPE_cible(Classique) + [TURPE_HTB2(type) −
    TURPE_HTB2(Classique)] × echelle_TURPE(cible)` (additif — un ratio direct n'a pas de sens sur
    du TURPE qui peut changer de signe entre Classique et Injection, voir "Mise à l'échelle du
    delta TURPE" ci-dessous pour `echelle_TURPE`).
  - Effet gabarit : même principe, `RAW_HTB2(type, g1) / RAW_HTB2(type, g0)` et
    `[TURPE_HTB2(type, g1) − TURPE_HTB2(type, g0)] × echelle_TURPE(cible)`.
  - Les deux se combinent (multiplication/addition successive) quand type ET gabarit manquent tous
    les deux pour la tension cible.
  - Hypothèse non vérifiée au-delà de HTB2 : que l'effet RELATIF (une fois mis à l'échelle de la
    tension cible) d'un changement de type TURPE ou de gabarit est le même quelle que soit la
    tension. Chaque extrapolation porte une note explicite le rappelant.

### Mise à l'échelle du delta TURPE (`_turpe_magnitude_scale`, 2026-10-01)

Retour utilisateur : la heatmap "Aurora Global Analysis" montrait le TRI HTA (TURPE Injection)
passer sous celui de HTB2 dès 2029, alors que HTA — beaucoup plus sensible au TURPE que HTB2 —
devrait au contraire tirer un gain TURPE plus GRAND du passage à Injection/gabarit, pas plus
petit ("en HTB2 le TRI est meilleur en gabarit grâce au TURPE, donc en HTA vu que le TURPE pèse
plus ça devrait avoir un effet d'autant plus grand").

Root cause : le delta TURPE (`TURPE_HTB2(type) − TURPE_HTB2(Classique)`, un nombre absolu en k€
normalisé 1 MW) était transféré tel quel à la tension cible, sans tenir compte du fait que le
TURPE est facturé au **kW de tarif réseau** (pas au MWh) — sa magnitude varie fortement et
systématiquement d'une tension à l'autre. Vérifié sur les 4 courbes Classique réelles (seules
disponibles pour toutes les tensions) :

| Tension | \|TURPE Classique\| / \|TURPE Classique HTB2\| (2h, moyenne 2027-2031) |
|---|---|
| HTA | ≈ 2.2x |
| HTB1 | ≈ 1.6x |
| HTB2 | 1.0x (référence) |
| HTB3 | ≈ 0.57x |

(stable entre 2h et 4h, à ±0.1 près). Un delta HTB2 transféré sans cette mise à l'échelle
sous-estimait donc le gain TURPE à HTA/HTB1 (et le surestimait à HTB3).

`_turpe_magnitude_scale(au_store, duree_h, tension)` retourne ce ratio (1.0 si `tension ==
"HTB2"`) ; chaque delta TURPE transféré (type TURPE, gabarit, ORO) est multiplié par ce facteur
avant d'être ajouté à la courbe Classique réelle de la tension cible. Exemple concret (2h,
Injection sans gabarit, COD2027, k€ normalisé 1 MW) :

| | avant le fix | après le fix |
|---|---|---|
| Delta HTB2 brut | +11.7 | +11.7 |
| Échelle HTA | (non appliquée) | ×2.2 |
| TURPE HTA Classique | -22.2 | -22.2 |
| TURPE HTA Injection résultant | **-10.5** (reste un coût) | **+5.99** (devient un vrai crédit) |

Le facteur RAW (multiplicatif, déjà indépendant de la tension par construction — validé
2026-10-01, voir "Benchmark de référence") n'est pas concerné, seul le delta TURPE (additif)
l'était.
  - **Un seul ratio/delta MOYEN (pas un par année)** — corrigé le 2026-10-01, suite à un retour
    utilisateur ("le TRI extrapolé doit rester du même ordre de grandeur que celui d'Aurora") : la
    version précédente calculait un ratio par année, ce qui propageait fidèlement les années où la
    référence HTB2 elle-même est verrouillée sur un seul COD (ex. "4h HTB2 gabarit (COD2030)") et
    peut y présenter un artefact propre à ce cas précis (le ratio RAW mesuré y saute de 0.78 à 1.04
    après 2044 — une rupture qui n'a de sens que pour ce projet COD2030 précis, probablement liée à
    son propre repowering, jamais un "effet gabarit" générique). Vérifié : le ratio moyen 4h (0.91)
    est quasi identique au ratio moyen 2h (0.92, lui calibré sur une référence non verrouillée) —
    la moyenne absorbe l'artefact là où le détail année par année l'amplifiait. Effet observé sur le
    TRI Projet extrapolé (HTA 4h gabarit injection, COD2030, avant/après) : passe d'un écart de
    -19 à -20 points de TRI vs sans gabarit (incohérent, signe opposé au 2h réel) à un écart de
    ~-9 points, du même signe et du même ordre de grandeur que l'effet gabarit réel mesuré sur HTB2
    aux 2 durées (-1 à -3 points, voir section "Benchmark de référence" ci-dessous). Contrepartie
    assumée : la courbe extrapolée n'a plus de variation annuelle *propre* à l'effet transféré
    (type TURPE/gabarit/ORO), seulement celle déjà portée par la courbe Classique/g0 réelle de
    départ — un compromis défendable faute d'assez de points réels pour calibrer un effet variable
    dans le temps de façon fiable.
- **Effet ORO, même principe (ratio/delta moyen)**, calibré sur les 4 cas HTB2 ORO réels
  (injection/soutirage × 2h/4h) : `RAW_ORO_cible = RAW_standard_cible × [RAW_HTB2_ORO(type) /
  RAW_HTB2_standard(type)]`. Appliqué par-dessus la courbe standard déjà résolue (réelle ou
  elle-même extrapolée à l'étape précédente). Le passage à un ratio moyen a aussi supprimé, comme
  effet de bord bienvenu, un bug de couverture calendaire distinct (une config verrouillée sur un
  seul COD zéro-remplie hors de sa fenêtre perdait silencieusement des années — plafonné une 1ère
  fois le 2026-09-24, puis rendu sans objet par la moyenne le 2026-10-01, un ratio moyen ne pouvant
  plus "manquer" d'année).
- **Combinaisons bloquées, pas extrapolées** : gabarit ou ORO avec le type TURPE Classique lèvent
  `AuroraConfigError`. Ce ne sont pas des données manquantes mais des combinaisons sans sens
  business — le gabarit et l'ORO limitent spécifiquement l'injection ou le soutirage, la
  distinction Classique ne s'applique pas. Extrapoler ici inventerait un chiffre pour un concept
  qui n'existe pas.
- **Heures de curtailment personnalisées (500-4000h)** : la courbe ORO à 3000h (réelle ou déjà
  extrapolée par l'étape précédente) sert d'ancre. Le ratio `(1 − perte%(heures)) / (1 −
  perte%(3000h))`, tiré de `config/aur_oro_curtailment_losses.yaml` (profil de perte % par année,
  interpolé linéairement entre les paliers 500h), rééchelonne la courbe RAW — jamais le TURPE
  (l'onglet source "Curtailment analysis" du databook Aurora ne documente que des pertes de
  revenu, pas un effet sur le TURPE). Hors de la plage 500-4000h analysée par Aurora, erreur
  explicite plutôt qu'une extrapolation sans aucune base.
  - `config/aur_oro_curtailment_losses.yaml` est **calibré sur un seul cas de référence** (2h HTB2
    injection, Central, COD2027, onglet "Curtailment analysis" du databook Aurora Q2 2026) —
    transféré tel quel à toutes les autres combinaisons/durées. C'est la moins bien fondée des
    trois extrapolations de ce module ; c'est pour ça qu'elle n'intervient qu'en dernier ressort,
    en rééchelonnement relatif d'une courbe ORO déjà résolue par ailleurs (jamais comme source
    absolue).
- **`AuStoreConfig.extrapolated: bool`** (défaut `False`) plutôt qu'un type séparé pour les configs
  synthétiques : garde tout le pipeline existant (`config_by_attributes`, `revenue_and_turpe_series`,
  toutes les stratégies) inchangé — une config extrapolée est juste une `AuStoreConfig` comme une
  autre, avec un flag et une clé technique explicite (`"{duree}h {tension} {type} [gabarit] [ORO
  [heures]] (extrapolé)"`).
- **`config_space.turpe_types()`/`gabarit_options()`/`oro_options()` élargis à l'espace théorique
  complet** (2026-09-24) : avant, ces fonctions ne proposaient que ce qu'Aurora avait réellement
  modélisé pour la tension/durée choisie (filtrage sur `AuStoreLibrary.configs`). Elles retournent
  désormais toujours `["Classique", "Injection", "Soutirage"]` / `[False, True]` (sauf gabarit avec
  Classique, toujours `[False]`) — l'UI n'a plus besoin de désactiver une option pour "donnée
  manquante", `resolve_config()` gère la suite. `config_space.has_cost_data()` (CAPEX/OPEX,
  `COPEX_library`) reste un filtre dur inchangé — aucune extrapolation proposée côté coûts, c'est
  une source de données totalement différente.

## Benchmark de référence (2026-10-01, non stocké dans le repo)

Le 2026-10-01, l'utilisateur a fourni un chemin local vers le databook source Aurora Q2 2026 FRA
(`Aurora_Q2_26_FRA_Flexible_Data_Forecast_Investment_Cases_v1.1.xlsm`) : 40+ cas standalone
(scénario Central) avec **TRI et NPV déjà calculés par Aurora avec leurs propres hypothèses de
CAPEX/OPEX/financement**, pas juste les courbes RAW/TURPE (que l'app avait déjà validées à la
décimale par ailleurs, voir `docs/specs/aur_cases.md`). Utilisé ponctuellement pour vérifier que
le TRI Projet que l'app calcule (avec ICP + repli Aurora, pas les hypothèses financières d'Aurora)
reste dans un ordre de grandeur plausible par rapport à ces cas réels, en particulier sur les
combinaisons extrapolées où aucune vérification directe n'était possible auparavant - c'est ce qui
a mis en évidence le besoin du fix ci-dessus (ratio moyen plutôt que par année).

**Non extrait dans un fichier du repo** : l'onglet "Disclaimer" du classeur source indique que le
contenu du databook (au-delà des seules données horaires explicitement visées par l'interdiction)
est la propriété et l'information confidentielle d'Aurora Energy Research, sous réserve des termes
du contrat de service de l'utilisateur avec Aurora - committer des valeurs extraites (même
résumées au niveau "cas") dans ce repo git n'est pas une décision à prendre unilatéralement.
Question ouverte, à trancher avec l'utilisateur (voir ci-dessous) avant de re-stocker quoi que ce
soit de ce fichier ici.

Ce fichier a aussi confirmé, par construction, une limite déjà connue : **Aurora n'a jamais
modélisé "HTA Injection/Soutirage sans gabarit"** (seule la variante gabarit existe pour HTA
Injection/Soutirage dans leurs cas d'investissement standalone) - contrairement à HTB2 qui a les
2 variantes. Une extrapolation HTA Injection sans gabarit reste donc, par nature, moins bien
ancrée qu'une extrapolation HTB2 équivalente (l'anchor "Classique" existe toujours, mais pas de
point de comparaison direct type-TURPE-sans-gabarit pour HTA).

## Questions ouvertes

- **Statut du databook Aurora source (TRI/NPV par cas) vis-à-vis de la confidentialité** - non
  tranché avec l'utilisateur (voir "Benchmark de référence" ci-dessus). En attendant, le fichier
  brut reste sur la machine de l'utilisateur, hors repo, et une extraction tentée le 2026-10-01
  (`config/aurora_reference_irr_cases.yaml`) a été laissée non trackée par git (`.gitignore`) sans
  être committée.
- **Pas d'extrapolation vers une 3ᵉ durée BESS** (ex. 6h) : `resolve_config()` requiert
  `duree_h` réel (2h ou 4h, seules durées qu'Aurora a modélisées) — extrapoler sur cet axe
  demanderait une toute autre méthode (interpolation entre 2h et 4h), non demandée et non
  implémentée.
- **Analyse globale (`global_sensitivity.py`) ne balaie pas l'espace extrapolé** : `enumerate_configs`
  continue d'énumérer uniquement les 22 configs réelles d'`AU_Store` (voir
  `docs/specs/global_sensitivity.md`) — étendre au plein espace théorique multiplierait le nombre
  de cas par ~3-4x (tous les types TURPE × gabarit pour HTA/HTB1/HTB3, en plus de l'ORO), au prix
  d'un temps de calcul et d'une lisibilité de la table dégradés pour une confiance moindre sur ces
  lignes. Le Configurateur (projet par projet) couvre le cas d'usage "explorer une config précise
  non modélisée" ; l'Analyse globale reste focalisée sur les données réelles pour l'instant.
