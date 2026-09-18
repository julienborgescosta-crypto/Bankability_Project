from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import degradation as degradation_module
from . import financial_engine
from .models import ProjectInputs

VOLTAGE_CLASSES = ["HTA", "HTB1", "HTB2"]
TURPE_TYPES = ["Classique", "Injection", "Soutirage"]
CONNECTION_TYPES = [
    "Industrial-New trench",
    "Industrial-Existing trench",
    "TSO 63kV",
    "TSO 90kV",
    "TSO 225kV",
    "DSO",
]
CONNECTION_CAPEX_MODES = ["library", "manual", "distance_rte", "distance_rte_and_substation"]

# Connection type -> voltage class, for the connection types where the mapping is
# fixed - confirmed against the real BP (DSO is distribution-level HTA; TSO 63kV
# and 90kV are both the HTB1 tier; TSO 225kV is HTB2). "Industrial-*" is
# deliberately absent: an industrial (private wire / behind-the-meter) connection
# can sit at any voltage level, so DevCaseParams.voltage_class requires an
# explicit override in that case instead of deriving it.
FIXED_VOLTAGE_CLASS_BY_CONNECTION_TYPE = {
    "DSO": "HTA",
    "TSO 63kV": "HTB1",
    "TSO 90kV": "HTB1",
    "TSO 225kV": "HTB2",
}

# core/dev_case.py CAPEX line items (table "CAPEX assumptions - AURORA (base
# 2028)" de COPEX_library, en €/kW - équivaut à k€/MW, donc x power_mw donne
# directement un total en k€). Validé contre le fichier réel : Total(2h-HTB1)
# = 538.4 x 40 MW = 21 536 k€, qui matche EXACTEMENT la colonne "Aurora (k€)"
# de la section 2 de l'onglet Advise Dev du BP source. "Grid connection" est
# géré séparément par connection_capex_keur() (les 3 autres modes le
# remplacent), donc exclu de la somme générique ici.
CAPEX_LINE_ITEMS = [
    "Battery system",
    "Inverter",
    "Balance of system",
    "Development",
    "EPC soft costs",
]
CAPEX_GRID_CONNECTION_LABEL = "Grid connection"

OPEX_LINE_ITEMS = ["Fixed O&M", "Insurance", "Grid charges", "Land lease", "Accise", "Other"]


def voltage_duration_key(voltage_class: str, duration_h: int) -> str:
    """Format de clé commun aux tables 'CAPEX assumptions - AURORA' et 'OPEX
    assumptions - AURORA' de COPEX_library (ex. '2h - HTB1')."""
    return f"{duration_h}h - {voltage_class}"


@dataclass
class DevCaseParams:
    """Hypothèses de développement saisies par l'utilisateur - miroir de l'onglet
    `Inputs Dev` du BP source (COD, puissance, durée, segment réseau, type TURPE,
    gabarit, mode de CAPEX de raccordement)."""

    cod_year: int
    power_mw: float
    duration_h: int  # 2 ou 4 (les seules durées couvertes par CF Aurora/COPEX_library)
    connection_type: str
    turpe_type: str = "Classique"
    gabarit: bool = False
    repowering: bool = False
    operating_years: int = 20
    connection_capex_mode: str = "library"
    distance_rte_km: float = 0.0
    distance_substation_km: float = 0.0
    manual_connection_capex_keur: float = 0.0
    land_lease_opex_keur: float = 0.0
    voltage_class_override: str | None = None
    name: str = "Cas de développement"
    location: str = ""

    @property
    def energy_mwh(self) -> float:
        return self.power_mw * self.duration_h

    @property
    def voltage_class(self) -> str:
        if self.voltage_class_override is not None:
            return self.voltage_class_override
        try:
            return FIXED_VOLTAGE_CLASS_BY_CONNECTION_TYPE[self.connection_type]
        except KeyError as exc:
            raise ValueError(
                f"connection_type '{self.connection_type}' n'a pas de classe de tension fixe "
                "(raccordement Industrial) - voltage_class_override est requis."
            ) from exc


@dataclass
class CopexLibrary:
    """Coûts unitaires extraits de `COPEX_library`, tous deux indexés par
    `voltage_duration_key()` ("{duration}h - {voltage_class}", ex. '2h - HTB1'
    - même taxonomie que `AuroraLibrary`, donc aucun mapping segment/classe de
    tension n'est nécessaire pour le CAPEX/OPEX, seulement pour dériver
    `voltage_class` depuis le `connection_type` choisi dans le formulaire) :
    - `capex_unit_costs` = table 'CAPEX assumptions - AURORA (base 2028)',
      postes Battery system/Inverter/Balance of system/Development/Grid
      connection/EPC soft costs, en €/kW (= k€/MW, x power_mw donne un total
      k€ directement - validé contre le fichier réel, voir CAPEX_LINE_ITEMS).
    - `opex_unit_costs` = table 'OPEX assumptions - AURORA', postes Fixed
      O&M/Insurance/Grid charges/Land lease/Accise/Other, même unité.
    - `capex_escalation`/`opex_escalation` = "Forecast price factor (selon
      année de COD)" de la même table : par poste (pas par segment - le même
      facteur s'applique aux 7 colonnes B-H d'une ligne), un delta relatif à
      appliquer au coût de base 2028 pour une année de COD différente (ex.
      Battery system 2030 : -0.20% ; Total 2030 : -1.67%). Absent (dict vide)
      si la table source ne les fournit pas."""

    capex_unit_costs: dict[str, dict[str, float]]
    opex_unit_costs: dict[str, dict[str, float]]
    capex_escalation: dict[str, dict[int, float]] = field(default_factory=dict)
    opex_escalation: dict[str, dict[int, float]] = field(default_factory=dict)


@dataclass
class AuroraLibrary:
    """`CF Aurora` : combo_key -> durée (2 ou 4h) -> année calendaire -> flux ->
    valeur (k€, normalisé 1 MW). combo_key (classe de tension + type TURPE +
    gabarit) construite par `aurora_combo_key()` (reproduit `I-Project!G39`) -
    la durée est un axe séparé (2 blocs de config par section CF Aurora,
    mirroring `AU_Store`'s Raw2h/Raw4h columns in the real BP)."""

    combos: dict[str, dict[int, dict[int, dict[str, float]]]]

    def years(self, combo_key: str, duration_h: int) -> list[int]:
        return sorted(self.combos[combo_key][duration_h].keys())

    def year_range(self) -> tuple[int, int] | None:
        """Plage d'années calendaires couverte par CF Aurora, toutes combos et
        durées confondues (union) - sert à borner l'année de COD dans le
        formulaire, plutôt que de laisser un COD hors plage retomber
        silencieusement sur un revenu nul (`_revenue_and_turpe_series`). Sur
        le fichier réel, cette plage est identique pour les 15 combos x 2
        durées (2028-2057) - `None` si la bibliothèque est vide."""
        all_years = [
            year
            for durations in self.combos.values()
            for years_for_duration in durations.values()
            for year in years_for_duration
        ]
        return (min(all_years), max(all_years)) if all_years else None


def aurora_combo_key(voltage_class: str, turpe_type: str, gabarit: bool) -> str:
    """Reproduit `I-Project!G39` :
    = classe_tension & (" injection"|" soutirage"|"" selon type TURPE)
      & (" gabarit" si gabarit et type != Classique)."""
    suffix = ""
    if turpe_type == "Injection":
        suffix = " injection"
    elif turpe_type == "Soutirage":
        suffix = " soutirage"
    gabarit_suffix = " gabarit" if (gabarit and turpe_type != "Classique") else ""
    return f"{voltage_class}{suffix}{gabarit_suffix}"


def _connection_cost_from_distance(distance_km: float) -> float:
    """`Inputs Dev!D20` : 'Coût racco calculé' = 4650.7 x distance^0.239 (k€)."""
    if distance_km <= 0:
        return 0.0
    return 4650.7 * distance_km**0.239


def _substation_cable_cost(distance_km: float) -> float:
    """`Inputs Dev!D22` : 'Coût cable calculé' = 1257.3 x distance^0.5761 (k€)."""
    if distance_km <= 0:
        return 0.0
    return 1257.3 * distance_km**0.5761


def escalated_unit_cost(
    base_value: float, escalation_for_label: dict[int, float], cod_year: int
) -> float:
    """Applique le "Forecast price factor (selon année de COD)" au coût de
    base 2028 : `value(cod_year) = base_value x (1 + delta(cod_year))`. La
    table source ne couvre que 2028-2034 (2028 -> delta 0 implicite) : une
    année de COD postérieure à la dernière année connue est plafonnée sur le
    dernier delta disponible (extrapolation prudente plutôt que de revenir à
    0% au-delà de la table) ; une année antérieure à 2028 (ne devrait pas
    arriver en pratique) n'est pas ajustée."""
    if not escalation_for_label:
        return base_value
    if cod_year in escalation_for_label:
        delta = escalation_for_label[cod_year]
    else:
        years = sorted(escalation_for_label.keys())
        delta = escalation_for_label[years[-1]] if cod_year > years[-1] else 0.0
    return base_value * (1 + delta)


def connection_capex_keur(params: DevCaseParams, library: CopexLibrary) -> float:
    """Reproduit la logique de sélection `Inputs Dev!D18-D23` : le mode choisi
    détermine la source du coût de raccordement. En mode 'library', la ligne
    'Grid connection' de la table CAPEX-AURORA est utilisée (€/kW x power_mw,
    escaladée selon l'année de COD - voir CAPEX_LINE_ITEMS/escalated_unit_cost)
    ; les 3 autres modes remplacent cette ligne par une valeur manuelle ou
    calculée depuis une distance (non escaladées : ce sont des formules/valeurs
    saisies directement par l'utilisateur, pas des coûts de bibliothèque)."""
    if params.connection_capex_mode == "manual":
        return params.manual_connection_capex_keur
    if params.connection_capex_mode == "distance_rte":
        return _connection_cost_from_distance(params.distance_rte_km)
    if params.connection_capex_mode == "distance_rte_and_substation":
        return _connection_cost_from_distance(params.distance_rte_km) + _substation_cable_cost(
            params.distance_substation_km
        )
    if params.connection_capex_mode == "library":
        key = voltage_duration_key(params.voltage_class, params.duration_h)
        unit_cost = library.capex_unit_costs.get(key, {}).get(CAPEX_GRID_CONNECTION_LABEL, 0.0)
        unit_cost = escalated_unit_cost(
            unit_cost,
            library.capex_escalation.get(CAPEX_GRID_CONNECTION_LABEL, {}),
            params.cod_year,
        )
        return unit_cost * params.power_mw
    raise ValueError(f"connection_capex_mode inconnu : '{params.connection_capex_mode}'")


def capex_total_keur(params: DevCaseParams, library: CopexLibrary) -> float:
    """CAPEX total = lignes CAPEX_LINE_ITEMS (€/kW x power_mw, escaladées selon
    l'année de COD) + raccordement (connection_capex_keur). Le niveau 2028 est
    validé exactement contre le fichier réel (voir CAPEX_LINE_ITEMS) - pas de
    marge/assurance supplémentaire, `Total` de la table source est déjà une
    simple somme des lignes ; l'escalade par année de COD, elle, n'a pas de
    figure de référence indépendante à comparer (voir docs/specs/dev_case.md)."""
    key = voltage_duration_key(params.voltage_class, params.duration_h)
    unit_costs = library.capex_unit_costs.get(key, {})

    generic_cost = sum(
        escalated_unit_cost(
            unit_costs.get(label, 0.0), library.capex_escalation.get(label, {}), params.cod_year
        )
        * params.power_mw
        for label in CAPEX_LINE_ITEMS
    )
    connection_cost = connection_capex_keur(params, library)
    return generic_cost + connection_cost


def opex_year1_keur(params: DevCaseParams, library: CopexLibrary) -> float:
    """OPEX annuel = somme des postes OPEX_LINE_ITEMS de la table 'OPEX
    assumptions - AURORA' (€/kW x power_mw, escaladée selon l'année de COD)
    + loyer foncier saisi par l'utilisateur (non couvert par cette table,
    donc non escaladé)."""
    key = voltage_duration_key(params.voltage_class, params.duration_h)
    unit_costs = library.opex_unit_costs.get(key, {})
    library_opex = (
        sum(
            escalated_unit_cost(
                unit_costs.get(label, 0.0), library.opex_escalation.get(label, {}), params.cod_year
            )
            for label in OPEX_LINE_ITEMS
        )
        * params.power_mw
    )
    return library_opex + params.land_lease_opex_keur


def _revenue_and_turpe_series(
    params: DevCaseParams, library: AuroraLibrary
) -> tuple[list[int], list[float], list[float]]:
    """Lit le bloc Aurora correspondant à la combo **par année calendaire**,
    décalé sur `operating_years` années à partir de `cod_year` - reproduit
    exactement le mécanisme de `AU_Store`/`BP Aurora` dans le fichier réel : la
    courbe Aurora est fixe par année calendaire, changer le COD revient juste à
    lire une autre tranche de la même courbe (pas de reconstruction spéciale).
    Pour chaque année, somme les flux dont le nom NE commence PAS par
    'tariff_TURPE' -> revenu (positif, déjà signé ainsi dans CF Aurora) ; les
    flux 'tariff_TURPE*' -> TURPE (déjà négatif). Mise à l'échelle par
    power_mw (blocs Aurora normalisés 1 MW), puis converti € -> k€ (/1000) :
    contrairement à COPEX_library (€/kW, où x power_mw en MW convertit déjà
    directement en k€ car les deux facteurs 1000 s'annulent), CF Aurora donne
    un montant en € pur pour 1 MW - validé contre le fichier réel (sans ce
    /1000, le revenu ressort à l'échelle du milliard d'euros). Une année
    calendaire absente du bloc Aurora (hors de la plage couverte par la
    simulation de marché) donne un revenu/TURPE nul plutôt qu'une erreur."""
    combo_key = aurora_combo_key(params.voltage_class, params.turpe_type, params.gabarit)
    if combo_key not in library.combos:
        raise ValueError(
            f"Combo Aurora '{combo_key}' introuvable dans CF Aurora "
            f"(classes disponibles : {sorted(library.combos)})."
        )
    durations_available = library.combos[combo_key]
    if params.duration_h not in durations_available:
        raise ValueError(
            f"Durée {params.duration_h}h introuvable pour la combo Aurora '{combo_key}' "
            f"(durées disponibles : {sorted(durations_available)})."
        )
    combo = durations_available[params.duration_h]

    calendar_years = [params.cod_year + i for i in range(params.operating_years)]
    revenue_series = []
    turpe_series = []
    for year in calendar_years:
        streams = combo.get(year, {})
        turpe = sum(v for k, v in streams.items() if k.startswith("tariff_TURPE"))
        revenue = sum(v for k, v in streams.items() if not k.startswith("tariff_TURPE"))
        revenue_series.append(revenue * params.power_mw / 1000.0)
        turpe_series.append(turpe * params.power_mw / 1000.0)
    return calendar_years, revenue_series, turpe_series


def build_project_inputs(
    params: DevCaseParams,
    aurora_library: AuroraLibrary,
    copex_library: CopexLibrary,
    *,
    degradation_case: str | None = "Base",
) -> ProjectInputs:
    """Construit un `ProjectInputs` synthétique à partir des hypothèses de
    développement - même forme que ce que produit `bp_parser.parse_full_bp`,
    donc utilisable tel quel par `financial_engine.compute_results()` et tous
    les onglets existants sans aucune modification."""
    calendar_years, revenue_series, turpe_series = _revenue_and_turpe_series(params, aurora_library)
    if degradation_case is not None:
        curve = degradation_module.degradation_multipliers(
            len(calendar_years), **degradation_module.DEGRADATION_CASES[degradation_case]
        )
        revenue_series = [r * m for r, m in zip(revenue_series, curve, strict=True)]

    capex_initial = capex_total_keur(params, copex_library)
    opex_year1 = opex_year1_keur(params, copex_library)

    length = len(calendar_years) + 1  # +1 pour l'année de construction (COD - 1)
    years = [params.cod_year - 1] + calendar_years
    capex_keur = [-capex_initial] + [0.0] * len(calendar_years)
    opex_keur = [0.0] + [-opex_year1] * len(calendar_years)
    revenues_keur = [0.0] + revenue_series
    turpe_keur = [0.0] + turpe_series
    end_of_life_keur = [0.0] * length
    net_cashflow_keur = [
        c + o + t + r + e
        for c, o, t, r, e in zip(
            capex_keur, opex_keur, turpe_keur, revenues_keur, end_of_life_keur, strict=True
        )
    ]

    return ProjectInputs(
        name=params.name,
        location=params.location,
        segment=params.voltage_class,
        cod=f"{params.cod_year}-01-01",
        operating_years=params.operating_years,
        usable_power_mw=params.power_mw,
        usable_energy_mwh=params.energy_mwh,
        capex_initial_keur=capex_initial,
        capex_repowering_keur=0.0,
        repowering=params.repowering,
        opex_year1_keur=opex_year1,
        opex_adjustment_keur=0.0,
        turpe_fixed_eur_per_kw=0.0,
        years=years,
        capex_keur=capex_keur,
        opex_keur=opex_keur,
        end_of_life_keur=end_of_life_keur,
        revenues_keur=revenues_keur,
        turpe_keur=turpe_keur,
        net_cashflow_keur=net_cashflow_keur,
    )


# Leviers structurels balayables (section "Analyses de sensibilité" d'Inputs Dev /
# section 5 d'Advise Dev) - chacun reconstruit un ProjectInputs complet par valeur,
# contrairement à sensitivity.py qui choque des multiplicateurs continus sur un
# ProjectInputs déjà figé.
def run_distance_sensitivity(
    base_params: DevCaseParams,
    aurora_library: AuroraLibrary,
    copex_library: CopexLibrary,
    distances_km: list[float],
    *,
    compute_kwargs: dict | None = None,
) -> list[dict]:
    compute_kwargs = compute_kwargs or {}
    rows = []
    for distance in distances_km:
        params = replace(
            base_params,
            connection_capex_mode="distance_rte",
            distance_rte_km=distance,
        )
        inputs = build_project_inputs(params, aurora_library, copex_library)
        result = financial_engine.compute_results(inputs, **compute_kwargs)
        rows.append(
            {
                "distance_km": distance,
                "connection_capex_keur": connection_capex_keur(params, copex_library),
                "project_irr": result.project_irr,
                "equity_irr": result.equity_irr,
                "dscr_min": result.dscr_min,
            }
        )
    return rows


def run_duration_sensitivity(
    base_params: DevCaseParams,
    aurora_library: AuroraLibrary,
    copex_library: CopexLibrary,
    durations_h: list[int],
    *,
    compute_kwargs: dict | None = None,
) -> list[dict]:
    compute_kwargs = compute_kwargs or {}
    rows = []
    for duration in durations_h:
        params = replace(base_params, duration_h=duration)
        inputs = build_project_inputs(params, aurora_library, copex_library)
        result = financial_engine.compute_results(inputs, **compute_kwargs)
        rows.append(
            {
                "duration_h": duration,
                "project_irr": result.project_irr,
                "equity_irr": result.equity_irr,
                "dscr_min": result.dscr_min,
            }
        )
    return rows


def run_config_sensitivity(
    base_params: DevCaseParams,
    aurora_library: AuroraLibrary,
    copex_library: CopexLibrary,
    configs: list[dict],
    *,
    compute_kwargs: dict | None = None,
) -> list[dict]:
    """`configs` : liste de dicts de champs DevCaseParams à surcharger (ex.
    `{"turpe_type": "Injection"}`, `{"gabarit": True}`, `{"repowering": True}`)
    - un dict vide = le cas de base, pour comparaison directe."""
    compute_kwargs = compute_kwargs or {}
    rows = []
    for overrides in configs:
        params = replace(base_params, **overrides)
        inputs = build_project_inputs(params, aurora_library, copex_library)
        result = financial_engine.compute_results(inputs, **compute_kwargs)
        rows.append(
            {
                "label": ", ".join(f"{k}={v}" for k, v in overrides.items()) or "Cas de base",
                "project_irr": result.project_irr,
                "equity_irr": result.equity_irr,
                "dscr_min": result.dscr_min,
            }
        )
    return rows


def run_cod_year_sensitivity(
    base_params: DevCaseParams,
    aurora_library: AuroraLibrary,
    copex_library: CopexLibrary,
    cod_years: list[int],
    *,
    compute_kwargs: dict | None = None,
) -> list[dict]:
    compute_kwargs = compute_kwargs or {}
    rows = []
    for cod_year in cod_years:
        params = replace(base_params, cod_year=cod_year)
        inputs = build_project_inputs(params, aurora_library, copex_library)
        result = financial_engine.compute_results(inputs, **compute_kwargs)
        rows.append(
            {
                "cod_year": cod_year,
                "project_irr": result.project_irr,
                "equity_irr": result.equity_irr,
                "dscr_min": result.dscr_min,
            }
        )
    return rows
