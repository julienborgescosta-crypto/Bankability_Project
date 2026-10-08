"""TURPE Power (frais reseau fixe+variable par tension) + CTA (% de TURPE
Power) + Accise sur l'electricite (taxe, base auxiliaires + pertes de
stockage) - 3 postes "Autres OPEX" du BP reel que ni la COPEX Library (ICP)
ni Aurora COPEX_library ne detaillent. Demande de l'utilisateur, 2026-10-08
(voir docs/specs/opex_grid_charges.md pour la methode complete et les
sources)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .copex_icp import icp_escalation_factor

DEFAULT_GRID_CHARGES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "aur_opex_grid_charges.yaml"
)
DEFAULT_CHARGE_VOLUME_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "aur_charge_volume.yaml"
)

NTP_YEARS_BEFORE_COD = 1  # meme convention que copex_icp.NTP_YEARS_BEFORE_COD


def load_grid_charges_terms(path: Path = DEFAULT_GRID_CHARGES_PATH) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_charge_volume_curves(
    path: Path = DEFAULT_CHARGE_VOLUME_PATH,
) -> dict[str, dict[int, float]]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@lru_cache(maxsize=1)
def _cached_grid_charges_terms(path: str) -> dict:
    return load_grid_charges_terms(Path(path))


@lru_cache(maxsize=1)
def _cached_charge_volume_curves(path: str) -> dict[str, dict[int, float]]:
    return load_charge_volume_curves(Path(path))


def grid_charges_terms_cached(path: Path = DEFAULT_GRID_CHARGES_PATH) -> dict:
    return _cached_grid_charges_terms(str(path))


def charge_volume_curves_cached(
    path: Path = DEFAULT_CHARGE_VOLUME_PATH,
) -> dict[str, dict[int, float]]:
    return _cached_charge_volume_curves(str(path))


def _escalation_multiplier(
    terms: dict, icp_escalation: dict[str, dict[int, float]], cod_year: int
) -> float:
    reference_label = terms["escalation_reference_label"]
    escalation = icp_escalation.get(reference_label, {})
    return icp_escalation_factor(escalation, cod_year - NTP_YEARS_BEFORE_COD)


def turpe_power_keur(
    *,
    tension: str,
    power_mw: float,
    cod_year: int,
    terms: dict,
    icp_escalation: dict[str, dict[int, float]],
) -> float:
    """Frais fixe + variable (x power_mw) par tension, escalade - voir
    `config/aur_opex_grid_charges.yaml`. Magnitude positive (cout) - le signe
    est applique par l'appelant, comme les autres postes OPEX de l'app."""
    if tension not in terms["turpe_power_fixed_fee_keur"]:
        raise ValueError(f"Pas de TURPE Power pour la tension '{tension}'.")
    fixed = terms["turpe_power_fixed_fee_keur"][tension]
    variable = terms["turpe_power_variable_fee_keur_per_mw"][tension] * power_mw
    base = fixed + variable
    return base * _escalation_multiplier(terms, icp_escalation, cod_year)


def cta_keur(*, tension: str, turpe_power_value_keur: float, terms: dict) -> float:
    """CTA = taux (DSO 5% / TSO 15%) x TURPE Power TOTAL (fixe+variable) -
    deja escalade si `turpe_power_value_keur` l'est (pas une 2e escalade
    independante, voir docs/specs/opex_grid_charges.md)."""
    if tension not in terms["cta_rate_pct"]:
        raise ValueError(f"Pas de taux CTA pour la tension '{tension}'.")
    return terms["cta_rate_pct"][tension] * turpe_power_value_keur


def accise_keur(
    *,
    tension: str,
    duree_h: int,
    power_mw: float,
    cod_year: int,
    terms: dict,
    icp_escalation: dict[str, dict[int, float]],
    charge_volume_curves: dict[str, dict[int, float]],
) -> float:
    """Taxe Accise = (consommation auxiliaires + pertes de stockage) x tarif,
    escaladee. Volume auxiliaires = ratio x MWh nominal (power_mw x duree_h,
    pas de courbe necessaire) ; volume charge (pour les pertes) vient de
    `charge_volume_curves` (1 courbe par duree_h/tension, voir
    `config/aur_charge_volume.yaml`) - leve une erreur explicite si la
    combinaison n'a pas de courbe, plutot qu'une Accise a 0 silencieuse."""
    key = f"{duree_h}h {tension}"
    if key not in charge_volume_curves:
        raise ValueError(
            f"Pas de courbe de volume charge pour '{key}' (disponibles : "
            f"{sorted(charge_volume_curves)})."
        )
    curve = charge_volume_curves[key]
    year = min(max(cod_year, min(curve)), max(curve))
    charge_mwh_per_mw_per_year = curve[year]
    charge_mwh = charge_mwh_per_mw_per_year * power_mw

    aux_mwh = terms["auxiliaries_consumption_ratio_mwh_per_mwh_ac_per_year"] * power_mw * duree_h
    losses_mwh = (
        charge_mwh * (1 - terms["round_trip_efficiency_pct"])
        if terms["accise_includes_losses"]
        else 0.0
    )
    base_mwh = aux_mwh + losses_mwh
    value_keur = base_mwh * terms["accise_tariff_eur_per_mwh"] / 1000.0
    return value_keur * _escalation_multiplier(terms, icp_escalation, cod_year)


def grid_charges_opex_keur(
    *,
    tension: str,
    duree_h: int,
    power_mw: float,
    cod_year: int,
    terms: dict | None = None,
    icp_escalation: dict[str, dict[int, float]] | None = None,
    charge_volume_curves: dict[str, dict[int, float]] | None = None,
) -> tuple[float, dict[str, float]]:
    """Point d'entree unique : TURPE Power + CTA + Accise, en une seule valeur
    OPEX (k€, magnitude positive - voir `capex_and_opex_keur`) + le detail par
    poste (pour l'UI/les tests). `icp_escalation` defaut a la table "OPEX -
    O&M" de la COPEX Library installee si non fournie."""
    terms = terms if terms is not None else grid_charges_terms_cached()
    charge_volume_curves = (
        charge_volume_curves if charge_volume_curves is not None else charge_volume_curves_cached()
    )
    if icp_escalation is None:
        from .copex_icp import load_icp_library_cached

        icp_escalation = load_icp_library_cached().escalation

    turpe_power = turpe_power_keur(
        tension=tension,
        power_mw=power_mw,
        cod_year=cod_year,
        terms=terms,
        icp_escalation=icp_escalation,
    )
    cta = cta_keur(tension=tension, turpe_power_value_keur=turpe_power, terms=terms)
    accise = accise_keur(
        tension=tension,
        duree_h=duree_h,
        power_mw=power_mw,
        cod_year=cod_year,
        terms=terms,
        icp_escalation=icp_escalation,
        charge_volume_curves=charge_volume_curves,
    )
    detail = {"turpe_power_keur": turpe_power, "cta_keur": cta, "accise_keur": accise}
    return turpe_power + cta + accise, detail
