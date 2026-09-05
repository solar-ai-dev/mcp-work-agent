"""Match an unresolved name/title against provider display-name metadata only."""

import re

_KOREAN_NAME_TITLE = re.compile(
    r"(?P<name>[가-힣]{1,4})\s*(?P<title>대리|과장|차장|부장|팀장|실장|이사|님)"
)


def person_discovery_term(mention: str) -> str:
    """Broaden an abbreviated surname/title for discovery, not participant filtering."""
    requested = _KOREAN_NAME_TITLE.fullmatch(mention.strip())
    if requested is None:
        return mention.strip()
    return requested["title"] if len(requested["name"]) == 1 else requested["name"]


def match_person_mention(mention: str, display_name: str) -> bool:
    """Surname + title may match several people; this does not resolve identity."""
    target = re.sub(r"\s+", "", mention).casefold()
    normalized = re.sub(r"\s+", "", display_name).casefold()
    if target == normalized:
        return True
    requested = _KOREAN_NAME_TITLE.fullmatch(mention.strip())
    if requested is None:
        return False
    return any(
        found["title"] == requested["title"]
        and (
            found["name"] == requested["name"]
            or len(requested["name"]) == 1 and found["name"].startswith(requested["name"])
        )
        for found in _KOREAN_NAME_TITLE.finditer(display_name)
    )
