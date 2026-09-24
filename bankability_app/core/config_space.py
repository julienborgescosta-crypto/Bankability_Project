"""Enumere/valide l'espace des configurations Aurora disponibles (`AU_Store`) -
couche fine au-dessus de `core.aur_cases` pour les besoins du Configurateur
(listes deroulantes en cascade, garde-fou COD2030). Le "mapping tension->segment"
du brief est trivial : `AuStoreConfig.tension` (HTA/HTB1/HTB2/HTB3) est deja le
meme libelle que `ProjectInputs.segment` ailleurs dans l'app - aucune table de
correspondance necessaire."""

from __future__ import annotations

from .aur_cases import AuStoreConfig, AuStoreLibrary
from .dev_case import CopexLibrary, voltage_duration_key


def has_cost_data(config: AuStoreConfig, copex_library: CopexLibrary) -> bool:
    """`AU_Store` modelise des configs (ex. HTB3) que `COPEX_library` ne couvre
    pas (verifie : seules HTA/HTB1/HTB2 y sont, voir docs/specs/aur_cases.md) -
    a filtrer en amont plutot que de laisser l'utilisateur choisir une config
    qui echouera au calcul (`aur_cases.capex_and_opex_keur` leve sinon)."""
    key = voltage_duration_key(config.tension, config.duree_h)
    return key in copex_library.capex_unit_costs and key in copex_library.opex_unit_costs


def durations(library: AuStoreLibrary) -> list[int]:
    return sorted({config.duree_h for config in library.configs})


def tensions(
    library: AuStoreLibrary,
    *,
    duree_h: int | None = None,
    copex_library: CopexLibrary | None = None,
) -> list[str]:
    """`copex_library` optionnel : si fourni, exclut les tensions sans donnees
    CAPEX/OPEX (voir `has_cost_data`) - a toujours fournir cote UI pour ne
    jamais proposer une config vouee a echouer."""
    configs = (
        library.configs if duree_h is None else [c for c in library.configs if c.duree_h == duree_h]
    )
    if copex_library is not None:
        configs = [c for c in configs if has_cost_data(c, copex_library)]
    return sorted({config.tension for config in configs})


ALL_TURPE_TYPES = ["Classique", "Injection", "Soutirage"]


def turpe_types(library: AuStoreLibrary, *, duree_h: int, tension: str) -> list[str]:
    """Toujours les 3 types TURPE (vocabulaire fixe de la methodologie, pas une
    donnee lue dans `AU_Store`) - reel si Aurora a modelise cette tension/duree
    pour ce type, sinon extrapole via `core.config_extrapolation.resolve_config`
    (2026-09-24). `library`/`duree_h`/`tension` gardes dans la signature pour ne
    pas casser les appelants existants, plus utilises pour filtrer."""
    del library, duree_h, tension
    return list(ALL_TURPE_TYPES)


def gabarit_options(
    library: AuStoreLibrary, *, duree_h: int, tension: str, turpe_type: str
) -> list[bool]:
    """Gabarit n'a de sens que pour TURPE Injection/Soutirage (jamais
    Classique - regle business, pas une simple absence de donnee, voir
    `core.config_extrapolation.resolve_config`). Reel si Aurora a modelise
    cette tension/duree pour ce type+gabarit, sinon extrapole."""
    del library, duree_h
    if turpe_type == "Classique":
        return [False]
    return [False, True]


def oro_options(*, turpe_type: str) -> list[bool]:
    """ORO (limitation non-firm 3000h/an) n'a de sens que pour TURPE
    Injection/Soutirage, meme regle business que le gabarit."""
    if turpe_type == "Classique":
        return [False]
    return [False, True]


def valid_cod_years(config: AuStoreConfig, candidate_years: list[int]) -> list[int]:
    """Filtre `candidate_years` sur le garde-fou COD2030 : une config sans
    contrainte (`valide_cod is None`) accepte n'importe quelle annee candidate,
    une config COD2030-only ne renvoie que 2030 (si presente dans la liste)."""
    if config.valide_cod is None:
        return list(candidate_years)
    return [year for year in candidate_years if year == config.valide_cod]


def is_cod_valid(config: AuStoreConfig, cod_year: int) -> bool:
    return config.valide_cod is None or config.valide_cod == cod_year


def is_year_range_covered(
    library: AuStoreLibrary, config: AuStoreConfig, *, cod_year: int, operating_years: int
) -> bool:
    """`valide_cod` (voir `is_cod_valid`) n'attrape que les configs
    explicitement verrouillees sur un seul COD - une config extrapolee
    (`config_extrapolation.resolve_config`) peut rester `valide_cod=None`
    ("toute") tout en ayant, dans les faits, une couverture calendaire plus
    etroite que la plage Aurora complete (bug signale par l'utilisateur,
    2026-09-24 : cas HTA gabarit+ORO, `valide_cod` a None mais RAW absent
    avant 2030 avant le fix de `config_extrapolation._clamped` - reste un
    garde-fou utile pour toute future config qui referrait la meme situation
    sans que le fix generique la couvre). Verifie directement sur les
    donnees plutot que sur une metadonnee separee, pour ne jamais se
    desynchroniser d'elles."""
    raw = library.raw_by_key.get(config.austore_key)
    if not raw:
        return False
    last_operating_year = cod_year + operating_years - 1
    return min(raw) <= cod_year and max(raw) >= last_operating_year
