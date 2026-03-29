"""Localized terminal messages for the BombParty bot."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["LANGUAGES", "Messages", "get_messages", "resolve_language"]

LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
}

_NAME_TO_CODE: dict[str, str] = {name.lower(): code for code, name in LANGUAGES.items()}
_NAME_TO_CODE.update(
    {
        "english": "en",
        "french": "fr",
        "german": "de",
        "spanish": "es",
        "francais": "fr",
        "espanol": "es",
        "eng": "en",
        "fra": "fr",
        "fre": "fr",
        "deu": "de",
        "ger": "de",
        "spa": "es",
        "anglais": "en",
        "allemand": "de",
        "espagnol": "es",
        "englisch": "en",
        "französisch": "fr",
        "franzosisch": "fr",
        "spanisch": "es",
        "inglés": "en",
        "ingles": "en",
        "francés": "fr",
        "frances": "fr",
        "alemán": "de",
        "aleman": "de",
        "castellano": "es",
        "deutch": "de",
    }
)


def _strip_accents(text: str) -> str:
    """Remove diacritics from a string (e.g. 'français' → 'francais')."""
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def resolve_language(value: str) -> str:
    """Resolve a language code or name to a 2-letter code.

    Accepts 2-letter codes, native names (with or without accents),
    English names, and common alternate names.

    Raises:
        ValueError: If the value doesn't match any known language.
    """
    lower = value.lower().strip()
    if lower in LANGUAGES:
        return lower
    if lower in _NAME_TO_CODE:
        return _NAME_TO_CODE[lower]
    stripped = _strip_accents(lower)
    if stripped in _NAME_TO_CODE:
        return _NAME_TO_CODE[stripped]
    supported = ", ".join(f"{code} ({name})" for code, name in LANGUAGES.items())
    raise ValueError(f"Unknown language: {value!r}. Supported: {supported}")


@dataclass(slots=True, frozen=True)
class Messages:
    """Localized message templates for a single language."""

    loaded_words: str
    press_to_toggle: str
    enabled_on: str
    error: str
    disabled: str
    paused: str
    resumed: str
    window_lost: str
    game_ended: str
    expired_for: str
    no_match: str
    played_for: str
    rejected_for: str
    gave_up: str
    exiting: str


_MESSAGES: dict[str, Messages] = {
    "en": Messages(
        loaded_words="Loaded {count} words",
        press_to_toggle="Press {key} to toggle",
        enabled_on="Enabled",
        error="Error: {detail}",
        disabled="Disabled",
        paused="Paused",
        resumed="Resumed",
        window_lost="Window lost: {detail}",
        game_ended="Game ended",
        expired_for="Expired for {syllable}",
        no_match="No match for {syllable}",
        played_for="Played {word} for {syllable}",
        rejected_for="Rejected {word} for {syllable}",
        gave_up="Gave up on {syllable}",
        exiting="Exiting",
    ),
    "fr": Messages(
        loaded_words="{count} mots chargés",
        press_to_toggle="Appuyez sur {key} pour activer",
        enabled_on="Activé",
        error="Erreur : {detail}",
        disabled="Désactivé",
        paused="En pause",
        resumed="Repris",
        window_lost="Fenêtre perdue : {detail}",
        game_ended="Partie terminée",
        expired_for="Expiré pour {syllable}",
        no_match="Aucun mot pour {syllable}",
        played_for="Joué {word} pour {syllable}",
        rejected_for="Refusé {word} pour {syllable}",
        gave_up="Abandonné sur {syllable}",
        exiting="Fermeture",
    ),
    "de": Messages(
        loaded_words="{count} Wörter geladen",
        press_to_toggle="{key} zum Umschalten drücken",
        enabled_on="Aktiviert",
        error="Fehler: {detail}",
        disabled="Deaktiviert",
        paused="Pausiert",
        resumed="Fortgesetzt",
        window_lost="Fenster verloren: {detail}",
        game_ended="Spiel beendet",
        expired_for="Abgelaufen für {syllable}",
        no_match="Kein Treffer für {syllable}",
        played_for="Gespielt {word} für {syllable}",
        rejected_for="Abgelehnt {word} für {syllable}",
        gave_up="Aufgegeben bei {syllable}",
        exiting="Beenden",
    ),
    "es": Messages(
        loaded_words="{count} palabras cargadas",
        press_to_toggle="Pulsa {key} para activar",
        enabled_on="Activado",
        error="Error: {detail}",
        disabled="Desactivado",
        paused="En pausa",
        resumed="Reanudado",
        window_lost="Ventana perdida: {detail}",
        game_ended="Partida terminada",
        expired_for="Expirado para {syllable}",
        no_match="Sin coincidencia para {syllable}",
        played_for="Jugado {word} para {syllable}",
        rejected_for="Rechazado {word} para {syllable}",
        gave_up="Rendido en {syllable}",
        exiting="Saliendo",
    ),
}


def get_messages(language_code: str) -> Messages:
    """Return the Messages instance for a language code.

    Falls back to English if the code is not found.
    """
    return _MESSAGES.get(language_code, _MESSAGES["en"])
