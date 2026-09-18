# L'analyse globale (Phase 5) énumère l'espace des configs plutôt que de le balayer

L'« analyse globale » du brief pourrait se lire comme une extension du module de sensibilité
existant (`sensitivity.py`, chocs one-way ±10 %/±20 % autour d'un cas de base). Mais l'espace des
configs Aurora est fini et petit (18 configs `AU_Store` × années de COD valides × {full merchant,
floor, tolling}), pas un continuum. Décision : `global_sensitivity.py` calcule et met en cache
une fois **toute** la combinatoire valide, exposée comme table triable/filtrable plus des heatmaps
et des coupes 1-2 variables à la volée depuis ce même cache — pas un balayage classique variable
par variable autour d'un cas de base. Rejeté : réutiliser le pattern tornado de `sensitivity.py`,
qui suppose un cas de base continu à perturber et redemande un run moteur par choc plutôt que de
réutiliser une grille finie précalculée.
