# La valorisation de revente au COD (stratégie 3) actualise les cashflows post-COD non-levérisés

**Amendée le 2026-09-17, avant implémentation** (voir Consequences) — la version initiale de cet
ADR proposait de re-dimensionner une dette au COD via `financial_engine`'s mode "dscr" ; ce mode
plafonne le principal par une assiette de gearing calculée sur le CAPEX (`gearing x (capex_total +
IDC + upfront fee)`, voir `_size_tranche_by_dscr`). Dans un rachat post-construction, `capex_total
= 0` (l'actif est déjà construit) → l'assiette vaut 0 → le plafond de dette annule tout
principal, quel que soit le CFADS disponible. Le mécanisme initial ne peut donc pas s'exécuter
tel quel sans fausser le résultat à 0.

La stratégie 3 (« racheter RtB & vendre au COD ») a besoin d'une « valeur de revente au COD » —
le prix qu'un exploitant futur paierait pour l'actif déjà construit et déjà financé. Décision :
calculer cette valeur comme la **PV des cashflows non-levérisés post-COD** (revenue + opex + turpe
+ end of life, la même définition de CFADS que le reste du moteur) actualisés au TRI cible de
l'acheteur à la revente — pas de dette re-dimensionnée, pas de nouvelle structure de capital.
C'est la définition standard de la valeur d'un actif pour un exploitant (DCF au rendement requis),
et ça correspond à la note déjà présente dans `docs/specs/aur_v2_methodology.md` ("valeur au
COD ≈ la PV du projet pour un exploitant"). Rejeté : re-dimensionner une dette au COD en garantissant
l'assiette de gearing par le prix de revente lui-même (LBO-style, `debt = gearing x prix`) — plus
fidèle à la pratique réelle des acquisitions mais introduit une résolution circulaire (le prix
dépend de la dette, la dette dépend du prix) pour un gain de réalisme marginal à ce stade ; à
reconsidérer si la précision de cette valeur devient un point bloquant en pratique.

## Consequences

La valeur de revente ainsi obtenue est **non-levérisée** — elle ne reflète pas le surcroît de
valeur qu'un acheteur relevant l'actif capterait via le bouclier fiscal de la dette / l'effet de
levier sur son propre TRI cible. C'est une sous-estimation prudente de la valeur réelle de
marché, documentée comme telle plutôt que masquée.
