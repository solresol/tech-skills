#!/usr/bin/env python3
"""Parse OpenDirector newsletters and load movement events into PostgreSQL.

Input is JSON Lines on a file or stdin.  Each record is a compact, auditable
representation of one Gmail message:

    {
      "id": "gmail message id",
      "thread_id": "gmail thread id",
      "internal_date": "milliseconds since epoch",
      "label_ids": ["CATEGORY_UPDATES"],
      "subject": "Director Changes ...",
      "from": "OpenDirector <info@opendirector.com.au>",
      "date": "Sun, 26 Jul 2026 21:38:53 +0000",
      "text_body": "..."
    }

The parser is deterministic.  It stores the source text and confidence so
every extracted event remains traceable and reviewable.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import html
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import Json


PARSE_VERSION = "deterministic-3"

MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        (
            "",
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        )
    )
    if name
}
MONTHS.update({name[:3].lower(): number for name, number in MONTHS.items()})

URL_RE = re.compile(r"\(\s*(https?://[^)]+)\s*\)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
DATE_MONTH_FIRST_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
    re.IGNORECASE,
)
WEEK_ENDING_RE = re.compile(
    r"(?:week\s+ending|w/e)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)"
    r"(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
WEEK_ENDING_MONTH_FIRST_RE = re.compile(
    r"(?:week\s+ending|w/e)\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,?\s+(\d{4}))?",
    re.IGNORECASE,
)
ROLE_RE = re.compile(
    r"\b("
    r"director|chair(?:man|person)?|chief|officer|secretary|president|"
    r"executive|managing|partner|counsel|treasurer|commissioner|"
    r"administrator|leader|head|founder|governor|trustee|member|"
    r"representative"
    r")\b",
    re.IGNORECASE,
)
ACTION_RE = re.compile(
    r"\b("
    r"appoint(?:ed|ment)?|join(?:ed|s)?|named|elect(?:ed)?|"
    r"nominat(?:e|ed|ion)|replac(?:e|es|ed|ing)|"
    r"become|becomes|became|take(?:s|n)?\s+(?:up|over)|"
    r"assum(?:e|es|ed)\s+(?:the\s+)?role|commence(?:s|d)?\s+as|"
    r"succeed(?:s|ed|ing)?|"
    r"resign(?:ed|ation)?|step(?:ped)?\s+down|depart(?:ed|ure)?|"
    r"retir(?:e|ed|ement)|leav(?:e|es|ing)|ceased?|not\s+stand|"
    r"transition(?:ed|s)?|promot(?:ed|ion)|acting"
    r")\b",
    re.IGNORECASE,
)
SECONDARY_APPOINTMENT_RE = re.compile(
    r"(?:^|[.!?]\s+|,\s+)"
    r"(?P<name>[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+"
    r"(?:\s+\([^)]+\))?"
    r"(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,5})\s+"
    r"(?:(?:(?:has|had)\s+been|was|is|will\s+be)\s+)?"
    r"(?P<action>appointed|named|elected|promoted)\s+"
    r"(?:as\s+)?(?P<role>[^.;]+)",
)
SECONDARY_JOIN_RE = re.compile(
    r"(?:^|[.!?]\s+|,\s+)"
    r"(?P<name>[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+"
    r"(?:\s+\([^)]+\))?"
    r"(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,5})\s+"
    r"(?P<action>will\s+join|has\s+joined|joined)\s+"
    r"(?P<rest>[^.;]+)",
)
SECONDARY_DEPARTURE_RE = re.compile(
    r"(?:^|[.!?]\s+|,\s+)"
    r"(?P<name>[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+"
    r"(?:\s+\([^)]+\))?"
    r"(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,5})\s+"
    r"(?P<action>"
    r"has\s+also\s+resigned|has\s+resigned|resigned|"
    r"has\s+stepped\s+down|will\s+step\s+down|"
    r"has\s+retired|will\s+retire|has\s+departed"
    r")\b",
)

FOOTER_PREFIXES = (
    "changing job?",
    "share this email",
    "stay current on all",
    "this email was sent to",
    "unsubscribe here",
)
SECTION_HEADINGS = {
    "director moves",
    "director changes",
    "board director changes",
    "executive moves",
    "executive changes",
}


@dataclass
class Newsletter:
    gmail_message_id: str
    gmail_thread_id: str | None
    subject: str
    sender: str | None
    received_at: datetime
    week_ending: date | None
    edition_type: str
    gmail_labels: list[str]
    source_url: str
    raw_text: str
    raw_headers: dict[str, str]
    content_sha256: str


@dataclass
class Movement:
    event_index: int
    person_name: str
    organization_name: str | None
    role_title: str | None
    movement_type: str
    effective_date: date | None
    announcement_text: str
    context_text: str | None
    predecessor_name: str | None
    successor_name: str | None
    person_url: str | None
    organization_url: str | None
    linkedin_url: str | None
    extraction_method: str
    extraction_confidence: float
    needs_review: bool
    raw_block: str


@dataclass
class ParseResult:
    movements: list[Movement]
    status: str
    notes: list[str]


def clean_space(value: str) -> str:
    value = html.unescape(value).replace("\xa0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def clean_markup(value: str) -> str:
    value = MARKDOWN_LINK_RE.sub(r"\1", value)
    value = re.sub(r"[*_#=]+", " ", value)
    return clean_space(value).strip("- ")


def text_without_url(value: str) -> str:
    value = MARKDOWN_LINK_RE.sub(r"\1", value)
    return clean_space(URL_RE.sub("", value))


def first_url(value: str) -> str | None:
    match = URL_RE.search(value)
    return match.group(1).strip() if match else None


def is_tracking_url(value: str | None) -> bool:
    if not value:
        return False
    host = urlparse(value).hostname or ""
    return "opendirector.com.au" in host or "sendib" in host or "mailin.fr" in host


def parse_received_at(record: dict[str, Any]) -> datetime:
    internal_date = record.get("internal_date")
    if internal_date is not None:
        try:
            return datetime.fromtimestamp(
                int(internal_date) / 1000, tz=timezone.utc
            )
        except (TypeError, ValueError, OSError):
            pass
    value = record.get("date") or record.get("headers", {}).get("Date")
    if value:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    raise ValueError("message has neither a valid internal_date nor Date header")


def parse_date_fragment(value: str, default_year: int) -> date | None:
    match = DATE_RE.search(value)
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else default_year
    else:
        match = DATE_MONTH_FIRST_RE.search(value)
        if not match:
            return None
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else default_year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_week_ending(subject: str, received_at: datetime) -> date | None:
    match = WEEK_ENDING_RE.search(subject)
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else received_at.year
    else:
        match = WEEK_ENDING_MONTH_FIRST_RE.search(subject)
        if not match:
            return None
        month = MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else received_at.year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def edition_type(subject: str, body: str) -> str:
    combined = f"{subject}\n{body[:2000]}".lower()
    if "executive moves" in combined or "executive changes" in combined:
        return "executive"
    if (
        "director moves" in combined
        or "director changes" in combined
        or "directors changes" in combined
    ):
        return "director"
    return "unknown"


def normalise_newsletter(record: dict[str, Any]) -> Newsletter:
    message_id = str(record.get("id") or record.get("gmail_message_id") or "")
    if not message_id:
        raise ValueError("message is missing id")
    text_body = record.get("text_body") or record.get("raw_text")
    if not isinstance(text_body, str) or not text_body.strip():
        raise ValueError(f"message {message_id} has no text body")
    headers = {
        str(k): str(v)
        for k, v in (record.get("headers") or {}).items()
        if v is not None
    }
    subject = clean_space(record.get("subject") or headers.get("Subject") or "")
    if not subject:
        raise ValueError(f"message {message_id} has no subject")
    sender = clean_space(record.get("from") or headers.get("From") or "") or None
    received_at = parse_received_at(record)
    raw_text = html.unescape(text_body).replace("\r\n", "\n").replace("\r", "\n")
    return Newsletter(
        gmail_message_id=message_id,
        gmail_thread_id=record.get("thread_id") or record.get("gmail_thread_id"),
        subject=subject,
        sender=sender,
        received_at=received_at,
        week_ending=parse_week_ending(subject, received_at),
        edition_type=edition_type(subject, raw_text),
        gmail_labels=[str(value) for value in (record.get("label_ids") or [])],
        source_url=f"https://mail.google.com/mail/#all/{message_id}",
        raw_text=raw_text,
        raw_headers=headers,
        content_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )


def paragraphs(body: str) -> list[str]:
    values = [
        clean_space(value)
        for value in re.split(r"\n[ \t]*\n+", body)
        if clean_space(value)
    ]
    return [
        value
        for value in values
        if not re.fullmatch(r"[-_=]{3,}", value)
    ]


def content_paragraphs(body: str) -> tuple[list[str], list[str]]:
    values = paragraphs(body)
    notes: list[str] = []
    start = None
    for index, value in enumerate(values):
        cleaned = clean_markup(text_without_url(value)).lower().strip("-: ")
        is_heading = cleaned in SECTION_HEADINGS or cleaned in {
            "director appointments",
            "director appointments / resignations",
        }
        starts_with_heading_and_entry = (
            cleaned.startswith("director appointments ")
            and " - " in cleaned
        )
        if is_heading or starts_with_heading_and_entry:
            start = index if starts_with_heading_and_entry else index + 1
            break
    if start is None:
        for index, value in enumerate(values):
            lowered = value.lower()
            if "director moves" in lowered or "executive moves" in lowered:
                start = index + 1
                break
    if start is None:
        notes.append("movement section heading not found")
        start = 0

    end = len(values)
    for index in range(start, len(values)):
        lowered = values[index].lower()
        if any(lowered.startswith(prefix) for prefix in FOOTER_PREFIXES):
            end = index
            break
    return values[start:end], notes


def looks_like_name(value: str) -> bool:
    value = clean_markup(text_without_url(value))
    if (
        not value
        or len(value) > 100
        or ACTION_RE.search(value)
        or re.search(r"\s-\s", value)
    ):
        return False
    words = value.split()
    if not 2 <= len(words) <= 8:
        return False
    if any(char in value for char in ":;!?"):
        return False
    capitalized = sum(
        1
        for word in words
        if word[:1].isupper() or word.startswith(("Dr", "Mr", "Ms"))
    )
    return capitalized >= max(2, len(words) - 1)


def looks_like_role(value: str) -> bool:
    value = text_without_url(value)
    return bool(value and len(value) <= 160 and ROLE_RE.search(value))


def looks_like_detail(value: str) -> bool:
    value = text_without_url(value)
    return (
        len(value) > 120
        or bool(ACTION_RE.search(value))
        or value.endswith(".")
        or value.lower().startswith(("effective ", "the board ", "the company "))
    )


def is_entry_start(values: Sequence[str], index: int) -> bool:
    if index + 2 >= len(values):
        return False
    return (
        looks_like_name(values[index])
        and looks_like_role(values[index + 1])
        and not looks_like_detail(values[index + 2])
        and clean_markup(values[index + 2]) not in {"", "#"}
    )


def classify_movement(text: str, person_name: str | None = None) -> str:
    candidate = text
    if person_name:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        matching = [
            sentence
            for sentence in sentences
            if person_name.split()[0].lower() in sentence.lower()
            or person_name.split()[-1].lower() in sentence.lower()
        ]
        if matching:
            candidate = " ".join(matching)
    patterns = (
        ("retirement", r"\bretir(?:e|ed|ement)\b"),
        (
            "departure",
            r"\b(resign(?:ed|ation)?|step(?:ped)? down|depart(?:ed|ure)?|"
            r"leav(?:e|es|ing)|ceased?|not stand)\b",
        ),
        ("transition", r"\b(transition(?:ed|s)?|promot(?:ed|ion))\b"),
        ("acting", r"\bacting\b"),
        (
            "appointment",
            r"\b(appoint(?:ed|ment)?|join(?:ed|s)?|named|elect(?:ed)?|"
            r"nominat(?:e|ed|ion)|replac(?:e|es|ed|ing)|"
            r"become|becomes|became|take(?:s|n)? (?:up|over)|"
            r"assum(?:e|es|ed) (?:the )?role|commence(?:s|d)? as|"
            r"succeed(?:s|ed|ing)?)\b",
        ),
    )
    candidates: list[tuple[int, str]] = []
    for movement_type, pattern in patterns:
        match = re.search(pattern, candidate, re.IGNORECASE)
        if match:
            candidates.append((match.start(), movement_type))
    return min(candidates)[1] if candidates else "unknown"


def sentence_for_person(text: str, person_name: str) -> str:
    surname = person_name.split()[-1].lower()
    first_name = person_name.split()[0].lower()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        lowered = sentence.lower()
        if (
            first_name in lowered or surname in lowered
        ) and ACTION_RE.search(sentence):
            return sentence.strip()
    for sentence in sentences:
        if ACTION_RE.search(sentence):
            return sentence.strip()
    return sentences[0].strip() if sentences else text.strip()


def effective_date_from_text(text: str, received_at: datetime) -> date | None:
    date_value = parse_date_fragment(text, received_at.year)
    if date_value:
        return date_value
    return None


def effective_date_for_person(
    text: str, person_name: str, received_at: datetime
) -> date | None:
    surname = re.sub(r"[^a-z0-9]", "", person_name.split()[-1].lower())
    for match in DATE_RE.finditer(text):
        following = text[match.end() : match.end() + 80]
        for_match = re.search(r"\bfor\s+([A-Z][A-Za-z'’.-]+)", following)
        if not for_match:
            continue
        candidate = re.sub(r"[^a-z0-9]", "", for_match.group(1).lower())
        if candidate == surname:
            return parse_date_fragment(match.group(0), received_at.year)
    return effective_date_from_text(text, received_at)


def infer_role(text: str, edition: str) -> str | None:
    text = re.sub(
        r"\b(independent),\s+(non-executive)\b",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )
    patterns = (
        r"\bappointed\s+"
        r"(?:[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’().-]+(?:\s+|$)){1,7}"
        r"as\s+(?:an?\s+|the\s+)?"
        r"([^,.;]+?)(?:\s+(?:of|at|to|for)\s+|,|\.|$)",
        r"\b(?:appointed|named|elected|promoted)\s+(?:to\s+[^,.;]+?\s+)?"
        r"as\s+(?:an?\s+|the\s+)?([^,.;]+?)(?:\s+(?:of|at|to|for)\s+|,|\.|$)",
        r"\b(?:join(?:ed|s)?|retir(?:e|ed)|resign(?:ed)?)\s+"
        r"(?:from\s+(?:the\s+)?(?:role\s+)?as\s+|as\s+)"
        r"(?:an?\s+|the\s+)?([^,.;]+?)(?:\s+(?:of|at|to|for)\s+|,|\.|$)",
        r"\bto\s+(?:the\s+)?additional role of\s+([^,.;]+)",
        r"\bappointed\s+(?:to\s+)?(?:the\s+)?(?:company's\s+)?"
        r"(Managing Director|Chair(?:man|person)?|Director|"
        r"Chief [A-Za-z& /-]+ Officer)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        role = clean_space(match.group(1)).strip(" ,")
        role = re.sub(r"\bDirectors\b", "Director", role)
        if 2 <= len(role) <= 140:
            return role
    if edition == "director":
        return "Director"
    return None


def relation_name(text: str, relation: str) -> str | None:
    if relation == "predecessor":
        patterns = (
            r"\bsucceeding\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5})",
            r"\bsucceed(?:s|ed)?\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5})",
            r"\breplacing\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5})",
        )
    else:
        patterns = (
            r"\bsucceeded\s+by\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5})",
            r"\breplaced\s+by\s+([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,5})",
        )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_space(match.group(1)).rstrip(".,")
    return None


def normalise_person_name(value: str) -> str:
    value = clean_space(re.sub(r"\s*\([^)]+\)\s*", " ", value)).strip(" ,.-")
    role_prefix = re.compile(
        r"^(?:(?:Current|Interim|Deputy)\s+)?(?:"
        r"Chief (?:Executive|Financial|Operating|Legal|Investment) Officer|"
        r"Company Secretary|Managing Director|Executive Director|"
        r"Chair(?:man|person)?|Director|CEO|CFO|COO"
        r")\s+",
        re.IGNORECASE,
    )
    value = role_prefix.sub("", value).strip()
    organization_role_prefix = re.compile(
        r"^(?:[A-Z][A-Za-zÀ-ÖØ-öø-ÿ&'’.-]+\s+){1,4}"
        r"(?:(?:Deputy\s+)?Chair(?:man|person)?|Director|"
        r"Chief (?:Executive|Financial|Operating|Legal|Investment) Officer|"
        r"CEO|CFO|COO)\s+",
        re.IGNORECASE,
    )
    value = organization_role_prefix.sub("", value).strip()
    return re.sub(
        r"^(?:Mr|Mrs|Ms|Miss|Dr|Mt)\.?\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def looks_like_person_candidate(value: str) -> bool:
    words = normalise_person_name(value).split()
    if not 2 <= len(words) <= 8:
        return False
    suffixes = {"am", "ao", "obe", "cbe", "md", "phd"}
    substantive = [
        re.sub(r"[^a-z]", "", word.lower())
        for word in words
        if re.sub(r"[^a-z]", "", word.lower()) not in suffixes
    ]
    return len([word for word in substantive if len(word) >= 2]) >= 2


def person_key(value: str) -> tuple[str, str]:
    words = normalise_person_name(value).split()
    if not words:
        return "", ""
    first_initial = re.sub(r"[^a-z0-9]", "", words[0].lower())[:1]
    surname = re.sub(r"[^a-z0-9]", "", words[-1].lower())
    return first_initial, surname


def secondary_movements(
    text: str,
    primary_name: str,
    organization_name: str | None,
    default_role: str | None,
    received_at: datetime,
    raw_block: str,
    primary_effective_date: date | None,
) -> list[Movement]:
    found: list[Movement] = []
    seen = {normalise_person_name(primary_name).lower()}
    primary_key = person_key(primary_name)
    matches: list[tuple[int, re.Match[str], str]] = []
    for regex, movement_type in (
        (SECONDARY_APPOINTMENT_RE, "appointment"),
        (SECONDARY_JOIN_RE, "appointment"),
        (SECONDARY_DEPARTURE_RE, "departure"),
    ):
        for match in regex.finditer(text):
            matches.append((match.start(), match, movement_type))
    for _, match, movement_type in sorted(matches, key=lambda item: item[0]):
        person = normalise_person_name(match.group("name"))
        if (
            not looks_like_person_candidate(person)
            or person.lower() in seen
            or person_key(person) == primary_key
            or person_key(person)[1] == primary_key[1]
        ):
            continue
        seen.add(person.lower())
        sentence = sentence_for_person(text[match.start() :], person)
        role = match.groupdict().get("role")
        if role:
            role = clean_space(
                re.split(
                    r"\b(?:effective|commencing|with effect|and will commence)\b",
                    role,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
            ).strip(" ,")
            role = re.sub(r"^(?:a|an|the)\s+", "", role, flags=re.IGNORECASE)
        event_date = effective_date_from_text(sentence, received_at)
        if event_date is None and re.search(
            r"\b(?:the\s+)?same date\b", sentence, re.IGNORECASE
        ):
            event_date = primary_effective_date
        if (
            movement_type == "appointment"
            and event_date is not None
            and event_date < received_at.date() - timedelta(days=180)
        ):
            continue
        if (
            movement_type == "departure"
            and re.search(r"\bretir(?:e|ed|ement)\b", match.group("action"), re.I)
        ):
            movement_type = "retirement"
        found.append(
            Movement(
                event_index=-1,
                person_name=person,
                organization_name=organization_name,
                role_title=role or default_role,
                movement_type=movement_type,
                effective_date=event_date,
                announcement_text=sentence,
                context_text=None,
                predecessor_name=None,
                successor_name=None,
                person_url=None,
                organization_url=None,
                linkedin_url=None,
                extraction_method=f"{PARSE_VERSION}:secondary-action",
                extraction_confidence=0.850 if role else 0.780,
                needs_review=role is None,
                raw_block=raw_block,
            )
        )
    return found


def parse_recent_blocks(
    values: Sequence[str], newsletter: Newsletter
) -> tuple[list[Movement], list[str]]:
    movements: list[Movement] = []
    notes: list[str] = []
    index = 0
    while index < len(values):
        if not is_entry_start(values, index):
            index += 1
            continue
        name_value, role_value, org_value = values[index : index + 3]
        next_index = index + 3
        while next_index < len(values) and not is_entry_start(values, next_index):
            next_index += 1
        body_values = list(values[index + 3 : next_index])
        linkedin_url = None
        detail_values: list[str] = []
        for value in body_values:
            lowered = text_without_url(value).lower()
            if lowered in {"in linkedin", "linkedin", "in"}:
                linkedin_url = first_url(value)
                continue
            if lowered.startswith("in linkedin"):
                linkedin_url = first_url(value)
                continue
            detail_values.append(value)
        person_name = text_without_url(name_value)
        role_title = text_without_url(role_value)
        organization_name = text_without_url(org_value)
        detail_text = clean_space(" ".join(text_without_url(v) for v in detail_values))
        raw_block = "\n\n".join(values[index:next_index])
        if not detail_text:
            notes.append(f"no movement detail for {person_name}")
            index = next_index
            continue
        announcement = sentence_for_person(detail_text, person_name)
        movement_type = classify_movement(announcement, person_name)
        effective_date = effective_date_from_text(announcement, newsletter.received_at)
        confidence = 0.965
        if effective_date is None:
            confidence -= 0.060
        if movement_type == "unknown":
            confidence -= 0.230
        primary = Movement(
            event_index=-1,
            person_name=person_name,
            organization_name=organization_name or None,
            role_title=role_title or None,
            movement_type=movement_type,
            effective_date=effective_date,
            announcement_text=announcement,
            context_text=detail_text if detail_text != announcement else None,
            predecessor_name=relation_name(detail_text, "predecessor"),
            successor_name=relation_name(detail_text, "successor"),
            person_url=first_url(name_value),
            organization_url=first_url(org_value),
            linkedin_url=linkedin_url,
            extraction_method=f"{PARSE_VERSION}:recent-block",
            extraction_confidence=max(confidence, 0.500),
            needs_review=movement_type == "unknown",
            raw_block=raw_block,
        )
        movements.append(primary)
        movements.extend(
            secondary_movements(
                detail_text,
                primary_name=person_name,
                organization_name=organization_name or None,
                default_role=role_title or None,
                received_at=newsletter.received_at,
                raw_block=raw_block,
                primary_effective_date=effective_date,
            )
        )
        index = next_index
    return movements, notes


def split_people(value: str) -> list[str]:
    people = [
        clean_space(person)
        for person in re.split(r"\s+and\s+", value)
        if clean_space(person)
    ]
    return people if people and all(looks_like_name(person) for person in people) else []


def parse_standard_heading(
    value: str, edition: str
) -> tuple[list[tuple[str, str | None]], str] | None:
    heading = clean_markup(text_without_url(value))
    heading = re.sub(
        r"^director appointments\s+",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    parts = [
        clean_space(part).strip(" .")
        for part in re.split(r"\s+-\s+", heading)
        if clean_space(part).strip(" .")
    ]
    if edition == "executive" and len(parts) >= 3:
        organization_name = parts[-1]
        fields = parts[:-1]
        people_and_roles: list[tuple[str, str | None]] = []
        if len(fields) == 2:
            people = split_people(fields[0])
            if not people:
                return None
            people_and_roles = [(person, fields[1]) for person in people]
        elif len(fields) == 3:
            split = re.match(
                r"^(.+?)\s+and\s+"
                r"([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’().-]+"
                r"(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’().-]+){1,5})$",
                fields[1],
            )
            if split and looks_like_name(fields[0]) and looks_like_name(split.group(2)):
                people_and_roles = [
                    (fields[0], clean_space(split.group(1))),
                    (clean_space(split.group(2)), fields[2]),
                ]
            else:
                return None
        elif len(fields) % 2 == 0:
            for index in range(0, len(fields), 2):
                if not looks_like_name(fields[index]):
                    return None
                people_and_roles.append((fields[index], fields[index + 1]))
        else:
            return None
        return people_and_roles, organization_name

    match = re.match(r"^(.+)\s*-\s*(.+?)$", heading)
    if not match:
        return None
    people = split_people(clean_space(match.group(1)))
    organization_name = clean_space(match.group(2)).strip(" .")
    if not people or organization_name.lower() in {
        "appointed",
        "resigned",
        "resigning",
        "retired",
        "departed",
    }:
        return None
    return [(person, None) for person in people], organization_name


def parse_old_executive_cards(
    values: Sequence[str], newsletter: Newsletter
) -> list[Movement]:
    entries: list[tuple[int, str, str]] = []
    for index, value in enumerate(values):
        heading = clean_markup(text_without_url(value))
        match = re.match(
            r"^(.+?)\s*-\s*"
            r"(Appointed|Resigned|Resigning|Retired|Departed)$",
            heading,
            re.IGNORECASE,
        )
        if match and looks_like_name(match.group(1)):
            entries.append(
                (index, clean_space(match.group(1)), match.group(2).lower())
            )
    movements: list[Movement] = []
    for entry_number, (index, person_name, heading_action) in enumerate(entries):
        next_index = (
            entries[entry_number + 1][0]
            if entry_number + 1 < len(entries)
            else len(values)
        )
        block_values = list(values[index:next_index])
        organization_name = None
        role_title = None
        for value in block_values[1:]:
            cleaned = clean_markup(text_without_url(value))
            match = re.match(r"^(.+?)\s+-\s+(.+?)$", cleaned)
            if match and not ACTION_RE.search(cleaned):
                organization_name = clean_space(match.group(1))
                role_title = clean_space(match.group(2)).rstrip(".")
        detail = clean_space(
            " ".join(
                clean_markup(text_without_url(value))
                for value in block_values[1:]
                if ACTION_RE.search(clean_markup(text_without_url(value)))
            )
        )
        if not detail:
            continue
        announcement = sentence_for_person(detail, person_name)
        movement_type = (
            "appointment"
            if heading_action == "appointed"
            else "retirement"
            if heading_action == "retired"
            else "departure"
        )
        movements.append(
            Movement(
                event_index=-1,
                person_name=person_name,
                organization_name=organization_name,
                role_title=role_title,
                movement_type=movement_type,
                effective_date=effective_date_from_text(
                    detail, newsletter.received_at
                ),
                announcement_text=announcement,
                context_text=detail if detail != announcement else None,
                predecessor_name=relation_name(detail, "predecessor"),
                successor_name=relation_name(detail, "successor"),
                person_url=None,
                organization_url=None,
                linkedin_url=next(
                    (
                        first_url(value)
                        for value in block_values
                        if clean_markup(value).lower().startswith("linkedin")
                    ),
                    None,
                ),
                extraction_method=f"{PARSE_VERSION}:old-executive-card",
                extraction_confidence=0.820,
                needs_review=organization_name is None or role_title is None,
                raw_block="\n\n".join(block_values),
            )
        )
    return movements


def parse_legacy_blocks(
    values: Sequence[str], newsletter: Newsletter
) -> tuple[list[Movement], list[str]]:
    old_executive = parse_old_executive_cards(values, newsletter)
    if old_executive:
        return old_executive, []

    movements: list[Movement] = []
    entries: list[
        tuple[int, list[tuple[str, str | None]], str]
    ] = []
    for index, value in enumerate(values):
        parsed = parse_standard_heading(value, newsletter.edition_type)
        if parsed:
            people_and_roles, organization_name = parsed
            entries.append((index, people_and_roles, organization_name))

    for entry_number, (index, people_and_roles, organization_name) in enumerate(
        entries
    ):
        next_index = (
            entries[entry_number + 1][0]
            if entry_number + 1 < len(entries)
            else len(values)
        )
        block_values = list(values[index:next_index])
        detail_values = [
            clean_markup(text_without_url(value))
            for value in block_values[1:]
            if not clean_markup(text_without_url(value)).lower().startswith(
                ("linkedin", "opendirector profile", "wiki")
            )
        ]
        detail = clean_space(" ".join(value for value in detail_values if value))
        if not detail or not ACTION_RE.search(detail):
            continue
        raw_block = "\n\n".join(block_values)
        linkedin_url = next(
            (
                first_url(value)
                for value in block_values
                if clean_markup(value).lower().startswith("linkedin")
            ),
            None,
        )
        primary_surnames = {
            person_key(person_name)[1] for person_name, _ in people_and_roles
        }
        block_primaries: list[Movement] = []
        for person_name, heading_role in people_and_roles:
            announcement = sentence_for_person(detail, person_name)
            movement_type = classify_movement(announcement, person_name)
            role_title = heading_role or infer_role(
                announcement, newsletter.edition_type
            )
            needs_review = movement_type == "unknown"
            confidence = 0.900 if heading_role else 0.880
            if role_title is None:
                confidence -= 0.080
            if len(people_and_roles) > 1:
                confidence -= 0.040
            if needs_review:
                confidence -= 0.220
            block_primaries.append(
                Movement(
                    event_index=-1,
                    person_name=person_name,
                    organization_name=organization_name or None,
                    role_title=role_title,
                    movement_type=movement_type,
                    effective_date=effective_date_for_person(
                        detail, person_name, newsletter.received_at
                    ),
                    announcement_text=announcement,
                    context_text=detail if detail != announcement else None,
                    predecessor_name=relation_name(detail, "predecessor"),
                    successor_name=relation_name(detail, "successor"),
                    person_url=first_url(values[index]),
                    organization_url=None,
                    linkedin_url=linkedin_url,
                    extraction_method=f"{PARSE_VERSION}:legacy-heading",
                    extraction_confidence=max(confidence, 0.450),
                    needs_review=needs_review,
                    raw_block=raw_block,
                )
            )
        movements.extend(block_primaries)
        if block_primaries:
            secondary = secondary_movements(
                detail,
                primary_name=block_primaries[0].person_name,
                organization_name=organization_name or None,
                default_role=block_primaries[0].role_title,
                received_at=newsletter.received_at,
                raw_block=raw_block,
                primary_effective_date=block_primaries[0].effective_date,
            )
            movements.extend(
                movement
                for movement in secondary
                if person_key(movement.person_name)[1] not in primary_surnames
            )
    return movements, []


def parse_newsletter(newsletter: Newsletter) -> ParseResult:
    values, notes = content_paragraphs(newsletter.raw_text)
    movements, recent_notes = parse_recent_blocks(values, newsletter)
    notes.extend(recent_notes)
    if not movements:
        movements, legacy_notes = parse_legacy_blocks(values, newsletter)
        notes.extend(legacy_notes)
    for event_index, movement in enumerate(movements, start=1):
        movement.event_index = event_index
    if not movements:
        notes.append("no movement records extracted")
        return ParseResult([], "failed", notes)
    if notes or any(movement.needs_review for movement in movements):
        return ParseResult(movements, "partial", notes)
    return ParseResult(movements, "parsed", notes)


def read_records(stream: Iterable[str]) -> Iterator[dict[str, Any]]:
    buffered = "".join(stream).strip()
    if not buffered:
        return
    try:
        value = json.loads(buffered)
    except json.JSONDecodeError:
        for line_number, line in enumerate(buffered.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error}") from error
        return
    if isinstance(value, list):
        for record in value:
            if not isinstance(record, dict):
                raise ValueError("JSON array entries must be objects")
            yield record
    elif isinstance(value, dict):
        yield value
    else:
        raise ValueError("input must be a JSON object, array, or JSON Lines")


def connect(config_filename: str):
    config = configparser.ConfigParser()
    if not config.read(config_filename):
        raise FileNotFoundError(config_filename)
    database = config["database"]
    return psycopg2.connect(
        dbname=database["dbname"],
        user=database["user"],
        password=database["password"],
        host=database["hostname"],
        port=database.get("port", "5432"),
    )


def apply_schema(conn, schema_filename: str) -> None:
    sql = Path(schema_filename).read_text(encoding="utf-8")
    with conn.cursor() as cursor:
        cursor.execute(sql)
    conn.commit()


def start_run(conn, source: str) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO opendirector.ingestion_runs (source, parse_version)
            VALUES (%s, %s)
            RETURNING id
            """,
            (source, PARSE_VERSION),
        )
        run_id = cursor.fetchone()[0]
    conn.commit()
    return run_id


def upsert_newsletter(
    conn, newsletter: Newsletter, result: ParseResult
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO opendirector.newsletters (
                gmail_message_id,
                gmail_thread_id,
                subject,
                sender,
                received_at,
                week_ending,
                edition_type,
                gmail_labels,
                source_url,
                raw_text,
                raw_headers,
                content_sha256,
                parse_version,
                parse_status,
                parse_notes
            )
            VALUES (
                %(gmail_message_id)s,
                %(gmail_thread_id)s,
                %(subject)s,
                %(sender)s,
                %(received_at)s,
                %(week_ending)s,
                %(edition_type)s,
                %(gmail_labels)s,
                %(source_url)s,
                %(raw_text)s,
                %(raw_headers)s,
                %(content_sha256)s,
                %(parse_version)s,
                %(parse_status)s,
                %(parse_notes)s
            )
            ON CONFLICT (gmail_message_id) DO UPDATE SET
                gmail_thread_id = EXCLUDED.gmail_thread_id,
                subject = EXCLUDED.subject,
                sender = EXCLUDED.sender,
                received_at = EXCLUDED.received_at,
                week_ending = EXCLUDED.week_ending,
                edition_type = EXCLUDED.edition_type,
                gmail_labels = EXCLUDED.gmail_labels,
                source_url = EXCLUDED.source_url,
                raw_text = EXCLUDED.raw_text,
                raw_headers = EXCLUDED.raw_headers,
                content_sha256 = EXCLUDED.content_sha256,
                parse_version = EXCLUDED.parse_version,
                parse_status = EXCLUDED.parse_status,
                parse_notes = EXCLUDED.parse_notes,
                last_ingested_at = CURRENT_TIMESTAMP
            """,
            {
                **asdict(newsletter),
                "raw_headers": Json(newsletter.raw_headers),
                "parse_version": PARSE_VERSION,
                "parse_status": result.status,
                "parse_notes": Json(result.notes),
            },
        )
        cursor.execute(
            """
            DELETE FROM opendirector.movements
            WHERE gmail_message_id = %s
              AND NOT manual_override
            """,
            (newsletter.gmail_message_id,),
        )
        loaded = 0
        for movement in result.movements:
            cursor.execute(
                """
                INSERT INTO opendirector.movements (
                    gmail_message_id,
                    event_index,
                    person_name,
                    organization_name,
                    role_title,
                    movement_type,
                    effective_date,
                    announcement_text,
                    context_text,
                    predecessor_name,
                    successor_name,
                    person_url,
                    organization_url,
                    linkedin_url,
                    extraction_method,
                    extraction_confidence,
                    needs_review,
                    raw_block
                )
                VALUES (
                    %(gmail_message_id)s,
                    %(event_index)s,
                    %(person_name)s,
                    %(organization_name)s,
                    %(role_title)s,
                    %(movement_type)s,
                    %(effective_date)s,
                    %(announcement_text)s,
                    %(context_text)s,
                    %(predecessor_name)s,
                    %(successor_name)s,
                    %(person_url)s,
                    %(organization_url)s,
                    %(linkedin_url)s,
                    %(extraction_method)s,
                    %(extraction_confidence)s,
                    %(needs_review)s,
                    %(raw_block)s
                )
                ON CONFLICT (gmail_message_id, event_index) DO NOTHING
                """,
                {
                    "gmail_message_id": newsletter.gmail_message_id,
                    **asdict(movement),
                },
            )
            loaded += cursor.rowcount
    conn.commit()
    return loaded


def finish_run(conn, run_id: int, counters: dict[str, int], errors: list[str]) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE opendirector.ingestion_runs
            SET completed_at = CURRENT_TIMESTAMP,
                messages_seen = %(messages_seen)s,
                messages_loaded = %(messages_loaded)s,
                movements_loaded = %(movements_loaded)s,
                messages_partial = %(messages_partial)s,
                messages_failed = %(messages_failed)s,
                notes = %(notes)s
            WHERE id = %(run_id)s
            """,
            {
                "run_id": run_id,
                **counters,
                "notes": Json({"errors": errors}),
            },
        )
    conn.commit()


def database_stats(conn) -> dict[str, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                count(*) AS newsletters,
                min(received_at)::date AS first_received,
                max(received_at)::date AS latest_received,
                count(*) FILTER (WHERE parse_status = 'parsed') AS parsed,
                count(*) FILTER (WHERE parse_status = 'partial') AS partial,
                count(*) FILTER (WHERE parse_status = 'failed') AS failed
            FROM opendirector.newsletters
            """
        )
        newsletter_stats = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                count(*) AS movements,
                count(*) FILTER (WHERE needs_review) AS needs_review,
                count(*) FILTER (WHERE movement_type = 'unknown') AS unknown,
                count(*) FILTER (WHERE effective_date IS NOT NULL) AS dated
            FROM opendirector.movements
            """
        )
        movement_stats = cursor.fetchone()
    return {
        "newsletters": newsletter_stats[0],
        "first_received": str(newsletter_stats[1]) if newsletter_stats[1] else None,
        "latest_received": str(newsletter_stats[2]) if newsletter_stats[2] else None,
        "parsed": newsletter_stats[3],
        "partial": newsletter_stats[4],
        "failed": newsletter_stats[5],
        "movements": movement_stats[0],
        "movements_needing_review": movement_stats[1],
        "unknown_movements": movement_stats[2],
        "movements_with_effective_date": movement_stats[3],
    }


def existing_newsletter_records(config_filename: str) -> list[dict[str, Any]]:
    conn = connect(config_filename)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    gmail_message_id,
                    gmail_thread_id,
                    subject,
                    sender,
                    (extract(epoch FROM received_at) * 1000)::bigint,
                    gmail_labels,
                    raw_headers,
                    raw_text
                FROM opendirector.newsletters
                ORDER BY received_at, gmail_message_id
                """
            )
            return [
                {
                    "id": row[0],
                    "thread_id": row[1],
                    "subject": row[2],
                    "from": row[3],
                    "internal_date": str(row[4]),
                    "label_ids": row[5],
                    "headers": row[6],
                    "text_body": row[7],
                }
                for row in cursor.fetchall()
            ]
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON/JSONL file, or - for stdin")
    parser.add_argument("--database-config", default="db.conf")
    parser.add_argument("--schema-file", default="opendirector_schema.sql")
    parser.add_argument("--source", default="gmail-connector")
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="create/update the opendirector schema before loading",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and report without changing PostgreSQL",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="include extracted movement details in dry-run output",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="print database coverage after loading",
    )
    parser.add_argument(
        "--reparse-existing",
        action="store_true",
        help="reparse all source newsletters already stored in PostgreSQL",
    )
    args = parser.parse_args(argv)

    if args.reparse_existing:
        records = existing_newsletter_records(args.database_config)
    else:
        stream = sys.stdin if args.input == "-" else open(args.input, encoding="utf-8")
        try:
            records = list(read_records(stream))
        finally:
            if stream is not sys.stdin:
                stream.close()

    parsed: list[tuple[Newsletter, ParseResult]] = []
    errors: list[str] = []
    for record in records:
        try:
            newsletter = normalise_newsletter(record)
            parsed.append((newsletter, parse_newsletter(newsletter)))
        except Exception as error:  # keep a bulk load moving and report the ID
            errors.append(f"{record.get('id', '<unknown>')}: {error}")

    if args.dry_run:
        output: dict[str, Any] = {
            "messages_seen": len(records),
            "messages_parsed": len(parsed),
            "movements": sum(len(result.movements) for _, result in parsed),
            "partial": sum(result.status == "partial" for _, result in parsed),
            "failed": sum(result.status == "failed" for _, result in parsed),
            "errors": errors,
            "message_results": [
                {
                    "message_id": newsletter.gmail_message_id,
                    "subject": newsletter.subject,
                    "status": result.status,
                    "movement_count": len(result.movements),
                    "needs_review": sum(
                        movement.needs_review for movement in result.movements
                    ),
                    "notes": result.notes,
                }
                for newsletter, result in parsed
            ],
        }
        if args.preview:
            output["preview"] = [
                {
                    "message_id": newsletter.gmail_message_id,
                    "subject": newsletter.subject,
                    "status": result.status,
                    "notes": result.notes,
                    "movements": [asdict(value) for value in result.movements],
                }
                for newsletter, result in parsed
            ]
        print(json.dumps(output, indent=2, default=str, ensure_ascii=False))
        return 1 if errors else 0

    conn = connect(args.database_config)
    try:
        if args.apply_schema:
            apply_schema(conn, args.schema_file)
        run_id = start_run(conn, args.source)
        counters = {
            "messages_seen": len(records),
            "messages_loaded": 0,
            "movements_loaded": 0,
            "messages_partial": 0,
            "messages_failed": len(errors),
        }
        for newsletter, result in parsed:
            try:
                loaded = upsert_newsletter(conn, newsletter, result)
                counters["messages_loaded"] += 1
                counters["movements_loaded"] += loaded
                counters["messages_partial"] += result.status == "partial"
                counters["messages_failed"] += result.status == "failed"
            except Exception as error:
                conn.rollback()
                counters["messages_failed"] += 1
                errors.append(f"{newsletter.gmail_message_id}: {error}")
        finish_run(conn, run_id, counters, errors)
        output: dict[str, Any] = {"run_id": run_id, **counters, "errors": errors}
        if args.stats:
            output["database"] = database_stats(conn)
        print(json.dumps(output, indent=2, default=str))
    finally:
        conn.close()
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
