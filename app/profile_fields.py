"""Normalize Indian contact fields. Blank means unknown; nothing is invented."""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+91[\s\-.]*)?(?:0[\s\-.]*)?(?:\d[\s\-.]*){10,12}")

_WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
}

INDIAN_CITIES = (
    "bengaluru",
    "bangalore",
    "hyderabad",
    "pune",
    "mumbai",
    "chennai",
    "delhi",
    "noida",
    "gurgaon",
    "gurugram",
    "kolkata",
    "ahmedabad",
    "jaipur",
    "kochi",
    "chandigarh",
    "indore",
    "lucknow",
    "nagpur",
    "coimbatore",
    "thiruvananthapuram",
    "bhubaneswar",
    "visakhapatnam",
    "remote",
)

# Canonical skill -> phrases that should count as that skill.
SKILL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "javascript": ("javascript", "java script", "js"),
    "typescript": ("typescript", "ts"),
    "kubernetes": ("kubernetes", "k8s", "kube"),
    "react": ("react", "reactjs", "react.js"),
    "node": ("node", "nodejs", "node.js"),
    "python": ("python", "py"),
    "postgresql": ("postgresql", "postgres", "psql"),
    "go": ("go", "golang"),
    "spring boot": ("spring boot", "springboot"),
    "amazon web services": ("amazon web services", "aws"),
    "google cloud": ("google cloud", "gcp"),
    "microsoft azure": ("microsoft azure", "azure"),
    "continuous integration": ("continuous integration", "ci/cd", "cicd"),
}


def normalize_email(value: str | None) -> str:
    if not value:
        return ""
    match = EMAIL_RE.search(value)
    if not match:
        return ""
    return match.group(0).lower()


def email_in_text(email: str, text: str) -> bool:
    if not email or not text:
        return False
    return email.lower() in text.lower()


def normalize_phone(value: str | None) -> str:
    """Return +91 and 10 digits, or blank when the number is not a mobile."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return ""
    return "+91" + digits


def phone_digits_in_text(phone: str, text: str) -> bool:
    if not phone or not text:
        return False
    wanted = phone.removeprefix("+91")
    return wanted in re.sub(r"\D", "", text)


def normalize_notice_period(value: str | None) -> tuple[str, int | None]:
    """Return (display text, days). Days stay None when the text has no duration."""
    raw = (value or "").strip()
    if not raw:
        return "", None
    lowered = raw.lower()
    if re.search(r"\bimmediate(ly)?\b", lowered) or "immediate joiner" in lowered:
        return raw, 0
    if "serving notice" in lowered:
        return raw, None
    match = re.search(
        r"(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen)"
        r"\s*(day|days|week|weeks|month|months)",
        lowered,
    )
    if not match:
        return raw, None
    amount_token, unit = match.group(1), match.group(2)
    amount = int(amount_token) if amount_token.isdigit() else _WORD_NUMBERS[amount_token]
    if unit.startswith("day"):
        days = amount
    elif unit.startswith("week"):
        days = amount * 7
    else:
        days = amount * 30
    return raw, days


def find_notice_period(text: str) -> tuple[str, int | None]:
    if not text:
        return "", None
    patterns = [
        r"(?:notice\s*period\s*[:\-]?\s*)([^\n.]{0,40})",
        r"\b(immediate(?:ly)?(?:\s+joiner)?)\b",
        r"\b(serving notice(?:\s+period)?)\b",
        r"\b(\d+\s*(?:day|days|week|weeks|month|months)(?:\s+notice)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            snippet = match.group(1).strip(" :-")
            return normalize_notice_period(snippet)
    return "", None


def find_email(text: str) -> str:
    match = EMAIL_RE.search(text or "")
    return match.group(0).lower() if match else ""


def find_phone(text: str) -> str:
    if not text:
        return ""
    for match in PHONE_RE.finditer(text):
        phone = normalize_phone(match.group(0))
        if phone:
            return phone
    return ""


def find_location(text: str) -> str:
    haystack = (text or "").lower()
    for city in INDIAN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", haystack):
            if city == "bangalore":
                return "Bengaluru"
            if city == "gurgaon":
                return "Gurugram"
            return city.title()
    labeled = re.search(r"(?:location|city|based in)\s*[:\-]?\s*([A-Za-z][A-Za-z .]{1,40})", text or "", re.I)
    if labeled:
        return labeled.group(1).strip().split("\n")[0][:80]
    return ""


def find_company(text: str) -> str:
    if not text:
        return ""
    labeled = re.search(
        r"(?:current(?:ly)?\s+(?:company|employer)|working at|employed at|company)\s*[:\-]?\s*([^\n,]{2,80})",
        text,
        flags=re.IGNORECASE,
    )
    if labeled:
        return labeled.group(1).strip(" :-")[:120]
    at_company = re.search(r"\bat\s+([A-Z][A-Za-z0-9& .]{1,60})", text)
    if at_company:
        return at_company.group(1).strip(" :-")[:120]
    return ""


def find_name(text: str) -> str:
    labeled = re.search(r"(?:^|\n)\s*name\s*[:\-]\s*([^\n]{2,80})", text or "", re.I)
    if labeled:
        return labeled.group(1).strip()[:80]
    for line in (text or "").splitlines():
        candidate = line.strip()
        if not candidate or "@" in candidate or any(ch.isdigit() for ch in candidate):
            continue
        words = candidate.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", word) for word in words):
            return candidate[:80]
    return ""


def find_years(text: str) -> int | None:
    match = re.search(r"(\d{1,2})\+?\s*(?:years|yrs)\b", text or "", re.I)
    if not match:
        return None
    years = int(match.group(1))
    if years > 50:
        return None
    return years


def canonicalize_skill(skill: str) -> str:
    token = re.sub(r"\s+", " ", (skill or "").strip().lower())
    if not token:
        return ""
    for canonical, phrases in SKILL_SYNONYMS.items():
        if token in phrases:
            return canonical
    return token


def skill_set(skills: list[str] | str) -> set[str]:
    if isinstance(skills, str):
        parts = re.split(r"[,;/|]+", skills)
    else:
        parts = skills
    found = set()
    for part in parts:
        canonical = canonicalize_skill(part)
        if canonical:
            found.add(canonical)
    return found
