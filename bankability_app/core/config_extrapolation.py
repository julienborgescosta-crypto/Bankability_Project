"""Extrapole les courbes RAW/TURPE Aurora pour les combinaisons (duree, tension,
type TURPE, gabarit, ORO, heures de curtailment) qu'Aurora n'a pas directement
modelisees dans `AU_Store` - jamais silencieux : toute courbe extrapolee porte
`AuStoreConfig.extrapolated=True` et une liste de notes expliquant la methode
utilisee. Voir docs/specs/config_extrapolation.md.

Methode (demandee par l'utilisateur, 2026-09-24, apres verification qu'aucune
config reelle ne serait perdue - les combinaisons reelles restent toujours
utilisees telles quelles, l'extrapolation ne s'active que pour combler un
trou) :

- **Effet type TURPE / gabarit** : modele a facteurs independants (RAW
  multiplicatif, TURPE additif), calibre sur HTB2 - seule tension ou Aurora a
  modelise Classique/Injection/Soutirage x gabarit 0/1 en integralite - puis
  transfere tel quel a la tension cible (en appliquant le(s) facteur(s) a la
  courbe Classique/g0 *reelle* de cette tension, qui existe toujours). Suppose
  que l'effet d'un changement de type TURPE ou de gabarit est independant de la
  tension - hypothese non verifiee au-dela de HTB2, documentee dans chaque note.
- **Effet ORO (limitation non-firm 3000h/an)** : meme principe, calibre sur les
  4 cas HTB2 ORO reels (injection/soutirage x 2h/4h) et transfere aux autres
  combinaisons injection/soutirage. N'a pas de sens pour le type TURPE
  Classique (l'ORO limite specifiquement l'injection ou le soutirage) - leve
  une erreur explicite plutot que d'inventer un chiffre.
- **Heures de curtailment personnalisees (500-4000h)** : le cas ORO reel (ou
  deja extrapole) a 3000h sert d'ancre ; le profil de perte % par annee de
  `config/aur_oro_curtailment_losses.yaml` (issu de l'onglet "Curtailment
  analysis" du databook Aurora Q2 2026, **calibre sur un seul cas de
  reference** - 2h HTB2 injection, Central, COD2027) donne le ratio relatif
  entre `heures` et 3000h, interpole lineairement entre les paliers 500h du
  databook. Hors de la plage 500-4000h, Aurora n'a rien analyse : erreur
  explicite plutot qu'une extrapolation non fondee."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from .aur_cases import AuroraConfigError, AuStoreConfig, AuStoreLibrary

REFERENCE_TENSION = "HTB2"  # seule tension avec la matrice complete type TURPE x gabarit
ORO_ELIGIBLE_TURPE_TYPES = ("Injection", "Soutirage")
DEFAULT_CURTAILMENT_HOURS = 3000

CURTAILMENT_LOSSES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "aur_oro_curtailment_losses.yaml"
)


@dataclass(frozen=True)
class ResolvedConfig:
    """Resultat de `resolve_config` : la config Aurora a utiliser (reelle ou
    synthetique) et la bibliotheque qui porte sa courbe - a passer telle quelle
    a `aur_cases.build_project_inputs`, comme n'importe quel `AuStoreConfig`
    reel. `notes` est vide si `config.extrapolated` est faux."""

    library: AuStoreLibrary
    config: AuStoreConfig
    notes: list[str]


def _load_curtailment_losses(path: Path = CURTAILMENT_LOSSES_PATH) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _clamped(table: dict[int, float], year: int) -> float:
    """Valeur de `table` a `year`, plafonnee sur la borne connue la plus
    proche si `year` est hors de sa couverture - meme convention que
    `aur_cases._shifted_degradation`/`copex_icp.escalated_unit_cost` (jamais
    de trou silencieux, jamais d'extrapolation au-dela de ce qui est connu -
    on retient juste la derniere valeur observee). Necessaire ici car la
    seule reference ORO reelle (HTB2, voir `_oro_raw_factor`) est elle-meme
    verrouillee sur un seul COD et zero-remplie hors de sa propre fenetre -
    sans ce plafonnement, `resolve_config` perdrait silencieusement les
    annees hors de cette fenetre (bug signale par l'utilisateur, 2026-09-24 :
    une config HTA extrapolee via ce ratio se retrouvait couverte 2030-2059
    au lieu de la pleine plage Aurora, cassant tout COD < 2030)."""
    if year in table:
        return table[year]
    years = table.keys()
    return table[min(years)] if year < min(years) else table[max(years)]


def _real_config(
    au_store: AuStoreLibrary, *, duree_h: int, tension: str, turpe_type: str, gabarit: bool
) -> AuStoreConfig | None:
    try:
        return au_store.config_by_attributes(
            duree_h=duree_h, tension=tension, turpe_type=turpe_type, gabarit=gabarit, oro=False
        )
    except AuroraConfigError:
        return None


def _turpe_type_raw_factor(
    au_store: AuStoreLibrary, *, duree_h: int, turpe_type: str
) -> dict[int, float]:
    """RAW_HTB2(turpe_type, gabarit=False) / RAW_HTB2(Classique, gabarit=False), par annee."""
    classique = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type="Classique", gabarit=False
    )
    target = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False
    )
    raw_classique = au_store.raw_by_key[classique.austore_key]
    raw_target = au_store.raw_by_key[target.austore_key]
    # 0.0 = annee hors de la fenetre reelle d'une config verrouillee sur un
    # COD (voir _oro_raw_factor ci-dessous, meme convention) - jamais un
    # RAW reel, a exclure plutot que produire un ratio ou un delta invalide.
    return {
        y: raw_target[y] / raw_classique[y]
        for y in raw_classique
        if y in raw_target and raw_classique[y] and raw_target[y]
    }


def _turpe_type_turpe_delta(
    au_store: AuStoreLibrary, *, duree_h: int, turpe_type: str
) -> dict[int, float]:
    classique = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type="Classique", gabarit=False
    )
    target = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False
    )
    turpe_classique = au_store.turpe_by_key[classique.austore_key]
    turpe_target = au_store.turpe_by_key[target.austore_key]
    return {
        y: turpe_target[y] - turpe_classique[y]
        for y in turpe_classique
        if y in turpe_target and turpe_classique[y] and turpe_target[y]
    }


def _gabarit_raw_factor(
    au_store: AuStoreLibrary, *, duree_h: int, turpe_type: str
) -> dict[int, float]:
    """RAW_HTB2(turpe_type, gabarit=True) / RAW_HTB2(turpe_type, gabarit=False), par annee."""
    g0 = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False
    )
    g1 = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=True
    )
    raw_g0 = au_store.raw_by_key[g0.austore_key]
    raw_g1 = au_store.raw_by_key[g1.austore_key]
    # Certaines configs gabarit=True reelles sont elles-memes verrouillees sur
    # un COD (ex. HTB2 4h Soutirage gabarit) et zero-remplies hors de leur
    # fenetre - meme exclusion que _turpe_type_raw_factor ci-dessus (bug
    # signale par l'utilisateur, 2026-09-24 : sans elle, un ratio 0.0 de
    # cette annee ecrasait silencieusement le RAW de la config extrapolee).
    return {y: raw_g1[y] / raw_g0[y] for y in raw_g0 if y in raw_g1 and raw_g0[y] and raw_g1[y]}


def _gabarit_turpe_delta(
    au_store: AuStoreLibrary, *, duree_h: int, turpe_type: str
) -> dict[int, float]:
    g0 = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False
    )
    g1 = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=True
    )
    turpe_g0 = au_store.turpe_by_key[g0.austore_key]
    turpe_g1 = au_store.turpe_by_key[g1.austore_key]
    return {
        y: turpe_g1[y] - turpe_g0[y]
        for y in turpe_g0
        if y in turpe_g1 and turpe_g0[y] and turpe_g1[y]
    }


def _oro_raw_factor(au_store: AuStoreLibrary, *, duree_h: int, turpe_type: str) -> dict[int, float]:
    """RAW_HTB2_ORO(turpe_type) / RAW_HTB2_standard(turpe_type, gabarit=False), par annee -
    calibre sur les 4 cas ORO reels (seuls disponibles)."""
    standard = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False, oro=False
    )
    oro = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False, oro=True
    )
    raw_standard = au_store.raw_by_key[standard.austore_key]
    raw_oro = au_store.raw_by_key[oro.austore_key]
    return {
        y: raw_oro[y] / raw_standard[y]
        for y in raw_standard
        if y in raw_oro and raw_standard[y] and raw_oro[y]
    }


def _oro_turpe_delta(
    au_store: AuStoreLibrary, *, duree_h: int, turpe_type: str
) -> dict[int, float]:
    standard = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False, oro=False
    )
    oro = au_store.config_by_attributes(
        duree_h=duree_h, tension=REFERENCE_TENSION, turpe_type=turpe_type, gabarit=False, oro=True
    )
    turpe_standard = au_store.turpe_by_key[standard.austore_key]
    turpe_oro = au_store.turpe_by_key[oro.austore_key]
    return {
        y: turpe_oro[y] - turpe_standard[y]
        for y in turpe_standard
        if y in turpe_oro and turpe_standard[y] and turpe_oro[y]
    }


def curtailment_loss_pct(hours: int, *, path: Path = CURTAILMENT_LOSSES_PATH) -> dict[int, float]:
    """Profil de perte % par annee a `hours` de curtailment, interpole
    lineairement entre les paliers 500h du databook Aurora. Leve une erreur
    hors de la plage 500-4000h analysee par Aurora (pas de base pour
    extrapoler plus loin sans inventer)."""
    data = _load_curtailment_losses(path)
    grid = data["hours_grid"]
    if not (grid[0] <= hours <= grid[-1]):
        raise AuroraConfigError(
            f"Curtailment hours {hours} outside the range analyzed by Aurora "
            f"({grid[0]}-{grid[-1]}h, Curtailment analysis sheet) - no basis to extrapolate."
        )
    losses_by_hours = data["loss_pct_by_hours"]
    if hours in losses_by_hours:
        return dict(losses_by_hours[hours])
    lower = max(h for h in grid if h <= hours)
    upper = min(h for h in grid if h >= hours)
    weight = (hours - lower) / (upper - lower)
    lower_curve = losses_by_hours[lower]
    upper_curve = losses_by_hours[upper]
    return {
        y: lower_curve[y] + weight * (upper_curve[y] - lower_curve[y])
        for y in lower_curve
        if y in upper_curve
    }


def resolve_config(
    au_store: AuStoreLibrary,
    *,
    duree_h: int,
    tension: str,
    turpe_type: str,
    gabarit: bool,
    oro: bool = False,
    curtailment_hours: int | None = None,
) -> ResolvedConfig:
    """Point d'entree unique : retourne une config Aurora utilisable telle
    quelle par `aur_cases.build_project_inputs` - reelle si Aurora l'a
    modelisee, sinon synthetisee par extrapolation (`config.extrapolated=True`,
    `notes` explique la ou les etapes appliquees). Ne bloque que les
    combinaisons sans aucun sens business (gabarit/ORO avec le type TURPE
    Classique) - tout le reste retombe sur une estimation plutot qu'une
    erreur."""
    if gabarit and turpe_type == "Classique":
        raise AuroraConfigError(
            "Gabarit only makes sense for TURPE Injection/Soutirage (never Classique) - "
            "a combination with no business equivalent, not just missing data."
        )
    if oro and turpe_type == "Classique":
        raise AuroraConfigError(
            "ORO (non-firm curtailment) only makes sense for TURPE Injection/Soutirage "
            "(never Classique) - a combination with no business equivalent, not just "
            "missing data."
        )
    if curtailment_hours is not None and not oro:
        raise AuroraConfigError("`curtailment_hours` only makes sense when `oro=True`.")

    notes: list[str] = []
    extrapolated = False

    # --- Etape 1 : (duree_h, tension, turpe_type, gabarit), sans ORO ---
    real = _real_config(
        au_store, duree_h=duree_h, tension=tension, turpe_type=turpe_type, gabarit=gabarit
    )
    if real is not None:
        raw = dict(au_store.raw_by_key[real.austore_key])
        turpe = dict(au_store.turpe_by_key[real.austore_key])
        valide_cod = real.valide_cod
    else:
        extrapolated = True
        anchor = au_store.config_by_attributes(
            duree_h=duree_h, tension=tension, turpe_type="Classique", gabarit=False
        )
        raw = dict(au_store.raw_by_key[anchor.austore_key])
        turpe = dict(au_store.turpe_by_key[anchor.austore_key])
        valide_cod = anchor.valide_cod
        if turpe_type != "Classique":
            factor = _turpe_type_raw_factor(au_store, duree_h=duree_h, turpe_type=turpe_type)
            delta = _turpe_type_turpe_delta(au_store, duree_h=duree_h, turpe_type=turpe_type)
            raw = {y: raw[y] * _clamped(factor, y) for y in raw}
            turpe = {y: turpe[y] + _clamped(delta, y) for y in turpe}
            notes.append(
                f"TURPE type {turpe_type} not modeled by Aurora for {tension} {duree_h}h - "
                f"estimated by transferring the RAW/TURPE ratio/delta observed between "
                f"{turpe_type} and Classique on {REFERENCE_TENSION} (the only voltage with "
                f"this real combination) to the real Classique curve for {tension}."
            )
        if gabarit:
            gfactor = _gabarit_raw_factor(au_store, duree_h=duree_h, turpe_type=turpe_type)
            gdelta = _gabarit_turpe_delta(au_store, duree_h=duree_h, turpe_type=turpe_type)
            raw = {y: raw[y] * _clamped(gfactor, y) for y in raw}
            turpe = {y: turpe[y] + _clamped(gdelta, y) for y in turpe}
            notes.append(
                f"Gabarit not modeled by Aurora for {tension} {turpe_type} {duree_h}h - "
                f"estimated by transferring the gabarit effect observed on {REFERENCE_TENSION} "
                f"{turpe_type} {duree_h}h."
            )

    # --- Etape 2 : ORO (limitation 3000h/an) ---
    if oro:
        real_oro = None
        if not extrapolated:
            # Un ORO reel implique toujours un standard reel pour la meme
            # combinaison (verifie sur les 4 cas connus) - inutile de tenter
            # si l'etape 1 a deja du extrapoler.
            try:
                real_oro = au_store.config_by_attributes(
                    duree_h=duree_h,
                    tension=tension,
                    turpe_type=turpe_type,
                    gabarit=gabarit,
                    oro=True,
                )
            except AuroraConfigError:
                real_oro = None
        if real_oro is not None:
            raw = dict(au_store.raw_by_key[real_oro.austore_key])
            turpe = dict(au_store.turpe_by_key[real_oro.austore_key])
            valide_cod = real_oro.valide_cod
            real = real_oro
        else:
            extrapolated = True
            oro_factor = _oro_raw_factor(au_store, duree_h=duree_h, turpe_type=turpe_type)
            oro_delta = _oro_turpe_delta(au_store, duree_h=duree_h, turpe_type=turpe_type)
            # oro_factor/oro_delta ne couvrent que les annees ou la reference
            # ORO reelle (HTB2) a une valeur non nulle - certaines references
            # sont elles-memes verrouillees sur un seul COD et zero-remplies
            # hors de cette fenetre (ex. "4h HTB2 Soutirage ORO" : 0 en dehors
            # de 2030-2059). Sans _clamped, ces annees disparaitraient de la
            # courbe extrapolee au lieu d'etre couvertes par le ratio le plus
            # proche connu (bug signale par l'utilisateur, 2026-09-24).
            raw = {y: raw[y] * _clamped(oro_factor, y) for y in raw}
            turpe = {y: turpe[y] + _clamped(oro_delta, y) for y in turpe}
            clamp_note = ""
            if min(raw) < min(oro_factor) or max(raw) > max(oro_factor):
                clamp_note = (
                    f" Outside {min(oro_factor)}-{max(oro_factor)} (the reference's own "
                    "coverage), the nearest known ratio is held constant."
                )
            notes.append(
                f"ORO not modeled by Aurora for {tension} {turpe_type} {duree_h}h"
                f"{' gabarit' if gabarit else ''} - estimated by transferring the ORO vs "
                f"standard RAW/TURPE ratio/delta observed on {REFERENCE_TENSION} {turpe_type} "
                f"{duree_h}h (the only real ORO combination for this duration/type)."
                f"{clamp_note}"
            )

        target_hours = (
            curtailment_hours if curtailment_hours is not None else DEFAULT_CURTAILMENT_HOURS
        )
        if target_hours != DEFAULT_CURTAILMENT_HOURS:
            extrapolated = True
            loss_target = curtailment_loss_pct(target_hours)
            loss_3000 = curtailment_loss_pct(DEFAULT_CURTAILMENT_HOURS)
            rescale = {
                y: (1 - loss_target[y]) / (1 - loss_3000[y]) for y in loss_target if y in loss_3000
            }
            raw = {y: raw[y] * _clamped(rescale, y) for y in raw}
            notes.append(
                f"ORO curve rescaled from 3000h (reference for the rest of the app) to "
                f"{target_hours}h via the Aurora databook's per-year loss % profile "
                f"(Curtailment analysis sheet, calibrated only on 2h HTB2 injection "
                f"Central COD2027) - an approximation, not a direct Aurora output for "
                f"this combination/duration."
            )

    if not extrapolated:
        return ResolvedConfig(library=au_store, config=real, notes=[])

    label_bits = [f"{duree_h}h", tension, turpe_type]
    if gabarit:
        label_bits.append("gabarit")
    if oro:
        label_bits.append("ORO")
        if curtailment_hours is not None and curtailment_hours != DEFAULT_CURTAILMENT_HOURS:
            label_bits.append(f"{curtailment_hours}h")
    label_bits.append("(extrapolated)")
    synthetic_key = " ".join(label_bits)

    synthetic_config = AuStoreConfig(
        drop_key=synthetic_key,
        austore_key=synthetic_key,
        duree_h=duree_h,
        tension=tension,
        turpe_type=turpe_type,
        gabarit=gabarit,
        oro=oro,
        pre_degraded=False,
        valide_cod=valide_cod,
        extrapolated=True,
    )
    extended_library = replace(
        au_store,
        configs=[*au_store.configs, synthetic_config],
        raw_by_key={**au_store.raw_by_key, synthetic_key: raw},
        turpe_by_key={**au_store.turpe_by_key, synthetic_key: turpe},
    )
    return ResolvedConfig(library=extended_library, config=synthetic_config, notes=notes)
