from datetime import date

from opendirector_ingest import (
    classify_movement,
    infer_role,
    looks_like_person_candidate,
    normalise_person_name,
    normalise_newsletter,
    parse_date_fragment,
    parse_newsletter,
    parse_week_ending,
)


DIRECTOR_MESSAGE = {
    "id": "director-message",
    "thread_id": "director-thread",
    "internal_date": "1785101933000",
    "label_ids": ["CATEGORY_UPDATES"],
    "subject": (
        "Director Changes - Soul Patts, Stockland - "
        "week ending 24th of July 2026"
    ),
    "from": "OpenDirector <info@opendirector.com.au>",
    "text_body": """
--------------
Director Moves
--------------

Anne Loveridge ( https://example.test/anne )

Director

Washington H Soul Pattinson and Company Limited ( https://example.test/soul )

Anne Loveridge will join the Board of Soul Patts as a Non-Executive Director,
effective 1 October 2026.

in LinkedIn ( https://linkedin.test/anne )

Beaux Pontak

Director

Latitude Group Holdings Limited ( https://example.test/latitude )

Effective 22 July 2026, Beaux Pontak resigned as a Non-Executive Director of
Latitude.

Tim Eastwood has been appointed as a Non-Executive Director, with effect from
the same date.

Changing job? Let us know your new email and stay informed.
""",
}

EXECUTIVE_MESSAGE = {
    "id": "executive-message",
    "internal_date": "1785186319000",
    "subject": (
        "Executive Changes - Macquarie Group, ASX - "
        "week ending 24th of July 2026"
    ),
    "from": "OpenDirector <info@opendirector.com.au>",
    "text_body": """
---------------
Executive Moves
---------------

Gregory Ward ( https://example.test/greg )

Managing Director and Chief Executive Officer

Macquarie Group Limited ( https://example.test/macquarie )

The Board of Macquarie Group has appointed Greg Ward as Managing Director and
Chief Executive Officer, effective 7 November 2026, succeeding Shemara
Wikramanayake.

Andrew Tobin ( https://example.test/andrew )

Chief Financial Officer

ASX Limited ( https://example.test/asx )

Andrew Tobin intends to retire from his role as Chief Financial Officer of ASX.

Changing job? Let us know your new email and stay informed.
""",
}


def test_week_ending_with_and_without_ordinal():
    received = normalise_newsletter(DIRECTOR_MESSAGE).received_at
    assert (
        parse_week_ending(DIRECTOR_MESSAGE["subject"], received)
        == date(2026, 7, 24)
    )
    assert (
        parse_week_ending("Board Director Changes - w/e September 24", received)
        == date(2026, 9, 24)
    )


def test_director_parser_emits_secondary_appointment():
    newsletter = normalise_newsletter(DIRECTOR_MESSAGE)
    result = parse_newsletter(newsletter)
    assert result.status == "parsed"
    assert [movement.person_name for movement in result.movements] == [
        "Anne Loveridge",
        "Beaux Pontak",
        "Tim Eastwood",
    ]
    assert [movement.movement_type for movement in result.movements] == [
        "appointment",
        "departure",
        "appointment",
    ]
    assert result.movements[0].effective_date == date(2026, 10, 1)
    assert result.movements[1].effective_date == date(2026, 7, 22)
    assert result.movements[2].effective_date == date(2026, 7, 22)


def test_executive_parser_captures_succession_and_retirement():
    newsletter = normalise_newsletter(EXECUTIVE_MESSAGE)
    result = parse_newsletter(newsletter)
    assert len(result.movements) == 2
    assert result.movements[0].movement_type == "appointment"
    assert result.movements[0].predecessor_name == "Shemara Wikramanayake"
    assert result.movements[1].movement_type == "retirement"


def test_action_classification():
    assert classify_movement("Lee has stepped down.") == "departure"
    assert classify_movement("Lee has been appointed.") == "appointment"
    assert classify_movement("Lee will retire.") == "retirement"
    assert classify_movement("Lee transitioned to CEO.") == "transition"
    assert classify_movement("Lee will commence as CEO.") == "appointment"
    assert classify_movement("Lee will succeed Pat as chair.") == "appointment"
    assert parse_date_fragment("effective as of June 9, 2023", 2023) == date(
        2023, 6, 9
    )
    assert (
        infer_role(
            "The board appointed Vikesh Ramsunder as Managing Director and "
            "Chief Executive Officer.",
            "director",
        )
        == "Managing Director and Chief Executive Officer"
    )


def test_historical_secondary_name_cleanup():
    assert normalise_person_name("Mr Garry Browne AM") == "Garry Browne AM"
    assert (
        normalise_person_name("Netwealth Chief Financial Officer Grant Boyle")
        == "Grant Boyle"
    )
    assert normalise_person_name("Pacific Smiles Chair Zita Peach") == "Zita Peach"
    assert not looks_like_person_candidate("Mr Taylor")
    assert not looks_like_person_candidate("M.D. Ph.D")
