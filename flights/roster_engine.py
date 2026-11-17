from __future__ import annotations

from typing import Dict, List, Tuple, Optional

import random
import re

from django.db import transaction

from .models import (
    Flight,
    PlaneType,
    Pilot,
    CabinCrew,
    FlightTicket,
    Roster,
    RosterCrewAssignment,
    RosterPassengerAssignment,
)


def _generate_seat_labels(prefix: str, count: int, start_row: int = 1, seats_per_row: int = 6) -> List[str]:
    # NOTE: `prefix` kept for backwards compatibility / readability (not used in label format)
    letters = list("ABCDEF")
    seats: List[str] = []
    row = start_row
    remaining = count
    while remaining > 0:
        for letter in letters[:seats_per_row]:
            if remaining <= 0:
                break
            seats.append(f"{row}{letter}")
            remaining -= 1
        row += 1
    return seats


def _build_seat_pools(plane: PlaneType) -> Dict[str, List[str]]:
    layout = plane.seat_layout or {}
    business_pool = list(layout.get("business", []))
    economy_pool = list(layout.get("economy", []))

    if not business_pool and plane.business_seats:
        business_pool = _generate_seat_labels("B", plane.business_seats, start_row=1, seats_per_row=4)
    if not economy_pool and plane.economy_seats:
        economy_pool = _generate_seat_labels("E", plane.economy_seats, start_row=20, seats_per_row=6)

    def dedup(seq: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in seq:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    return {
        "business": dedup(business_pool),
        "economy": dedup(economy_pool),
    }


def _seat_type_for_ticket(ticket: FlightTicket) -> str:
    cls = str(ticket.ticket_class or "").lower()
    return "business" if cls.startswith("bus") else "economy"


def _select_pilots(flight: Flight, pilot_ids: Optional[List[int]] = None) -> List[Pilot]:
    """
    Select pilots for a flight.

    Requirements:
    - At least one senior pilot
    - At least one junior pilot
    - At most two trainees

    Manual selection is supported via `pilot_ids`.
    """
    if pilot_ids:
        pilots = list(Pilot.objects.filter(id__in=pilot_ids))
        if not pilots:
            raise ValueError("No pilots selected")

        # Validate eligibility
        for pilot in pilots:
            if pilot.vehicle_restriction and pilot.vehicle_restriction != flight.plane_type:
                raise ValueError(f"Pilot {pilot.code} is not qualified for plane type {flight.plane_type.code}")
            if pilot.max_range_km and flight.distance_km and pilot.max_range_km < flight.distance_km:
                raise ValueError(
                    f"Pilot {pilot.code} max range ({pilot.max_range_km}km) is less than flight distance ({flight.distance_km}km)"
                )

        seniors = [p for p in pilots if p.seniority == "senior"]
        juniors = [p for p in pilots if p.seniority == "junior"]
        trainees = [p for p in pilots if p.seniority == "trainee"]

        if not seniors:
            raise ValueError("Flight requires at least one senior pilot")
        if not juniors:
            raise ValueError("Flight requires at least one junior pilot")
        if len(trainees) > 2:
            raise ValueError(f"Flight can have at most two trainees, but {len(trainees)} were selected")

        return pilots

    # Automatic selection
    qs = Pilot.objects.filter(
        vehicle_restriction=flight.plane_type,
        max_range_km__gte=(flight.distance_km or 0),
    ).order_by("seniority", "code")

    seniors = list(qs.filter(seniority="senior"))
    juniors = list(qs.filter(seniority="junior"))
    trainees = list(qs.filter(seniority="trainee"))

    if not seniors or not juniors:
        raise ValueError("Insufficient pilots to satisfy senior and junior requirements")

    picks: List[Pilot] = [seniors[0], juniors[0]]
    for t in trainees[:2]:
        if t not in picks:
            picks.append(t)
    return picks


_CABIN_SENIOR_MIN = 1
_CABIN_SENIOR_MAX = 4
_CABIN_JUNIOR_MIN = 4
_CABIN_JUNIOR_MAX = 16
_CABIN_CHEF_MIN = 0
_CABIN_CHEF_MAX = 2


def _split_cabin_crew(crew: List[CabinCrew]) -> Tuple[List[CabinCrew], List[CabinCrew], List[CabinCrew]]:
    chefs = [c for c in crew if c.role == "chef"]
    seniors = [c for c in crew if c.role != "chef" and c.seniority == "senior"]
    juniors = [c for c in crew if c.role != "chef" and c.seniority == "junior"]
    return seniors, juniors, chefs


def _validate_cabin_crew_counts(
    *,
    flight: Flight,
    seniors: List[CabinCrew],
    juniors: List[CabinCrew],
    chefs: List[CabinCrew],
    total_count: int,
) -> None:
    # Enforce the spec (pasted.txt section 4)
    if not (_CABIN_SENIOR_MIN <= len(seniors) <= _CABIN_SENIOR_MAX):
        raise ValueError(
            f"Cabin crew must have {_CABIN_SENIOR_MIN}-{_CABIN_SENIOR_MAX} senior attendants (excluding chefs)."
        )
    if not (_CABIN_JUNIOR_MIN <= len(juniors) <= _CABIN_JUNIOR_MAX):
        raise ValueError(
            f"Cabin crew must have {_CABIN_JUNIOR_MIN}-{_CABIN_JUNIOR_MAX} junior attendants (excluding chefs)."
        )
    if not (_CABIN_CHEF_MIN <= len(chefs) <= _CABIN_CHEF_MAX):
        raise ValueError(f"Cabin crew must have {_CABIN_CHEF_MIN}-{_CABIN_CHEF_MAX} chefs.")

    # Enforce vehicle limits too
    plane_min = max(flight.plane_type.min_cabin_crew, _CABIN_SENIOR_MIN + _CABIN_JUNIOR_MIN)
    plane_max = flight.plane_type.max_cabin_crew
    if total_count < plane_min:
        raise ValueError(f"At least {plane_min} cabin crew members required for this flight.")
    if total_count > plane_max:
        raise ValueError(f"At most {plane_max} cabin crew members allowed for this flight.")


def _select_cabin_crew(flight: Flight, cabin_crew_ids: Optional[List[int]] = None) -> List[CabinCrew]:
    """
    Select cabin crew for a flight.

    Spec constraints (pasted.txt section 4):
      - 1–4 senior attendants (excluding chefs)
      - 4–16 junior attendants (excluding chefs)
      - 0–2 chefs
    Plus plane-type constraints: min_cabin_crew / max_cabin_crew and vehicle restrictions.
    """
    if cabin_crew_ids:
        crew = list(
            CabinCrew.objects.filter(id__in=cabin_crew_ids).prefetch_related("vehicle_restrictions", "recipes")
        )
        if not crew:
            raise ValueError("No cabin crew selected")

        for member in crew:
            if not member.vehicle_restrictions.filter(id=flight.plane_type.id).exists():
                raise ValueError(f"Cabin crew {member.code} is not qualified for plane type {flight.plane_type.code}")

        seniors, juniors, chefs = _split_cabin_crew(crew)
        _validate_cabin_crew_counts(flight=flight, seniors=seniors, juniors=juniors, chefs=chefs, total_count=len(crew))
        return crew

    qs = (
        CabinCrew.objects.filter(vehicle_restrictions=flight.plane_type)
        .prefetch_related("vehicle_restrictions", "recipes")
        .order_by("seniority", "role", "code")
    )

    all_seniors = list(qs.filter(seniority="senior").exclude(role="chef"))
    all_juniors = list(qs.filter(seniority="junior").exclude(role="chef"))
    all_chefs = list(qs.filter(role="chef"))

    if len(all_seniors) < _CABIN_SENIOR_MIN:
        raise ValueError("Insufficient senior cabin crew available for this flight")
    if len(all_juniors) < _CABIN_JUNIOR_MIN:
        raise ValueError("Insufficient junior cabin crew available for this flight")

    plane_min = max(flight.plane_type.min_cabin_crew, _CABIN_SENIOR_MIN + _CABIN_JUNIOR_MIN)
    plane_max = min(
        flight.plane_type.max_cabin_crew,
        _CABIN_SENIOR_MAX + _CABIN_JUNIOR_MAX + _CABIN_CHEF_MAX,
    )

    seniors: List[CabinCrew] = all_seniors[:_CABIN_SENIOR_MIN]
    juniors: List[CabinCrew] = all_juniors[:_CABIN_JUNIOR_MIN]

    capacity_after_min = max(0, plane_max - (len(seniors) + len(juniors)))
    chefs_to_take = min(_CABIN_CHEF_MAX, len(all_chefs), capacity_after_min)
    chefs: List[CabinCrew] = all_chefs[:chefs_to_take]

    crew: List[CabinCrew] = []
    crew.extend(seniors)
    crew.extend(juniors)
    crew.extend(chefs)

    next_j_idx = _CABIN_JUNIOR_MIN
    next_s_idx = _CABIN_SENIOR_MIN
    next_c_idx = chefs_to_take

    while len(crew) < plane_min and len(crew) < plane_max:
        if len(juniors) < _CABIN_JUNIOR_MAX and next_j_idx < len(all_juniors):
            juniors.append(all_juniors[next_j_idx])
            crew.append(all_juniors[next_j_idx])
            next_j_idx += 1
            continue

        if len(seniors) < _CABIN_SENIOR_MAX and next_s_idx < len(all_seniors):
            seniors.append(all_seniors[next_s_idx])
            crew.append(all_seniors[next_s_idx])
            next_s_idx += 1
            continue

        if len(chefs) < _CABIN_CHEF_MAX and next_c_idx < len(all_chefs):
            chefs.append(all_chefs[next_c_idx])
            crew.append(all_chefs[next_c_idx])
            next_c_idx += 1
            continue

        break

    _validate_cabin_crew_counts(flight=flight, seniors=seniors, juniors=juniors, chefs=chefs, total_count=len(crew))
    return crew


def _assign_passenger_seats(plane: PlaneType, tickets: List[FlightTicket]) -> Tuple[List[Dict], Dict[str, List[str]]]:
    pools = _build_seat_pools(plane)

    # Remove seats already pre-assigned in tickets to avoid double assignment
    for ticket in tickets:
        seat = ticket.seat_number
        target_pool = _seat_type_for_ticket(ticket)
        if seat and seat in pools.get(target_pool, []):
            pools[target_pool].remove(seat)

    passenger_assignments: List[Dict] = []
    handled_affinity = set()

    def take_seat(pool_key: str) -> str:
        pool = pools.get(pool_key, [])
        if not pool:
            fallback_key = "economy" if pool_key == "business" else "business"
            pool = pools.get(fallback_key, [])
        if not pool:
            raise ValueError("No seats left to assign")
        return pool.pop(0)

    def find_neighboring_seats(pool_key: str, count: int) -> List[str]:
        """
        Try to find neighboring seats (same row) for affiliated passengers.
        Falls back to sequential seats if neighboring not possible.
        """
        pool = pools.get(pool_key, [])
        if not pool or count <= 0:
            return []

        seats_by_row: Dict[int, List[str]] = {}
        for seat in pool:
            row_match = re.match(r"(\\d+)([A-Z]+)", seat)
            if row_match:
                row_num = int(row_match.group(1))
                seats_by_row.setdefault(row_num, []).append(seat)

        for row_num in sorted(seats_by_row.keys()):
            row_seats = sorted(seats_by_row[row_num])
            if len(row_seats) >= count:
                selected = row_seats[:count]
                for s in selected:
                    if s in pools[pool_key]:
                        pools[pool_key].remove(s)
                return selected

        # Fallback: take sequential seats from pool
        selected = []
        for _ in range(count):
            if pools[pool_key]:
                selected.append(pools[pool_key].pop(0))
        return selected

    # Affinity groups first
    for ticket in tickets:
        passenger = ticket.passenger
        if not passenger or passenger.id in handled_affinity:
            continue

        affiliates = list(passenger.affiliated_passengers.all())
        if not affiliates:
            continue

        group = [passenger] + affiliates
        seat_type = _seat_type_for_ticket(ticket)
        seats_needed = len([p for p in group if not p.is_infant])

        if seat_type not in pools or not pools[seat_type]:
            fallback_key = "economy" if seat_type == "business" else "business"
            if fallback_key in pools and pools[fallback_key]:
                seat_type = fallback_key
            else:
                raise ValueError("No seats left to assign")

        seats = find_neighboring_seats(seat_type, seats_needed)
        while len(seats) < seats_needed:
            seats.append(take_seat(seat_type))

        idx = 0
        for member in group:
            if member.is_infant:
                passenger_assignments.append(
                    {"passenger": member, "seat_number": None, "seat_type": seat_type, "is_infant": True}
                )
            else:
                passenger_assignments.append(
                    {"passenger": member, "seat_number": seats[idx], "seat_type": seat_type, "is_infant": False}
                )
                idx += 1
            handled_affinity.add(member.id)

    # Remaining passengers
    for ticket in tickets:
        passenger = ticket.passenger
        if not passenger or passenger.id in handled_affinity:
            continue

        seat_type = _seat_type_for_ticket(ticket)

        if passenger.is_infant:
            passenger_assignments.append(
                {"passenger": passenger, "seat_number": None, "seat_type": seat_type, "is_infant": True}
            )
            continue

        seat = ticket.seat_number or take_seat(seat_type)
        passenger_assignments.append(
            {"passenger": passenger, "seat_number": seat, "seat_type": seat_type, "is_infant": False}
        )

    return passenger_assignments, pools


def _menu_item_to_dict(item) -> Dict[str, str]:
    return {"name": item.name, "category": getattr(item, "category", None), "description": getattr(item, "description", "")}


def _build_menu_payload(flight: Flight, cabin_crew: List[CabinCrew]) -> Dict:
    """
    Vehicle type has a standard menu. If a chef participates, add a random recipe from that chef.
    """
    plane = flight.plane_type
    standard_items = list(plane.standard_menu.all()) if plane else []
    standard = [_menu_item_to_dict(i) for i in standard_items]

    chef_specials = []
    served = list(standard)

    for chef in [c for c in cabin_crew if c.role == "chef"]:
        recipes = list(chef.recipes.all())
        if not recipes:
            continue
        dish = random.choice(recipes)
        dish_dict = _menu_item_to_dict(dish)
        chef_specials.append(
            {"chef_code": chef.code, "chef_name": f"{chef.first_name} {chef.last_name}", "dish": dish_dict}
        )
        served.append(dish_dict)

    return {"standard": standard, "chef_specials": chef_specials, "served": served}


def generate_roster(
    flight_id: int,
    backend: str = "sql",
    user=None,
    pilot_ids: Optional[List[int]] = None,
    cabin_crew_ids: Optional[List[int]] = None,
) -> Roster:
    flight = Flight.objects.select_related("plane_type", "origin_airport", "destination_airport").get(id=flight_id)

    with transaction.atomic():
        pilots = _select_pilots(flight, pilot_ids)
        cabin_crew = _select_cabin_crew(flight, cabin_crew_ids)

        tickets = list(FlightTicket.objects.select_related("passenger").filter(flight=flight))
        passenger_assignments, remaining_pools = _assign_passenger_seats(flight.plane_type, tickets)

        menu_payload = _build_menu_payload(flight, cabin_crew)

        crew_payload = (
            [
                {"type": "pilot", "code": p.code, "name": f"{p.first_name} {p.last_name}", "seniority": p.seniority}
                for p in pilots
            ]
            + [
                {
                    "type": "cabin",
                    "code": c.code,
                    "name": f"{c.first_name} {c.last_name}",
                    "role": c.role,
                    "seniority": c.seniority,
                }
                for c in cabin_crew
            ]
        )

        passenger_payload = [
            {
                "name": f"{a['passenger'].first_name} {a['passenger'].last_name}",
                "seat": a["seat_number"],
                "seat_type": a["seat_type"],
                "infant": a["is_infant"],
            }
            for a in passenger_assignments
        ]

        roster_payload = {
            "flight": flight.flight_number,
            "backend": backend,
            "menu": menu_payload,
            "crew": crew_payload,
            "passengers": passenger_payload,
            "remaining_seats": remaining_pools,
        }

        nosql_ref: Optional[str] = None
        payload_for_sql = roster_payload

        if backend == "nosql":
            from .nosql_store import store_payload  # optional dependency

            nosql_ref = store_payload(roster_payload)
            payload_for_sql = {}

        roster = Roster.objects.create(
            flight=flight,
            backend=backend,
            payload=payload_for_sql,
            nosql_ref=nosql_ref,
            created_by=user if user and getattr(user, "is_authenticated", False) else None,
        )

        for pilot in pilots:
            RosterCrewAssignment.objects.create(
                roster=roster,
                crew_type="pilot",
                pilot=pilot,
                assigned_role=pilot.seniority or "",
            )

        for crew in cabin_crew:
            RosterCrewAssignment.objects.create(
                roster=roster,
                crew_type="cabin",
                cabin_crew=crew,
                assigned_role=crew.role or "",
            )

        for assignment in passenger_assignments:
            RosterPassengerAssignment.objects.create(
                roster=roster,
                passenger=assignment["passenger"],
                seat_number=assignment["seat_number"],
                seat_type=assignment["seat_type"],
                is_infant=assignment["is_infant"],
            )

    return roster
