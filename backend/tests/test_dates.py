from datetime import datetime

from app.dates import HOSPITAL_TIMEZONE, parse_hospital_datetime
from app.integrations.fhir import parse_time as parse_fhir_time
from app.routes.icu import _parse_time as parse_icu_time
from app.services.medicines import _parse_time as parse_medicine_time


def test_naive_clinical_datetime_is_kept_as_hospital_wall_clock():
    assert parse_hospital_datetime("2026-10-20T09:15:00") == datetime(2026, 10, 20, 9, 15)


def test_offset_datetime_is_normalized_to_hospital_time_without_shifting_its_calendar_day():
    assert parse_hospital_datetime("2026-10-19T20:30:00Z") == datetime(2026, 10, 20, 2, 0)


def test_timezone_offset_parsing_is_shared_by_fhir_icu_and_medication_times():
    expected = datetime(2026, 10, 20, 9, 0)
    assert parse_fhir_time("2026-10-20T03:30:00Z") == expected
    assert parse_icu_time("2026-10-20T03:30:00Z") == expected
    assert parse_medicine_time("2026-10-20T03:30:00Z") == expected


def test_hospital_zone_is_explicit():
    assert HOSPITAL_TIMEZONE.key == "Asia/Kolkata"
