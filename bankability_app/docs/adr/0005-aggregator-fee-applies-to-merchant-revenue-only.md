# Le frais d'agrégateur (portefeuille) s'applique à la part merchant du revenu, pas au sécurisé

Un projet du Configurateur peut avoir un overlay contractuel (floor/tolling, `core/contract_overlay.py`)
qui sécurise une partie du revenu. Décision : le mécanisme de frais d'agrégateur
(`aur_cases.aggregator_fee_series`) s'applique uniquement à la part **merchant** du revenu
ajusté (`revenu_ajusté - revenu_sécurisé`), jamais à la part sécurisée par le floor/tolling.
Raisonnement : pendant une période de tolling, le prix est fixe et payé directement par
l'off-taker — il n'y a pas de trading/optimisation de marché à rémunérer sur ce flux ; pendant une
période de floor, seul l'excédent au-dessus du floor (déjà partagé avec l'agrégateur côté
contrat) reste exposé au marché. Rejeté : appliquer le frais à l'ensemble du revenu ajusté
(secured + merchant) comme le fait `aur_cases.build_project_inputs` en mode mono-projet — plus
simple mais double-compte la commission sur un flux qui, par construction, n'a pas transité par
un mécanisme de trading pendant l'overlay.

## Consequences

`core/portfolio.py` ne réutilise donc **pas** le paramètre `aggregator_fee` de
`aur_cases.build_project_inputs` (qui appliquerait le frais à tout le revenu) : il construit le
`ProjectInputs` sans frais, applique l'overlay contractuel, puis calcule et ajoute lui-même le
frais sur la seule part merchant.
